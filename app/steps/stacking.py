"""Stacking : inventaire, conversion + alignement + tri du fond, empilement, mesure du stack (stacking.md)."""
import csv
import re
import os
import shutil
from pathlib import Path

from astropy.io import fits

from .. import fitsio, inventory
from ..siril import opt, q
from .base import P, Step
from ..calibration import calib_signature, calibrate_session  # noqa: F401
from .sessions import (_find, _sessions_for_mode, devices, groups, hm, is_multi, model,  # noqa: F401 (réexportés)
                       mode_effect, pose_table, proc_dir)


class Inventaire(Step):
    id, phase, kind = "S1", "Stacking", "formulaire"
    title = "Inventaire et choix des filtres"
    help = ("Vérifie tes poses (tableau ci-dessous) et choisis comment utiliser les filtres. Ce choix ne compte que si "
            "tu as, pour la même cible, des poses avec un filtre bi-bande et d'autres avec un filtre large bande.\n"
            "Bi-bande (codé « LP » : LP du Seestar, L-eXtreme, L-eNhance, ALP-T, Duo…) : ne laisse passer que le rouge (Hα) "
            "et le turquoise (OIII) ; il fait ressortir les nébuleuses et coupe la pollution lumineuse, mais donne des étoiles "
            "aux couleurs peu naturelles. Large bande (codé « IRCUT » : UV/IR cut, IRCUT, sans filtre, L-Pro…) : tout le "
            "visible, couleurs naturelles, étoiles justes, mais beaucoup moins de contraste sur une nébuleuse.\n\n"
            "A. Tout empiler ensemble — le plus de signal, le plus simple. En contrepartie : couleurs non calibrables (pas "
            "de SPCC), étoiles aux couleurs moins justes, et sur une galaxie le bi-bande n'apporte presque rien.\n"
            "B. Deux stacks séparés — chaque filtre à sa place. Nébuleuse : la nébuleuse vient du bi-bande, les étoiles du "
            "large bande (couleurs naturelles). Galaxie : la galaxie vient du large bande, avec les régions HII du bi-bande "
            "en plus. Le meilleur rendu, mais plus long. Il faut une trentaine de minutes de large bande au moins.\n"
            "C. Un seul filtre — couleurs cohérentes et SPCC possible, simple ; mais les poses de l'autre filtre sont "
            "laissées de côté.\n\n"
            "Conseil : nébuleuse → A (B si les couleurs des étoiles te gênent) ; galaxie → C avec le large bande (B "
            "seulement pour une galaxie aux régions HII visibles : M33, M51, M101, M81).\n"
            "Le matériel est lu dans les en-têtes des poses ; vérifie sa fiche (bouton « Matériel » en haut).")
    params = [
        P("mode", "Filtres", "choice", "A", choices=[["A", "A. Tout ensemble"], ["B", "B. Deux stacks séparés"],
                                                    ["C", "C. Un seul filtre"]], show_if={"_deux_filtres": [True]},
          help="avec plusieurs appareils, B fait un stack par filtre et par appareil, puis les combine filtre par filtre"),
        P("filtre_c", "Filtre gardé (mode C)", "choice", "IRCUT", choices=[["LP", "Bi-bande (LP)"], ["IRCUT", "Large bande (IRCUT)"]],
          show_if={"mode": ["C"], "_deux_filtres": [True]}),
        P("principal", "Appareil principal (plusieurs appareils)", "choice", "", choices=[], show_if={"_multi": [True]},
          help="sa géométrie sert de référence : les autres stacks sont alignés et remis à son échelle"),
    ]
    preview_key = "apercu"

    def summary(self, p):
        """Poses disponibles par appareil et par filtre, avec le temps d'intégration."""
        ses = p.state.get("sessions", [])
        lines = pose_table(ses, {d: model(p, d) for d in {s.get("device") for s in ses}})
        from .. import materiel
        _, new = materiel.seen(p)
        if new:
            lines.append("Matériel reconnu d'après les poses : " + ", ".join(model(p, d) for d in new) +
                         ". Vérifie sa fiche (bouton « Matériel » en haut) : nom, ouverture, pixels, capteur pour SPCC.")
        filt = {s.get("filter") for s in ses}
        if not {"LP", "IRCUT"} <= filt:
            noms = sorted({s.get("filter_name") or s.get("filter") or "?" for s in ses})
            lines.append(f"Un seul type de filtre dans ce projet ({', '.join(noms)}) : "
                         "le choix A / B / C ne se pose pas.")
        elif len({s.get("device") for s in ses}) > 1:
            lines.append("Plusieurs appareils : en mode B, chaque appareil empile chacun de ses filtres à part, puis "
                         "l'étape « Combinaison des appareils » réunit les stacks filtre par filtre.")
        return lines

    def _devs(self, p):
        out = []
        for s in p.state.get("sessions", []):
            if s.get("device") and s["device"] not in out:
                out.append(s["device"])
        return out

    def _best(self, p, devs):
        """Appareil principal par défaut : la plus grande ouverture (sinon la plus longue focale)."""
        from .. import materiel
        def key(d):
            pr = materiel.profile(d, p=p, sample=materiel._sample(p, d))
            return (float(pr.get("ouverture") or 0), float(pr.get("focale") or 0))
        return max(devs, key=key) if devs else ""

    def meta(self, p):
        m = super().meta(p)
        devs = self._devs(p)
        for x in m["params"]:
            if x["name"] == "principal":
                x["choices"] = [[d, model(p, d)] for d in devs]
        return m

    def dyn_defaults(self, p):
        filt = {s.get("filter") for s in p.state.get("sessions", [])}
        devs = self._devs(p)
        return {"_deux_filtres": {"LP", "IRCUT"} <= filt, "_multi": len(devs) > 1,
                "mode": "A" if p.type == "nebuleuse" else "C", "filtre_c": "IRCUT" if p.type == "galaxie" else "LP",
                "principal": p.state.get("principal") if p.state.get("principal") in devs else self._best(p, devs)}

    def run(self, ctx, prm, tag):
        p = ctx.p
        ses = p.state.get("sessions", [])
        if not ses:
            raise ValueError("aucune session dans ce projet")
        info, filters, devices, exps = [], set(), set(), set()
        for s in ses:
            d = inventory.describe(s["path"])
            s.update({k: d.get(k) for k in ("count", "filter", "exptime", "exptimes", "date", "instrument",
                                             "object", "ra", "dec", "size", "focal", "device", "filter_name", "pixel",
                                             "lat", "lon", "bayer") if k in d})
            filters.add(s.get("filter"))
            devices.add(s.get("device") or "?")
            exps.update(s.get("exptimes") or [s.get("exptime")])
            if not s.get("bayer"):
                info.append(f"ATTENTION : {s['name']} : pas de matrice de Bayer (BAYERPAT) dans l'en-tête : caméra mono ? "
                            "L'atelier ne traite que les caméras couleur.")
            info.append(f"{s['name']} : {s.get('count')} poses, filtre {s.get('filter_name') or s.get('filter')} "
                        f"({'bi-bande' if s.get('filter') == 'LP' else 'large bande'}), {s.get('exptime')} s, {s.get('date')}, {s.get('instrument')} ({s.get('device')}, focale {s.get('focal')})")
        both = {"LP", "IRCUT"} <= filters
        if not both:
            info.append("Un seul filtre présent : le choix A/B/C ne s'applique pas.")
        elif p.type == "galaxie":
            info.append("Recommandé pour une galaxie : C (IRCUT) ; B seulement si la galaxie a des régions HII visibles.")
        else:
            info.append("Conseillé pour une nébuleuse : A. B donne des étoiles aux couleurs plus justes (celles du "
                        "large bande), mais demande plus de travail.")
        if len({e for e in exps if e}) > 1:
            info.append(f"Durées de pose différentes ({sorted(e for e in exps if e)}) : elles s'empilent ensemble "
                        "(-norm=addscale et -weight=noise compensent).")
        kept = [s for s in ses if not (both and prm["mode"] == "C" and s.get("filter") != prm["filtre_c"])]
        devices = {s.get("device") or "?" for s in kept}
        if len(devices) > 1:
            from .. import materiel
            _, nouveaux = materiel.seen(p)
            if nouveaux:
                info.append("Nouveau matériel : " + ", ".join(model(p, d) for d in nouveaux) + ". Vérifie sa fiche (bouton "
                            "« Matériel ») : ouverture, taille des pixels, capteur pour SPCC.")
            pr = prm.get("principal") if prm.get("principal") in devices else self._best(p, list(devices))
            gain = []
            for d in sorted(devices - {pr}):
                a, b = (materiel.profile(x, p=p, sample=materiel._sample(p, x)).get("ouverture") for x in (d, pr))
                if a and b:
                    gain.append(f"{model(p, d)} : ~{100 * (float(a) / float(b)) ** 2:.0f} % de la lumière du principal "
                                "par zone du ciel")
            par = "un stack par filtre et par appareil" if prm["mode"] == "B" and both else "un stack par appareil"
            info.append(f"Plusieurs appareils ({' + '.join(model(p, d) for d in sorted(devices))}) : {par}, "
                        f"puis étape « Combinaison des appareils » (alignement sur {model(p, pr)}, échelle comprise"
                        + (", filtre par filtre" if prm["mode"] == "B" and both else "") + ")."
                        + (" Gain attendu : " + " ; ".join(gain) + "." if gain else "")
                        + " Un instrument plus petit peut adoucir les détails : la combinaison sera comparée au principal seul.")
        models = {d: model(p, d) for d in {s.get("device") for s in ses}}
        info = pose_table(ses, models) + mode_effect(ses, models, prm, p.type) + info
        rgb, hdr = inventory.quick_rgb(inventory.lights_of(ses[0]["path"])[0])
        out = ctx.out(tag, "apercu")
        fitsio.write(out, rgb, None)
        p.save()
        return {"outputs": {"apercu": ctx.rel(out)}, "info": info, "linear": True,
                "extra": {"both": both}}

    def on_validate(self, p, var):
        both = var.get("extra", {}).get("both")
        mode = var["params"]["mode"] if both else "unique"
        p.state["mode"] = mode
        prm = var["params"]
        p.state["filtre_c"] = prm.get("filtre_c")
        fams = devices(p)
        p.state["principal"] = prm.get("principal") if prm.get("principal") in fams else (self._best(p, fams) or fams[0])
        p.state["devices"] = devices(p)
        p.state["device"] = model(p, p.state["principal"])

    def notes(self, p, st):
        s = f"Mode filtres : {p.mode}" + (f" ({p.state.get('filtre_c')})" if p.mode == "C" else "")
        if len(p.state.get("devices") or []) > 1:
            s += " ; appareils : " + " + ".join(model(p, d) for d in p.state["devices"]) + f" (principal {model(p, p.state['principal'])})"
        return s


def classer(allrows, prm):
    """Trois niveaux, comme au point de contrôle manuel :
    - nette : fond au moins `facteur` fois la normale de la nuit, ou moins de 25 % des étoiles, ou écart très fort ;
    - mitigée : signalée par le tri (fond nettement inhabituel, ou moins de 40 % des étoiles) sans être nette ;
    - limite : non signalée mais à surveiller (fond +10 %, étoiles sous 60 % de la normale, FWHM 1,3 fois plus large).
    Retourne (signalées nettes + mitigées, limites, pose de référence typique)."""
    import statistics
    fac, zt = float(prm.get("facteur", 2.0)), float(prm.get("z", 5.0))
    num = lambda r, k: float(r.get(k) or 0)
    sess = {}
    for r in allrows:
        sess.setdefault(r.get("session", ""), []).append(r)
    flagged, limites, ref = [], [], None
    for rs in sess.values():
        med_et = statistics.median(num(r, "etoiles") for r in rs) or 1
        fw = [num(r, "fwhm") for r in rs if num(r, "fwhm") > 0]
        med_fw = statistics.median(fw) if fw else 0
        best = min(rs, key=lambda r: (abs(num(r, "rapport") - 1), -num(r, "etoiles")))
        if ref is None or len(rs) > ref[1]:
            ref = (best, len(rs))
        for r in rs:
            rap, z, et, f = num(r, "rapport"), num(r, "z"), num(r, "etoiles"), num(r, "fwhm")
            r = dict(r, etoiles_pct=round(100 * et / med_et))
            if r.get("raison"):
                net = rap > fac or et < 0.25 * med_et or (z > 2 * zt and rap > 1.25)
                r["niveau"] = "nette" if net else "mitigee"
                flagged.append(r)
                continue
            why = []
            if rap > 1.10:
                why.append(f"fond x{rap:.2f}")
            elif z > 0.6 * zt and rap > 1.05:
                why.append(f"fond +{z:.1f} sigma")
            if et < 0.6 * med_et:
                why.append(f"{r['etoiles_pct']} % des étoiles habituelles")
            if med_fw and f > 1.3 * med_fw:
                why.append(f"étoiles moins fines (FWHM x{f / med_fw:.2f})")
            if why:
                limites.append(dict(r, niveau="limite", raison=" ; ".join(why)))
    limites.sort(key=lambda r: -num(r, "rapport"))
    return flagged, limites[:20], (dict(ref[0]) if ref else None)


class Alignement(Step):
    id, phase, single = "S2", "Stacking", True
    title = "Conversion, alignement et tri du fond de ciel"
    help = ("Siril convertit les poses et calcule leur alignement. L'appli repère ensuite les poses suspectes : fond "
            "du ciel deux fois plus clair que les autres (Lune, aube, pollution passagère), nettement plus clair que la "
            "normale, ou ayant perdu la plupart de leurs étoiles (voile nuageux). Rien n'est écarté ici : tu décides à l'étape suivante.")
    params = [P("facteur", "Fond trop clair : seuil (x la médiane de la nuit)", "float", 2.0, 1.2, 4, 0.1,
                help="signale les poses au fond au moins 2 fois plus clair que la pose typique de la nuit (Lune, aube, "
                     "gros nuage) ; plus bas = plus sévère"),
              P("z", "Fond inhabituel : sensibilité (plus bas = plus sévère)", "float", 5.0, 2, 10, 0.5,
                help="signale les poses dont le fond s'écarte nettement de sa variation normale dans la nuit (et d'au moins "
                     "15 %) : voiles nuageux discrets ; 3 = sévère, 5 = défaut, 8 = seulement les écarts flagrants")]

    def run(self, ctx, prm, tag):
        p = ctx.p
        if not is_multi(p):
            return self.run_group(ctx, prm, p.root / "process", _sessions_for_mode(p))
        out = {"outputs": {}, "info": [], "extra": {"groups": {}}}
        for dev, ses in groups(p):
            r = self.run_group(ctx, prm, proc_dir(p, dev), ses, dev)
            out["info"] += [f"— {model(p, dev)} —"] + r["info"]
            out["extra"]["groups"][dev] = r["extra"]
        return out

    def run_group(self, ctx, prm, proc, ses, dev=""):
        p = ctx.p
        ranges, start = [], 1
        for s in ses:
            n = len(inventory.lights_of(s["path"]))
            ranges.append({"session": s["name"], "filter": s.get("filter"), "de": start, "a": start + n - 1})
            start += n
        self._cal_info = []
        if self._reusable(proc, ses, start - 1):
            ctx.log(f"Conversion et alignement déjà faits pour ces {start - 1} poses : repris tels quels "
                    "(seul le tri du fond est recalculé).")
        else:
            self._convert_register(ctx, proc, ses, dev)
        r = self._tri(ctx, prm, proc, ranges, start)
        if self._cal_info:
            r["info"] = self._cal_info + r.get("info", [])
        elif not any(calib_signature(s) for s in ses):
            r["info"] = ["Pas de darks / flats / offsets dans les sessions : poses utilisées telles quelles "
                         "(normal pour un Seestar ; pour une caméra astro, les ranger améliore le fond)."] + r.get("info", [])
        return r

    @staticmethod
    def _reusable(proc, ses, total):
        """Séquence déjà convertie et alignée pour exactement ces sessions (évite de tout refaire pour changer un seuil)."""
        seq = proc / "combined_.seq"
        if not seq.exists():
            return False
        lines = seq.read_text(encoding="utf-8", errors="replace").splitlines()
        n_i = sum(1 for l in lines if l.startswith("I "))
        n_r = sum(1 for l in lines if l.startswith("R") and len(l) > 1 and l[1] in "0123*")
        mark = proc / "sessions.json"
        if mark.exists():
            try:
                import json
                if json.loads(mark.read_text()) != [[s["path"], calib_signature(s)] for s in ses]:
                    return False
            except Exception:
                return False
        return n_i == total and n_r >= total

    def _convert_register(self, ctx, proc, ses, dev):
        p = ctx.p
        if proc.exists():
            shutil.rmtree(proc)
        proc.mkdir()
        cmds, start = [], 1
        self._cal_info = []
        for s in ses:
            lights, msg = calibrate_session(ctx, s)
            self._cal_info += msg
            n = len(inventory.lights_of(s["path"]))
            try:
                out_rel = os.path.relpath(proc, lights)
            except ValueError:
                out_rel = str(proc)
            cmds += [f"cd {q(lights)}", f"convert combined -start={start} {opt('-out', out_rel)}"]
            start += n
        cmds += [f"cd {q(proc)}", "register combined_ -2pass"]
        ctx.sir(cmds, cwd=p.root, name=f"conversion_alignement{('_' + dev) if dev else ''}")
        if not (proc / "combined_.seq").exists():
            raise RuntimeError("combined_.seq absent après register : voir le journal de Siril")
        import json
        (proc / "sessions.json").write_text(json.dumps([[s["path"], calib_signature(s)] for s in ses]))

    def _tri(self, ctx, prm, proc, ranges, start):
        seq = proc / "combined_.seq"
        plages = ",".join(f"{r['de']}-{r['a']}" for r in ranges)
        args = [seq, "--facteur", prm["facteur"], "--z", prm["z"]]
        if len(ranges) > 1:
            args += ["--plages", plages]
        txt = ctx.py("tri_fond_ciel.py", args, cwd=proc)
        with open(proc / "tri_fond_ciel.csv", encoding="utf-8") as f:
            allrows = list(csv.DictReader(f))
        rows, limites, ref = classer(allrows, prm)
        info = [l for l in txt.splitlines() if l.strip() and not l.startswith(("unselect", "puis", "Tableau", "index("))
                and not l.lstrip()[:1].isdigit()][:8]
        info.insert(0, "Plages : " + ", ".join(f"{r['session']} ({r['filter']}) {r['de']}–{r['a']}" for r in ranges))
        n_net = sum(r["niveau"] == "nette" for r in rows)
        info.append(f"Tri : {n_net} pose(s) à écarter nettement, {len(rows) - n_net} mitigée(s) (à toi de décider), "
                    f"{len(limites)} proche(s) de la limite (gardées). Choix pose par pose, avec vignettes, à l'étape S3.")
        return {"outputs": {}, "info": info,
                "extra": {"ranges": ranges, "flagged": rows, "limites": limites, "reference": ref, "total": start - 1}}

    def on_validate(self, p, var):
        ex = var.get("extra", {})
        if "groups" in ex:
            p.state["facts"]["groups"] = ex["groups"]
            p.state["facts"].update(total=sum(g["total"] for g in ex["groups"].values()), ranges=None,
                                    flagged=[dict(r, appareil=d) for d, g in ex["groups"].items() for r in g["flagged"]])
        else:
            p.state["facts"].pop("groups", None)
            p.state["facts"].update(ranges=ex.get("ranges"), flagged=ex.get("flagged"), total=ex.get("total"))

    def notes(self, p, st):
        f = p.state["facts"]
        if f.get("groups"):
            return "Conversion + alignement, une séquence par appareil : " + " ; ".join(
                f"{model(p, d)} {g['total']} poses (" + ", ".join(f"{r['filter']} {r['de']}–{r['a']}" for r in g["ranges"])
                + f"), {len(g['flagged'])} signalées" for d, g in f["groups"].items())
        return (f"Conversion + alignement : {f.get('total')} poses ; plages "
                + ", ".join(f"{r['filter']} {r['de']}–{r['a']}" for r in f.get("ranges") or [])
                + f" ; poses signalées par le tri : {len(f.get('flagged') or [])}")


class Empilement(Step):
    id, phase, single = "S3", "Stacking", True
    title = "Empilement"
    help = ("Les poses sont alignées puis empilées, chacune pondérée selon son bruit ; les pixels aberrants (satellites, "
            "avions) sont rejetés. Choisis d'abord les poses à écarter : le tri de l'étape précédente les classe en "
            "rejets nets (écartés d'office), mitigées (à toi de voir) et proches de la limite (gardées). « voir » ouvre "
            "une pose, à comparer avec la pose typique de la nuit. Le filtre de rondeur écarte les poses aux étoiles allongées (plus bas = plus strict). "
            "Mode B : l'appli vérifie que les deux stacks ont bien le bon nombre de poses et la même taille.")
    params = [P("filter_round", "Filtre de rondeur (k)", "float", 2.5, 1.5, 4, 0.1),
              P("filter_fwhm", "Filtre FWHM (k, 0 = aucun)", "float", 0, 0, 4, 0.1),
              P("exclure", "Poses à écarter (index de séquence)", "text", "",
                help="rempli par les cases ci-dessus ; modifiable à la main (virgules)")]
    preview_key = "stack"
    canonical = {}
    interaction = "poses"

    def ready(self, p):
        st = p.state["steps"].get("S2", {})
        return (st.get("status") in ("done", "stale"), "valider d'abord l'alignement (S2)")

    def dyn_defaults(self, p):
        key = "index_seq_1" if p_base(p) == 1 else "index_seq_0"
        net = lambda rows: ",".join(str(r[key]) for r in rows if r.get("niveau", "nette") == "nette")
        g = p.state["facts"].get("groups")
        if g:
            return {"exclure": " ; ".join(f"{d}: " + net(gg["flagged"]) for d, gg in g.items())}
        return {"exclure": net(p.state["facts"].get("flagged") or [])}

    def poses(self, p):
        """Poses à montrer dans le choix : par appareil, signalées (nettes, mitigées), limites et pose typique."""
        key = "index_seq_1" if p_base(p) == 1 else "index_seq_0"
        f = p.state["facts"]
        st = p.state["steps"].get("S2", {})
        var = (st.get("variants") or [{}])[st.get("chosen") or 0] if st.get("variants") else {}
        ex = var.get("extra", {}) if var else {}
        def pack(src, dev):
            return {"dev": dev, "key": key, "reference": src.get("reference"),
                    "poses": (src.get("flagged") or []) + (src.get("limites") or [])}
        if f.get("groups"):
            gex = ex.get("groups", {})
            return [pack(gex.get(d, g), d) for d, g in f["groups"].items()]
        return [pack(ex if ex.get("flagged") is not None else f, "")]

    def compose_preview(self, ctx, outputs, tag=""):
        k = "stack" if "stack" in outputs else f"stack_{devices(ctx.p)[0]}"
        return ctx.p.abs(outputs[k]) if k in outputs else None

    def run(self, ctx, prm, tag):
        p = ctx.p
        g = p.state["facts"].get("groups")
        if not g:
            return self.run_group(ctx, prm, p.root / "process", p.state["facts"].get("total"),
                                  [int(x) for x in str(prm["exclure"]).replace(";", ",").split(",") if x.strip().isdigit()])
        excl = parse_excl(prm["exclure"])
        out = {"outputs": {}, "info": [], "extra": {"groups": {}}, "images": [], "linear": True}
        for dev in g:
            r = self.run_group(ctx, prm, proc_dir(p, dev), g[dev]["total"], excl.get(dev, []), dev)
            out["outputs"][f"stack_{dev}"] = r["outputs"]["stack"]
            for k in ("stack_lp", "stack_ir"):                 # mode B : un stack par filtre de cet appareil
                if k in r["outputs"]:
                    out["outputs"][f"{k}_{dev}"] = r["outputs"][k]
            out["info"] += [f"— {model(p, dev)} —"] + r["info"]
            out["extra"]["groups"][dev] = r["extra"]
            keys = [k for k in ("stack_lp", "stack_ir") if k in r["outputs"]] if p.mode == "B" else ["stack"]
            for k in keys:
                img = ctx.out(tag, f"{k}_{dev}", ".jpg", folder="apercus")
                fitsio.preview(p.abs(r["outputs"][k]), img, True)
                out["images"].append(ctx.rel(img))
        out["info"].append("Stacks séparés par appareil" + (" et par filtre" if p.mode == "B" else "")
                           + " : prochaine étape, « Combinaison des appareils ».")
        return out

    def run_group(self, ctx, prm, proc, total, excl, dev=""):
        p = ctx.p
        T = p.T + (f"_{dev}" if dev else "")
        for f in proc.glob("r_combined_*"):
            f.unlink()
        cmds = [f"cd {q(proc)}"]
        if excl:
            b = p_base(p)
            cmds.append(f"select combined_ {b} {total - 1 + b}")
            cmds += [f"unselect combined_ {i} {i}" for i in excl]
        filt = f"-filter-round={prm['filter_round']}k"
        if prm["filter_fwhm"] > 0:
            filt += f" -filter-fwhm={prm['filter_fwhm']}k"
        if excl:
            filt += " -filter-included"
        base_cmds = list(cmds)
        cmds.append(f"seqapplyreg combined_ {filt} -framing=max -drizzle -scale=1.0 -pixfrac=1.0 -kernel=square")
        ctx.sir(cmds, cwd=p.root, name=f"seqapplyreg{('_' + dev) if dev else ''}")
        rfiles = sorted(f for f in proc.glob("r_combined_*") if f.suffix.lower() in (".fit", ".fits"))
        cadre_info = []
        if rfiles:
            # -framing=max agrandit le cadre jusqu'à contenir TOUTES les poses : quelques poses très décalées ou mal
            # alignées (autre nuit, autre pointage) le font exploser, et le stack devient vide aux trois quarts
            # (GraXpert et la combinaison des appareils échouent dessus). Cadre démesuré -> cadrage centré.
            h0 = fits.getheader(str(rfiles[0]))
            cw, ch = int(h0.get("NAXIS1") or 0), int(h0.get("NAXIS2") or 0)
            sizes = [s.get("size") for s in p.state.get("sessions", []) if s.get("size")
                     and (not dev or s.get("device") == dev)]
            if sizes and cw and ch:
                fw, fh = max(sizes, key=lambda z: z[0] * z[1])
                ratio = cw * ch / max(fw * fh, 1)
                if ratio > 2.5:
                    for f in proc.glob("r_combined_*"):
                        f.unlink()
                    ctx.sir(base_cmds + [f"seqapplyreg combined_ {filt} -framing=cog -drizzle -scale=1.0 -pixfrac=1.0 -kernel=square"],
                            cwd=p.root, name=f"seqapplyreg_cog{('_' + dev) if dev else ''}")
                    rfiles = sorted(f for f in proc.glob("r_combined_*") if f.suffix.lower() in (".fit", ".fits"))
                    h1 = fits.getheader(str(rfiles[0])) if rfiles else {}
                    cadre_info.append(f"ATTENTION : cadrage maximal démesuré ({cw}x{ch} px pour des poses de {fw}x{fh}, "
                                      f"{ratio:.1f} fois leur surface : quelques poses très décalées ou mal alignées) : "
                                      f"alignement refait avec un cadrage centré, {h1.get('NAXIS1')}x{h1.get('NAXIS2')} px. "
                                      "Les zones vues par trop peu de poses sont laissées de côté.")
        n = len(rfiles)
        if n < 2:
            raise RuntimeError(f"seqapplyreg n'a gardé que {n} pose(s) sur {total}{' pour le ' + dev if dev else ''} : "
                               "l'empilement est impossible. Causes probables : alignement raté à l'étape S2 pour cet "
                               "appareil (trop peu d'étoiles), ou filtre de rondeur trop strict (essaie 3 ou 3.5).")
        info = cadre_info + [f"Poses alignées et retenues : {n} sur {total}" + (f" ({len(excl)} écartées à la main)" if excl else "")]
        stack_cmd = "rej 3 3 -norm=addscale -output_norm -rgb_equal -maximize -feather=5 -weight=noise"
        outputs, extra = {}, {}
        filters = [inventory.norm_filter(fits.getheader(str(f)).get("FILTER"), "") for f in rfiles] if p.mode == "B" else []
        seul = next(iter(set(filters))) if dev and len(set(filters)) == 1 and filters[0] in ("LP", "IRCUT") else None
        if seul:
            # mode B à plusieurs appareils : cet appareil n'a qu'un des deux filtres, un seul stack, rangé à son filtre
            stem = f"{T}_{seul}_stack"
            dropped = stack_retry(ctx, proc, "r_combined_", stack_cmd, f"../{stem}", f"stack_{dev}_{seul}")
            f = _find(p.root, stem)
            if not f:
                raise RuntimeError("stack absent après `stack`")
            hdr = fits.getheader(str(f))
            key = "stack_lp" if seul == "LP" else "stack_ir"
            outputs = {"stack": ctx.rel(f), key: ctx.rel(f)}
            extra = {"stacks": {seul: [int(hdr.get("STACKCNT") or 0), hdr.get("LIVETIME")]}}
            info.append(f"Un seul filtre pour cet appareil ({seul}) : un stack {seul} de {hdr.get('STACKCNT')} poses, "
                        f"{hdr.get('LIVETIME')} s, combiné aux autres stacks {seul} à l'étape suivante.")
            if dropped:
                info.append(drop_info(dropped))
        elif p.mode == "B":
            lp = [i + 1 for i, f in enumerate(filters) if f == "LP"]
            ir = [i + 1 for i, f in enumerate(filters) if f == "IRCUT"]
            if not lp or not ir or lp != list(range(1, len(lp) + 1)):
                raise RuntimeError(f"frontière LP/IRCUT introuvable dans les r_combined_ (LP {len(lp)}, IRCUT {len(ir)}) : "
                                   "l'en-tête FILTER manque ou l'ordre n'est pas LP puis IRCUT")
            # Sélection des poses de chaque filtre dans r_combined_, empilée SANS pondération par le bruit : Siril 1.4
            # plante (0xC0000005) au calcul des pondérations d'une sélection ; des séquences refaites à part sont,
            # elles, refusées (pas de données d'alignement). Observé sur 700 poses Seestar.
            b = p_base(p)
            last = n - 1 + b
            lp_last, ir_first = lp[-1] - 1 + b, ir[0] - 1 + b
            # pas de -maximize : il recadre chaque stack d'après ses propres poses, et LP / IRCUT (autres nuits,
            # autre pointage) n'auraient plus la même taille ; les poses alignées ont déjà toutes la même taille
            cmd_b = " ".join(x for x in stack_cmd.split() if not x.startswith("-weight=") and x != "-maximize") + " -filter-included"
            sel = {"LP": [f"select r_combined_ {b} {last}", f"unselect r_combined_ {ir_first} {last}"],
                   "IRCUT": [f"select r_combined_ {b} {last}", f"unselect r_combined_ {b} {lp_last}"]}
            dropped = [stack_retry(ctx, proc, "r_combined_", cmd_b, f"../{T}_{key}_stack", f"stack_modeB_{key}",
                                   pre=sel[key], post=[f"select r_combined_ {b} {last}"]) for key in ("LP", "IRCUT")]
            info.append("Mode B : empilements sans pondération par le bruit (Siril plante avec une sélection de poses) : "
                        "les poses comptent toutes autant.")
            f_lp, f_ir = _find(p.root, f"{T}_LP_stack"), _find(p.root, f"{T}_IRCUT_stack")
            if not f_lp or not f_ir:
                raise RuntimeError("un des deux stacks manque")
            h1, h2 = fits.getheader(str(f_lp)), fits.getheader(str(f_ir))
            c1, c2 = int(h1.get("STACKCNT", 0)), int(h2.get("STACKCNT", 0))
            dims_ok = (h1.get("NAXIS1"), h1.get("NAXIS2")) == (h2.get("NAXIS1"), h2.get("NAXIS2"))
            info.append(f"Stack LP : {c1} poses, {h1.get('LIVETIME')} s ; stack IRCUT : {c2} poses, {h2.get('LIVETIME')} s")
            if c1 + c2 != n:
                raise RuntimeError(f"contrôle mode B en échec : {c1} poses LP + {c2} IRCUT = {c1 + c2}, alors que {n} poses "
                                   "alignées étaient retenues : une partie n'a pas été empilée (voir le journal de Siril).")
            if not dims_ok:
                # Siril donne à chaque stack d'une sélection son propre cadre : on recale le stack secondaire sur
                # le principal par ses étoiles (même méthode que la combinaison de deux appareils)
                main_f, sec_f, sec_key = (f_lp, f_ir, "IRCUT") if p.type == "nebuleuse" else (f_ir, f_lp, "LP")
                info += recaler(ctx, main_f, sec_f, sec_key)
                h1, h2 = fits.getheader(str(f_lp)), fits.getheader(str(f_ir))
            info.append("Contrôle : STACKCNT LP + IRCUT = poses retenues, mêmes dimensions. OK")
            for key, d in zip(("LP", "IRCUT"), dropped):
                if d:
                    info.append(drop_info(d).replace("ATTENTION : ", f"ATTENTION : stack {key} : ", 1))
            main, sec = (f_lp, f_ir) if p.type == "nebuleuse" else (f_ir, f_lp)
            outputs = {"stack": ctx.rel(main), "stack2": ctx.rel(sec), "stack_lp": ctx.rel(f_lp), "stack_ir": ctx.rel(f_ir)}
            extra = {"stacks": {"LP": [c1, h1.get("LIVETIME")], "IRCUT": [c2, h2.get("LIVETIME")]},
                     "principal": "LP" if p.type == "nebuleuse" else "IRCUT"}
            hdr = fits.getheader(str(main))
            extra.update(stackcnt=c1 + c2, livetime=float(h1.get("LIVETIME") or 0) + float(h2.get("LIVETIME") or 0))
        else:
            stem = f"{T}_stack" if dev else f"{T}_true_combined"
            dropped = stack_retry(ctx, proc, "r_combined_", stack_cmd, f"../{stem}", f"stack{('_' + dev) if dev else ''}")
            f = _find(p.root, stem)
            if not f:
                raise RuntimeError("stack absent après `stack`")
            hdr = fits.getheader(str(f))
            outputs = {"stack": ctx.rel(f)}
            info.append(f"STACKCNT {hdr.get('STACKCNT')} · LIVETIME {hdr.get('LIVETIME')} s")
            if dropped:
                info.append(drop_info(dropped))
        extra.setdefault("stackcnt", hdr.get("STACKCNT"))
        extra.setdefault("livetime", hdr.get("LIVETIME"))
        extra.update(n_aligned=n,
                     dims=[hdr.get("NAXIS1"), hdr.get("NAXIS2")], date=str(hdr.get("DATE-OBS", ""))[:19],
                     ra=hdr.get("RA"), dec=hdr.get("DEC"), focal=hdr.get("FOCALLEN"), pix=hdr.get("XPIXSZ"),
                     excl=excl)
        return {"outputs": outputs, "info": info, "extra": extra, "linear": True}

    def on_validate(self, p, var):
        ex = var.get("extra", {})
        if "groups" in ex:
            gs = p.state["facts"].setdefault("groups", {})
            for d, e in ex["groups"].items():
                gs.setdefault(d, {}).update(e)
            pr = ex["groups"][devices(p)[0]]
            p.state["facts"].update({k: pr.get(k) for k in ("date", "ra", "dec", "focal", "pix", "dims")})
            p.state["facts"].update(n_aligned=sum(e["n_aligned"] for e in ex["groups"].values()),
                                    stackcnt=sum(int(e.get("stackcnt") or 0) for e in ex["groups"].values()),
                                    livetime=sum(float(e.get("livetime") or 0) for e in ex["groups"].values()))
            for k in ("stack", "stack2", "stack_lp", "stack_ir"):
                p.state["files"].pop(k, None)         # les stacks communs viennent de l'étape de combinaison
        else:
            p.state["facts"].update(ex)

    def notes(self, p, st):
        f = p.state["facts"]
        if f.get("groups") and any("stackcnt" in g for g in f["groups"].values()):
            return f"Empilement (filtre rondeur {st['params'].get('filter_round')}k), par appareil : " + " ; ".join(
                f"{model(p, d)} {g.get('stackcnt')} poses, {g.get('livetime')} s" for d, g in f["groups"].items())
        s = (f"Empilement : filtre rondeur {st['params'].get('filter_round')}k, {f.get('n_aligned')} poses retenues, "
             f"STACKCNT {f.get('stackcnt')}, LIVETIME {f.get('livetime')} s")
        if f.get("stacks"):
            s += " ; mode B : " + ", ".join(f"{k} {v[0]} poses / {v[1]} s" for k, v in f["stacks"].items()) + \
                 f" ; stack principal {f.get('principal')}"
        return s


def recaler(ctx, main_f, sec_f, sec_key):
    """Remet le stack secondaire sur la grille du principal (appariement d'étoiles, translation attendue).
    L'original est gardé à côté (…_avant_recalage.fit)."""
    from .. import align
    P_, hp = fitsio.read(main_f)
    S_, hs = fitsio.read(sec_f)
    ctx.log(f"Tailles différentes ({S_.shape[2]}x{S_.shape[1]} contre {P_.shape[2]}x{P_.shape[1]}) : recalage du stack "
            f"{sec_key} sur le principal par ses étoiles")
    t = align.similarity(S_, P_, scale=1.0)
    if t["miroir"] or abs(t["echelle"] - 1) > 0.01 or abs(t["rotation_deg"]) > 0.5 or t["rms_px"] > 1.0:
        raise RuntimeError(f"les deux stacks n'ont pas la même taille et leur recalage est douteux (échelle x{t['echelle']}, "
                           f"rotation {t['rotation_deg']}°, écart résiduel {t['rms_px']} px, {t['etoiles']} étoiles) : "
                           "arrêt plutôt qu'un stack mal superposé")
    Sw, cov = align.warp(S_, t["M"], P_.shape[1:])
    keep = Path(str(sec_f).rsplit(".", 1)[0] + "_avant_recalage.fit")
    shutil.copy2(sec_f, keep)
    hs["NAXIS1"], hs["NAXIS2"] = P_.shape[2], P_.shape[1]
    fitsio.write(sec_f, Sw, hs)
    M = t["M"]
    return [f"Stack {sec_key} recalé sur le principal : les deux stacks n'avaient pas la même taille (cadre propre à "
            f"chaque sélection dans Siril). Décalage {M[0][2]:+.1f} / {M[1][2]:+.1f} px, {t['etoiles']} étoiles communes, "
            f"écart résiduel {t['rms_px']} px. Les bords sans données seront retirés au cadrage."]


CRASH = ("3221225477", "0xc0000005", "segmentation", "-1073741819")


def stack_retry(ctx, folder, seq, stack_cmd, out, name, pre=(), post=()):
    """stack, avec des replis si Siril refuse ou plante, chacun signalé :
    1. plantage (violation d'accès, au calcul des pondérations) -> sans pondération par le bruit ;
    2. refus -> sans -maximize ni -feather.
    Renvoie la liste des options retirées (vide si le premier essai a réussi)."""
    tries = [[], ["-weight="], ["-maximize", "-feather="], ["-maximize", "-feather=", "-weight="]]
    last = None
    for drop in tries:
        cmd = " ".join(x for x in stack_cmd.split() if not any(x.startswith(d) for d in drop))
        if drop and cmd == stack_cmd:
            continue
        try:
            ctx.sir([f"cd {q(folder)}", *pre, f"stack {seq} {cmd} -out={out}", *post], cwd=ctx.p.root,
                    name=name + ("" if not drop else "_sans_" + "_".join(d.strip("-=") for d in drop)))
            return drop
        except Exception as e:
            from ..jobs import Cancelled
            if isinstance(e, Cancelled) or getattr(ctx.job, "cancel_requested", False):
                raise
            last = e
            crash = any(c in str(e).lower() for c in CRASH)
            ctx.log(f"ATTENTION : empilement refusé{' (plantage de Siril)' if crash else ''} : nouvel essai "
                    "avec des options plus simples.")
    raise last


DROP_TEXT = {"-weight=": "sans pondération par le bruit (les poses comptent toutes autant)",
             "-maximize": "sans cadrage maximal", "-feather=": "sans adoucissement des bords"}


def drop_info(drop):
    return ("ATTENTION : Siril a refusé l'empilement avec toutes les options ; refait "
            + ", ".join(DROP_TEXT[d] for d in drop) + ".") if drop else None


def parse_excl(text):
    """« S50: 4,7 ; S30: 2 » -> {"S50": [4, 7], "S30": [2]}"""
    out = {}
    for part in str(text).split(";"):
        if ":" not in part:
            continue
        d, lst = part.split(":", 1)
        out[d.strip()] = [int(x) for x in lst.split(",") if x.strip().isdigit()]
    return out


def p_base(p):
    from .. import config
    return int(config.load().get("select_index_base", 1))


def mesure_alertes(lines):
    """Diagnostic de mesure_stack.py -> alertes (ATTENTION …) avec leur cause, pour que remedies.py propose quoi
    faire et, quand c'est possible, des réglages (filtres de l'empilement S3)."""
    txt = " ".join(lines)
    out = []
    m = re.search(r"FWHM médiane : ([\d.]+) px", txt)
    if m and float(m.group(1)) > 4.5:
        out.append(f"ATTENTION : étoiles larges (FWHM médiane {m.group(1)} px) : turbulence, buée ou mise au point "
                   "sur une partie des poses")
    m = re.search(r"Étoiles allongées : excentricité médiane ([\d.]+)", txt)
    if m:
        cause = ("suivi ou vent" if "UNIFORME" in txt else "rotation de champ" if "TANGENTIEL" in txt
                 else "optique" if "RADIAL" in txt else "causes mélangées")
        out.append(f"ATTENTION : étoiles allongées (excentricité {m.group(1)}), cause probable : {cause}")
    m = re.search(r"Écart de FWHM sur le champ : (\d+)%", txt)
    if m and int(m.group(1)) >= 20:
        cause = ("courbure de champ" if "COURBURE" in txt else "un seul coin" if "UN SEUL COIN" in txt
                 else "inclinaison" if "INCLINAISON" in txt else "sans motif net")
        side = re.search(r"côté ([\w-]+) le plus flou", txt) or re.search(r"UN SEUL COIN FLOU \(([\w-]+)", txt)
        out.append(f"ATTENTION : finesse des étoiles inégale sur le champ ({m.group(1)} %"
                   + (f", côté {side.group(1)} le plus flou" if side else "") + f"), cause probable : {cause}")
    return out


class Mesure(Step):
    id, phase, optional = "S4", "Stacking", True
    title = "Mesure du stack (FWHM, S/N)"
    help = ("Contrôle de qualité du stack avant le traitement : cette étape ne modifie rien, elle mesure.\n"
            "• Carte de finesse des étoiles (FWHM) et de leur forme : si les étoiles sont larges ou allongées, partout ou "
            "dans un coin, l'appli donne la cause probable (poses floues ou bougées, optique, rotation de champ) et, sous "
            "l'alerte, ce qu'il faut faire, avec un bouton qui y mène : refaire l'empilement (S3) en écartant les poses en "
            "cause, ou laisser BlurXTerminator (P3) et le cadrage (P0) s'en charger.\n"
            "• Carte du signal/bruit : où l'image est propre ou bruitée. Avec une zone dessinée sur une partie faible de "
            "l'objet, elle dit combien de temps de pose il faudrait en plus pour qu'elle devienne propre : utile pour "
            "décider s'il vaut la peine de refaire une nuit.\n"
            "Sans alerte orange, il n'y a rien à corriger : valide et continue. L'étape peut aussi être passée.")
    params = [P("zones", "Zones à mesurer", "text", "",
                help="se remplit en dessinant sur l'image ci-dessus (nom:x,y,largeur,hauteur, origine en haut à gauche)")]

    def ready(self, p):
        return (p.file("stack") is not None, "pas encore de stack")

    def run(self, ctx, prm, tag):
        p = ctx.p
        out = p.root / "essais" / f"mesure_r{ctx.run_no}{tag}"
        out.mkdir(parents=True, exist_ok=True)
        args = [p.file("stack"), "--cible", p.T, "--sortie", out]
        for z in [z.strip() for z in prm["zones"].split(";") if z.strip()]:
            args += ["--zone", z]
        ctx.py("mesure_stack.py", args)
        txt = out / f"mesure_{p.T}.txt"
        lines = txt.read_text(encoding="utf-8").splitlines() if txt.exists() else []
        imgs = [ctx.rel(f) for f in sorted(out.glob("*.png"))]
        info = list(lines) + mesure_alertes(lines)
        return {"outputs": {}, "info": info, "images": imgs, "extra": {"mesure": lines}}

    def on_validate(self, p, var):
        p.state["facts"]["mesure"] = var.get("extra", {}).get("mesure", [])

    def notes(self, p, st):
        return "Mesure du stack :\n" + "\n".join("  " + l for l in p.state["facts"].get("mesure", []))


STEPS = [Inventaire(), Alignement(), Empilement(), Mesure()]

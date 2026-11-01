"""Phase 1, linéaire : cadrage, fond, calibration des couleurs, netteté, débruitage (outils au choix : outils.py)."""
from pathlib import Path

import numpy as np

from .. import checks, config, fitsio, outils
from ..siril import q
from .base import P, Step


def stem(path):
    return q(Path(path).with_suffix(""))


def fix_ext(path):
    """Siril peut écrire .fits selon ses réglages : ramener au nom attendu en .fit."""
    path = Path(path)
    if path.exists():
        return path
    for ext in (".fits", ".fts", ".FIT"):
        alt = path.with_suffix(ext)
        if alt.exists():
            alt.replace(path)
            return path
    raise RuntimeError(f"Siril n'a pas écrit {path.name}")


def tool(ctx, inp, out, commands, name):
    """load <inp> ; <commandes> ; save <out>  — en un seul appel Siril."""
    ctx.sir([f"load {q(inp)}"] + commands + [f"save {stem(out)}"], name=name)
    out = fix_ext(out)
    # un script Python qui échoue sans le dire laisse l'image intacte, et Siril l'enregistre quand même
    scripts = [c.split('"')[1] for c in commands if c.startswith("pyscript") and '"' in c]
    if scripts and len(commands) == 1:
        a, _ = fitsio.read(inp)
        b, _ = fitsio.read(out)
        if a.shape == b.shape and np.allclose(a[:, ::7, ::7], b[:, ::7, ::7], atol=1e-6):
            raise RuntimeError(f"{scripts[0]} n'a rien modifié (script absent, licence, ou erreur non signalée par "
                               "Siril) : voir le journal")
    return out


def five_boxes(data, hdr):
    rgb = fitsio.display(data, hdr)
    H, W = rgb.shape[:2]
    b = 150
    boxes = {"centre": (W // 2 - b // 2, H // 2 - b // 2), "haut-g": (20, 20), "haut-d": (W - b - 20, 20),
             "bas-g": (20, H - b - 20), "bas-d": (W - b - 20, H - b - 20)}
    out = []
    for k, (x, y) in boxes.items():
        r = rgb[y:y + b, x:x + b]
        out.append(f"{k} {'/'.join(str(int(np.median(r[..., c]) * 65535)) for c in range(3))}")
    return "Médianes R/V/B (zéros compris) : " + " · ".join(out)


class Cadrage(Step):
    id, phase, kind = "P0", "1 · Linéaire", "creatif"
    title = "Recadrage et cadrage"
    help = ("Retire les bords de l'empilement (bruités et colorés, ils fausseraient la suite) et fixe le cadrage de "
            "l'image. Dessine le cadre à la souris sur l'image ci-dessous : glisse pour un nouveau cadre, attrape le "
            "cadre pour le déplacer, ses poignées pour le redimensionner ; un format (carré, 3:2, 16:9…) peut être imposé. "
            "Le cadre proposé au départ retire seulement les bords. Repère d'abord ce qu'il ne faut pas couper : étoile "
            "marquante, noyau, galaxies satellites. Ce recadrage sert aussi d'« image brute » dans la fiche.")
    params = [P("rect", "Rectangle x, y, l, h (affiché)", "rect", None)]
    preview_key = "crop"
    canonical = {"crop": "{T}_crop.fit"}
    interaction = "crop"
    reference_step = "S3"

    def reference_for(self, p):
        st = p.state["steps"].get("S3B", {})
        return "S3B" if st.get("status") in ("done", "stale") else "S3"
    produces = ("crop",)

    def ready(self, p):
        return (p.file("stack") is not None, "pas encore de stack (S3)")

    def dyn_defaults(self, p):
        f = p.file("stack")
        if not f:
            return {}
        cache = p.state["facts"].get("crop_suggest")
        if cache and cache[0] == str(f) and cache[1] == f.stat().st_mtime:
            return {"rect": cache[2]}
        data, hdr = fitsio.read(f)
        r = fitsio.suggest_crop(data, hdr)
        p.state["facts"]["crop_suggest"] = [str(f), f.stat().st_mtime, r]
        p.save()
        return {"rect": r}

    def run(self, ctx, prm, tag):
        p = ctx.p
        src = p.file("stack")
        rect = prm.get("rect") or self.dyn_defaults(p)["rect"]
        x, y, w, h = [int(v) for v in rect]
        data, hdr = fitsio.read(src)
        H = data.shape[1]
        out = ctx.out(tag, "crop")
        origin = ctx.cfg.get("crop_y_origin", "haut")
        ys = y if origin == "haut" else H - y - h
        tool(ctx, src, out, ["boxselect -clear", f"crop {x} {ys} {w} {h}"], "cadrage")
        info = []
        verdict = _check_crop(data, hdr, out, x, y, w, h)
        if verdict == "inverse":
            other = "bas" if origin == "haut" else "haut"
            ctx.log(f"Le recadrage ne correspond pas à la zone demandée : Siril compte y depuis le {other}. "
                    "Réglage corrigé et recadrage refait.")
            config.set_value("crop_y_origin", other)
            ctx.cfg["crop_y_origin"] = other
            ys = y if other == "haut" else H - y - h
            tool(ctx, src, out, ["boxselect -clear", f"crop {x} {ys} {w} {h}"], "cadrage_corrige")
            verdict = _check_crop(data, hdr, out, x, y, w, h)
            info.append(f"Convention de Siril détectée et enregistrée : y compté depuis le {other}.")
        if verdict != "ok":
            info.append("ATTENTION : impossible de confirmer que le recadrage correspond au rectangle demandé.")
        d2, h2 = fitsio.read(out)
        info.append(f"Recadrage {x} {y} {w} {h} (y depuis le haut) → {d2.shape[2]}x{d2.shape[1]} px")
        info.append(five_boxes(d2, h2))
        if not h2.get("PLTSOLVD") and not h2.get("CTYPE1"):
            info.append("Pas de plate-solve dans l'en-tête : SPCC le refera (platesolve -force).")
        info += checks.cut_objects(data, hdr, [x, y, w, h])
        info += checks.borders_left(d2, h2, "le recadrage")
        return {"outputs": {"crop": ctx.rel(out)}, "info": info, "extra": {"rect": [x, y, w, h]}}

    def on_validate(self, p, var):
        p.state["facts"]["crop"] = var.get("extra", {}).get("rect")

    def notes(self, p, st):
        return f"Recadrage : x y w h = {' '.join(map(str, p.state['facts'].get('crop') or []))} (y depuis le haut) → T_crop"


def _check_crop(data, hdr, out, x, y, w, h):
    """Compare la sortie de Siril à la zone attendue (sens affiché) ; détecte une convention y inversée."""
    try:
        got, gh = fitsio.read(out)
        g = fitsio.display(got, gh).mean(2)
        full = fitsio.display(data, hdr).mean(2)
        H = full.shape[0]
        if g.shape != (h, w):
            return "inconnu"

        def corr(a, b):
            a, b = a[::4, ::4].ravel(), b[::4, ::4].ravel()
            if a.std() == 0 or b.std() == 0:
                return 0
            return float(np.corrcoef(a, b)[0, 1])
        c_ok = corr(g, full[y:y + h, x:x + w])
        yb = H - y - h
        c_inv = corr(g, full[yb:yb + h, x:x + w]) if 0 <= yb <= H - h else -1
        if c_ok >= 0.98:
            return "ok"
        if c_inv >= 0.98 and c_inv > c_ok:
            return "inverse"
        return "inconnu"
    except Exception:
        return "inconnu"


class GraXpert(Step):
    id, phase = "P1", "1 · Linéaire"
    help = ("Retire les dégradés du fond du ciel (pollution lumineuse, Lune). Sur une galaxie, vérifie sur un zoom "
            "que les bras extérieurs et le halo sont toujours là ; sinon, monte le lissage. L'outil se choisit dans "
            "Réglages > Outils (GraXpert, Siril, commande personnalisée, ou aucun).")
    params = [P("smoothing", "Lissage", "float", 1.0, 0, 1, 0.05)]
    preview_key = "bge"
    canonical = {"bge": "{T}_BGE.fit"}
    optional = True
    produces = ("bge",)

    @property
    def title(self):
        return f"Extraction du fond ({outils.nom(config.load(), 'fond')})"

    def applies(self, p):
        ok, why = outils.sans_objet(config.load(), "fond")
        if not ok:
            return ok, why
        st = p.state["steps"].get("S3B", {})
        m = p.state["facts"].get("multi") or {}
        if st.get("status") in ("done", "stale") and m.get("graxpert") and not m.get("fond_rate"):
            return False, "fond déjà extrait de chaque stack avant la combinaison des appareils"
        return True, ""

    def ready(self, p):
        return (p.file("crop") is not None, "valider d'abord le cadrage (P0)")

    def run(self, ctx, prm, tag):
        out = ctx.out(tag, "BGE")
        tool(ctx, ctx.p.file("crop"), out, outils.commandes(ctx.cfg, "fond", prm["smoothing"]), "fond")
        d, h = fitsio.read(out)
        return {"outputs": {"bge": ctx.rel(out)}, "info": [five_boxes(d, h)]}

    def notes(self, p, st):
        return f"Extraction du fond : {outils.nom(config.load(), 'fond')}, lissage {st['params'].get('smoothing')}"


def principal_profile(p):
    from .. import materiel
    from .stacking import devices
    devs = devices(p) or [s.get("device") for s in p.state.get("sessions", [])][:1]
    dev = p.state.get("principal") or (devs[0] if devs else "inconnu")
    return dev, materiel.profile(dev, p=p, sample=materiel._sample(p, dev))


class SPCC(Step):
    id, phase, kind = "P2", "1 · Linéaire", "creatif"
    title = "Calibration des couleurs (SPCC)"
    help = ("Calibre les couleurs d'après les étoiles du champ (Siril identifie le champ, puis compare aux couleurs "
            "connues des étoiles). « Large bande » pour un filtre large (UV/IR cut, IRCUT, sans filtre), « bande étroite » "
            "pour un filtre bi-bande seul (LP, L-eXtreme…). Si les deux sont empilés ensemble (mode A), aucun réglage ne "
            "correspond : passe l'étape. Le capteur et le filtre viennent de la fiche Matériel ; sans capteur connu, "
            "Siril fait une calibration photométrique plus simple (PCC). La correction S50 Pro compense la réponse de "
            "son capteur (rouge x1.128, bleu x1.041).")
    params = [P("type", "Type", "choice", "large", choices=[["large", "Large bande"], ["etroite", "Bande étroite (bi-bande)"]]),
              P("correction", "Correction S50 Pro (fiche Matériel)", "bool", False)]
    preview_key = "spcc"
    canonical = {"spcc": "{T}_SPCC.fit"}
    optional = True
    produces = ("spcc",)

    def dyn_defaults(self, p):
        filt = {s.get("filter") for s in p.state.get("sessions", [])}
        _, prof = principal_profile(p)
        return {"correction": prof.get("correction") == "s50pro", "type": "etroite" if filt == {"LP"} else "large"}

    def ready(self, p):
        return (p.latest("bge", "crop") is not None, "valider d'abord le cadrage")

    def run(self, ctx, prm, tag):
        p = ctx.p
        src = p.latest("bge", "crop")
        out = ctx.out(tag, "SPCC")
        dev, prof = principal_profile(p)
        cat = " -catalog=localgaia" if ctx.cfg.get("spcc_catalog_local", True) else ""
        sensor = str(prof.get("capteur_spcc") or "").strip()
        info = []
        if not sensor:
            cmd = "pcc" + cat
            info.append(f"Capteur de « {prof.get('nom')} » non renseigné (fiche Matériel) : calibration photométrique "
                        "simple (PCC) à la place de SPCC.")
        elif prm["type"] == "large":
            cmd = (f'spcc "-oscsensor={sensor}" "-oscfilter={prof.get("filtre_spcc") or "UV/IR Block"}"{cat} '
                   '"-whiteref=Average Spiral Galaxy"')
        else:
            cmd = (f'spcc "-oscsensor={sensor}" -narrowband -rwl=656.28 -rbw=20 -gwl=500.70 -gbw=30 '
                   f'-bwl=500.70 -bbw=30{cat} "-whiteref=Average Spiral Galaxy"')
        tool(ctx, src, out, ["platesolve -force", cmd], "spcc")
        if p.mode == "A":
            info.append("ATTENTION : filtres bi-bande + large bande mélangés (mode A) : aucun mode SPCC ne correspond.")
        d, h = fitsio.read(out)
        info.append("Après calibration : " + five_boxes(d, h))
        if prm["correction"]:
            d2, txt = s50pro_correction(d)
            fitsio.write(out, d2, h)
            info.append(txt)
            info.append("Après correction : " + five_boxes(d2, h))
        return {"outputs": {"spcc": ctx.rel(out)}, "info": info}

    def notes(self, p, st):
        prm = st.get("params", {})
        _, prof = principal_profile(p)
        base = f"SPCC {prm.get('type')} ({prof.get('capteur_spcc')})" if prof.get("capteur_spcc") else "PCC (capteur inconnu)"
        return base + (" + correction S50 Pro (R x1.128, B x1.041)" if prm.get("correction") else "")


def s50pro_correction(d):
    """(canal − fond) × facteur + fond (couleurs.md) ; fond mesuré sur le ciel, pixels nuls exclus."""
    out = d.copy()
    parts = []
    for c, k in ((0, 1.128), (2, 1.041)):
        f = fitsio.sky_level(d[c])
        out[c] = np.clip((d[c] - f) * k + f, 0, 1) * (d[c] > 0)
        parts.append(f"{'RVB'[c]} fond {f:.5f} x{k}")
    return out, "Correction S50 Pro : " + ", ".join(parts)


class BXT(Step):
    id, phase, kind = "P3", "1 · Linéaire", "creatif"
    help = ("Renforce la netteté (déconvolution). Avec BlurXTerminator : réglage « marqué » (0.75 / 0.4) ou plus doux "
            "(0.5 / 0.25). Avec Siril : plus d'itérations = plus net, mais des anneaux sombres peuvent apparaître autour "
            "des étoiles. Juge sur un zoom avec une zone fine et une étoile brillante ; sur une galaxie, surveille le noyau. "
            "Outil : Réglages > Outils.")
    params = [P("sn", "Netteté de la nébuleuse ou de la galaxie", "float", 0.75, 0, 1, 0.05, show_if={"_outil": ["rcastro", "perso"]},
                help="détails de l'objet (filaments, bras, poussières) : plus haut = plus net, mais trop fort donne un "
                     "aspect granuleux ou « dessiné » (option --sn de BlurXTerminator ; avec une commande personnalisée : "
                     "valeur de {force})"),
              P("ss", "Netteté et finesse des étoiles", "float", 0.4, 0, 1, 0.05, show_if={"_outil": ["rcastro"]},
                help="resserre les étoiles (plus petites, plus rondes) : trop fort peut créer un anneau sombre autour "
                     "des plus brillantes (option --ss)"),
              P("ansp", "Mesurer le flou de l'image automatiquement (conseillé)", "bool", True, show_if={"_outil": ["rcastro"]},
                help="BlurXTerminator mesure lui-même le flou de ton image (turbulence, mise au point) pour régler la "
                     "netteté de l'objet ; décoché, il suppose un flou standard qui peut être faux pour ton instrument "
                     "(option --ansp : « automatic non-stellar PSF »)"),
              P("iters", "Itérations (Richardson-Lucy)", "int", 10, 2, 40, 1, show_if={"_outil": ["siril"]})]
    default_variants = [{"sn": 0.75, "ss": 0.4, "iters": 10}, {"sn": 0.5, "ss": 0.25, "iters": 6}]
    preview_key = "bxt"
    canonical = {"bxt": "{T}_BXT.fit"}
    optional = True
    produces = ("bxt",)

    @property
    def title(self):
        return f"Netteté ({outils.nom(config.load(), 'nettete')})"

    def applies(self, p):
        return outils.sans_objet(config.load(), "nettete")

    def dyn_defaults(self, p):
        return {"_outil": outils.choix(config.load(), "nettete")}

    def ready(self, p):
        return (p.latest("spcc", "bge", "crop") is not None, "valider d'abord le cadrage")

    def run(self, ctx, prm, tag):
        out = ctx.out(tag, "BXT")
        src = ctx.p.latest("spcc", "bge", "crop")
        tool(ctx, src, out, outils.commandes(ctx.cfg, "nettete", prm["sn"], ss=prm["ss"], ansp=prm["ansp"],
                                             iters=prm["iters"]), "nettete")
        return {"outputs": {"bxt": ctx.rel(out)}, "info": checks.noise_change(src, out, "après netteté")}

    def notes(self, p, st):
        x = st["params"]
        c = outils.choix(config.load(), "nettete")
        if c == "rcastro":
            return f"Netteté : BlurXTerminator --sn {x.get('sn')} --ss {x.get('ss')}" + (" --ansp" if x.get("ansp") else "")
        if c == "siril":
            return f"Netteté : déconvolution Richardson-Lucy de Siril, {x.get('iters')} itérations"
        return f"Netteté : {outils.nom(config.load(), 'nettete')} (force {x.get('sn')})"


class NXTLin(Step):
    id, phase, kind = "P4", "1 · Linéaire", "creatif"
    help = ("Débruitage sur l'image entière, étoiles comprises. 0.5 doux, 0.8 net, 0.9 fort (risque d'aspect "
            "« plastique ») : c'est le zoom qui décide. Outil : Réglages > Outils (NoiseXTerminator, GraXpert, Siril…).")
    params = [P("dn", "Force", "float", 0.8, 0, 1, 0.05)]
    default_variants = [{"dn": 0.5}, {"dn": 0.8}, {"dn": 0.9}]
    preview_key = "nxt"
    canonical = {"nxt": "{T}_nxt.fit"}
    optional = True
    produces = ("nxt",)

    @property
    def title(self):
        return f"Débruitage linéaire ({outils.nom(config.load(), 'debruitage')})"

    def applies(self, p):
        return outils.sans_objet(config.load(), "debruitage")

    def ready(self, p):
        return (p.latest("bxt", "spcc", "bge", "crop") is not None, "valider d'abord le cadrage")

    def run(self, ctx, prm, tag):
        out = ctx.out(tag, "nxt")
        src = ctx.p.latest("bxt", "spcc", "bge", "crop")
        tool(ctx, src, out, outils.commandes(ctx.cfg, "debruitage", prm["dn"]), "debruitage")
        d, _ = fitsio.read(out)
        return {"outputs": {"nxt": ctx.rel(out)},
                "info": [f"bruit de fond par canal R/V/B (ADU) : {noise(d)}"] + checks.noise_change(src, out, "après débruitage", "baisse")}

    def notes(self, p, st):
        return f"Débruitage linéaire : {outils.nom(config.load(), 'debruitage')} {st['params'].get('dn')}, image entière"


def noise(d):
    vals = []
    for c in range(d.shape[0]):
        v = d[c][::2, ::2]
        v = v[v > 0]
        lo = v[v <= np.percentile(v, 50)]
        med = np.median(lo)
        vals.append(int(1.4826 * np.median(np.abs(lo - med)) * 65535))
    return "/".join(map(str, vals))


STEPS = [Cadrage(), GraXpert(), SPCC(), BXT(), NXTLin()]

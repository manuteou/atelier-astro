"""Combinaison de stacks de plusieurs appareils (ex. deux télescopes sur la même cible).

Par appareil : recadrage des bords peu couverts (comme l'étape 0, sinon GraXpert est faussé), GraXpert.
Puis chaque stack secondaire est aligné sur le principal (étoiles, échelle et rotation comprises), remis à sa
géométrie, égalisé canal par canal sur le principal (même fond, même réponse couleur : la calibration couleur
se fait ensuite une seule fois, sur le résultat, avec le profil du principal) et combiné en linéaire, chaque
stack pondéré par son bruit mesuré. Les pixels non couverts par un secondaire gardent le principal seul.
"""
import json
from pathlib import Path

import numpy as np

from .. import align, checks, fitsio, outils
from .base import P, Step
from .lineaire import tool
from .stacking import devices, is_multi, model


def _crop_borders(data, hdr):
    rect = fitsio.suggest_crop(data, hdr)
    x, y, w, h = rect
    H = data.shape[1]
    r0 = y if fitsio.top_down(hdr) else H - (y + h)
    out = data[:, r0:r0 + h, x:x + w]
    hd = hdr.copy()
    for k in list(hd.keys()):
        if k.startswith(("CRPIX", "CRVAL", "CD1_", "CD2_", "CDELT", "CTYPE", "PC1_", "PC2_", "PLTSOLVD", "A_", "B_", "AP_", "BP_")):
            hd.remove(k, remove_all=True)
    return out, hd, rect


def _cached(ctx, dev, kind, src, params, make):
    """Résultat intermédiaire réutilisé tant que la source et les réglages n'ont pas changé (évite de relancer
    GraXpert pour chaque variante)."""
    d = ctx.p.root / "essais"
    out = d / f"{ctx.p.T}_S3B_{dev}_{kind}.fit"
    meta = out.with_suffix(".json")
    key = {"src": str(src), "mtime": Path(src).stat().st_mtime, **params}
    if out.exists() and meta.exists():
        try:
            if json.loads(meta.read_text()) == key:
                return out
        except Exception:
            pass
    make(out)
    meta.write_text(json.dumps(key))
    return out


def _pix_scale(p, dev, hdr):
    """Secondes d'arc par pixel d'un stack : en-tête (FOCALLEN, XPIXSZ), sinon fiche Matériel."""
    from .. import materiel
    try:
        f, px = float(hdr.get("FOCALLEN") or 0), float(hdr.get("XPIXSZ") or 0)
    except (TypeError, ValueError):
        f = px = 0
    prof = materiel.profile(dev, p=p, sample=materiel._sample(p, dev))
    f = f or float(prof.get("focale") or 0)
    px = px or float(prof.get("pixel") or 0)
    if f and px:
        return 206.265 * px / f
    return 1000.0 / f if f else None          # pixels inconnus : rapport des focales seul (même capteur supposé)


class Combinaison(Step):
    id, phase, kind = "S3B", "Stacking", "creatif"
    title = "Combinaison des appareils"
    help = ("Réunit les stacks de tes différents appareils. Chacun est recadré de ses bords et passe dans GraXpert ; "
            "les autres sont ensuite alignés sur l'appareil principal (par les étoiles, échelle et rotation comprises), "
            "ramenés à son fond et à ses couleurs, puis combinés, chacun pesant selon son bruit et sa finesse. Compare "
            "toujours au « principal seul » sur un zoom : un instrument plus petit apporte du signal mais des détails moins fins. "
            "Pas encore essayé sur tes données.")
    params = [
        P("mode", "Résultat", "choice", "combinaison",
          choices=[["combinaison", "Combinaison pondérée"], ["principal", "Principal seul"], ["secondaire", "Autre(s) appareil(s) seul(s)"]]),
        P("poids", "Poids des autres appareils (x auto)", "float", 1.0, 0, 3, 0.05, show_if={"mode": ["combinaison"]},
          help="1 = pondération par le bruit mesuré ; moins pour privilégier la finesse du principal"),
        P("graxpert", "Extraire le fond de chaque stack avant (outil de Réglages > Outils)", "bool", True),
        P("smoothing", "Lissage", "float", 1.0, 0, 1, 0.05, show_if={"graxpert": [True]}),
    ]
    default_variants = [{"mode": "combinaison", "poids": 1.0}, {"mode": "combinaison", "poids": 0.5}, {"mode": "principal"}]
    preview_key = "stack"
    canonical = {"stack": "{T}_multi_combined.fit"}

    def applies(self, p):
        return (is_multi(p), "un seul appareil dans ce projet")

    def ready(self, p):
        ok = all(p.file(f"stack_{d}") for d in devices(p))
        return ok, "valider d'abord l'empilement par appareil (S3)"

    def _prepare(self, ctx, dev, prm):
        src = ctx.p.file(f"stack_{dev}")

        def mk_crop(out):
            d, h = fitsio.read(src)
            c, hd, rect = _crop_borders(d, h)
            fitsio.write(out, c, hd)
            ctx.log(f"{dev} : bords retirés, rectangle {rect}")
        cur = _cached(ctx, dev, "crop", src, {"bords": 2}, mk_crop)
        if prm["graxpert"] and outils.actif(ctx.cfg, "fond"):
            def mk_bge(out):
                tool(ctx, cur, out, outils.commandes(ctx.cfg, "fond", prm["smoothing"]), f"fond_{dev}")
            cur = _cached(ctx, dev, "bge", cur, {"smoothing": prm["smoothing"], "outil": outils.choix(ctx.cfg, "fond")}, mk_bge)
        return cur

    def run(self, ctx, prm, tag):
        p = ctx.p
        devs = devices(p)
        pr = devs[0]
        files = {d: self._prepare(ctx, d, prm) for d in (devs if prm["mode"] != "principal" else devs[:1])}
        P_, hdr = fitsio.read(files[pr])
        H, W = P_.shape[1:]
        info, details = [], {}
        sp = align.noise(P_)
        info.append(f"{model(p, pr)} (principal) : {W}x{H} px, bruit de fond {sp * 65535:.1f} ADU")
        num = P_ * (P_.max(0) > 0)
        wP = 1.0 / max(sp, 1e-9) ** 2
        den = np.full((H, W), wP, np.float32) * (P_.max(0) > 0)
        num = num * wP
        sec_only, sec_cov = np.zeros_like(P_), np.zeros((H, W), bool)
        sc = {d: _pix_scale(p, d, fitsio.header(files[d])) for d in files}
        for d in (devs[1:] if prm["mode"] != "principal" else []):
            S, hs = fitsio.read(files[d])
            expected = sc[d] / sc[pr] if sc.get(d) and sc.get(pr) else None
            t = align.similarity(S, P_, scale=expected)
            msg = (f"{model(p, d)} aligné sur {model(p, pr)} : {t['etoiles']} étoiles communes, écart résiduel "
                   f"{t['rms_px']} px, échelle x{t['echelle']}, rotation {t['rotation_deg']}°" + (", image miroir" if t["miroir"] else ""))
            info.append(msg)
            if expected:
                if abs(t["echelle"] / expected - 1) > 0.05:
                    info.append(f"ATTENTION : échelle mesurée x{t['echelle']} alors que focales et pixels donnent x{expected:.3f} "
                                "(alignement à vérifier sur le zoom)")
            if t["rms_px"] > 1.0:
                info.append("ATTENTION : écart résiduel au-dessus de 1 px : étoiles possiblement doublées, vérifier le zoom.")
            Sw, cov = align.warp(S, t["M"], (H, W))
            Sm, coefs = align.linear_match(Sw, P_, cov, blur=0.5 * t["echelle"])
            ss_native = align.noise(S) / max(np.mean([c[0] for c in coefs]), 1e-6)
            # Un pixel natif du secondaire couvre echelle² pixels du principal : à surface égale il apporte
            # echelle² fois moins de mesures indépendantes, d'où le poids divisé par echelle².
            k2 = max(t["echelle"], 1.0) ** 2
            wS = prm["poids"] / (max(ss_native, 1e-9) ** 2 * k2) if prm["mode"] == "combinaison" else 0.0
            covf = cov.astype(np.float32)
            num += wS * Sm * covf
            den += wS * covf
            sec_only += Sm * covf
            sec_cov |= cov
            info.append(f"  couverture du champ principal : {cov.mean() * 100:.0f} % · égalisation R/V/B (pente, décalage) {coefs}")
            info.append(f"  bruit de fond natif {ss_native * 65535:.1f} ADU (ramené au principal), un de ses pixels couvre "
                        f"{k2:.1f} pixels du principal → poids relatif {(wS / wP) if wP else 0:.2f}")
            details[d] = {**t, "egalisation": coefs, "poids_relatif": round(wS / wP, 3), "couverture": round(float(cov.mean()), 3)}
        if prm["mode"] == "principal":
            out_data = P_
            info.append("Résultat : principal seul (référence de comparaison).")
        elif prm["mode"] == "secondaire":
            out_data = np.where(sec_cov[None], sec_only, 0).astype(np.float32)
            info.append("Résultat : autre(s) appareil(s) seul(s), remis à la géométrie du principal.")
        else:
            out_data = np.where(den[None] > 0, num / np.maximum(den[None], 1e-12), 0).astype(np.float32)
            rel = sum(v["poids_relatif"] for v in details.values())
            info.append(f"Gain théorique sur le bruit de fond : x{np.sqrt(1 + rel):.2f} (indicatif : le stack agrandi a un "
                        "bruit corrélé, le gain réel sur les petits détails est plus faible).")
            info.append(f"Bruit haute fréquence mesuré : {sp * 65535:.1f} → {align.noise(out_data) * 65535:.1f} ADU "
                        "(le lissage de l'agrandissement y contribue).")
        hd = hdr.copy()
        lt = float(hdr.get("LIVETIME") or 0)
        if prm["mode"] == "combinaison" and lt:
            eq = lt * (1 + sum(v["poids_relatif"] for v in details.values()))
            hd["LIVETIME"] = (round(eq, 1), "equivalent principal (combinaison multi-appareils)")
            info.append(f"LIVETIME de l'en-tête : {eq:.0f} s, équivalent en temps du principal (pour les estimations de S/N) ; "
                        "la fiche donne le temps réel par appareil.")
        hd["HISTORY"] = "Atelier astro : combinaison " + " + ".join(model(p, d) for d in devs)
        out = ctx.out(tag, "multi")
        fitsio.write(out, out_data, hd)
        if prm["mode"] == "combinaison" and sec_cov.any():
            info += checks.doubled_stars(out_data, ref=P_)
        imgs = []
        if prm["mode"] == "combinaison" and 0.02 < sec_cov.mean() < 0.98:     # carte utile seulement si partielle
            m = ctx.out(tag, "couverture", ".jpg", folder="apercus")
            from PIL import Image
            Image.fromarray((np.flipud(sec_cov) if not fitsio.top_down(hdr) else sec_cov).astype(np.uint8) * 255).save(m)
            imgs.append(ctx.rel(m))
        return {"outputs": {"stack": ctx.rel(out)}, "info": info, "images": imgs, "linear": True,
                "extra": {"multi": {"mode": prm["mode"], "poids": prm["poids"], "graxpert": prm["graxpert"],
                                    "smoothing": prm["smoothing"], "appareils": details, "principal": pr}}}

    def on_validate(self, p, var):
        p.state["facts"]["multi"] = var["extra"]["multi"]

    def notes(self, p, st):
        m = p.state["facts"].get("multi") or {}
        s = f"Combinaison des appareils : {m.get('mode')}"
        if m.get("mode") == "combinaison":
            s += f", poids x{m.get('poids')}"
        s += " ; GraXpert par stack" + (f" (lissage {m.get('smoothing')})" if m.get("graxpert") else " : non")
        for d, v in (m.get("appareils") or {}).items():
            s += (f" ; {model(p, d)} aligné sur {model(p, m.get('principal'))} (échelle x{v['echelle']}, "
                  f"rotation {v['rotation_deg']}°, {v['etoiles']} étoiles, écart {v['rms_px']} px, poids relatif {v['poids_relatif']})")
        return s


STEPS = [Combinaison()]

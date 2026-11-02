"""Phase 3 : bicolore Hα / OIII (P8B), facultatif, filtre bi-bande (LP) seulement.

Le calque sans étoiles est séparé en deux calques mono : Hα (canal rouge) et OIII (moyenne du vert et du bleu). Chacun
reçoit son propre traitement, puis ils sont recombinés avec les couleurs choisies (deux couleurs au choix, ou les
palettes HOO et cuivre-bleu). Le résultat sert d'entrée à l'étape Couleurs (P8), qui propose alors « aucune » couleur.

Ordre, gaz par gaz : débruitage (avant tout gain : on ne grossit pas le bruit), retrait de la part d'Hα mêlée à l'OIII, gain du signal au-dessus du fond,
luminosité (courbe sur le seul signal), contraste local (Hα). Le fond du ciel garde son niveau.
"""

import numpy as np

from .. import checks, color_ops, fitsio, outils
from .base import P, Step
from .couleurs import fused_preview, galaxy_layer
from .lineaire import tool

# palettes : contribution (R, V, B) d'une unité de signal Hα et d'une unité de signal OIII au-dessus du fond
# (mêmes coefficients que palette_narrowband.py ; cuivre-bleu sans SII : SII remplacé par Hα)
PALETTES = {"hoo": ((1.0, 0.0, 0.15), (0.0, 1.0, 1.0)),
            "cuivre_bleu": ((1.7, 0.75, 0.0), (0.0, 0.5, 1.4))}


def a_du_lp(p):
    """(utilisable, avertissement) : il faut des poses au filtre bi-bande dans le stack utilisé."""
    filtres = {str(s.get("filter", "")).upper() for s in p.state.get("sessions", [])}
    if "LP" not in filtres:
        return False, "pas de poses au filtre bi-bande (LP) : l'Hα et l'OIII ne sont pas séparables"
    if p.mode == "C" and p.state.get("filtre_c") != "LP":
        return False, "mode C avec le filtre large bande : l'Hα et l'OIII ne sont pas séparables"
    if p.mode == "A" and "IRCUT" in filtres:
        return True, ("INFO : poses LP et large bande empilées ensemble (mode A) : la séparation Hα / OIII est moins "
                      "nette (le large bande mêle toutes les couleurs) ; le mode B, ou C avec le LP, donne des calques plus purs.")
    return True, ""


def _mono(d):
    return d[0] if d.ndim == 3 else d


def _fond(x, mask):
    return float(np.median(x[mask])) if mask.any() else float(np.percentile(x, 20))


def _debruite(ctx, x, h, force, nom, info):
    """Débruitage d'un calque mono : outil de Réglages > Outils, sinon lissage interne des zones faibles."""
    if force <= 0:
        return x
    if outils.actif(ctx.cfg, "debruitage"):
        src, dst = ctx.out("", f"{nom}_avant_debruitage"), ctx.out("", f"{nom}_debruite")
        fitsio.write(src, x[None], h)
        try:
            tool(ctx, src, dst, outils.commandes(ctx.cfg, "debruitage", round(float(force), 2)), f"bicolore_debruitage_{nom}")
            y, _ = fitsio.read(dst)
            y = _mono(y)
            if y.shape == x.shape and np.isfinite(y).all():
                return y.astype(np.float32)
            info.append(f"ATTENTION : débruitage {nom} : sortie inattendue de l'outil, lissage interne utilisé")
        except Exception as e:                           # outil absent ou en échec : on continue, et on le dit
            from ..jobs import Cancelled
            if isinstance(e, Cancelled):
                raise
            info.append(f"ATTENTION : débruitage {nom} par {outils.nom(ctx.cfg, 'debruitage')} impossible ({str(e)[:80]}) : "
                        "lissage interne utilisé")
    import cv2
    fl = cv2.GaussianBlur(x, (0, 0), 1.2 + 1.8 * force)
    sig = cv2.GaussianBlur(x, (0, 0), 6)
    lo, hi = np.percentile(sig, 50), np.percentile(sig, 99)
    faible = 1 - np.clip((sig - lo) / max(hi - lo, 1e-6), 0, 1)      # les zones faibles sont lissées davantage
    k = float(np.clip(force, 0, 1)) * (0.4 + 0.6 * faible)
    return (x * (1 - k) + fl * k).astype(np.float32)


def part_ha(Ha, O, fh, fo):
    """Part d'Hα mêlée au calque OIII : rapport OIII / Hα (lissés) le plus bas observé là où l'Hα est fort (5e centile
    sur les 10 % de pixels à l'Hα le plus fort) : on suppose qu'une partie de ces zones n'a presque pas d'OIII."""
    import cv2
    hs = cv2.GaussianBlur(Ha - fh, (0, 0), 3)
    os_ = cv2.GaussianBlur(O - fo, (0, 0), 3)
    fort = hs > np.percentile(hs, 90)
    if fort.sum() < 100 or float(np.median(hs[fort])) <= 1e-4:
        return 0.0
    return float(np.clip(np.percentile(os_[fort] / np.maximum(hs[fort], 1e-6), 5), 0, 0.9))


def _signal(x, fond, gain, lum):
    """Signal au-dessus du fond : multiplié par le gain, puis courbe de luminosité (1 = inchangé) ; le fond ne bouge pas."""
    s = (x - fond) * gain
    pos = np.clip(s / max(1 - fond, 1e-6), 0, 1) ** (1 / max(lum, 0.05)) * (1 - fond)
    return np.where(s > 0, pos, s).astype(np.float32)          # sous le fond (bruit) : inchangé, pour garder un ciel naturel


def _couleur(hexa):
    c = color_ops.hex_rgb(hexa)
    return c / max(float(c.max()), 1e-6)


class Bicolore(Step):
    id, phase, kind, optional = "P8B", "3 · Couleurs et export", "creatif", True
    title = "Bicolore Hα / OIII (filtre LP)"
    help = ("Sépare le calque sans étoiles en deux gaz : l'Hα (le rouge du filtre LP) et l'OIII (le bleu-vert), montrés "
            "en noir et blanc sous chaque variante. Chacun a son propre traitement : l'OIII, plus faible et plus bruité, "
            "est débruité d'abord (avant son gain, pour ne pas grossir le bruit ; la force proposée tient compte du "
            "débruitage déjà fait en P4), puis amplifié ; l'Hα supporte du contraste local. Ils sont ensuite réunis "
            "avec deux couleurs que tu choisis, ou les palettes HOO (rouge / turquoise) et cuivre-bleu. Le résultat "
            "part vers l'étape Couleurs (P8), qui propose alors « aucune » couleur : tu peux la passer ou y ajouter une "
            "touche. Étape facultative, seulement avec le filtre bi-bande.")
    params = [
        P("palette", "Couleurs", "choice", "perso",
          choices=[["perso", "Deux couleurs au choix"], ["hoo", "Palette HOO (rouge / turquoise)"],
                   ["cuivre_bleu", "Palette cuivre-bleu"]]),
        P("c_ha", "Couleur de l'Hα", "color", "#ff5a2a", show_if={"palette": ["perso"]}),
        P("c_oiii", "Couleur de l'OIII", "color", "#26c4e8", show_if={"palette": ["perso"]}),
        P("ha_lum", "Hα : luminosité", "float", 1.0, 0.6, 1.8, 0.05, help="éclaircit ou assombrit le signal Hα, sans toucher au fond"),
        P("ha_contraste", "Hα : contraste local (relief)", "float", 0.0, 0, 1, 0.05,
          help="relief des filaments et des bords des nuages sombres, dans l'Hα seulement"),
        P("ha_debruit", "Hα : débruitage", "float", 0.0, 0, 1, 0.05,
          help="en général inutile : le débruitage de P4 suffit pour l'Hα, le signal le plus fort"),
        P("oiii_pur", "OIII : retirer l'Hα qui s'y mêle", "float", 1.0, 0, 1, 0.05,
          help="le vert et le bleu contiennent aussi une part d'Hα : sans ce retrait, l'OIII se superpose partout à "
               "l'Hα et les deux couleurs se mélangent en gris ou blanc. La part est mesurée sur les zones où l'Hα "
               "domine ; 1 = retirée entièrement, 0 = séparation brute"),
        P("oiii_debruit", "OIII : débruitage (avant le gain)", "float", 0.4, 0, 1, 0.05,
          help="proposé d'après la force retenue en P4 : plus P4 était fort, plus celui-ci est léger, pour éviter un "
               "aspect lissé « plastique »"),
        P("oiii_gain", "OIII : gain", "float", 1.6, 0.5, 4.0, 0.1,
          help="fait ressortir l'OIII (souvent bien plus faible que l'Hα) ; son bruit monte d'autant"),
        P("oiii_lum", "OIII : luminosité", "float", 1.0, 0.6, 1.8, 0.05),
        P("force", "Force", "float", 1.0, 0.1, 1.0, 0.05,
          help="1 = couleurs bicolores pures ; plus bas, mélange avec les couleurs d'origine (des couleurs opposées "
               "mélangées tirent vers le gris)"),
    ]
    default_variants = [{"palette": "perso"}, {"palette": "perso", "oiii_gain": 2.4},
                        {"palette": "cuivre_bleu"}, {"palette": "hoo"}]
    preview_key = "bicolore"
    linear = False
    reference_step = "P7T"
    canonical = {"bicolore": "{T}_bicolore.fit"}
    produces = ("bicolore",)

    def applies(self, p):
        ok, msg = a_du_lp(p)
        return (ok, "" if ok else msg)

    def ready(self, p):
        return (p.file("naturel") is not None, "valider d'abord l'image naturelle (P7T)")

    def dyn_defaults(self, p):
        st = p.state["steps"].get("P4", {})
        dn = (st.get("params") or {}).get("dn") if st.get("status") in ("done", "stale") else None
        if dn is None:
            return {"oiii_debruit": 0.5}
        dn = float(dn)
        return {"oiii_debruit": 0.2 if dn >= 0.8 else (0.35 if dn >= 0.6 else 0.5)}

    def compose_preview(self, ctx, outputs, tag=""):
        return fused_preview(ctx, ctx.p.abs(outputs["bicolore"]), tag)

    def run(self, ctx, prm, tag):
        p = ctx.p
        src = galaxy_layer(p)
        d, h = fitsio.read(src)
        if d.shape[0] < 3:
            raise ValueError("le calque sans étoiles n'est pas en couleur : pas d'Hα / OIII à séparer")
        info = []
        _, avert = a_du_lp(p)
        if avert:
            info.append(avert)
        mask = fitsio.sky_mask(d)
        Ha, O = d[0].astype(np.float32), ((d[1] + d[2]) / 2).astype(np.float32)
        fh, fo = _fond(Ha, mask), _fond(O, mask)
        sh = float(np.percentile(Ha, 99) - fh)
        alpha = part_ha(Ha, O, fh, fo)
        info.append(f"Séparation : Hα = rouge, OIII = moyenne vert + bleu ; part d'Hα mêlée à l'OIII mesurée {alpha:.2f}, "
                    f"retirée à {100 * prm['oiii_pur']:.0f} %")
        # traitement séparé : débruitage d'abord (avant le gain)
        o_av = ctx.out(tag, "oiii_avant")
        fitsio.write(o_av, O[None], h)
        Hd = _debruite(ctx, Ha, h, prm["ha_debruit"], f"Ha_{tag}", info)
        Od = _debruite(ctx, O, h, prm["oiii_debruit"], f"OIII_{tag}", info)
        if prm["oiii_debruit"] > 0:                    # effet du débruitage seul, avant le retrait de l'Hα
            o_ap = ctx.out(tag, "oiii_debruite")
            fitsio.write(o_ap, Od[None], h)
            info += [l.replace("grain du fond", "grain de l'OIII") for l in
                     checks.noise_change(o_av, o_ap, "après son débruitage", expect="baisse")]
        if prm["oiii_pur"] > 0:
            Od = (Od - prm["oiii_pur"] * alpha * (Hd - fh)).astype(np.float32)
        so = float(np.percentile(Od, 99) - fo)
        info.append(f"Signal fort (99e percentile au-dessus du fond) : Hα {sh:.3f}, OIII {so:.3f} "
                    f"({100 * so / max(sh, 1e-6):.0f} % de l'Hα)")
        st4 = p.state["steps"].get("P4", {})
        dn4 = float((st4.get("params") or {}).get("dn") or 0) if st4.get("status") in ("done", "stale") else 0.0
        if dn4 + prm["oiii_debruit"] > 1.3:
            info.append(f"ATTENTION : débruitage cumulé fort sur l'OIII (P4 {dn4:g} + ici {prm['oiii_debruit']:g}) : "
                        "risque d'aspect lissé « plastique » ; regarde la bulle OIII au zoom, ou baisse l'un des deux.")
        h_sig = _signal(Hd, fh, 1.0, prm["ha_lum"])
        o_sig = _signal(Od, fo, prm["oiii_gain"], prm["oiii_lum"])
        if prm["ha_contraste"] > 0:
            r = color_ops.box_radius(Ha.shape[1])
            det = h_sig - color_ops.box_blur3(h_sig, r)
            w = np.clip(h_sig / max(sh, 1e-6), 0, 1)                 # relief dans le signal, pas dans le ciel
            h_sig = h_sig + 1.5 * prm["ha_contraste"] * det * w
        # recombinaison
        if prm["palette"] == "perso":
            ca, co = _couleur(prm["c_ha"]), _couleur(prm["c_oiii"])
            noms = f"Hα {prm['c_ha']}, OIII {prm['c_oiii']}"
        else:
            ca, co = (np.array(v, np.float32) for v in PALETTES[prm["palette"]])
            noms = {"hoo": "palette HOO", "cuivre_bleu": "palette cuivre-bleu"}[prm["palette"]]
        fond = (fh + fo) / 2
        y = fond + ca[:, None, None] * h_sig[None] + co[:, None, None] * o_sig[None]
        y = np.clip(y, 0, 1).astype(np.float32)
        k = float(np.clip(prm["force"], 0, 1))
        out_data = (d[:3] * (1 - k) + y * k).astype(np.float32)
        o = ctx.out(tag, "bicolore")
        fitsio.write(o, out_data, h)
        info.append(f"Recombinaison : {noms}, force {k:g} ; OIII gain x{prm['oiii_gain']:g}, luminosité Hα "
                    f"{prm['ha_lum']:g} / OIII {prm['oiii_lum']:g} ; fond du ciel gardé à {fond:.3f}")
        ec = float((out_data.max(0) >= 0.995).mean() * 100)
        if ec > 0.5:
            info.append(f"ATTENTION : {ec:.1f} % des pixels saturés au maximum : baisse le gain ou la luminosité")
        info += checks.noise_change(src, o, "après bicolore")
        # aperçus noir et blanc des deux gaz traités
        imgs = []
        for nom, sig, f0 in (("Ha", h_sig, fh), ("OIII", o_sig, fo)):
            j = ctx.out(tag, f"gaz_{nom}", ".jpg", folder="apercus")
            mono = np.clip(f0 + sig, 0, 1)
            fitsio.save_jpeg(fitsio.display(np.stack([mono] * 3), h), j, quality=90, width=900)
            imgs.append(ctx.rel(j))
        return {"outputs": {"bicolore": ctx.rel(o)}, "info": info, "images": imgs}

    def notes(self, p, st):
        x = st.get("params", {})
        pal = (f"couleurs Hα {x.get('c_ha')} / OIII {x.get('c_oiii')}" if x.get("palette") == "perso"
               else {"hoo": "palette HOO", "cuivre_bleu": "palette cuivre-bleu"}.get(x.get("palette"), x.get("palette")))
        return (f"Bicolore Hα / OIII : {pal}, force {x.get('force')} ; Hα luminosité {x.get('ha_lum')}, contraste "
                f"{x.get('ha_contraste')}, débruitage {x.get('ha_debruit')} ; OIII débruitage {x.get('oiii_debruit')}, "
                f"gain {x.get('oiii_gain')}, luminosité {x.get('oiii_lum')}, Hα retiré de l'OIII {x.get('oiii_pur')}")


STEPS = [Bicolore()]

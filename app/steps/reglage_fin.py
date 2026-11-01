"""Phase 3 (2/4) : réglage fin des couleurs en direct (P8F). La formule est dans color_ops.tune, recopiée
en JavaScript (web/js/etapes/reglage_fin.js) pour l'aperçu instantané."""
from .. import color_ops, fitsio
from .base import P, Step
from .couleurs import clipped_pct, fused_preview, sky_of, stars_final


FINE = ("temperature", "teinte", "rotation", "saturation", "vibrance", "luminosite", "noirs", "proteger_fond")


class ReglageFin(Step):
    id, phase, kind, optional, single = "P8F", "3 · Couleurs et export", "creatif", True, True
    title = "Réglage fin des couleurs (en direct)"
    help = ("Part de la variante validée à l'étape Couleurs et l'ajuste finement : chaque curseur modifie l'aperçu "
            "immédiatement (aperçu réduit, avec les étoiles). Température : plus chaud (orangé) ou plus froid (bleu). "
            "Teinte : vers le magenta ou vers le vert. Rotation : fait tourner toutes les couleurs. Saturation : toutes "
            "les couleurs ; vibrance : surtout les couleurs encore ternes. Luminosité : éclaircit les tons moyens. "
            "Noirs : assombrit le fond. « Protéger le fond » laisse le ciel tel quel (seul l'objet change). Quand ça te "
            "plaît : « Appliquer en pleine résolution », puis valide.")
    params = [
        P("temperature", "Température (froid <-> chaud)", "float", 0.0, -1, 1, 0.02),
        P("teinte", "Teinte (vert <-> magenta)", "float", 0.0, -1, 1, 0.02),
        P("rotation", "Rotation des couleurs (°)", "float", 0.0, -40, 40, 1),
        P("saturation", "Saturation", "float", 0.0, -0.6, 1.0, 0.02),
        P("vibrance", "Vibrance (couleurs ternes)", "float", 0.0, 0, 1.0, 0.02),
        P("luminosite", "Luminosité des tons moyens", "float", 1.0, 0.6, 1.6, 0.01),
        P("noirs", "Noirs (assombrir le fond)", "float", 0.0, 0, 0.15, 0.005),
        P("proteger_fond", "Protéger le fond du ciel", "bool", True),
    ]
    default_variants = [{}]
    preview_key = "G_fin"
    linear = False
    interaction = "live"
    reference_step = "P8"
    canonical = {"G_fin": "{T}_G_fin.fit"}
    produces = ("G_fin",)

    def ready(self, p):
        return (p.file("G_final") is not None, "valider d'abord les couleurs (P8)")

    def compose_preview(self, ctx, outputs, tag=""):
        return fused_preview(ctx, ctx.p.abs(outputs["G_fin"]), tag)

    def run(self, ctx, prm, tag):
        p = ctx.p
        d, h = fitsio.read(p.file("G_final"))
        sky = sky_of(d)
        y = color_ops.tune(d, prm, sky)
        o = ctx.out(tag, "G_fin")
        fitsio.write(o, y, h)
        s = fitsio.stats(y)
        info = [f"Médianes R/V/B : {s['medianes']} · niveau du ciel mesuré {sky:.3f}"]
        c0, c1 = clipped_pct(d), clipped_pct(y)
        if c1 > c0 + 0.3:
            info.append(f"ATTENTION : zones saturées après réglage fin : {c1:.1f} % des pixels au maximum (avant : {c0:.1f} %)")
        if prm.get("noirs", 0) > 0 and not prm.get("proteger_fond", True):
            L = y.mean(0)
            z = float((L <= 0.002).mean() * 100)
            if z > 2:
                info.append(f"ATTENTION : noir écrasé après réglage fin : {z:.1f} % des pixels à zéro")
        return {"outputs": {"G_fin": ctx.rel(o)}, "info": info}

    def notes(self, p, st):
        prm = st.get("params", {})
        base = {"temperature": 0, "teinte": 0, "rotation": 0, "saturation": 0, "vibrance": 0, "luminosite": 1, "noirs": 0}
        ch = [f"{k} {prm[k]}" for k in base if k in prm and float(prm[k]) != base[k]]
        return "Réglage fin des couleurs : " + (", ".join(ch) if ch else "aucun changement") + \
               (" (fond protégé)" if prm.get("proteger_fond", True) else "")


def live_sources(p, width=1400):
    """Aperçus réduits (sens affiché) du calque couleur validé et des étoiles, pour le réglage en direct dans le navigateur."""
    g = p.file("G_final")
    if not g:
        raise ValueError("valider d'abord les couleurs (P8)")
    s = stars_final(p)
    d, h = fitsio.read(g)
    sky = sky_of(d)
    out = {"sky": sky, "w": int(d.shape[2]), "h": int(d.shape[1])}
    folder = p.root / "apercus"
    folder.mkdir(exist_ok=True)
    stamp = int(g.stat().st_mtime)
    base = folder / f"{p.T}_P8F_live_{stamp}.jpg"
    if not base.exists():
        for old in folder.glob(f"{p.T}_P8F_live_*.jpg"):
            old.unlink(missing_ok=True)
        fitsio.save_jpeg(fitsio.display(d, h), base, quality=95, width=width)
    out["base"] = p.rel(base)
    if s:
        sb = folder / f"{p.T}_P8F_live_{stamp}_{int(s.stat().st_mtime)}_etoiles.jpg"
        if not sb.exists():
            sd, sh = fitsio.read(s)
            fitsio.save_jpeg(fitsio.display(sd, sh), sb, quality=95, width=width)
        out["stars"] = p.rel(sb)
    return out


STEPS = [ReglageFin()]

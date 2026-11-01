"""Phase 3 (4/4) : retouches locales (P11) : éditeur dans le navigateur, contrôle « rien hors des cercles »."""
import numpy as np

from .. import fitsio
from .base import P, Step


def retouch_check(before, after, lines):
    """Contrôle : rien n'a bougé hors des cercles demandés, et chaque cercle a bien modifié quelque chose."""
    a, ha = fitsio.read(before)
    b, _ = fitsio.read(after)
    diff = np.abs(fitsio.display(b, ha) - fitsio.display(a, ha)).max(2) > 1e-5
    H, W = diff.shape
    yy, xx = np.mgrid[0:H, 0:W]
    inside = np.zeros_like(diff)
    out = []
    for i, l in enumerate(lines, 1):
        x, y, r = float(l[1]), float(l[2]), float(l[3])
        disc = (xx - x) ** 2 + (yy - y) ** 2 <= (r + 1.5) ** 2
        inside |= disc
        n = int((diff & disc).sum())
        if n == 0:
            out.append(f"INFO : retouche {i} ({l[0]} {int(x)} {int(y)}) n'a rien changé : pas de vert en trop à cet endroit, "
                       "ou version naturelle identique")
    outside = int((diff & ~inside).sum())
    if outside:
        out.append(f"ATTENTION : {outside} pixels modifiés hors des cercles demandés")
    else:
        out.insert(0, f"OK : {int(diff.sum())} pixels modifiés, tous dans les cercles ; rien d'autre n'a changé")
    return out


def retouch_sources(p):
    """Image actuelle et version naturelle en pleine résolution (sens affiché) pour l'éditeur de retouches."""
    cur, nat = p.latest("fusion_nxt", "fusion"), p.latest("naturel_nxt", "naturel")
    if not cur:
        raise ValueError("valider d'abord la fusion (P9)")
    folder = p.root / "apercus"
    folder.mkdir(exist_ok=True)
    out = {}
    for key, src in (("image", cur), ("naturel", nat)):
        if not src:
            continue
        jpg = folder / f"{p.T}_P11_{key}_{int(src.stat().st_mtime)}.jpg"
        if not jpg.exists():
            for old in folder.glob(f"{p.T}_P11_{key}_*.jpg"):
                old.unlink(missing_ok=True)
            d, h = fitsio.read(src)
            fitsio.save_jpeg(fitsio.display(d, h), jpg, quality=95)
        out[key] = p.rel(jpg)
    d, _ = fitsio.read(cur)
    out.update(w=int(d.shape[2]), h=int(d.shape[1]))
    return out


class Retouches(Step):
    id, phase, kind, optional = "P11", "3 · Couleurs et export", "creatif", True
    title = "Retouches locales"
    help = ("Facultative : seulement si tu vois un petit défaut en regardant l'image de près. Sinon, « Passer l'étape ». "
            "Deux corrections : un point vert (souvent au centre d'une galaxie) ou un anneau coloré autour d'une étoile "
            "brillante (la zone est reprise de la version naturelle). Choisis l'outil, zoome avec la molette, clique sur le "
            "défaut : le cercle montre la zone corrigée et la correction s'affiche tout de suite. Ensuite « Appliquer », "
            "compare avec la référence, valide.")
    params = [P("liste", "Retouches (une par ligne : vert|remplace x y rayon)", "textarea", "")]
    preview_key = "fusion_ret"
    linear = False
    single = True
    interaction = "retouche"
    reference_step = "P9"
    canonical = {"fusion_ret": "{T}_fusion_retouche.fit", "naturel_ret": "{T}_fusion_naturel_retouche.fit"}
    produces = ("fusion_ret", "naturel_ret")

    def ready(self, p):
        return (p.file("fusion") is not None, "valider d'abord la fusion (P9)")

    def run(self, ctx, prm, tag):
        p = ctx.p
        cur = p.latest("fusion_nxt", "fusion")
        nat = p.latest("naturel_nxt", "naturel")
        lines = [l.split() for l in prm["liste"].splitlines() if l.strip()]
        if not lines:
            raise ValueError("aucune retouche : clique sur un défaut dans l'image, ou « Passer l'étape » s'il n'y en a pas")
        info = []
        for i, l in enumerate(lines):
            mode, x, y, r = l[0], int(float(l[1])), int(float(l[2])), int(float(l[3]))
            o = ctx.out(tag, f"ret{i}")
            if mode == "vert":
                ctx.py("retouche_locale.py", ["vert", cur, o, x, y, r])
                o2 = ctx.out(tag, f"nat{i}")
                ctx.py("retouche_locale.py", ["vert", nat, o2, x, y, r])
                nat = o2
            elif mode == "remplace":
                ctx.py("retouche_locale.py", ["remplace", cur, o, x, y, r, nat])
            else:
                raise ValueError(f"mode inconnu : {mode}")
            info.append(f"{mode} x {x}, y {y} (depuis le haut), r {r}")
            cur = o
        info += retouch_check(p.latest("fusion_nxt", "fusion"), cur, lines)
        out_nat = nat if str(nat) != str(p.latest("naturel_nxt", "naturel")) else None
        outs = {"fusion_ret": ctx.rel(cur)}
        if out_nat:
            outs["naturel_ret"] = ctx.rel(out_nat)
        return {"outputs": outs, "info": info}

    def notes(self, p, st):
        lines = [l for l in st["params"].get("liste", "").splitlines() if l.strip()]
        return f"Retouches locales : {len(lines)} (" + " ; ".join(lines) + ")"


STEPS = [Retouches()]

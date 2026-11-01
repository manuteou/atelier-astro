"""Contrôles automatiques (la partie mécanique du travail de l'agent astro-controle).

Chaque fonction renvoie des lignes « OK … » ou « ATTENTION … » avec ce que ça veut dire, affichées sous
l'aperçu de la variante. Les mesures sont faites toujours de la même façon ; le jugement esthétique reste
à l'utilisateur. Coordonnées : image affichée, x depuis la gauche, y depuis le haut.
"""
import numpy as np
from scipy import ndimage as ndi

from . import fitsio


def _lum_display(data, hdr):
    return fitsio.display(data, hdr).mean(2)


# ------------------------------------------------------------- bords ---
def borders_left(data, hdr, label="l'image", zeros_only=False):
    """Bords d'alignement restés (bandes vides, plus sombres ou plus claires sur le pourtour).
    zeros_only : seulement les bandes vides (image étirée, où un dégradé de fond n'est pas un bord)."""
    H, W = data.shape[1:]
    if zeros_only:
        L = _lum_display(data, hdr)
        side = {"gauche": L[:, :6], "droite": L[:, -6:], "haut": L[:6, :], "bas": L[-6:, :]}
        bad = [k for k, v in side.items() if (v <= 0).mean() > 0.2]
        if bad:
            return [f"ATTENTION bande vide sur le bord de {label} ({', '.join(bad)}) : liseré d'alignement resté, "
                    "recadrer un peu plus serré."]
        return ["OK        aucune bande vide sur les bords."]
    x, y, w, h = fitsio.suggest_crop(data, hdr, tol=0.05)
    step = max(4, min(H, W) // 100)
    m = {"gauche": x - step, "haut": y - step, "droite": W - (x + w) - step, "bas": H - (y + h) - step}
    bad = {k: v for k, v in m.items() if v > 2 * step}
    if bad:
        return [f"ATTENTION bords d'alignement restants sur {label} : " +
                ", ".join(f"{k} ~{v} px" for k, v in bad.items()) +
                " — bandes bruitées ou colorées : recadrer un peu plus serré de ce côté."]
    return ["OK        aucun bord d'alignement visible sur le pourtour."]


# ------------------------------------------------------- objet coupé ---
def cut_objects(data, hdr, rect):
    """Avant recadrage : l'objet principal ou une étoile très brillante touche-t-il le bord du rectangle ?"""
    x, y, w, h = [int(v) for v in rect]
    L = _lum_display(fitsio.autostretch(data), hdr)
    H, W = L.shape
    out = []
    # objet étendu : zone lumineuse à grande échelle (nébuleuse, galaxie)
    big = ndi.gaussian_filter(L, max(H, W) / 80)
    valid = big[big > 0]
    if valid.size:
        thr = np.percentile(valid, 97)
        lab, n = ndi.label(big > thr)
        if n:
            sizes = ndi.sum(np.ones_like(L), lab, range(1, n + 1))
            k = int(np.argmax(sizes)) + 1
            ys, xs = np.nonzero(lab == k)
            bx0, bx1, by0, by1 = xs.min(), xs.max(), ys.min(), ys.max()
            inside = (bx0 >= x and bx1 <= x + w and by0 >= y and by1 <= y + h)
            if not inside:
                part = ((np.clip(xs, x, x + w) == xs) & (np.clip(ys, y, y + h) == ys)).mean()
                out.append(f"ATTENTION la partie la plus lumineuse de l'objet (x {bx0}–{bx1}, y {by0}–{by1}) dépasse du "
                           f"cadre : {100 * (1 - part):.0f} % en est coupé.")
    # étoiles très brillantes : halo coupé par le bord
    Ls = ndi.gaussian_filter(L, 2)
    peaks = (Ls == ndi.maximum_filter(Ls, 15)) & (Ls > np.percentile(Ls, 99.95))
    ys, xs = np.nonzero(peaks)
    order = np.argsort(-Ls[ys, xs])[:5]
    for i in order:
        px, py = int(xs[i]), int(ys[i])
        r = 25
        d = min(px - x, x + w - px, py - y, y + h - py)
        if -r < d < r:
            out.append(f"ATTENTION étoile très brillante en x {px}, y {py} à {d} px du bord du cadre : son halo sera coupé.")
    if not out:
        out.append("OK        l'objet principal et les étoiles les plus brillantes sont dans le cadre.")
    return out


# --------------------------------------------------- étoiles doublées ---
def _echo(data, max_shift=15):
    """Pic secondaire de l'autocorrélation du calque d'étoiles : (force, contraste, dx, dy).
    Le rayon minimal suit la taille des étoiles, pour qu'une étoile simplement large ou un peu ovale ne passe
    pas pour un doublement."""
    L = data[:3].mean(0) if data.shape[0] >= 3 else data[0]
    H, W = L.shape
    c = 1024
    y0, x0 = max(0, H // 2 - c // 2), max(0, W // 2 - c // 2)
    L = L[y0:y0 + c, x0:x0 + c]
    hp = np.clip(L - ndi.median_filter(L, 9), 0, None)
    thr = np.percentile(hp, 99.5)
    hp = np.where(hp > thr, hp, 0)
    if hp.max() <= 0:
        return None
    F = np.fft.rfft2(hp)
    ac = np.fft.fftshift(np.fft.irfft2(F * np.conj(F), s=hp.shape))
    cy, cx = np.array(ac.shape) // 2
    ac = ac / ac[cy, cx]
    yy, xx = np.mgrid[-max_shift:max_shift + 1, -max_shift:max_shift + 1]
    win = ac[cy - max_shift:cy + max_shift + 1, cx - max_shift:cx + max_shift + 1].copy()
    rr = np.hypot(yy, xx)
    prof = [win[np.abs(rr - r) < 0.5].mean() for r in range(0, max_shift)]
    r_half = next((r for r, v in enumerate(prof) if v < 0.5), 3)
    r_min = max(3.5, 2.0 * r_half)
    win[rr < r_min] = 0
    k = np.unravel_index(np.argmax(win), win.shape)
    peak, dy, dx = float(win[k]), int(yy[k]), int(xx[k])
    ring = win[(rr >= r_min) & (np.abs(rr - rr[k]) < 1.5)]
    contrast = peak - float(np.median(ring)) if ring.size else peak
    return peak, contrast, dx, dy


def doubled_stars(data, ref=None):
    """Étoiles doublées ou décalées (fusion de calques, combinaison d'appareils). Avec `ref` (la même image sans
    le second calque), l'alerte ne sort que si l'écho apparaît avec la combinaison."""
    e = _echo(data)
    if e is None:
        return []
    peak, contrast, dx, dy = e
    if not (peak > 0.2 and contrast > 0.12):
        return [f"OK        pas d'étoiles doublées (écho maximal {peak:.2f})."]
    if ref is not None:
        er = _echo(ref)
        if er is not None and er[0] >= peak - 0.08:
            return [f"OK        pas de doublement dû à la combinaison : le même écho ({er[0]:.2f}) existe déjà dans "
                    "l'image de référence seule — c'est la forme des étoiles (un peu ovales), pas un décalage."]
    return [f"ATTENTION étoiles doublées ou décalées : beaucoup d'étoiles ont un « écho » à environ {abs(dx)} px en x "
            f"et {abs(dy)} px en y (force {peak:.2f}). Les calques ne sont pas superposés : vérifier sur un zoom étoilé."]


# -------------------------------------------------------- grain ---
def noise(data):
    from .align import noise as n
    return n(data)


def noise_change(before, after, label, expect=None):
    """Évolution du grain du fond entre deux fichiers du même domaine (linéaire / étiré)."""
    a, _ = fitsio.read(before)
    b, _ = fitsio.read(after)
    na, nb = noise(a), noise(b)
    if na <= 0:
        return []
    ch = (nb / na - 1) * 100
    txt = f"grain du fond {label} : {na * 65535:.1f} → {nb * 65535:.1f} ADU ({ch:+.0f} %)"
    if expect == "baisse" and ch > -5:
        return [f"ATTENTION {txt} : le débruitage n'a presque rien changé (licence, script, réglage trop faible ?)."]
    if expect != "baisse" and ch > 40:
        return [f"ATTENTION {txt} : le fond devient nettement plus granuleux ; un débruitage final peut être utile."]
    return [f"OK        {txt}."]


# ---------------------------------------------------- noir écrasé ---
def crushed_blacks(data):
    z = [float((data[c] <= 0).mean() * 100) for c in range(data.shape[0])]
    if max(z) > 5:
        return [f"ATTENTION noir écrasé : {max(z):.1f} % des pixels sont à zéro sur au moins un canal — le signal le plus "
                "faible du fond est perdu. Fond cible un peu plus haut, ou fond « neutre » plutôt que « noir »."]
    return []


# ------------------------------------------------- export conforme ---
def export_matches(jpg, fit_path, other_fit, rotation, mirror, label):
    """Le JPEG exporté est-il bien la version voulue (et pas l'autre) ?"""
    from PIL import Image
    im = np.asarray(Image.open(jpg).convert("RGB"), np.float32) / 255
    if mirror:
        im = im[:, ::-1]
    k = {0: 0, 90: 1, 180: 2, 270: 3}[int(rotation) % 360]
    im = np.rot90(im, k)

    def diff(path):
        d, h = fitsio.read(path)
        ref = fitsio.display(d, h)
        if ref.shape[:2] != im.shape[:2]:
            return 1.0
        return float(np.abs(ref[::4, ::4] - im[::4, ::4]).mean())
    d1 = diff(fit_path)
    d2 = diff(other_fit) if other_fit and str(other_fit) != str(fit_path) else None
    if d1 > 0.02:
        return [f"ATTENTION {label} : le JPEG ne correspond pas à la version choisie (écart moyen {d1 * 255:.1f}/255)."]
    if d2 is not None and d2 + 1e-4 < d1:
        return [f"ATTENTION {label} : le JPEG ressemble plus à l'autre version — naturelle et colorisée interverties ?"]
    return [f"OK        {label} : conforme à la version choisie (écart {d1 * 255:.1f}/255)."]

"""Halos et reflets laissés par les étoiles brillantes sur le calque sans étoiles (après StarXTerminator).

Trois défauts, trois corrections, toutes locales (le reste de l'image n'est pas touché) :
- cœur résiduel (croissant ou disque clair à la place d'une étoile très brillante) : remplacé par le fond environnant
  (moyenne lissée des pixels voisins), avec un grain de même force que le bruit autour pour ne pas faire de tache lisse ;
- lueur autour de l'étoile : la partie à symétrie circulaire (profil radial bas, 25e percentile par anneau) est
  retirée jusqu'au rayon où elle se fond dans le ciel ; la nébuleuse, qui n'est pas circulaire autour de l'étoile,
  passe au travers ;
- reflet (fantôme : disque ou anneau décalé de l'étoile, souvent bleuté sur un Seestar) : l'utilisateur l'entoure
  d'un cercle ; dans le disque, les grandes échelles sont remplacées par le fond interpolé depuis l'extérieur, les
  détails fins (nébuleuse, grain) sont gardés."""
import numpy as np
import cv2


def profil(img, cx, cy, R, q=25, pas=2.0):
    """Percentile q par anneau de largeur `pas` autour de (cx, cy), jusqu'à R. img : (C, H, W).
    Retourne (rayons, profils (C, n), fenêtre (y0, y1, x0, x1), carte des distances de la fenêtre)."""
    C, H, W = img.shape
    y0, y1 = max(0, int(cy - R)), min(H, int(cy + R) + 1)
    x0, x1 = max(0, int(cx - R)), min(W, int(cx + R) + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    r = np.hypot(xx - cx, yy - cy)
    nb = int(R / pas) + 1
    m = r < R
    k = (r[m] / pas).astype(int)
    order = np.argsort(k, kind="stable")
    cuts = np.searchsorted(k[order], np.arange(nb + 1))
    prof = np.full((C, nb), np.nan)
    for c in range(C):
        v = img[c, y0:y1, x0:x1][m][order]
        for b in range(nb):
            s = v[cuts[b]:cuts[b + 1]]
            if len(s) >= 6:
                prof[c, b] = np.percentile(s, q)
    return (np.arange(nb) + 0.5) * pas, prof, (y0, y1, x0, x1), r


def _comble(p):
    ok = np.isfinite(p)
    if not ok.any():
        return np.zeros_like(p)
    return np.interp(np.arange(len(p)), np.nonzero(ok)[0], p[ok])


def soustraire(img, cx, cy, R, force=1.0, pas=2.0, fondu=0.12):
    """Retire la composante circulaire autour de (cx, cy) jusqu'à R ; le niveau de référence est pris dans l'anneau
    R .. 1,25 R (le ciel juste autour). Retourne (image, lumière retirée en moyenne dans le disque, 0-1)."""
    rb, prof, (y0, y1, x0, x1), r = profil(img, cx, cy, 1.25 * R, 25, pas)
    nb, nin = prof.shape[1], max(int(R / pas), 2)
    out = img.copy()
    retire = []
    for c in range(img.shape[0]):
        p = _comble(prof[c])
        b = float(np.median(p[nin:])) if nb > nin else float(p[-1])
        e = np.clip(p - b, 0, None)
        e[nin:] = 0
        e = np.convolve(np.pad(e, 4, mode="edge"), np.ones(9) / 9, mode="valid")
        t = np.clip((nin - np.arange(nb)) / max(fondu * nin, 1), 0, 1)      # fondu vers 0 au bord du disque
        e *= t * t * (3 - 2 * t)
        mod = np.interp(r / pas - 0.5, np.arange(nb), e, right=0).astype(np.float32) * float(force)
        out[c, y0:y1, x0:x1] -= mod
        retire.append(float(mod[r < R].mean()) if (r < R).any() else 0.0)
    return out, float(np.mean(retire))


def remplir(img, mask, sigma, seed=0):
    """Remplace la zone `mask` (1 = à remplacer) par la moyenne lissée de ses voisins, bord fondu, plus un grain de la
    force du bruit mesuré juste autour (sinon la zone paraît lisse comme du plastique)."""
    rng = np.random.default_rng(seed)
    m = mask.astype(np.float32)
    w = 1 - m
    soft = np.clip(cv2.GaussianBlur(m, (0, 0), max(sigma / 4, 1)) * 1.5, 0, 1)
    anneau = (cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))) > 0) & (mask == 0)
    out = img.copy()
    den = cv2.GaussianBlur(w, (0, 0), sigma)
    for c in range(img.shape[0]):
        f = cv2.GaussianBlur(img[c] * w, (0, 0), sigma) / np.maximum(den, 1e-6)
        if anneau.any():
            fin = img[c] - cv2.GaussianBlur(img[c], (0, 0), 2)
            s = 1.4826 * float(np.median(np.abs(fin[anneau])))
            f = f + (cv2.GaussianBlur(rng.normal(0, 1, f.shape).astype(np.float32), (0, 0), 0.7) * s * 1.9)
        out[c] = img[c] * (1 - soft) + f * soft
    return out


def etoiles_brillantes(stars, n, seuil=0.5, aire_min=60):
    """Les n plus grosses étoiles du calque d'étoiles : liste de (x, y, rayon), coordonnées numpy."""
    mx = stars.max(0)
    k, lab, st, cent = cv2.connectedComponentsWithStats((mx > seuil).astype(np.uint8), connectivity=8)
    if k <= 1:
        return []
    idx = np.argsort(-st[1:, cv2.CC_STAT_AREA])[:max(int(n), 0)] + 1
    return [(float(cent[i][0]), float(cent[i][1]), float(np.sqrt(st[i, cv2.CC_STAT_AREA] / np.pi)))
            for i in idx if st[i, cv2.CC_STAT_AREA] >= aire_min]


def rayon_coeur(img, cx, cy, rc):
    """Rayon du cœur résiduel : là où la médiane radiale redescend près du niveau mesuré à 3 rayons d'étoile."""
    L = img.mean(0)[None]
    rb, p50, _, _ = profil(L, cx, cy, 4 * rc, 50, 2)
    p = _comble(p50[0])
    ref = float(np.median(p[int(2.5 * rc / 2):int(3.5 * rc / 2)])) if len(p) > 4 else float(p[-1])
    haut = float(p[: max(int(rc / 2), 1)].max())
    if haut <= ref:
        return 1.0 * rc
    sous = np.nonzero(p < ref + 0.06 * (haut - ref))[0]
    r = float(rb[sous[0]]) if len(sous) else 1.5 * rc
    return float(np.clip(r, 1.0 * rc, 2.5 * rc))


def rayon_lueur(img, cx, cy, rc):
    """Rayon où la lueur se fond dans le ciel : le profil radial bas (au-delà du cœur) est redescendu à 10 % de sa
    hauteur au-dessus de son minimum."""
    rb, p25, _, _ = profil(img.mean(0)[None], cx, cy, 10 * rc, 25, 4)
    d = np.convolve(_comble(p25[0]), np.ones(5) / 5, "same")
    i0 = min(int(1.5 * rc / 4), len(d) - 2)
    fin = max(int(len(d) * 0.85), i0 + 2)
    seg = d[i0:fin]
    bas = float(seg.min())
    sous = np.nonzero(seg <= bas + 0.1 * (seg[0] - bas))[0]
    j = i0 + (int(sous[0]) if len(sous) else int(np.argmin(seg)))
    return float(np.clip(rb[j], 2 * rc, min(8 * rc, 3 * rc + 120)))


def effacer_reflet(img, cx, cy, R, force=1.0):
    """Efface un reflet de forme quelconque dans le disque (cx, cy, R) : ses grandes échelles sont remplacées par le
    fond interpolé depuis l'extérieur du disque, ses petites échelles (détails fins de la nébuleuse, grain) sont
    gardées. Retourne (image, lumière retirée en moyenne dans le disque, 0-1)."""
    C, H, W = img.shape
    m = max(4, int(0.5 * R))
    y0, y1, x0, x1 = max(0, int(cy - R - 2 * m)), min(H, int(cy + R + 2 * m) + 1), max(0, int(cx - R - 2 * m)), min(W, int(cx + R + 2 * m) + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    r = np.hypot(xx - cx, yy - cy)
    dedans = (r < R).astype(np.float32)
    w = np.clip((1.0 * R - r) / max(0.15 * R, 2) + 0.5, 0, 1) * float(min(force, 1.0))   # fondu sur le bord
    s_fin = max(R / 20, 2.0)
    out = img.copy()
    k = 4 if R > 60 else 1                                    # fond interpolé sur une image réduite (rapide)
    ext = 1 - dedans
    retire = []
    for c in range(C):
        a = img[c, y0:y1, x0:x1].astype(np.float32)
        sa = cv2.resize(a * ext, None, fx=1 / k, fy=1 / k, interpolation=cv2.INTER_AREA)
        se = cv2.resize(ext, None, fx=1 / k, fy=1 / k, interpolation=cv2.INTER_AREA)
        sig = max(0.45 * R / k, 1.0)
        fond = cv2.GaussianBlur(sa, (0, 0), sig) / np.maximum(cv2.GaussianBlur(se, (0, 0), sig), 1e-4)
        fond = cv2.resize(fond, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_CUBIC)
        detail = a - cv2.GaussianBlur(a, (0, 0), s_fin)
        neuf = fond + detail
        res = a * (1 - w) + neuf * w
        out[c, y0:y1, x0:x1] = res
        retire.append(float((a - res)[r < R].mean()) if (r < R).any() else 0.0)
    return out, float(np.mean(retire))


def corriger(starless, stars, n_etoiles=3, force=1.0, cercles=(), coeur=True):
    """Corrige le calque sans étoiles. cercles : [(x, y, r)] en coordonnées numpy. Retourne (image, lignes d'info)."""
    out = starless.astype(np.float32).copy()
    info = []
    for k, (x, y, r) in enumerate(cercles):
        out, ret = effacer_reflet(out, x, y, r, force)
        info.append(f"Reflet {k + 1} effacé : centre ({x:.0f}, {y:.0f}), rayon {r:.0f} px, lumière retirée "
                    f"{ret * 255:.1f}/255 en moyenne dans le disque (détails fins gardés)")
    for k, (x, y, rc) in enumerate(etoiles_brillantes(stars, n_etoiles)):
        if coeur:
            rco = rayon_coeur(out, x, y, rc)
            yy, xx = np.ogrid[: out.shape[1], : out.shape[2]]
            out = remplir(out, (np.hypot(xx - x, yy - y) < rco).astype(np.uint8), 0.8 * rco, seed=k)
        else:
            rco = 0
        dans = next((i for i, (a, b, rr) in enumerate(cercles) if np.hypot(x - a, y - b) < rr), None)
        if dans is not None:                    # la lueur est déjà effacée avec le reflet qui l'entoure
            info.append(f"Étoile brillante {k + 1} ({x:.0f}, {y:.0f}, rayon {rc:.0f} px) : "
                        + (f"cœur résiduel remplacé sur {rco:.0f} px, " if coeur else "")
                        + f"lueur traitée avec le cercle {dans + 1}")
            continue
        rg = rayon_lueur(out, x, y, rc)
        out, ret = soustraire(out, x, y, rg, force, fondu=0.6)     # long fondu : pas de disque sombre autour
        info.append(f"Étoile brillante {k + 1} ({x:.0f}, {y:.0f}, rayon {rc:.0f} px) : "
                    + (f"cœur résiduel remplacé sur {rco:.0f} px, " if coeur else "")
                    + f"lueur retirée jusqu'à {rg:.0f} px ({ret * 255:.1f}/255 en moyenne)")
    return np.clip(out, 0, 1).astype(np.float32), info

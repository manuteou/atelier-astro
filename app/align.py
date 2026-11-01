"""Alignement d'un stack sur un autre par les étoiles, échelle comprise (appareils de focales différentes).

Méthode (celle d'astroalign, réécrite ici pour ne rien ajouter aux dépendances) :
  1. détection des étoiles (maxima locaux du fond lissé, centroïde pondéré) ;
  2. triangles formés par chaque étoile et ses voisines ; leurs deux rapports de côtés ne dépendent
     ni de l'échelle, ni de la rotation, ni du décalage ;
  3. triangles semblables appariés, votes sur les couples d'étoiles, puis similitude (rotation + échelle
     uniforme + décalage) estimée par RANSAC, affinée sur toutes les étoiles retrouvées.
Les tableaux restent dans l'ordre FITS des deux côtés (même convention : pas de retournement à gérer).
"""
from itertools import combinations

import cv2
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree


def luminance(data):
    return data[:3].mean(0) if data.shape[0] >= 3 else data[0]


def _fond_local(L, k=4, taille=9):
    """Fond à grande échelle (médiane glissante sur une image réduite k fois, puis agrandie) : garde la nébuleuse et
    le gradient, pas les étoiles."""
    small = L[::k, ::k]
    m = ndi.median_filter(small, taille)
    up = ndi.zoom(m, (L.shape[0] / m.shape[0], L.shape[1] / m.shape[1]), order=1)
    out = np.empty_like(L)
    h, w = min(up.shape[0], L.shape[0]), min(up.shape[1], L.shape[1])
    out[:h, :w] = up[:h, :w]
    out[h:, :] = out[h - 1:h, :] if h < L.shape[0] else out[h:, :]
    out[:, w:] = out[:, w - 1:w] if w < L.shape[1] else out[:, w:]
    return out


def detect(L, n=200, border=10):
    valid = ndi.binary_erosion(L > 0, iterations=border)
    v = L[valid]
    if v.size < 1000:
        return np.zeros((0, 2)), np.zeros(0)
    # fond local (nébuleuse, galaxie, gradient du ciel) retiré avant la recherche des pics : sans cela, sur un stack
    # dont le fond n'est pas aplani, le seuil est faussé et les étoiles des zones sombres ou claires sont perdues
    L = L - _fond_local(np.where(valid, L, float(np.median(v))))
    v = L[valid]
    bg = float(np.median(v))
    sig = 1.4826 * float(np.median(np.abs(v - bg))) or 1e-6
    Ls = ndi.gaussian_filter(L, 1.5)
    peaks = (Ls == ndi.maximum_filter(Ls, 9)) & (Ls > bg + 5 * sig) & valid
    ys, xs = np.nonzero(peaks)
    if xs.size == 0:
        return np.zeros((0, 2)), np.zeros(0)
    flux = Ls[ys, xs] - bg
    order = np.argsort(-flux)[:n]
    ys, xs, flux = ys[order], xs[order], flux[order]
    pts = []
    H, W = L.shape
    for y, x in zip(ys, xs):
        y0, y1, x0, x1 = max(y - 2, 0), min(y + 3, H), max(x - 2, 0), min(x + 3, W)
        w = np.clip(Ls[y0:y1, x0:x1] - bg, 0, None)
        s = w.sum() or 1
        gy, gx = np.mgrid[y0:y1, x0:x1]
        pts.append(((gx * w).sum() / s, (gy * w).sum() / s))
    return np.array(pts, float), flux


def _triangles(xy, k=6):
    if len(xy) < 3:
        return np.zeros((0, 2)), np.zeros((0, 3), int)
    tree = cKDTree(xy)
    tris = set()
    for i in range(len(xy)):
        _, idx = tree.query(xy[i], k=min(k + 1, len(xy)))
        for a, b in combinations(np.atleast_1d(idx)[1:], 2):
            tris.add(tuple(sorted((i, int(a), int(b)))))
    inv, verts = [], []
    for t in tris:
        p = xy[list(t)]
        d = np.array([np.linalg.norm(p[1] - p[2]), np.linalg.norm(p[0] - p[2]), np.linalg.norm(p[0] - p[1])])
        o = np.argsort(d)
        ds = d[o]
        if ds[2] < 8 or ds[0] / ds[2] < 0.1:
            continue
        inv.append((ds[0] / ds[2], ds[1] / ds[2]))
        verts.append(np.array(t)[o])
    return np.array(inv), np.array(verts, int).reshape(-1, 3)


def _lsq(zs, zr):
    """Similitude aux moindres carrés en nombres complexes : zr ≈ a·zs + t."""
    ms, mr = zs.mean(), zr.mean()
    ds, dr = zs - ms, zr - mr
    a = (np.conj(ds) * dr).sum() / max((np.abs(ds) ** 2).sum(), 1e-12)
    return a, mr - a * ms


def _match(src_xy, ref_xy, tol=0.006, mirror=False, scale=None):
    """Correspondances par triangles semblables, puis consensus : chaque couple de correspondances candidates
    donne une similitude, retenue si elle envoie le plus d'étoiles de src sur des étoiles de ref (< 2 px)."""
    zs_all = src_xy[:, 0] + 1j * src_xy[:, 1]
    if mirror:
        zs_all = np.conj(zs_all) * -1          # x -> -x
    si, sv = _triangles(src_xy)
    ri, rv = _triangles(ref_xy)
    if len(si) == 0 or len(ri) == 0:
        return None
    tree = cKDTree(ri)
    votes = {}
    for a, cand in enumerate(tree.query_ball_point(si, tol)):
        for b in cand:
            for vs, vr in zip(sv[a], rv[b]):
                votes[(vs, vr)] = votes.get((vs, vr), 0) + 1
    cands = sorted(votes.items(), key=lambda kv: -kv[1])[:200]
    lo, hi = (scale * 0.85, scale * 1.15) if scale else (0.2, 5.0)
    if len(cands) < 2:
        return None
    zr_all = ref_xy[:, 0] + 1j * ref_xy[:, 1]
    rtree = cKDTree(ref_xy)

    def score(a, t, thr=2.0):
        z = a * zs_all + t
        d, j = rtree.query(np.c_[z.real, z.imag])
        return d < thr, j, d

    best = (0, None)
    for i in range(len(cands)):
        (s1, r1), _ = cands[i]
        for k in range(i + 1, len(cands)):
            (s2, r2), _ = cands[k]
            if s1 == s2 or r1 == r2:
                continue
            dz = zs_all[s2] - zs_all[s1]
            if abs(dz) < 5:
                continue
            a = (zr_all[r2] - zr_all[r1]) / dz
            if not lo < abs(a) < hi:
                continue
            t = zr_all[r1] - a * zs_all[s1]
            ok, _, _ = score(a, t)
            n = int(ok.sum())
            if n > best[0]:
                best = (n, (a, t))
    if best[1] is None or best[0] < 6:
        return None
    a, t = best[1]
    for thr in (2.0, 1.5, 1.5):
        ok, j, _ = score(a, t, thr)
        if ok.sum() < 6:
            break
        # une étoile de ref au plus une fois
        _, first = np.unique(j[ok], return_index=True)
        idx = np.nonzero(ok)[0][first]
        a, t = _lsq(zs_all[idx], zr_all[j[idx]])
    ok, j, d = score(a, t, 1.5)
    rms = float(np.sqrt(np.mean(d[ok] ** 2))) if ok.any() else 99.0
    return a, t, int(ok.sum()), rms


def similarity(src_data, ref_data, scale=None):
    """Similitude qui envoie les pixels de src sur ceux de ref. Retourne un dict (ou lève ValueError).
    Plusieurs tailles de liste d'étoiles sont essayées : trop d'étoiles faibles noient les bons triangles,
    trop peu n'en laissent pas assez en commun. La solution qui retrouve le plus d'étoiles est gardée."""
    Ls, Lr = luminance(src_data), luminance(ref_data)
    s_all, _ = detect(Ls, 400)
    r_all, _ = detect(Lr, 400)
    if len(s_all) < 10 or len(r_all) < 10:
        raise ValueError(f"trop peu d'étoiles détectées ({len(s_all)} / {len(r_all)}) pour aligner les appareils")
    best, mirrored = None, False
    for ns, nr in ((120, 120), (80, 100), (200, 200), (400, 400), (50, 70)):
        s_xy, r_xy = s_all[:ns], r_all[:nr]
        for mir in (False, True):
            for sc in ((scale, None) if scale else (None,)):
                res = _match(s_xy, r_xy, mirror=mir, scale=sc)
                if res is not None and (best is None or res[2] > best[2]):
                    best, mirrored = res, mir
            if best is not None and best[2] >= 25 and not mir:
                break
        if best is not None and best[2] >= 25:
            break
    res = best
    if res is None or res[2] < 10:
        raise ValueError("alignement impossible : pas assez d'étoiles communes retrouvées entre les deux stacks")
    s_xy, r_xy = s_all, r_all
    a, t, n, rms = res
    # matrice 2x3 pour cv2 : (x, y) -> (re, im) de a·z + t, avec z = -x + iy si miroir
    sx = -1.0 if mirrored else 1.0
    M = np.array([[a.real * sx, -a.imag, t.real], [a.imag * sx, a.real, t.imag]], float)
    return {"M": M.tolist(), "etoiles": n, "rms_px": round(rms, 3), "echelle": round(float(abs(a)), 4),
            "rotation_deg": round(float(np.degrees(np.angle(a))), 2), "miroir": mirrored,
            "detectees": [len(s_xy), len(r_xy)]}


def warp(src_data, M, shape):
    """Image src remise sur la grille de ref (Lanczos) + masque de couverture (1 = pixel entièrement couvert)."""
    H, W = shape
    M = np.asarray(M, np.float32)
    out = np.stack([cv2.warpAffine(c, M, (W, H), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
                    for c in src_data]).astype(np.float32)
    valid = (src_data.max(0) > 0).astype(np.float32)
    cov = cv2.warpAffine(valid, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    cov = ndi.binary_erosion(cov > 0.999, iterations=3)
    return np.clip(out, 0, 1) * cov, cov


def noise(data):
    """Bruit de fond par pixel (0-1) : MAD du résidu haute fréquence sur les pixels de ciel."""
    L = luminance(data)
    v = np.isfinite(L) & (L > 0)
    if v.sum() < 100:
        raise ValueError("image vide ou invalide (aucun pixel exploitable) : bruit de fond impossible à mesurer")
    L = np.where(v, L, 0)
    hp = L - ndi.median_filter(L, 5)
    sky = v & (L <= np.percentile(L[v], 60))
    r = hp[sky]
    return float(1.4826 * np.median(np.abs(r - np.median(r))))


def linear_match(src, ref, mask, blur=0.0):
    """Ramène chaque canal de src sur ref : src ≈ a·ref + b (médianes par tranches), puis (src − b)/a.
    `blur` lisse ref pour lui donner la finesse de src avant l'ajustement (seulement pour le calcul)."""
    out = src.copy()
    coefs = []
    for c in range(src.shape[0]):
        r = ndi.gaussian_filter(ref[c], blur) if blur > 0 else ref[c]
        s = ndi.gaussian_filter(src[c], 0.7)
        m = mask & (ref[c] > 0) & (r < 0.9)
        rv, sv = r[m], s[m]
        if rv.size < 1000:
            raise ValueError("zone commune trop petite pour égaliser les couleurs")
        qs = np.quantile(rv, np.linspace(0.01, 0.995, 41))
        xs, ys = [], []
        for lo, hi in zip(qs[:-1], qs[1:]):
            sel = (rv >= lo) & (rv < hi)
            if sel.sum() > 30:
                xs.append(np.median(rv[sel]))
                ys.append(np.median(sv[sel]))
        a, b = np.polyfit(xs, ys, 1)
        if a <= 0.05:
            raise ValueError(f"égalisation du canal {c} incohérente (pente {a:.3f})")
        out[c] = np.where(mask, np.clip((src[c] - b) / a, 0, 1), 0)
        coefs.append((round(float(a), 4), round(float(b), 5)))
    return out, coefs

#!/usr/bin/env python3
"""mesure_stack.py : mesure un stack SANS LE MODIFIER. Deux cartes + un résumé chiffré pour NOTES.md :

  1. FWHM et excentricité des étoiles sur tout le champ (courbes de niveau), avec un
     diagnostic quand l'écart dépasse 10 % : courbure de champ, inclinaison du capteur,
     allongement uniforme (suivi, vent), allongement tangentiel (rotation de champ de la
     monture alt-az), allongement radial (optique).
  2. Rapport signal/bruit PAR PIXEL en fausses couleurs (paliers <1, 1-3, 3-5, 5-10, >10)
     et, pour chaque zone, le temps de pose supplémentaire pour atteindre S/N 3, 5 et 10
     (S/N proportionnel à la racine du temps : t_sup = t x ((cible/sn)^2 - 1)).

S'exécute DANS L'ESPACE DE TRAVAIL sur le FITS stagé (numpy, scipy, astropy, matplotlib ;
`pip install --break-system-packages astropy` si absent) :
  python3 mesure_stack.py <stack.fit> --cible T --sortie <dossier>
        [--zone "bras:x,y,w,h" ...] [--retourner] [--grille 8x5] [--max-etoiles 1500]

Entrée : un FITS LINÉAIRE de Siril (stack brut, ou après recadrage/GraXpert : le S/N y est
plus juste car le fond est plat). Couleur (3,H,W) ou mono (H,W), 16 bits ou flottant.
Temps : LIVETIME, sinon STACKCNT x EXPTIME. Échelle : FOCALLEN et XPIXSZ (x XBINNING) ;
à défaut, FWHM en pixels seulement. Pixels nuls (bords de -framing=max) ignorés.

Repère : les coordonnées (zones, textes) sont celles de l'image affichée, origine en haut
à gauche, comme l'aperçu. Les lignes FITS sont lues de bas en haut (norme FITS) sauf si
ROWORDER = 'TOP-DOWN'. VÉRIFIER au premier essai que le fond des cartes a la même
orientation que l'aperçu du stack ; sinon relancer avec --retourner.

Sorties : mesure_<T>_etoiles.png, mesure_<T>_sn.png, mesure_<T>.txt (résumé à recopier
dans NOTES.md), mesure_<T>.json (chiffres bruts).

Limites (à dire à l'utilisateur) : S/N estimé avec le bruit du fond de ciel (le bruit de
photon de l'objet est négligé : sous-estime un peu le bruit dans les zones brillantes,
sans effet sur les zones faibles qui comptent) ; bruit corrélé par le drizzle/l'alignement
mesuré tel quel sur les pixels. FWHM par ajustement gaussien elliptique : comparable d'une
image à l'autre avec ce script, pas forcément au chiffre de Siril (fonction de Moffat).
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from scipy import ndimage, optimize

try:
    from astropy.io import fits
except ImportError:
    sys.exit("astropy manquant : pip install --break-system-packages astropy")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap

FWHM_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))


# ---------------------------------------------------------------- lecture
def lire(chemin, retourner):
    with fits.open(chemin) as h:
        hdu = next(x for x in h if x.data is not None)
        data = np.asarray(hdu.data, dtype=np.float32)
        hdr = hdu.header
    if data.ndim == 3:
        if data.shape[0] in (1, 3):
            lum = data.mean(axis=0) if data.shape[0] == 3 else data[0]
        else:  # (H,W,3)
            lum = data.mean(axis=2)
    else:
        lum = data
    if np.nanmax(lum) > 2.0:  # 16 bits
        lum = lum / 65535.0
    lum = np.nan_to_num(lum, nan=0.0)
    ordre = str(hdr.get("ROWORDER", "BOTTOM-UP")).upper()
    haut_bas = ordre.startswith("TOP")
    if not haut_bas:
        lum = lum[::-1]
    if retourner:
        lum = lum[::-1]
    return lum, hdr


def infos(hdr):
    t = hdr.get("LIVETIME")
    if not t and hdr.get("STACKCNT") and hdr.get("EXPTIME"):
        t = float(hdr["STACKCNT"]) * float(hdr["EXPTIME"])
    echelle = None
    if hdr.get("FOCALLEN") and hdr.get("XPIXSZ"):
        binning = float(hdr.get("XBINNING", 1) or 1)
        echelle = 206.265 * float(hdr["XPIXSZ"]) * binning / float(hdr["FOCALLEN"])
    return {"temps_s": float(t) if t else None, "echelle": echelle,
            "exptime": float(hdr["EXPTIME"]) if hdr.get("EXPTIME") else None,
            "stackcnt": int(hdr["STACKCNT"]) if hdr.get("STACKCNT") else None,
            "objet": str(hdr.get("OBJECT", "")).strip()}


# ---------------------------------------------------------------- fond et bruit
def fond_et_bruit(lum, valide, tuile=64):
    """Fond lisse (polynôme 2D d'ordre 2 sur les médianes de tuiles de ciel) et bruit
    par pixel (MAD des tuiles de ciel, interpolé). Les tuiles d'objet sont rejetées
    itérativement (vers le haut seulement) pour qu'une grande nébuleuse ne soit pas prise
    pour du fond."""
    H, W = lum.shape
    ny, nx = max(H // tuile, 2), max(W // tuile, 2)
    ty, tx = H // ny, W // nx
    pts = []
    grille_sig = np.full((ny, nx), np.nan)
    for j in range(ny):
        for i in range(nx):
            b = lum[j * ty:(j + 1) * ty, i * tx:(i + 1) * tx]
            v = valide[j * ty:(j + 1) * ty, i * tx:(i + 1) * tx]
            if v.mean() < 0.9:
                continue
            x = b[v]
            # ciel de la tuile : rejet itératif à 2.5 sigma vers le haut (étoiles, objet)
            ciel = x
            for _ in range(6):
                med = np.median(ciel)
                sig = 1.4826 * np.median(np.abs(ciel - med))
                garde_px = ciel < med + 2.5 * sig
                if garde_px.all() or garde_px.sum() < 0.3 * x.size:
                    break
                ciel = ciel[garde_px]
            med = np.median(ciel)
            # bruit : MAD des pixels sous la médiane, symétrisée (insensible aux étoiles)
            bas = x[x <= np.median(x)]
            sig = 1.4826 * np.median(np.median(x) - bas)
            pts.append(((i + 0.5) * tx, (j + 0.5) * ty, med, sig))
            # bruit « de couverture » : différences entre pixels voisins (insensible aux
            # structures lisses d'une nébuleuse), pour repérer les zones vues par peu de poses
            dx = np.diff(b, axis=1)[v[:, 1:] & v[:, :-1]]
            grille_sig[j, i] = 1.4826 * np.median(np.abs(dx - np.median(dx))) / math.sqrt(2)
    if len(pts) < 6:
        sys.exit("Trop peu de zones valides pour estimer le fond.")
    P = np.array(pts)
    X, Y, M, S = P[:, 0] / W, P[:, 1] / H, P[:, 2], P[:, 3]

    def base(x, y):
        return np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], axis=1)

    garde = np.ones(len(P), bool)
    for _ in range(12):
        A = base(X[garde], Y[garde])
        coef, *_ = np.linalg.lstsq(A, M[garde], rcond=None)
        res = M - base(X, Y) @ coef
        # dispersion mesurée sur la moitié basse des résidus seulement : une grande
        # nébuleuse (jusqu'à ~la moitié du champ) ne la gonfle pas
        r = res[garde]
        bas = r[r <= np.median(r)]
        s = 1.4826 * np.median(np.median(r) - bas)
        nouveau = res < np.median(r) + 3.0 * max(s, 1e-9)
        if nouveau.sum() < max(6, 0.2 * len(P)) or np.array_equal(nouveau, garde):
            break
        garde = nouveau
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    fond = (base(xx.ravel() / W, yy.ravel() / H) @ coef).reshape(H, W).astype(np.float32)
    # bruit : modèle d'ordre 1 sur les tuiles de ciel (varie avec la couverture des bords)
    A1 = np.stack([np.ones(garde.sum()), X[garde], Y[garde],
                   np.abs(X[garde] - 0.5), np.abs(Y[garde] - 0.5)], axis=1)
    cs, *_ = np.linalg.lstsq(A1, S[garde], rcond=None)
    B1 = np.stack([np.ones(H * W), xx.ravel() / W, yy.ravel() / H,
                   np.abs(xx.ravel() / W - 0.5), np.abs(yy.ravel() / H - 0.5)], axis=1)
    bruit = (B1 @ cs).reshape(H, W).astype(np.float32)
    bruit = np.clip(bruit, 0.5 * np.median(S[garde]), None)
    # faible couverture (bords de -framing=max, zones vues par peu de poses) : bruit de
    # tuile > 1.5x la médiane, ou tuile sans mesure ; ces zones partent au recadrage
    ref = np.nanmedian(grille_sig)
    fort = ~(grille_sig <= 1.5 * ref)
    # seulement les zones reliées au bord du cadre : une nébuleuse au milieu du champ a
    # aussi un « bruit » de tuile élevé (sa structure), mais n'est pas un défaut de couverture
    etiq, n = ndimage.label(fort)
    bord = set(np.unique(np.concatenate([etiq[0], etiq[-1], etiq[:, 0], etiq[:, -1]]))) - {0}
    faible = np.isin(etiq, list(bord))
    masque = np.kron(faible.astype(np.uint8), np.ones((ty, tx), np.uint8)).astype(bool)
    masque = np.pad(masque, ((0, H - masque.shape[0]), (0, W - masque.shape[1])), mode="edge")
    return fond, bruit, masque, {"tuiles_ciel": int(garde.sum()), "tuiles": int(len(P)),
                                 "bruit_median": float(np.median(S[garde])),
                                 "faible_couverture": float(masque.mean())}


# ---------------------------------------------------------------- étoiles
def gauss2d(coord, amp, x0, y0, sx, sy, th, c):
    x, y = coord
    ct, st = math.cos(th), math.sin(th)
    a = ct * ct / (2 * sx * sx) + st * st / (2 * sy * sy)
    b = -math.sin(2 * th) / (4 * sx * sx) + math.sin(2 * th) / (4 * sy * sy)
    cc = st * st / (2 * sx * sx) + ct * ct / (2 * sy * sy)
    return (c + amp * np.exp(-(a * (x - x0) ** 2 + 2 * b * (x - x0) * (y - y0)
                               + cc * (y - y0) ** 2))).ravel()


def etoiles(lum, fond, bruit, valide, max_etoiles, r=7):
    H, W = lum.shape
    net = lum - fond
    lisse = ndimage.gaussian_filter(net, 1.0)
    seuil = 8.0 * bruit / 2.0  # bruit réduit ~/2 par le lissage
    pics = (lisse == ndimage.maximum_filter(lisse, size=2 * r + 1)) & (lisse > seuil)
    satur = np.percentile(lum[valide], 99.995) if valide.any() else 1.0
    satur = min(satur * 0.98, 0.95)
    ys, xs = np.nonzero(pics)
    ok = (xs > 2 * r) & (xs < W - 2 * r) & (ys > 2 * r) & (ys < H - 2 * r)
    ys, xs = ys[ok], xs[ok]
    # isolées : pas d'autre pic dans 2r
    if len(xs):
        ordre = np.argsort(-lisse[ys, xs])
        ys, xs = ys[ordre], xs[ordre]
        prises = np.zeros((H // (2 * r) + 1, W // (2 * r) + 1), int)
        for y, x in zip(ys, xs):
            prises[y // (2 * r), x // (2 * r)] += 1
        dense = prises[ys // (2 * r), xs // (2 * r)] > 1
        ys, xs = ys[~dense], xs[~dense]
    # répartir l'échantillon sur tout le champ (pas seulement les plus brillantes)
    if len(xs) > max_etoiles:
        cases = (ys * 6 // H) * 8 + (xs * 8 // W)
        choix = []
        par_case = max(max_etoiles // 48, 5)
        for c in np.unique(cases):
            idx = np.nonzero(cases == c)[0]
            choix.extend(idx[len(idx) // 10: len(idx) // 10 + par_case])  # sauter les 10 % plus brillantes
        choix = np.array(sorted(choix))
        ys, xs = ys[choix], xs[choix]
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    res = []
    for y, x in zip(ys, xs):
        b = lum[y - r:y + r + 1, x - r:x + r + 1]
        if b.max() >= satur or not valide[y - r:y + r + 1, x - r:x + r + 1].all():
            continue
        c0 = float(np.median(np.concatenate([b[0], b[-1], b[:, 0], b[:, -1]])))
        amp0 = float(b.max() - c0)
        if amp0 <= 0:
            continue
        try:
            p, _ = optimize.curve_fit(
                gauss2d, (xx, yy), b.ravel(),
                p0=(amp0, 0, 0, 1.5, 1.5, 0.0, c0),
                bounds=([0, -2, -2, 0.4, 0.4, -math.pi, -1], [10, 2, 2, r, r, math.pi, 2]),
                maxfev=400)
        except (RuntimeError, ValueError):
            continue
        amp, dx, dy, sx, sy, th, c = p
        if amp < 5 * bruit[y, x]:
            continue
        sa, sb = (sx, sy) if sx >= sy else (sy, sx)
        ang = th if sx >= sy else th + math.pi / 2
        ang = -ang  # la forme gaussienne tourne dans l'autre sens : angle en coordonnées
        ang = (ang + math.pi / 2) % math.pi - math.pi / 2  # tableau (x droite, y bas), [-90°, 90°[
        fw = FWHM_SIGMA * math.sqrt(sa * sb)
        ecc = math.sqrt(max(0.0, 1 - (sb / sa) ** 2))
        res.append((x + dx, y + dy, fw, ecc, ang, amp))
    return np.array(res) if res else np.zeros((0, 6))


# ---------------------------------------------------------------- diagnostic optique
def grille_valeurs(E, W, H, nx, ny, col, mini=5):
    G = np.full((ny, nx), np.nan)
    N = np.zeros((ny, nx), int)
    for j in range(ny):
        for i in range(nx):
            m = ((E[:, 0] >= i * W / nx) & (E[:, 0] < (i + 1) * W / nx)
                 & (E[:, 1] >= j * H / ny) & (E[:, 1] < (j + 1) * H / ny))
            N[j, i] = m.sum()
            if m.sum() >= mini:
                G[j, i] = np.median(E[m, col])
    return G, N


def diagnostic(E, W, H, nx, ny):
    d = {}
    fw, ecc, ang = E[:, 2], E[:, 3], E[:, 4]
    G, N = grille_valeurs(E, W, H, nx, ny, 2)
    Ge, _ = grille_valeurs(E, W, H, nx, ny, 3)
    med = float(np.median(fw))
    vals = G[~np.isnan(G)]
    d["fwhm_mediane_px"] = med
    d["fwhm_min_tuile"], d["fwhm_max_tuile"] = float(vals.min()), float(vals.max())
    d["ecart_relatif"] = float((np.percentile(vals, 90) - np.percentile(vals, 10)) / med)
    d["ecc_mediane"] = float(np.median(ecc))
    # centre / coins (tiers du champ)
    cx, cy = E[:, 0] / W - 0.5, E[:, 1] / H - 0.5
    centre = (np.abs(cx) < 1 / 6) & (np.abs(cy) < 1 / 6)
    coins = {}
    for nom, sx, sy in (("haut-gauche", -1, -1), ("haut-droite", 1, -1),
                        ("bas-gauche", -1, 1), ("bas-droite", 1, 1)):
        m = (cx * sx > 1 / 4) & (cy * sy > 1 / 4)
        coins[nom] = float(np.median(fw[m])) if m.sum() >= 5 else None
    d["fwhm_centre"] = float(np.median(fw[centre])) if centre.sum() >= 5 else None
    d["fwhm_coins"] = coins
    # plan (inclinaison) vs terme radial (courbure)
    rr = cx ** 2 + cy ** 2
    A = np.stack([np.ones_like(cx), cx, cy, rr], axis=1)
    coef, *_ = np.linalg.lstsq(A, fw, rcond=None)
    pente_x, pente_y, courb = coef[1], coef[2], coef[3]
    amp_plan = math.hypot(pente_x, pente_y) / med  # variation relative d'un bord à l'autre
    amp_courb = courb * 0.5 / med                   # centre -> coin (rr = 0.5 au coin)
    d["inclinaison_rel"], d["courbure_rel"] = float(amp_plan), float(amp_courb)
    direction = math.degrees(math.atan2(-pente_y, pente_x))  # vers le côté le plus flou
    cotes = ["droite", "haut-droite", "haut", "haut-gauche", "gauche", "bas-gauche", "bas",
             "bas-droite"]
    d["cote_flou"] = cotes[int(((direction + 22.5) % 360) // 45)]
    # orientation des allongements (seulement les étoiles nettement allongées)
    m = ecc > 0.45
    d["etoiles_allongees"] = float(m.mean())
    if m.sum() >= 10:
        z = np.exp(2j * ang[m])
        d["coherence_direction"] = float(abs(z.mean()))
        d["angle_moyen"] = float(-math.degrees(np.angle(z.mean()) / 2))  # vu à l'écran, + = monte vers la droite
        phi = np.arctan2(cy[m], cx[m])  # direction radiale depuis le centre
        d["indice_radial"] = float(np.mean(np.cos(2 * (ang[m] - phi))))  # +1 radial, -1 tangentiel
    msg = []
    seuil = 0.10
    em = d["ecc_mediane"]
    axes = math.sqrt(max(0.0, 1 - em * em))  # rapport petit axe / grand axe
    d["rapport_axes"] = float(axes)
    # repères usuels : excentricité < 0.45 ronde, 0.45-0.6 légèrement ovale (normal pour un
    # petit instrument, invisible sans zoom), >= 0.6 allongée (visible)
    if d["ecart_relatif"] <= seuil and em < 0.45:
        msg.append(f"Champ homogène : écart de FWHM {d['ecart_relatif']:.0%} (≤ 10 %), "
                   f"étoiles rondes (excentricité médiane {em:.2f}).")
    else:
        if d["ecart_relatif"] > seuil:
            msg.append(f"Écart de FWHM sur le champ : {d['ecart_relatif']:.0%} (> 10 %).")
            vals_coins = {k: v for k, v in coins.items() if v}
            pire = max(vals_coins, key=vals_coins.get) if len(vals_coins) == 4 else None
            autres = [v for k, v in vals_coins.items() if k != pire]
            un_coin = (pire is not None and vals_coins[pire] > 1.12 * np.median(autres)
                       and (max(autres) - min(autres)) < 0.06 * np.median(autres))
            if amp_courb > seuil and amp_courb > amp_plan:
                msg.append(f"  Indice : COURBURE DE CHAMP (coins plus flous que le centre de "
                           f"{amp_courb:.0%} en moyenne, de façon symétrique).")
            elif un_coin:
                exc = vals_coins[pire] / np.median(autres) - 1
                msg.append(f"  Indice : UN SEUL COIN FLOU ({pire}, +{exc:.0%} par rapport aux trois "
                           f"autres) : inclinaison du capteur, ou alignement moins bon dans ce coin "
                           f"(sessions au cadrage décalé, distorsion). À vérifier sur une autre cible.")
            elif amp_plan > seuil:
                msg.append(f"  Indice : INCLINAISON du capteur ou mise au point décentrée "
                           f"(FWHM qui monte d'un côté à l'autre de {amp_plan:.0%}, côté "
                           f"{d['cote_flou']} le plus flou).")
            else:
                msg.append("  Variation sans motif net (seeing variable, nuages, zone "
                           "d'étoiles saturées) : pas de diagnostic optique.")
        if em >= 0.45:
            coh = d.get("coherence_direction", 0)
            ir = d.get("indice_radial", 0)
            if em < 0.6:
                msg.append(f"Étoiles légèrement ovales : excentricité médiane {em:.2f} (rapport des "
                           f"axes {axes:.2f}), courant pour un petit instrument et peu visible "
                           f"sans zoom.")
                pref = "  Tendance"
            else:
                msg.append(f"Étoiles allongées : excentricité médiane {em:.2f} (rapport des axes "
                           f"{axes:.2f}), visible à pleine résolution.")
                pref = "  Indice"
            if coh > 0.6:
                msg.append(f"{pref} : allongement UNIFORME (même direction partout, "
                           f"{d['angle_moyen']:+.0f}° par rapport à l'horizontale, + = montant vers "
                           f"la droite) : suivi, vent, ou poses trop longues.")
            elif ir < -0.4:
                msg.append(f"{pref} : allongement TANGENTIEL (en arc autour du centre, plus "
                           "fort vers les bords) : rotation de champ de la monture alt-az "
                           "pendant chaque pose. Remède : poses plus courtes, ou écarter les "
                           "poses prises près du zénith.")
            elif ir > 0.4:
                msg.append(f"{pref} : allongement RADIAL (étoiles pointées vers le centre, "
                           "plus fort aux bords) : aberration optique (coma, inclinaison).")
            elif em >= 0.6:
                msg.append("  Directions d'allongement mélangées : pas de cause unique nette.")
    d["messages"] = msg
    return d, G, Ge, N


# ---------------------------------------------------------------- images
def etire(x, valide):
    v = x[valide]
    med = np.median(v)
    mad = np.median(np.abs(v - med)) * 1.4826
    lo = med - 2.8 * mad
    hi = np.percentile(v, 99.9)
    y = np.clip((x - lo) / max(hi - lo, 1e-9), 0, 1)
    m = np.clip((med - lo) / max(hi - lo, 1e-9), 1e-4, 0.999)
    cible = 0.25
    k = (m - 1) * cible / ((2 * cible - 1) * m - cible)  # MTF qui envoie m sur 0.25
    return ((k - 1) * y) / ((2 * k - 1) * y - k)


def reduire(img, largeur=1400):
    f = max(1, int(math.ceil(img.shape[1] / largeur)))
    if f == 1:
        return img, 1
    H, W = (img.shape[0] // f) * f, (img.shape[1] // f) * f
    return img[:H, :W].reshape(H // f, f, W // f, f).mean(axis=(1, 3)), f


def griser(ax, exclu, W, H):
    if exclu is not None and exclu.any():
        ax.imshow(np.ma.masked_where(~exclu, exclu.astype(float)), cmap="Greys", vmin=0, vmax=2,
                  alpha=0.75, extent=(0, W, H, 0), interpolation="nearest")


def carte_etoiles(fond_img, E, G, Ge, W, H, d, unite, echelle, chemin, titre, exclu=None):
    fig, axes = plt.subplots(1, 2, figsize=(16, 16 * H / W / 2 + 1.6), dpi=110)
    ext = (0, W, H, 0)
    for ax, grille, nom, cmap in ((axes[0], G, "FWHM", "viridis"),
                                  (axes[1], Ge, "Excentricité", "magma")):
        ax.imshow(fond_img, cmap="gray", extent=ext, interpolation="bilinear")
        g = grille.copy()
        if np.isnan(g).all():
            continue
        g[np.isnan(g)] = np.nanmedian(g)
        lisse = ndimage.zoom(ndimage.gaussian_filter(g, 0.6), 8, order=1)
        if nom == "FWHM" and echelle:
            lisse = lisse * echelle
        yy = np.linspace(0, H, lisse.shape[0])
        xx = np.linspace(0, W, lisse.shape[1])
        # échelle d'au moins ±10 % (FWHM) ou de 0.3 (excentricité) : un champ sain
        # doit paraître uniforme, pas montrer son bruit comme une structure
        med = float(np.median(lisse))
        demi = max(0.10 * med if nom == "FWHM" else 0.15,
                   float(lisse.max() - med), float(med - lisse.min()))
        vmin, vmax = med - demi, med + demi
        if nom != "FWHM":
            vmin, vmax = max(0.0, vmin), min(1.0, vmax)
        im = ax.imshow(lisse, cmap=cmap, alpha=0.35, extent=ext, interpolation="bilinear",
                       vmin=vmin, vmax=vmax)
        griser(ax, exclu, W, H)
        niveaux = np.linspace(vmin, vmax, 11)[1:-1]
        niveaux = niveaux[(niveaux > lisse.min()) & (niveaux < lisse.max())]
        cs = ax.contour(xx, yy, lisse, levels=niveaux if len(niveaux) else 3,
                        colors="white", linewidths=0.8)
        ax.clabel(cs, fmt="%.2f", fontsize=8)
        fig.colorbar(im, ax=ax, fraction=0.035, pad=0.01,
                     label=f"FWHM ({unite})" if nom == "FWHM" else "excentricité")
        if nom == "Excentricité" and len(E):
            pas = max(1, len(E) // 400)
            Es = E[::pas]
            lg = 0.035 * W * Es[:, 3]
            ax.quiver(Es[:, 0], Es[:, 1], lg * np.cos(Es[:, 4]), lg * np.sin(Es[:, 4]),
                      color="cyan", angles="xy", scale_units="xy", scale=1, width=0.0015,
                      headwidth=0, headlength=0, headaxislength=0, pivot="middle")
        ax.set_title(nom, fontsize=12)
        ax.set_xlim(0, W)
        ax.set_ylim(H, 0)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle(titre, fontsize=13)
    texte = "\n".join(d["messages"])
    fig.text(0.01, 0.005, texte, fontsize=9, va="bottom", family="DejaVu Sans")
    fig.tight_layout(rect=(0, 0.04 + 0.018 * len(d["messages"]), 1, 0.97))
    fig.savefig(chemin, facecolor="white")
    plt.close(fig)


PALIERS = [0, 1, 3, 5, 10, 1e9]
COULEURS = ["#1b1f2b", "#7b2d8e", "#d1495b", "#edae49", "#66c2a5"]
NOMS = ["< 1", "1–3", "3–5", "5–10", "> 10"]


def temps_txt(s):
    if s is None:
        return "?"
    if not math.isfinite(s):
        return "hors de portée (pas de signal mesurable)"
    if s <= 0:
        return "atteint"
    mn = int(round(s / 60))
    h, m = mn // 60, mn % 60
    if h >= 100:
        return f"{h} h (irréaliste)"
    return f"{h} h {m:02d}" if h else f"{m} min"


def ajout_temps(sn, t):
    out = {}
    for cible in (3, 5, 10):
        if t is None or sn is None or not np.isfinite(sn):
            out[cible] = None
        elif sn <= 0.05:
            out[cible] = float("inf")
        else:
            out[cible] = t * ((cible / sn) ** 2 - 1)
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fits")
    ap.add_argument("--cible", default=None)
    ap.add_argument("--sortie", default=".")
    ap.add_argument("--zone", action="append", default=[],
                    help="nom:x,y,w,h en pixels de l'image affichée (origine en haut à gauche)")
    ap.add_argument("--retourner", action="store_true")
    ap.add_argument("--grille", default="")
    ap.add_argument("--max-etoiles", type=int, default=1500)
    a = ap.parse_args()

    lum, hdr = lire(a.fits, a.retourner)
    inf = infos(hdr)
    T = a.cible or inf["objet"].replace(" ", "") or os.path.splitext(os.path.basename(a.fits))[0]
    os.makedirs(a.sortie, exist_ok=True)
    H, W = lum.shape
    valide = ndimage.binary_erosion(lum > 0, iterations=12, border_value=1)  # n'érode qu'autour des pixels nuls
    if valide.mean() < 0.2:
        sys.exit("Moins de 20 % de pixels non nuls : image vide ou mal lue.")

    fond, bruit, faible, info_fond = fond_et_bruit(lum, valide)
    complet = valide & ~faible  # zone bien couverte : seule utilisée pour les mesures
    if complet.mean() < 0.3:
        complet = valide
        info_fond["faible_couverture"] = 0.0

    # ---- étoiles
    E = etoiles(lum, fond, bruit, complet, a.max_etoiles)
    if a.grille:
        nx, ny = (int(v) for v in a.grille.lower().split("x"))
    else:
        nx, ny = (8, 5) if W >= H else (5, 8)
    echelle = inf["echelle"]
    unite = "″" if echelle else "px"
    fond_img, f = reduire(etire(lum, valide))
    resume = [f"# Mesure du stack {T}",
              f"Fichier : {os.path.basename(a.fits)}   {W}x{H} px   "
              f"intégration : {temps_txt(inf['temps_s']) if inf['temps_s'] else '?'}   "
              f"échelle : {echelle:.2f}″/px" if echelle else
              f"Fichier : {os.path.basename(a.fits)}   {W}x{H} px   échelle inconnue"]
    d = {}
    if len(E) < 30:
        resume.append(f"Étoiles mesurées : {len(E)} (trop peu pour une carte : champ pauvre, "
                      f"image non linéaire, ou seuil trop haut).")
    else:
        d, G, Ge, N = diagnostic(E, W, H, nx, ny)
        conv = echelle if echelle else 1.0
        coins = ", ".join(f"{k} {v * conv:.2f}" for k, v in d["fwhm_coins"].items() if v)
        resume += [
            f"Étoiles mesurées : {len(E)}   FWHM médiane : {d['fwhm_mediane_px']:.2f} px"
            + (f" ({d['fwhm_mediane_px'] * echelle:.2f}″)" if echelle else ""),
            f"FWHM par zone ({unite}) : de {d['fwhm_min_tuile'] * conv:.2f} à "
            f"{d['fwhm_max_tuile'] * conv:.2f}   centre "
            f"{(d['fwhm_centre'] or float('nan')) * conv:.2f}   coins : {coins}",
            f"Excentricité médiane : {d['ecc_mediane']:.2f}",
        ] + d["messages"]
        carte_etoiles(fond_img, E, G, Ge, W, H, d, unite, echelle,
                      os.path.join(a.sortie, f"mesure_{T}_etoiles.png"),
                      f"{T} : FWHM et excentricité des étoiles ({len(E)} étoiles)",
                      exclu=reduire(faible.astype(float))[0] > 0.5)

    # ---- S/N par pixel
    net = lum - fond
    petit, fr = reduire(np.where(valide, net, np.nan), largeur=max(W // 2, 600))
    petit = np.nan_to_num(petit, nan=0.0)
    signal = ndimage.median_filter(petit, size=7)  # efface bruit et étoiles (~14 px pleine résolution)
    signal = ndimage.zoom(signal, (H / signal.shape[0], W / signal.shape[1]), order=1)
    signal = signal[:H, :W]
    if signal.shape != lum.shape:
        signal = np.pad(signal, ((0, H - signal.shape[0]), (0, W - signal.shape[1])), mode="edge")
    sn = np.where(complet, signal / bruit, np.nan)
    t = inf["temps_s"]
    sn_aff, _ = reduire(np.nan_to_num(sn, nan=-1), largeur=1400)

    zones = []
    for z in a.zone:
        try:
            nom, coords = z.split(":")
            x, y, w, h = (int(v) for v in coords.split(","))
        except ValueError:
            sys.exit(f"Zone mal écrite : {z!r} (attendu nom:x,y,w,h)")
        bloc = sn[max(y, 0):y + h, max(x, 0):x + w]
        v = bloc[np.isfinite(bloc)]
        zones.append({"nom": nom, "x": x, "y": y, "w": w, "h": h,
                      "sn": float(np.median(v)) if v.size else None})
    # zones automatiques : signal faible (étendues) et signal moyen
    # objet = régions ÉTENDUES à S/N > 1 (les taches d'étoiles résiduelles sont écartées)
    objet = np.isfinite(sn) & (sn > 1.0)
    objet = ndimage.binary_opening(objet, iterations=3)
    etiq, n = ndimage.label(objet)
    if n:
        tailles = ndimage.sum(objet, etiq, index=np.arange(1, n + 1))
        grandes = np.nonzero(tailles >= 0.0005 * objet.size)[0] + 1
        objet = np.isin(etiq, grandes)
    if objet.sum() > 500:
        vals = sn[objet]
        for nom, q in (("nébulosité étendue (S/N > 1), quart le plus faible", 25), ("nébulosité étendue (S/N > 1), médiane", 50)):
            zones.append({"nom": nom, "auto": True, "sn": float(np.percentile(vals, q))})
    ciel = np.isfinite(sn)
    surfaces = {NOMS[k]: float(((sn >= PALIERS[k]) & (sn < PALIERS[k + 1]) & ciel).sum()
                                / max(ciel.sum(), 1)) for k in range(5)}
    surfaces[NOMS[0]] += float(((sn < 0) & ciel).sum() / max(ciel.sum(), 1))
    for z in zones:
        z["temps_sup"] = ajout_temps(z["sn"], t)

    # carte S/N
    fig, ax = plt.subplots(figsize=(12, 12 * H / W + 1.8), dpi=110)
    cmap = ListedColormap(COULEURS)
    norm = BoundaryNorm(PALIERS, cmap.N)
    ax.imshow(fond_img, cmap="gray", extent=(0, W, H, 0), interpolation="bilinear")
    masque = np.ma.masked_where(sn_aff < 0, sn_aff)
    ax.imshow(masque, cmap=cmap, norm=norm, alpha=0.62, extent=(0, W, H, 0),
              interpolation="nearest")
    griser(ax, reduire(faible.astype(float))[0] > 0.5, W, H)
    for z in zones:
        if z.get("auto"):
            continue
        ax.add_patch(plt.Rectangle((z["x"], z["y"]), z["w"], z["h"], fill=False,
                                   ec="white", lw=1.5))
        ax.text(z["x"], z["y"] - 8, f"{z['nom']} : S/N {z['sn']:.1f}" if z["sn"] else z["nom"],
                color="white", fontsize=9, va="bottom",
                bbox=dict(fc="black", alpha=0.5, lw=0))
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in COULEURS]
    ax.legend(handles, [f"S/N {n} ({surfaces[n]:.0%} du champ)" for n in NOMS],
              loc="upper right", fontsize=9, framealpha=0.8)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(f"{T} : rapport signal/bruit par pixel"
                 + (f" ({temps_txt(t)} d'intégration)" if t else ""), fontsize=12)
    lignes = []
    for z in zones:
        if z["sn"] is None:
            continue
        ts = z["temps_sup"]
        lignes.append(f"{z['nom']} : S/N {z['sn']:.1f} → temps en plus pour S/N 3 : "
                      f"{temps_txt(ts[3])}, 5 : {temps_txt(ts[5])}, 10 : {temps_txt(ts[10])}")
    fig.text(0.01, 0.005, "\n".join(lignes), fontsize=9, va="bottom")
    fig.tight_layout(rect=(0, 0.02 + 0.022 * len(lignes), 1, 1))
    fig.savefig(os.path.join(a.sortie, f"mesure_{T}_sn.png"), facecolor="white")
    plt.close(fig)

    if info_fond["faible_couverture"] > 0:
        resume.insert(2, f"Zones peu couvertes exclues des mesures (bords, gris sur les cartes) : "
                         f"{info_fond['faible_couverture']:.0%} du cadre")
    resume += ["", f"Bruit du fond (par pixel, 0-1) : {info_fond['bruit_median']:.3g}   "
               f"zones de ciel retenues : {info_fond['tuiles_ciel']}/{info_fond['tuiles']}",
               "Surface du champ par palier de S/N : "
               + ", ".join(f"{n} {v:.0%}" for n, v in surfaces.items())]
    if t is None:
        resume.append("Temps d'intégration inconnu (ni LIVETIME ni STACKCNT x EXPTIME) : "
                      "pas de calcul de temps supplémentaire.")
    resume += lignes
    if t and inf["exptime"]:
        resume.append(f"(1 pose = {inf['exptime']:g} s ; les temps supposent les mêmes "
                      f"conditions de ciel et S/N proportionnel à la racine du temps)")

    with open(os.path.join(a.sortie, f"mesure_{T}.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(resume) + "\n")
    brut = {"cible": T, "largeur": W, "hauteur": H, "infos": inf, "fond": info_fond,
            "etoiles": len(E), "diagnostic": {k: v for k, v in d.items()},
            "surfaces_sn": surfaces,
            "zones": [{k: (None if isinstance(v, float) and not math.isfinite(v) else v)
                       for k, v in z.items() if k != "temps_sup"}
                      | {"temps_sup_s": {str(c): (None if v is None or not math.isfinite(v)
                                                  else round(v)) for c, v in
                                         z["temps_sup"].items()}} for z in zones]}
    with open(os.path.join(a.sortie, f"mesure_{T}.json"), "w", encoding="utf-8") as fh:
        json.dump(brut, fh, ensure_ascii=False, indent=1, default=float)
    print("\n".join(resume))
    print(f"\nCartes : {os.path.join(a.sortie, f'mesure_{T}_etoiles.png')}, "
          f"{os.path.join(a.sortie, f'mesure_{T}_sn.png')}")


if __name__ == "__main__":
    main()

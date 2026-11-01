# Coloration "objet entier" (variante B des colorations de fin de traitement) sur l'image ETIREE.
# Probleme : `satu` seul n'agit pratiquement que sur le noyau (seuil mediane + sigma) ; les versions naturelle et colorisee sortent quasi identiques.
# Ici : renfort de couleur PROPORTIONNEL A LA LUMINOSITE de l'objet (galaxie / nebuleuse), luminance conservee, ciel non touche,
# couleur lissee dans les zones faibles (le bruit de couleur n'est pas amplifie).
# Usage (Siril) : pyscript "<chemin>/coloration_galaxie.py" <etiree.fit> <sortie.fit> [force=0.8] [lissage_px=6]
#  - force : renfort maximal de la chrominance dans les zones lumineuses (chroma x (1 + force * poids)), 0.5 doux, 0.8 net, 1.2 fort ;
#  - poids = 0 dans le ciel, 1 dans les zones les plus lumineuses de l'objet (progressif entre les deux) ;
#  - lissage_px : rayon gaussien de la chrominance dans les zones faibles (poids bas).
import sys, numpy as np, cv2
from astropy.io import fits


def run(src, dst, force=0.8, smooth=6.0):
    h = fits.open(src)
    x = h[0].data.astype(np.float32)
    scale = 65535.0 if x.max() > 1.5 else 1.0
    x = x / scale
    L = x.mean(0)
    ls = cv2.GaussianBlur(L, (0, 0), 8)
    lo = np.percentile(ls, 60)      # niveau du ciel (60e percentile du lisse)
    hi = np.percentile(ls, 99.5)
    w = np.clip((ls - lo) / max(hi - lo, 1e-6), 0, 1)
    w = w * w * (3 - 2 * w)         # smoothstep
    chroma = x - L
    chroma_s = np.stack([cv2.GaussianBlur(chroma[c], (0, 0), smooth) for c in range(3)])
    eff = w * chroma + (1 - w) * chroma_s           # lisse dans les zones faibles
    new = L + (1 + force * w) * eff
    zone = np.clip((w - 0.01) * 5, 0, 1)          # exactement 0 dans le ciel (poids < 0.01)
    out = np.clip(x + zone * (new - x), 0, 1)
    sat = lambda im, m: float(np.mean((im.max(0) - im.min(0))[m] / np.maximum(im.max(0)[m], 1e-6)))
    noyau, bras, ciel = w > 0.8, (w > 0.1) & (w < 0.4), w < 0.01
    print('saturation moyenne  noyau %.2f -> %.2f | bras faibles %.2f -> %.2f | ciel %.2f -> %.2f' % (
        sat(x, noyau), sat(out, noyau), sat(x, bras), sat(out, bras), sat(x, ciel), sat(out, ciel)))
    print('ciel : ecart maximal de pixel %.5f' % float(np.abs(out - x)[:, ciel].max()))
    fits.PrimaryHDU((out * scale).astype(np.float32), h[0].header).writeto(dst, overwrite=True)
    print('OK', dst)


if __name__ == '__main__':
    a = sys.argv
    run(a[1], a[2], float(a[3]) if len(a) > 3 else 0.8, float(a[4]) if len(a) > 4 else 6.0)

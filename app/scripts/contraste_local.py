# Contraste local de l'objet (galaxie / nebuleuse) sur l'image ETIREE, sans toucher au ciel.
# Usage (Siril) : pyscript "<chemin>/contraste_local.py" <etiree.fit> <sortie.fit> [force=0.6] [rayons=6,20,60]
#  - agit sur la LUMINANCE seule (les couleurs ne changent pas de teinte) : L' = L + force * somme_k(poids_k * (L - flou_k(L))) ;
#  - poids par defaut des 3 echelles 0.3 / 0.8 / 0.5 (normalises), comme palettes.md ;
#  - poids objet = 0 dans le ciel : le fond n'est pas modifie (ecart maximal affiche) ;
#  - hautes lumieres protegees : le gain diminue vers 1 pour ne pas ecreter le noyau.
import sys, numpy as np, cv2
from astropy.io import fits


def run(src, dst, force=0.6, rayons=(6, 20, 60)):
    h = fits.open(src)
    x = h[0].data.astype(np.float32)
    scale = 65535.0 if x.max() > 1.5 else 1.0
    x = x / scale
    L = x.mean(0)
    ls = cv2.GaussianBlur(L, (0, 0), 8)
    lo, hi = np.percentile(ls, 60), np.percentile(ls, 99.5)
    w = np.clip((ls - lo) / max(hi - lo, 1e-6), 0, 1)
    w = w * w * (3 - 2 * w)
    zone = np.clip((w - 0.01) * 5, 0, 1)
    poids = np.array([0.3, 0.8, 0.5][:len(rayons)], np.float32)
    poids /= poids.sum()
    detail = sum(p * (L - cv2.GaussianBlur(L, (0, 0), r)) for p, r in zip(poids, rayons))
    protege = 1 - np.clip((L - 0.85) / 0.15, 0, 1)
    newL = np.clip(L + force * detail * zone * protege, 0, 1)
    ratio = newL / np.maximum(L, 1e-6)
    out = np.clip(x * ratio, 0, 1)
    ciel = zone <= 0
    print('hautes lumieres (99e pc.) %.3f -> %.3f | zones sombres de l\'objet (5e pc. de L dans l\'objet) %.3f -> %.3f' % (
        np.percentile(L[zone > 0.5], 99), np.percentile(newL[zone > 0.5], 99),
        np.percentile(L[zone > 0.5], 5), np.percentile(newL[zone > 0.5], 5)))
    print('ciel : ecart maximal de pixel %.5f' % float(np.abs(out - x)[:, ciel].max()))
    bruit = lambda im: float(np.median(np.abs((im - cv2.GaussianBlur(im, (0, 0), 2))[zone > 0.3])))
    print('bruit haute frequence dans l\'objet %.4f -> %.4f' % (bruit(L), bruit(out.mean(0))))
    fits.PrimaryHDU((out * scale).astype(np.float32), h[0].header).writeto(dst, overwrite=True)
    print('OK', dst)


if __name__ == '__main__':
    a = sys.argv
    run(a[1], a[2], float(a[3]) if len(a) > 3 else 0.6,
        tuple(float(v) for v in a[4].split(',')) if len(a) > 4 else (6, 20, 60))

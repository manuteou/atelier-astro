# Teinte doree / lave ou bleu froid de l'objet (technique B de palettes.md), sur l'image ou le calque galaxie ETIRE.
# Usage (Siril) : pyscript "<chemin>/palette_doree_froide.py" <etiree.fit> <sortie.fit> dore|froid [force=0.7] [lissage=6]
#  - luminance conservee : seule la couleur change ; ciel non touche (poids objet = 0, ecart maximal affiche) ;
#  - poids = luminosite lissee de l'objet (comme coloration_galaxie.py) ;
#  - "exces Hα" : sans extraction narrowband, l'excès de rouge sur (V+B)/2 (lisse) sert de proxy aux regions HII ;
#  - dore : rampe rouge profond -> orange -> jaune dore suivant la luminosite^1.4, renforcee la ou l'exces est faible
#    (les regions HII gardent leur rose/rouge propre) ;
#  - froid : rampe bleu profond -> cyan -> bleu clair ; les regions HII (exces Hα) gardent leur couleur chaude.
# Valeurs de depart a regler a l'oeil (calees sur M33 : force 0.5 doux, 0.7 net, 1.0 fort).
import sys, numpy as np, cv2
from astropy.io import fits

RAMPES = {
    'dore': [(0.0, (1.0, 0.05, 0.04)), (0.5, (1.0, 0.45, 0.08)), (1.0, (1.0, 0.80, 0.22))],
    'froid': [(0.0, (0.05, 0.12, 0.55)), (0.5, (0.10, 0.60, 0.95)), (1.0, (0.65, 0.88, 1.0))],
}


def rampe(t, pts):
    xs = [p[0] for p in pts]
    return np.stack([np.interp(t, xs, [p[1][c] for p in pts]) for c in range(3)]).astype(np.float32)


def run(src, dst, mode='dore', force=0.7, smooth=6.0):
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
    ha = cv2.GaussianBlur(x[0] - 0.5 * (x[1] + x[2]), (0, 0), smooth)
    ha = np.clip(ha / max(np.percentile(ha[zone > 0.5], 99), 1e-6), 0, 1)       # 0 = pas d'exces, 1 = region HII
    t = np.clip(ls / max(hi, 1e-6), 0, 1) ** 1.4
    col = rampe(t, RAMPES[mode])
    lum = (0.2126 * col[0] + 0.7152 * col[1] + 0.0722 * col[2])
    col = col / np.maximum(lum, 1e-6) * L                                     # meme luminance que l'original
    poids = zone * force * (1 - ha) if mode == 'froid' else zone * force * (1 - 0.6 * ha)
    out = np.clip(x + np.clip(poids, 0, 1) * (col - x), 0, 1)
    ciel = zone <= 0
    sat = lambda im, m: float(np.mean((im.max(0) - im.min(0))[m] / np.maximum(im.max(0)[m], 1e-6)))
    noyau, bras = w > 0.8, (w > 0.1) & (w < 0.4)
    print('%s force %.2f | saturation noyau %.2f -> %.2f, bras %.2f -> %.2f | luminance (moyenne objet) %.3f -> %.3f' % (
        mode, force, sat(x, noyau), sat(out, noyau), sat(x, bras), sat(out, bras),
        L[zone > 0.5].mean(), out.mean(0)[zone > 0.5].mean()))
    print('ciel : ecart maximal de pixel %.5f' % float(np.abs(out - x)[:, ciel].max()))
    fits.PrimaryHDU((out * scale).astype(np.float32), h[0].header).writeto(dst, overwrite=True)
    print('OK', dst)


if __name__ == '__main__':
    a = sys.argv
    run(a[1], a[2], a[3] if len(a) > 3 else 'dore', float(a[4]) if len(a) > 4 else 0.7,
        float(a[5]) if len(a) > 5 else 6.0)

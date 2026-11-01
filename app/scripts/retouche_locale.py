# Retouches locales de fin de traitement (sur l'image etiree, avant l'export). Deux modes, dans un disque adouci (x, y, r) :
#   vert     : supprime un point vert (typique : noyau d'une galaxie) en limitant G a max(R, B) dans le disque ;
#   remplace : reprend dans le disque une AUTRE version de l'image (ex. version moins saturee) pour corriger un anneau colore autour d'une etoile.
# Usage (Siril) :
#   pyscript "<chemin>/retouche_locale.py" vert     <entree.fit> <sortie.fit> <x> <y> <r>
#   pyscript "<chemin>/retouche_locale.py" remplace <entree.fit> <sortie.fit> <x> <y> <r> <autre_version.fit>
# x, y : coordonnees telles qu'affichees par Siril (x depuis la gauche, y depuis le HAUT de l'image affichee) ; r : rayon en pixels
# (le bord est adouci sur ~40 % du rayon). Rien n'est modifie hors du disque. Les deux fichiers doivent avoir la meme taille.
import sys, numpy as np, cv2
from astropy.io import fits


def disque(H, W, x, y, r):
    yy, xx = np.mgrid[0:H, 0:W]
    row = H - 1 - y                        # y affiche (depuis le haut) -> ligne du tableau FITS
    d = np.sqrt((xx - x) ** 2 + (yy - row) ** 2)
    return np.clip((r - d) / max(0.4 * r, 1.0), 0, 1).astype(np.float32)


def run(mode, src, dst, x, y, r, other=None):
    h = fits.open(src)
    d = h[0].data.astype(np.float32)
    scale = 65535.0 if d.max() > 1.5 else 1.0
    d = d / scale
    m = disque(d.shape[1], d.shape[2], x, y, r)
    out = d.copy()
    if mode == 'vert':
        g = np.minimum(d[1], np.maximum(d[0], d[2]))
        out[1] = d[1] * (1 - m) + g * m
    elif mode == 'remplace':
        o = fits.getdata(other).astype(np.float32) / scale
        if o.shape != d.shape:
            raise SystemExit('les deux fichiers n ont pas la meme taille')
        out = d * (1 - m) + o * m
    else:
        raise SystemExit('mode inconnu : vert ou remplace')
    print('pixels modifies : %d | variation maximale %.3f | hors disque : aucune modification' % (
        int((np.abs(out - d).max(0) > 1e-6).sum()), float(np.abs(out - d).max())))
    fits.PrimaryHDU((np.clip(out, 0, 1) * scale).astype(np.float32), h[0].header).writeto(dst, overwrite=True)
    print('OK', dst)


if __name__ == '__main__':
    a = sys.argv
    run(a[1], a[2], a[3], float(a[4]), float(a[5]), float(a[6]), a[7] if len(a) > 7 else None)

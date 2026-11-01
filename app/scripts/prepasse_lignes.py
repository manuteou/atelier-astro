# Pre-passe : retrait des BANDES LIGNE PAR LIGNE, mesurees hors de l'objet (galaxie / nebuleuse), a faire AVANT l'aplanissement du fond.
# Seul, l'aplanissement (aplanir_fond_ciel.py) laisse des plaques a bords nets quand le fond a des bandes plus fortes que les bras faibles ;
# retirer d'abord les bandes evite que l'objet soit confondu avec elles. aplanir_fond_ciel.py appelle deja cette pre-passe par defaut.
# Usage (Siril) : pyscript "<chemin>/prepasse_lignes.py" <source.fit> <sortie.fit> [part_ciel=0.85] [lissage_px=40]
#  - masque objet : pixels de lumiere lissee au-dessus du percentile <part_ciel>, dilates (jamais mesures) ;
#  - par canal : mediane de chaque ligne sur le ciel, moins sa version lissee (lissage_px) = bande ; retiree de la ligne entiere.
#    Les degrades a grande echelle ne sont pas touches. Lignes avec moins de 15 % de ciel : pas de correction (interpolee).
import sys, numpy as np, cv2
from astropy.io import fits


def retire_bandes(d, frac=0.85, smooth=40.0):
    lum = cv2.GaussianBlur(d.mean(0), (0, 0), 12)
    obj = (lum > np.percentile(lum, 100 * frac)).astype(np.uint8)
    obj = cv2.dilate(obj, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61))).astype(bool)
    sky = ~obj
    H, W = sky.shape
    ok_rows = sky.sum(1) > 0.15 * W
    out = d.copy()
    for c in range(d.shape[0]):
        r = np.where(sky, d[c], np.nan)
        med = np.nanmedian(np.where(ok_rows[:, None], r, np.nan), axis=1)
        idx = np.arange(H)
        good = np.isfinite(med)
        med = np.interp(idx, idx[good], med[good])
        band = med - cv2.GaussianBlur(med.reshape(-1, 1).astype(np.float32), (0, 0), smooth).ravel()
        band[~ok_rows] = np.interp(idx[~ok_rows], idx[ok_rows], band[ok_rows]) if (~ok_rows).any() else band[~ok_rows]
        out[c] = d[c] - band[:, None]
    return out, sky


def run(src, dst, frac=0.85, smooth=40.0):
    h = fits.open(src)
    d = h[0].data.astype(np.float32)
    scale = 65535.0 if d.max() > 1.5 else 1.0
    out, sky = retire_bandes(d / scale, frac, smooth)
    def bandes(x):
        return float(np.mean([np.nanstd(np.nanmedian(np.where(sky, x[c], np.nan), axis=1) -
                                        cv2.GaussianBlur(np.nan_to_num(np.nanmedian(np.where(sky, x[c], np.nan), axis=1)).reshape(-1, 1).astype(np.float32), (0, 0), smooth).ravel())
                              for c in range(x.shape[0])]))
    print('amplitude des bandes (ecart-type des medianes de lignes, unites 0-65535) : avant %.1f -> apres %.1f' % (
        bandes(d / scale) * 65535, bandes(out) * 65535))
    fits.PrimaryHDU((np.clip(out, 0, 1) * scale).astype(np.float32), h[0].header).writeto(dst, overwrite=True)
    print('OK', dst)


if __name__ == '__main__':
    a = sys.argv
    run(a[1], a[2], float(a[3]) if len(a) > 3 else 0.85, float(a[4]) if len(a) > 4 else 40.0)

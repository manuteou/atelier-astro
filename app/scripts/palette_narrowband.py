# Palettes narrowband a partir de canaux mono Ha / OIII (/ SII), deja ETIRES (0-1) avec la MEME fonction (ex. split d'un RVB etire en lie).
# Usage (Siril) : pyscript "<chemin>/palette_narrowband.py" <palette> <ha.fit> <oiii.fit> <sortie.fit> [sii.fit]
# Palettes : hoo (R=Ha, V=OIII, B=OIII+0.15*Ha) | cuivre_bleu (R=0.9Ha+0.8SII, V=0.45Ha+0.30SII+0.50OIII, B=1.4OIII ; sans SII : SII remplace par Ha).
# Le fond du ciel (mediane de chaque canal) est conserve : les coefficients ne s'appliquent qu'au signal au-dessus du fond.
# Attention bruit : les gains > 1 amplifient le bruit du canal OIII (deja le plus bruite). Mesure sur NGC 7380 (fond, apres satu) : bruit rouge +68 %,
# bleu +31 % par rapport au melange Ha / 50-50 / OIII ; HOO double le bruit du vert. Debruiter avant (NXT lineaire) ; preferer la version voulue au rendu propre.
import sys, numpy as np
from astropy.io import fits


def lire(p):
    h = fits.open(p)
    x = h[0].data.astype(np.float32)
    s = 65535.0 if x.max() > 1.5 else 1.0
    x = x / s
    if x.ndim == 3:
        x = x.mean(0)
    return x, h[0].header, s


def palette(nom, H, O, S=None):
    bh, bo = float(np.median(H)), float(np.median(O))
    b = (bh + bo) / 2
    h, o = H - bh, O - bo
    s = (S - float(np.median(S))) if S is not None else h
    if nom == 'hoo':
        R, G, B = b + h, b + o, b + o + 0.15 * h
    elif nom == 'cuivre_bleu':
        R = b + 0.9 * h + 0.8 * s
        G = b + 0.45 * h + 0.30 * s + 0.50 * o
        B = b + 1.40 * o
    else:
        raise SystemExit('palette inconnue : %s (hoo | cuivre_bleu)' % nom)
    return np.clip(np.stack([R, G, B]), 0, 1).astype(np.float32)


if __name__ == '__main__':
    a = sys.argv
    nom, H, hh, s = a[1], *lire(a[2])
    O = lire(a[3])[0]
    S = lire(a[5])[0] if len(a) > 5 else None
    out = palette(nom, H, O, S)
    m = lambda c: float(out[c].mean())
    print('%s | moyennes R/V/B %.3f %.3f %.3f | max %.3f' % (nom, m(0), m(1), m(2), float(out.max())))
    fits.PrimaryHDU((out * s).astype(np.float32), hh).writeto(a[4], overwrite=True)
    print('OK', a[4])

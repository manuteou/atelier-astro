# Neutralisation de l'exces de vert du calque d'etoiles, AVANT le renfort de couleur (sinon le renfort verdit les petites etoiles et le noyau).
# Usage (Siril) : pyscript "<chemin>/neutralise_vert_etoiles.py" <calque_etoiles.fit> <sortie.fit> [facteur_force]
# Mesure : sur les pixels d'etoiles (max des canaux > 0.02), rapport du vert a la moyenne rouge/bleu, en FLUX (somme), ce qui evite
# le piege de `stat` (qui ignore les pixels a zero et fausse les moyennes sur ce calque). Correction : G x (1/rapport) quand le vert est en exces.
# Avec [facteur_force], applique ce facteur sur G sans mesurer (ex. 0.856). Imprime le rapport mesure pour verification.
import sys, numpy as np
from astropy.io import fits


def run(src, dst, force=None):
    h = fits.open(src)
    d = h[0].data.astype(np.float32)
    scale = 65535.0 if d.max() > 1.5 else 1.0
    x = d / scale
    m = x.max(0) > 0.02
    if m.sum() < 50:
        raise SystemExit('trop peu de pixels d etoiles pour mesurer')
    r, g, b = (x[c][m].sum() for c in range(3))
    ratio = g / ((r + b) / 2.0)
    print('pixels d etoiles : %d | rapport vert / moyenne(rouge, bleu) = %.3f (1.000 = neutre)' % (m.sum(), ratio))
    f = force if force is not None else (1.0 / ratio if ratio > 1.0 else 1.0)
    x[1] *= f
    print('facteur applique au vert : %.3f' % f)
    fits.PrimaryHDU((np.clip(x, 0, 1) * scale).astype(np.float32), h[0].header).writeto(dst, overwrite=True)


if __name__ == '__main__':
    a = sys.argv
    run(a[1], a[2], float(a[3]) if len(a) > 3 else None)

# Combinaison de deux filtres empiles SEPAREMENT puis alignes (meme taille) : ajoute les regions HII captees par le LP (dual-bande)
# a une image large bande IRCUT. Usage typique : galaxie (IRCUT = image principale, LP = Halpha des bras).
# Usage (Siril) : pyscript "<chemin>/combiner_filtres.py" <base_ircut.fit> <lp.fit> <sortie.fit> [force=1.0] [seuil=2.5] [rose=0.15] [k=auto]
#   base_ircut.fit : calque sans etoiles IRCUT ETIRE (RVB)            lp.fit : calque sans etoiles LP ETIRE (RVB ; canal rouge = Halpha) ou Halpha mono
#   force : gain de l'exces Halpha ajoute au rouge (0.5 / 1.0 / 1.5 a proposer cote a cote)
#   seuil : nombre d'ecarts-types de l'exces sous lequel rien n'est ajoute (protege le fond et le bruit du continuum)
#   rose  : part de l'exces ajoutee aussi au bleu (Hbeta), pour un rose naturel plutot qu'un rouge pur
#   k     : facteur de continuum (Halpha_LP ~ k * rouge_IRCUT sur la galaxie) ; 'auto' = mediane du rapport sur les pixels de l'objet
# Principe : exces = (Ha - fond) - k * (rouge IRCUT - fond), lisse (gaussienne 1.2 px), moins seuil * sigma, plancher 0.
# Seuls les pixels ou le LP montre plus de rouge que le continuum de la galaxie sont touches : le fond du ciel et le reste de la galaxie restent identiques.
# Ecrit aussi <sortie>_masque_ha.fit (exces ajoute, mono) pour controle.
import sys, numpy as np
from astropy.io import fits


def lire(p):
    h = fits.open(p)
    x = h[0].data.astype(np.float32)
    s = 65535.0 if x.max() > 1.5 else 1.0
    return x / s, h[0].header, s


def fond_sigma(x):
    m = float(np.median(x))
    bas = x[x <= m]
    sig = 1.4826 * float(np.median(np.abs(bas - m))) if bas.size else 0.0
    return m, max(sig, 1e-6)


def lisse(x, sigma=1.2):
    r = int(3 * sigma + 0.5)
    t = np.arange(-r, r + 1, dtype=np.float32)
    g = np.exp(-0.5 * (t / sigma) ** 2)
    g /= g.sum()
    p = np.pad(x, r, mode='edge')
    y = np.zeros_like(p)
    for i, w in enumerate(g):
        y += w * np.roll(p, i - r, axis=0)
    z = np.zeros_like(p)
    for i, w in enumerate(g):
        z += w * np.roll(y, i - r, axis=1)
    return z[r:-r, r:-r]


def combiner(base, lp, force=1.0, seuil=2.5, rose=0.15, k='auto'):
    if base.ndim != 3 or base.shape[0] != 3:
        raise SystemExit('ERREUR : la base IRCUT doit etre une image RVB (3 canaux)')
    ha = lp[0] if lp.ndim == 3 else lp
    if ha.shape != base.shape[1:]:
        raise SystemExit('ERREUR : tailles differentes (IRCUT %s, LP %s) : aligner les deux stacks et appliquer le meme recadrage'
                         % (base.shape[1:], ha.shape))
    r = base[0]
    mh, sh = fond_sigma(ha)
    mr, sr = fond_sigma(r)
    h, c = ha - mh, r - mr
    objet = c > 5 * sr
    if k == 'auto':
        if objet.sum() < 100:
            raise SystemExit('ERREUR : trop peu de pixels d objet dans le rouge IRCUT pour estimer k ; le passer a la main')
        k = float(np.median(h[objet] / c[objet]))
    else:
        k = float(k)
    e = lisse(h - k * c)
    zone = objet if objet.sum() >= 100 else np.ones_like(objet)
    me = float(np.median(e[zone]))
    se = 1.4826 * float(np.median(np.abs(e[zone] - me)))
    ajout = np.maximum(e - me - seuil * se, 0)
    out = base.copy()
    out[0] = r + force * ajout
    out[2] = base[2] + rose * force * ajout
    out = np.clip(out, 0, 1).astype(np.float32)
    return out, ajout.astype(np.float32), dict(k=k, sigma=se, objet=float(objet.mean()), touche=float((ajout > 0).mean()))


if __name__ == '__main__':
    a = sys.argv
    if len(a) < 4:
        raise SystemExit(__doc__ or 'usage : base_ircut.fit lp.fit sortie.fit [force] [seuil] [rose] [k]')
    base, hb, s = lire(a[1])
    lp = lire(a[2])[0]
    force = float(a[4]) if len(a) > 4 else 1.0
    seuil = float(a[5]) if len(a) > 5 else 2.5
    rose = float(a[6]) if len(a) > 6 else 0.15
    k = a[7] if len(a) > 7 else 'auto'
    out, ajout, info = combiner(base, lp, force, seuil, rose, k)
    ciel = ajout == 0
    d_ciel = [float(np.median(out[i][ciel]) - np.median(base[i][ciel])) for i in range(3)]
    t = ajout > 0
    gain_r = float((out[0][t] - base[0][t]).mean()) if t.any() else 0.0
    print('k continuum %.3f | sigma exces %.5f | objet %.1f %% du champ | pixels touches %.2f %% | ajout rouge moyen %.4f, max %.4f'
          % (info['k'], info['sigma'], 100 * info['objet'], 100 * info['touche'], gain_r, float(force * ajout.max())))
    print('ecart du fond (sortie - base) R/V/B : %.6f %.6f %.6f (attendu 0)' % tuple(d_ciel))
    if info['touche'] > 0.15:
        print('ATTENTION : plus de 15 %% du champ touche : continuum mal soustrait (k trop bas ?) ou LP non aligne ; monter le seuil ou passer k a la main')
    fits.PrimaryHDU((out * s).astype(np.float32), hb).writeto(a[3], overwrite=True)
    m = a[3][:-4] if a[3].lower().endswith('.fit') else a[3]
    fits.PrimaryHDU((ajout * s).astype(np.float32), hb).writeto(m + '_masque_ha.fit', overwrite=True)
    print('OK', a[3], '+', m + '_masque_ha.fit')

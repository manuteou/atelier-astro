# Aplanissement du fond du ciel sur le calque SANS ETOILES (etire, apres la separation des etoiles, avant la fusion en ecran).
# Usage (Siril) : pyscript "<chemin>/aplanir_fond_ciel.py" <source.fit> <sortie.fit> [part_ciel=0.85] [sigma_px=40] [prepasse=1] [x y largeur hauteur]
# Les 4 derniers arguments (facultatifs) donnent une zone de CONTROLE (coordonnees affichees par Siril, y depuis le haut), p. ex. un bras externe faible :
# le script imprime le signal de cette zone au-dessus du ciel avant -> apres et le pourcentage conserve. Sous ~80 %, proposer une part_ciel plus basse (0.70).
# Etape 0 (par defaut) : pre-passe de retrait des bandes ligne par ligne, mesurees hors de l'objet (voir prepasse_lignes.py) ; 0 = desactivee.
# Corrige les plaques claires/sombres, les bandes lignes/colonnes et les taches de teinte du fond, sans toucher a l'objet :
#  1. masque "ciel" = les <part_ciel> pixels les moins lumineux de la lumiere lissee (puis erode) ; l'objet est interpole, jamais mesure ;
#  2. par canal : carte du fond = moyenne lissee (sigma px) des pixels de ciel, retiree ; niveau du ciel conserve ;
#  3. retrait des profils lignes et colonnes residuels mesures sur le ciel ; medianes de ciel egalisees entre canaux.
# Part_ciel : 0.85 retenu sur M33 (fond uniforme, galaxie intacte) ; 0.70 laisse une bande verdatre ; 0.50 corrige les bandes seulement.
# ATTENTION : suppose que la cible n'occupe pas tout le champ (au moins ~20 % de ciel). Si elle le remplit (grande nebuleuse),
# descendre part_ciel (0.5) ou ne pas l'utiliser : le script avertit quand le ciel retenu n'est pas nettement plus sombre que le reste.
import sys, numpy as np, cv2
from astropy.io import fits


def bandes_lignes(d, frac=0.85, smooth=40.0):
    # meme methode que prepasse_lignes.py : mediane de chaque ligne sur le ciel (hors objet), moins sa version lissee
    lum = cv2.GaussianBlur(d.mean(0), (0, 0), 12)
    obj = (lum > np.percentile(lum, 100 * frac)).astype(np.uint8)
    sky = ~cv2.dilate(obj, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61))).astype(bool)
    H, W = sky.shape
    ok = sky.sum(1) > 0.15 * W
    idx = np.arange(H)
    out = d.copy()
    for c in range(d.shape[0]):
        med = np.nanmedian(np.where(ok[:, None] & sky, d[c], np.nan), axis=1)
        good = np.isfinite(med)
        med = np.interp(idx, idx[good], med[good])
        band = med - cv2.GaussianBlur(med.reshape(-1, 1).astype(np.float32), (0, 0), smooth).ravel()
        out[c] = d[c] - band[:, None]
    return out


def run(src, dst, frac=0.85, sig=40.0, prepasse=True, box=None):
    hd = fits.open(src)
    d = hd[0].data.astype(np.float32)
    hdr = hd[0].header
    if d.ndim != 3 or d.shape[0] != 3:
        raise SystemExit('image couleur 3 canaux attendue')
    scale = 65535.0 if d.max() > 1.5 else 1.0
    d = d / scale
    d0 = d.copy()
    if prepasse:
        d = bandes_lignes(d, frac, sig)
    lum = d.mean(0)
    sm = cv2.GaussianBlur(lum, (0, 0), 12)
    thr = np.percentile(sm, 100 * frac)
    sky = cv2.erode((sm < thr).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))).astype(bool)
    w = sky.astype(np.float32)
    p5, p50, p95 = np.percentile(sm, [5, 50, 95])
    if (p95 - p50) < 1.5 * (p50 - p5):
        print('AVERTISSEMENT : le haut de l image n est pas nettement plus lumineux que le reste ; la cible remplit peut-etre le champ. '
              'Baisser part_ciel (0.5) ou ne pas appliquer.')
    print('ciel retenu : %.0f %% de l image' % (100 * sky.mean()))
    out = d.copy()
    for c in range(3):
        x = d[c]
        num = cv2.GaussianBlur(x * w, (0, 0), sig)
        den = cv2.GaussianBlur(w, (0, 0), sig)
        far = cv2.GaussianBlur(x * w, (0, 0), sig * 3) / np.maximum(cv2.GaussianBlur(w, (0, 0), sig * 3), 1e-4)
        model = np.where(den > 0.02, num / np.maximum(den, 1e-4), far)
        ped = float(np.median(x[sky]))
        y = x - (model - ped)
        for axis in (1, 0):  # profils lignes puis colonnes, mesures sur le ciel
            r = np.where(sky, y - ped, np.nan)
            prof = np.nanmedian(r, axis=axis)
            prof = np.where(np.isfinite(prof), prof, 0).astype(np.float32)
            prof = cv2.GaussianBlur(prof.reshape(-1, 1), (0, 0), 2).ravel()
            y = y - (prof[:, None] if axis == 1 else prof[None, :])
        out[c] = y
    meds = np.array([np.median(out[c][sky]) for c in range(3)])
    for c in range(3):
        out[c] -= meds[c] - meds.mean()
    out = np.clip(out, 0, 1)
    if box:
        bx, by, bw, bh = [int(v) for v in box]
        H = d.shape[1]
        sl = (slice(H - by - bh, H - by), slice(bx, bx + bw))
        ciel0, ciel1 = float(np.median(d0.mean(0)[sky])), float(np.median(out.mean(0)[sky]))
        a = float(d0.mean(0)[sl].mean()) - ciel0
        b = float(out.mean(0)[sl].mean()) - ciel1
        print('zone de controle : signal au-dessus du ciel %.5f -> %.5f (%.0f %% conserve)%s' % (
            a, b, 100 * b / a if a > 0 else float('nan'), ' | ATTENTION : baisser part_ciel (0.70)' if a > 0 and b / a < 0.8 else ''))
    fits.PrimaryHDU((out * scale).astype(np.float32), hdr).writeto(dst, overwrite=True)
    print('OK', dst, '| ciel (0-1) R/V/B :', ' / '.join('%.5f' % np.median(out[c][sky]) for c in range(3)))


if __name__ == '__main__':
    a = sys.argv
    run(a[1], a[2], float(a[3]) if len(a) > 3 else 0.85, float(a[4]) if len(a) > 4 else 40.0, (a[5] != '0') if len(a) > 5 else True, a[6:10] if len(a) > 9 else None)

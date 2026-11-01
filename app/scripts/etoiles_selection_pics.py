# Selection d'etoiles ETOILE PAR ETOILE (methode par defaut depuis 0.30.0, validee sur NGC 281 le 30/10/2026) : les etoiles voisines fusionnees dans une meme tache sont
# separees par montee de gradient (chaque pixel rattache a son pic), si bien qu'une etoile brillante gardee n'emmene plus
# ses petites voisines (grappes). Reprise telle quelle du calque d'origine dans le bassin de chaque etoile retenue.
# Usage : pyscript etoiles_selection_pics.py <calque_etoiles.fit> <sans_etoiles.fit> <sortie.fit> <N_ciel> <N_objet>
#         [part_objet=0.97] [plancher=0.08] [pic_min=0.20] [coeur=0] [halo=7]
#  - amas (11e argument, optionnel) : 'x,y,r[,pic]' en coordonnees numpy (ligne 0 = premiere ligne du FITS) ; les etoiles du disque
#    de pic > pic (defaut pic_min), ou les <pic> plus brillantes si pic est un entier > 1, sont gardees en plus des N_objet (protege un amas comme IC 1590).
#  - halo : taille (px) de l'ouverture qui recree le halo lisse des etoiles gardees la ou une voisine retiree le mordait (0 = non).
#  - plancher : niveau de la zone partagee en bassins (bas = halos complets) ; pic_min : pic minimal d'une etoile ;
#  - coeur > 0 : rayon max (px) autour du pic = coeur * (flux relatif)^0.25, au-dela le bassin est coupe (option).
#  - N_objet : les N plus brillantes gardees aussi DANS la zone de l'objet (etoiles_selection.py n'y touchait jamais).
#  - reglage valide sur calque etire (NGC 281) : 0.97 0.08 0.20 0 11 (halo 7 laisse des fantomes, 11 est propre).
# Ecrit aussi <sortie>_selection.fit.
import sys, numpy as np, cv2
from astropy.io import fits


def run(stars_p, starless_p, out_p, n_ciel, n_obj, frac=0.97, plancher=0.08, pic_min=0.20, coeur=0.0, halo=7, amas=None):
    h = fits.open(stars_p)
    st = h[0].data.astype(np.float32)
    sl = fits.getdata(starless_p).astype(np.float32)
    scale = 65535.0 if st.max() > 1.5 else 1.0
    st, sl = st / scale, sl / scale
    C, H, W = st.shape
    lum = cv2.GaussianBlur(sl.mean(0), (0, 0), 12)
    obj = (lum > np.percentile(lum, 100 * frac)).astype(np.uint8)
    obj = cv2.dilate(obj, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (81, 81)))
    m = cv2.GaussianBlur(obj.astype(np.float32), (0, 0), 40)
    mx = st.max(0)
    sm = cv2.GaussianBlur(mx, (0, 0), 0.8)
    zone = mx > plancher
    # rattachement de chaque pixel a son pic par montee de gradient (pointeur vers le voisin 3x3 le plus lumineux)
    pad = np.pad(sm, 1, constant_values=-1.0)
    best = sm.copy(); arg = np.arange(H * W).reshape(H, W)
    ptr = arg.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            v = pad[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
            b = v > best
            best = np.where(b, v, best)
            ptr = np.where(b, arg + dy * W + dx, ptr)
    ptr = ptr.ravel()
    for _ in range(60):
        nxt = ptr[ptr]
        if np.array_equal(nxt, ptr):
            break
        ptr = nxt
    root = (ptr == np.arange(H * W)).reshape(H, W) & zone   # sommets (plateaux satures inclus)
    npk, mk = cv2.connectedComponents(root.astype(np.uint8), connectivity=8)  # un plateau = une etoile
    okpk = np.zeros(npk, bool); pkmax = np.zeros(npk, np.float32)
    np.maximum.at(pkmax, mk.ravel(), mx.ravel()); okpk[1:] = pkmax[1:] > pic_min
    bas = mk.ravel()[ptr].reshape(H, W)
    bas[~zone] = 0
    bas[~okpk[bas]] = 0                          # sommets trop faibles : bruit, pas une etoile retenue possible
    n = npk
    flux = np.zeros(n, np.float64); np.add.at(flux, bas.ravel(), mx.ravel())
    pkv = np.zeros(n, np.float32); np.maximum.at(pkv, bas.ravel(), mx.ravel())
    cy = np.zeros(n); cx = np.zeros(n); cnt = np.bincount(mk.ravel(), minlength=n).astype(float)
    yy, xx = np.nonzero(mk)
    np.add.at(cy, mk[yy, xx], yy); np.add.at(cx, mk[yy, xx], xx)
    ids_ok = okpk
    cnt[0] = 1; cy /= np.maximum(cnt, 1); cx /= np.maximum(cnt, 1)
    mc = m[np.clip(cy.astype(int), 0, H - 1), np.clip(cx.astype(int), 0, W - 1)]
    ids = (np.arange(n) > 0) & ids_ok
    keep = np.zeros(n, bool)
    for nom, z, N in (('ciel', ids & (mc < 0.01), n_ciel), ('objet', ids & (mc >= 0.01), n_obj)):
        idx = np.where(z)[0]
        top = idx[np.argsort(-flux[idx])[:int(N)]]
        keep[top] = True
        print('zone %s : %d etoiles (pics), %d gardees, pic de la derniere %.3f' % (nom, len(idx), len(top), float(pkv[top].min()) if len(top) else 0.0))
    if amas is not None:                         # amas protege : toutes ses etoiles (pic > pic_min) gardees en plus
        ax, ay, ar = amas[:3]
        apic = amas[3] if len(amas) > 3 else pic_min
        inn = ids & (np.hypot(cx - ax, cy - ay) <= ar)
        if apic > 1:                             # entier > 1 : les N plus brillantes de l'amas (par flux)
            idx = np.where(inn)[0]; inn = np.zeros(n, bool); inn[idx[np.argsort(-flux[idx])[:int(apic)]]] = True
        else:
            inn &= pkv > apic
        print('amas protege (%d, %d, r=%d) : %d etoiles gardees, dont %d en plus' % (ax, ay, ar, int(inn.sum()), int((inn & ~keep).sum())))
        keep |= inn
    sel = keep[bas].astype(np.float32)
    if coeur > 0:
        rmax = np.zeros(n); rmax[keep] = coeur * (flux[keep] / np.median(flux[keep])) ** 0.25
        r = np.hypot(np.arange(W)[None, :] - cx[bas], np.arange(H)[:, None] - cy[bas])
        sel *= (r <= rmax[bas] + 1).astype(np.float32)
    # bord doux : plus de pixels hors bassin, adoucissement leger seulement a l'interieur des bassins retenus
    soft = np.clip(cv2.GaussianBlur(sel, (0, 0), 1.0) * 1.3, 0, 1)
    sel = np.where(zone, soft * (sel > 0), soft) * ((bas == 0) | keep[bas])
    # halos entailles : la ou une voisine retiree mordait dans le halo d'une etoile gardee, on remet le halo lisse
    # (ouverture morphologique : enleve les petites etoiles, garde les halos larges), seulement pres des etoiles gardees
    if halo > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(halo), int(halo)))
        op = np.stack([cv2.morphologyEx(st[c], cv2.MORPH_OPEN, k) for c in range(C)])
        pres = cv2.dilate((sel > 0.5).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))).astype(np.float32)
        pres = cv2.GaussianBlur(pres, (0, 0), 2) * (keep[bas] == 0)
        out = st * sel + np.minimum(op, st) * pres * (1 - sel)
    else:
        out = st * sel
    fits.PrimaryHDU((out * scale).astype(np.float32), h[0].header).writeto(out_p, overwrite=True)
    fits.PrimaryHDU(sel.astype(np.float32)).writeto(out_p.replace('.fit', '_selection.fit'), overwrite=True)
    print('masque objet : %.0f %% de l image | etoiles separees : %d' % (100 * (m > 0.5).mean(), n - 1))


if __name__ == '__main__':
    a = sys.argv
    f = lambda i, d: float(a[i]) if len(a) > i else d
    run(a[1], a[2], a[3], int(a[4]), int(a[5]), f(6, 0.97), f(7, 0.08), f(8, 0.20), f(9, 0.0), f(10, 7),
        tuple(float(v) for v in a[11].split(',')) if len(a) > 11 else None)

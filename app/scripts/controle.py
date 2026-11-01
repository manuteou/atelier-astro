#!/usr/bin/env python3
"""
controle.py - mesures mécaniques pour le contrôle qualité astro (projet astro-siril).

Le script fait les vérifications chiffrées, toujours de la même façon.
L'agent de contrôle lit son rapport, puis se concentre sur le jugement :
images, NOTES.md, consigne de l'utilisateur, tout ce qui sort de l'ordinaire.
Le script ne remplace PAS l'agent.

Conventions (identiques partout) :
  - Valeurs en ADU sur 0-65535 (un FIT 32 bits 0-1 est multiplié par 65535).
  - Médianes, zéros compris. Jamais de moyennes pour juger la neutralité.
  - Positions données en (x, y compté depuis le HAUT de l'image affichée)
    ET en ligne FITS (Siril range la ligne 0 en bas de l'image).
  - Chaque ligne du rapport commence par OK, ATTENTION ou INFO.
  - Code de sortie : 0 si aucune ATTENTION, 1 sinon, 2 en cas d'erreur.

Sous-commandes :
  fit FICHIER.fit                    fond, neutralité, zéros, écrêtage, coins, grille, bruit, en-tête
  diff AVANT.fit APRES.fit           ce qui a changé entre deux FIT (zones, nombre de pixels)
  ecran FUSION.fit CALQUE1 CALQUE2   vérifie fusion = min(1-(1-a)(1-b), 1)
  export IMAGE FIT [--autre FIT]     JPEG/TIFF : taille, profondeur, profil ICC, correspondance au FIT
  notes NOTES.md [--dossier DIR]     fichiers cités absents, fichiers « à ne pas utiliser » encore cités

Dépendances : numpy, astropy, scipy, Pillow (tifffile conseillé pour les TIFF 16 bits).
"""

import argparse
import os
import re
import sys

import numpy as np

ATTENTIONS = []


def ligne(statut, texte):
    if statut == "ATTENTION":
        ATTENTIONS.append(texte)
    print(f"{statut:<9} {texte}")


def titre(texte):
    print(f"\n== {texte}")


def fmt3(v):
    return "/".join(f"{x:.0f}" for x in v)


# ----------------------------------------------------------------- lecture

def lire_fit(chemin):
    from astropy.io import fits
    with fits.open(chemin, memmap=False) as h:
        hdu = next(x for x in h if x.data is not None)
        data = np.asarray(hdu.data)
        header = hdu.header.copy()
    entier = np.issubdtype(data.dtype, np.integer)
    data = data.astype(np.float32)
    if entier:
        data /= 65535.0
    if data.ndim == 2:
        data = data[None]
    # Siril : ligne 0 en bas. On retourne pour avoir l'image telle qu'affichée.
    affiche = data[:, ::-1, :] * 65535.0
    return affiche, header


def lire_image(chemin):
    """Retourne (tableau HxWxC en 0-255 float, profondeur en bits, profil ICC bytes ou None)."""
    from PIL import Image
    icc = None
    with Image.open(chemin) as im:
        icc = im.info.get("icc_profile")
        mode = im.mode
    ext = os.path.splitext(chemin)[1].lower()
    if ext in (".tif", ".tiff"):
        try:
            import tifffile
            with tifffile.TiffFile(chemin) as t:
                page = t.pages[0]
                arr = page.asarray()
                bits = page.bitspersample
                tag = page.tags.get("InterColorProfile")
                if tag is not None and icc is None:
                    icc = bytes(tag.value)
            arr = arr.astype(np.float32)
            if bits == 16:
                arr /= 257.0
            if arr.ndim == 3 and arr.shape[0] in (3, 4) and arr.shape[-1] not in (3, 4):
                arr = np.moveaxis(arr, 0, -1)
            return arr[..., :3] if arr.ndim == 3 else arr[..., None], bits, icc
        except ImportError:
            ligne("INFO", "tifffile absent : TIFF lu par Pillow, profondeur 16 bits non vérifiable")
    from PIL import Image
    with Image.open(chemin) as im:
        im = im.convert("RGB")
        arr = np.asarray(im, dtype=np.float32)
    bits = 8 if mode in ("RGB", "L", "P", "RGBA") else None
    return arr, bits, icc


def nom_icc(icc):
    if not icc:
        return None
    try:
        import io
        from PIL import ImageCms
        p = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        return ImageCms.getProfileDescription(p).strip() or "profil sans nom"
    except Exception:
        return "profil présent (nom illisible)"


# ----------------------------------------------------------------- masques

def masques_ciel(img):
    """Masque de ciel (objet exclu) et masque de ciel hors étoiles, sur l'image affichée."""
    from scipy import ndimage as ndi
    lum = img.mean(axis=0)
    # travail en réduction x4 pour la vitesse, puis remise à l'échelle
    f = 4
    h, w = lum.shape
    petit = lum[: h - h % f, : w - w % f].reshape(h // f, f, w // f, f).mean(axis=(1, 3))
    lisse = ndi.gaussian_filter(petit, 25 / f)
    seuil = np.percentile(lisse, 70)            # objet = 30 % les plus lumineux
    objet = lisse > seuil
    dist = ndi.distance_transform_edt(~objet)
    objet = dist <= 40 / f                       # dilatation d'environ 40 px
    ciel_p = ~objet
    ciel = np.zeros_like(lum, dtype=bool)
    grand = np.repeat(np.repeat(ciel_p, f, axis=0), f, axis=1)
    ciel[: grand.shape[0], : grand.shape[1]] = grand
    # étoiles : excès local au-dessus d'un fond lissé
    fond = ndi.gaussian_filter(lum, 8)
    resid = lum - fond
    mad = np.median(np.abs(resid[ciel] - np.median(resid[ciel]))) * 1.4826 if ciel.any() else 0
    etoiles = resid > 3 * max(mad, 1e-6)
    etoiles = ndi.binary_dilation(etoiles, iterations=4)
    return ciel, ciel & ~etoiles


def mediane_canaux(img, masque):
    return np.array([np.median(c[masque]) for c in img])


# ----------------------------------------------------------------- fit

def cmd_fit(a):
    img, hdr = lire_fit(a.fichier)
    c, h, w = img.shape
    titre(f"FIT {os.path.basename(a.fichier)}")
    ligne("INFO", f"dimensions {w}x{h}, {c} canal(aux)")

    nan = int(np.isnan(img).sum())
    ligne("OK" if nan == 0 else "ATTENTION", f"pixels NaN : {nan}")
    img = np.nan_to_num(img)

    ecr = (img >= 0.9999 * 65535).any(axis=0).mean() * 100
    ligne("OK" if ecr <= a.tol_ecretage else "ATTENTION",
          f"pixels écrêtés (au moins un canal >= 0,9999) : {ecr:.4f} % (seuil {a.tol_ecretage} %)")
    ligne("INFO", f"min {fmt3(img.reshape(c, -1).min(1))}, max {fmt3(img.reshape(c, -1).max(1))}")

    zeros = np.array([(ch <= 0).mean() * 100 for ch in img])
    ecart_z = zeros.max() - zeros.min()
    ligne("OK" if ecart_z <= a.tol_zeros else "ATTENTION",
          f"pixels à 0 par canal : {'/'.join(f'{z:.2f}' for z in zeros)} % "
          f"(écart {ecart_z:.2f} point, seuil {a.tol_zeros} ; un écart = point noir différent selon le canal)")

    if c == 3:
        ciel, ciel_sans = masques_ciel(img)
        if a.etoiles:
            et, _ = lire_fit(a.etoiles)
            if et.shape[1:] == img.shape[1:]:
                ciel_sans = ciel & (et.max(axis=0) < 50)
                ligne("INFO", f"ciel hors étoiles défini par le calque {os.path.basename(a.etoiles)} (< 50 ADU)")
            else:
                ligne("ATTENTION", "calque d'étoiles de dimensions différentes : ignoré")
        ligne("INFO", f"masque de ciel : {ciel.mean()*100:.0f} % du champ, "
                      f"dont {ciel_sans.mean()*100:.0f} % hors étoiles")
        m = mediane_canaux(img, ciel)
        ms = mediane_canaux(img, ciel_sans)
        ref = m[1]
        ec = max(abs(m[0] - ref), abs(m[2] - ref))
        ecs = max(abs(ms[0] - ms[1]), abs(ms[2] - ms[1]))
        fond_ok = ecs <= a.tol_neutre
        # Le fond hors étoiles fait foi : si lui est neutre, l'écart global vient des halos d'étoiles.
        ligne("OK" if ec <= a.tol_neutre else ("INFO" if fond_ok else "ATTENTION"),
              f"ciel, médianes R/V/B : {fmt3(m)} (écart max au vert {ec:.0f} ADU, seuil {a.tol_neutre})")
        ligne("OK" if fond_ok else "ATTENTION",
              f"ciel hors étoiles, médianes R/V/B : {fmt3(ms)} (écart max au vert {ecs:.0f} ADU)")
        if ec > a.tol_neutre and fond_ok:
            ligne("INFO", "le fond lui-même est neutre : l'écart du ciel global vient de la lumière des étoiles")
            if not a.etoiles:
                ligne("INFO", "masque d'étoiles estimé : pour une mesure exacte, relancer avec --etoiles <calque d'étoiles>")

        # bruit : écart-type robuste du résidu haute fréquence dans le ciel hors étoiles
        from scipy import ndimage as ndi
        bruit = []
        for ch in img:
            r = ch - ndi.gaussian_filter(ch, 3)
            v = r[ciel_sans]
            bruit.append(np.median(np.abs(v - np.median(v))) * 1.4826)
        ligne("INFO", f"bruit du fond (MAD haute fréquence, pas le bgnoise Siril) R/V/B : {fmt3(bruit)}")

        # coins (boîtes de 150 px, image affichée)
        b = 150
        coins = {
            "haut-gauche": (slice(0, b), slice(0, b)),
            "haut-droite": (slice(0, b), slice(w - b, w)),
            "bas-gauche": (slice(h - b, h), slice(0, b)),
            "bas-droite": (slice(h - b, h), slice(w - b, w)),
        }
        txt = []
        mins = []
        for nom, (ys, xs) in coins.items():
            v = np.array([np.median(ch[ys, xs]) for ch in img])
            txt.append(f"{nom} {fmt3(v)}")
            mins.append(v.min())
        ligne("INFO", "coins 150 px (orientation affichée) : " + " ; ".join(txt))
        if min(mins) < 0.15 * ref:
            ligne("ATTENTION", "un coin a un canal presque nul : teinte du fond déséquilibrée à cet endroit")

        # grille 5x4 sur le ciel
        nx, ny = 4, 5
        cases = []
        for j in range(ny):
            for i in range(nx):
                ys = slice(j * h // ny, (j + 1) * h // ny)
                xs = slice(i * w // nx, (i + 1) * w // nx)
                mk = ciel[ys, xs]
                if mk.mean() < 0.2:      # case trop couverte par l'objet : ignorée
                    continue
                cases.append([np.median(ch[ys, xs][mk]) for ch in img])
        if cases:
            cases = np.array(cases)
            lo, hi = cases.min(0), cases.max(0)
            etendue = (hi - lo) / np.maximum(m, 1)
            txt = " ; ".join(f"{n} {l:.0f}–{u:.0f}" for n, l, u in zip("RVB", lo, hi))
            ok = etendue.max() <= a.tol_grille
            ligne("OK" if ok else "ATTENTION",
                  f"fond, grille 5x4 ({len(cases)} cases couvertes à 20 % au moins) : {txt} "
                  f"(étendue max {etendue.max()*100:.0f} % de la médiane, seuil {a.tol_grille*100:.0f} %)")

    # en-tête
    titre("En-tête FITS")
    expt = hdr.get("EXPTIME")
    if expt is not None:
        ligne("ATTENTION" if expt <= 0 else "INFO",
              f"EXPTIME = {expt}" + (" (négatif ou nul : ne pas l'utiliser)" if expt <= 0 else ""))
    for k in ("LIVETIME", "STACKCNT", "FILENAME"):
        if k in hdr:
            ligne("INFO", f"{k} = {hdr[k]} (ne pas reprendre dans la fiche : chiffres = NOTES.md)")


# ----------------------------------------------------------------- diff

def cmd_diff(a):
    from scipy import ndimage as ndi
    av, _ = lire_fit(a.avant)
    ap, _ = lire_fit(a.apres)
    titre(f"DIFF {os.path.basename(a.avant)} -> {os.path.basename(a.apres)}")
    if av.shape != ap.shape:
        ligne("ATTENTION", f"dimensions différentes : {av.shape} contre {ap.shape}")
        return
    d = np.abs(ap - av).max(axis=0)
    chg = d > a.tol * 65535
    n = int(chg.sum())
    h = chg.shape[0]
    ligne("INFO", f"pixels modifiés : {n} ({n / chg.size * 100:.3f} % de l'image), écart max {d.max():.1f} ADU")
    if n == 0:
        ligne("INFO", "les deux fichiers sont identiques")
        return
    lab, nb = ndi.label(ndi.binary_dilation(chg, iterations=10))
    ligne("OK" if nb <= a.zones else "ATTENTION",
          f"zones modifiées : {nb} (attendu au plus {a.zones})")
    objets = ndi.find_objects(lab)
    tailles = ndi.sum(chg, lab, range(1, nb + 1))
    ordre = np.argsort(tailles)[::-1][:5]
    for k in ordre:
        sl = objets[k]
        yy, xx = np.nonzero(chg[sl] & (lab[sl] == k + 1))
        y0, y1 = sl[0].start + yy.min(), sl[0].start + yy.max()
        x0, x1 = sl[1].start + xx.min(), sl[1].start + xx.max()
        ligne("INFO",
              f"zone {k+1} : {int(tailles[k])} px, x {x0}-{x1}, "
              f"y depuis le haut {y0}-{y1}, lignes FITS {h-1-y1}-{h-1-y0}")


# ----------------------------------------------------------------- ecran

def cmd_ecran(a):
    f, _ = lire_fit(a.fusion)
    c1, _ = lire_fit(a.calque1)
    c2, _ = lire_fit(a.calque2)
    titre(f"FUSION EN ÉCRAN {os.path.basename(a.fusion)}")
    if not (f.shape == c1.shape == c2.shape):
        ligne("ATTENTION", f"dimensions différentes : {f.shape}, {c1.shape}, {c2.shape}")
        return
    x1, x2 = c1 / 65535, c2 / 65535
    attendu = np.minimum(1 - (1 - x1) * (1 - x2), 1) * 65535
    e = np.abs(attendu - f)
    ligne("OK" if e.max() <= a.tol else "ATTENTION",
          f"écart à min(1-(1-a)(1-b),1) : max {e.max():.3f} ADU, moyen {e.mean():.4f} ADU (seuil {a.tol})")


# ----------------------------------------------------------------- export

def vers_8bits(img_fit):
    return np.clip(img_fit / 65535.0, 0, 1).transpose(1, 2, 0) * 255.0


def redim(arr, taille_hw):
    from PIL import Image
    if arr.shape[:2] == taille_hw:
        return arr
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    im = im.resize((taille_hw[1], taille_hw[0]), Image.LANCZOS)
    return np.asarray(im, dtype=np.float32)


def comparer(img, fit8):
    """Écart moyen pour 4 orientations ; retourne liste triée (écart, nom)."""
    ref = redim(fit8, img.shape[:2]) if fit8.shape[:2] != img.shape[:2] else fit8
    variantes = {
        "même sens": ref,
        "retourné haut-bas": ref[::-1],
        "retourné gauche-droite": ref[:, ::-1],
        "pivoté 180°": ref[::-1, ::-1],
    }
    res = []
    for nom, r in variantes.items():
        if r.shape != img.shape:
            continue
        res.append((float(np.abs(img - r).mean()), nom))
    return sorted(res)


def cmd_export(a):
    img, bits, icc = lire_image(a.image)
    titre(f"EXPORT {os.path.basename(a.image)}")
    taille = os.path.getsize(a.image)
    ligne("INFO", f"{img.shape[1]}x{img.shape[0]}, {bits} bits par canal, {taille:,} octets".replace(",", " "))
    if a.bits and bits != a.bits:
        ligne("ATTENTION", f"profondeur {bits} bits, attendu {a.bits}")
    n = nom_icc(icc)
    ligne("OK" if n else "ATTENTION", f"profil ICC : {n or 'absent'}")
    if n and "srgb" not in n.lower():
        ligne("ATTENTION", f"le profil ne semble pas être du sRGB : {n}")

    ecr = (img >= 254).any(axis=2).mean() * 100
    noir = (img <= 0).all(axis=2).mean() * 100
    ligne("OK" if ecr <= a.tol_ecretage else "ATTENTION",
          f"pixels >= 254 sur au moins un canal : {ecr:.3f} % ; noirs purs : {noir:.4f} %")

    bord = 6
    bords = np.concatenate([img[:bord].ravel(), img[-bord:].ravel(),
                            img[:, :bord].ravel(), img[:, -bord:].ravel()])
    centre = img[img.shape[0]//3: 2*img.shape[0]//3, img.shape[1]//3: 2*img.shape[1]//3]
    rb, rc = bords.mean(), centre.mean()
    ligne("OK" if rb <= max(rc * 0.6, 40) else "ATTENTION",
          f"bords ({bord} px) moyenne {rb:.1f} contre centre {rc:.1f} (un bord clair = liseré résiduel)")

    if a.fit:
        f, _ = lire_fit(a.fit)
        if f.shape[0] != 3:
            ligne("INFO", "FIT non couleur : correspondance non calculée")
            return
        res = comparer(img, vers_8bits(f))
        meilleur, sens = res[0]
        ligne("OK" if sens == "même sens" else "ATTENTION",
              f"orientation par rapport au FIT : {sens} (écart moyen {meilleur:.2f} ; "
              f"suivant : {res[1][1]} {res[1][0]:.2f})")
        ligne("OK" if meilleur <= a.tol_corresp else "ATTENTION",
              f"correspondance au FIT {os.path.basename(a.fit)} : écart moyen {meilleur:.2f}/255 "
              f"(seuil {a.tol_corresp} ; 2-3 est normal pour un JPEG)")
        if a.autre:
            g, _ = lire_fit(a.autre)
            autre = comparer(img, vers_8bits(g))[0][0]
            ligne("OK" if meilleur < autre else "ATTENTION",
                  f"plus proche de son FIT ({meilleur:.2f}) que de {os.path.basename(a.autre)} ({autre:.2f})")


# ----------------------------------------------------------------- notes

EXT = r"(?:fit|fits|fts|jpg|jpeg|tif|tiff|png|pdf|py)"
RE_FICH = re.compile(r"[\w\\/.\-]+\." + EXT + r"\b", re.IGNORECASE)
RE_INTERDIT = re.compile(r"(ne plus utiliser|ne pas utiliser|à ne pas utiliser|remplacés?|FAUX)", re.IGNORECASE)


def cmd_notes(a):
    texte = open(a.notes, encoding="utf-8").read().splitlines()
    titre(f"NOTES {os.path.basename(a.notes)}")

    # fichiers déclarés interdits : ceux cités APRÈS la mention, sur la même ligne
    interdits = set()
    for l in texte:
        mt = RE_INTERDIT.search(l)
        if mt:
            for f in RE_FICH.findall(l[mt.start():]):
                interdits.add(os.path.basename(f.replace("\\", "/")))
            # cas « X.fit ... est FAUX » : le fichier est cité avant
            if mt.group(1).upper() == "FAUX":
                avant = RE_FICH.findall(l[:mt.start()])
                if avant:
                    interdits.add(os.path.basename(avant[-1].replace("\\", "/")))
    ligne("INFO", f"fichiers marqués à ne plus utiliser : {len(interdits)}")

    # lignes « actives » qui citent un fichier interdit
    section = ""
    pb = 0
    for i, l in enumerate(texte, 1):
        if l.startswith("#"):
            section = l.lower()
        active = ("prochaine étape" in l.lower()) or ("fichiers clés" in section)
        if not active or RE_INTERDIT.search(l):
            continue
        cites = {os.path.basename(f.replace("\\", "/")) for f in RE_FICH.findall(l)}
        mauvais = sorted(cites & interdits)
        if mauvais:
            pb += 1
            ligne("ATTENTION", f"ligne {i} cite un fichier à ne plus utiliser : {', '.join(mauvais)}")
    if pb == 0:
        ligne("OK", "aucune ligne « Prochaine étape » ni « Fichiers clés » ne renvoie vers un fichier à ne plus utiliser")

    if a.dossier:
        manquants = []
        vus = set()
        for l in texte:
            for f in RE_FICH.findall(l):
                rel = f.replace("\\", "/")
                base = os.path.basename(rel)
                if base in vus or rel.startswith("http"):
                    continue
                vus.add(base)
                if "*" in base or base in interdits:
                    continue
                candidats = [os.path.join(a.dossier, rel), os.path.join(a.dossier, base),
                             os.path.join(a.dossier, "essais", base)]
                if not any(os.path.exists(c) for c in candidats):
                    manquants.append(base)
        cles = [m for m in manquants if any(m in l for l in texte if "fichiers clés" in l.lower())]
        if manquants:
            ligne("INFO", f"{len(manquants)} fichier(s) cité(s) absent(s) du dossier "
                          f"(normal pour des intermédiaires supprimés) : {', '.join(manquants[:15])}"
                          + (" …" if len(manquants) > 15 else ""))
        # absents dans la section Fichiers clés : plus grave
        sec = ""
        cles = set()
        for l in texte:
            if l.startswith("#"):
                sec = l.lower()
            if "fichiers clés" in sec and not RE_INTERDIT.search(l):
                for f in RE_FICH.findall(l):
                    b = os.path.basename(f.replace("\\", "/"))
                    if b in manquants:
                        cles.add(b)
        if cles:
            ligne("ATTENTION", f"fichiers clés absents du dossier : {', '.join(sorted(cles))}")
        else:
            ligne("OK", "tous les fichiers de « Fichiers clés » existent")


# ----------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)

    f = s.add_parser("fit")
    f.add_argument("fichier")
    f.add_argument("--etoiles", help="calque d'étoiles : définit le ciel hors étoiles (plus précis)")
    f.add_argument("--tol-neutre", type=float, default=25, help="écart max au vert, ADU (défaut 25)")
    f.add_argument("--tol-zeros", type=float, default=1.0, help="écart max de %% de zéros entre canaux (défaut 1)")
    f.add_argument("--tol-ecretage", type=float, default=0.05, help="%% max de pixels écrêtés (défaut 0,05)")
    f.add_argument("--tol-grille", type=float, default=0.35, help="étendue max du fond / médiane (défaut 0,35)")

    d = s.add_parser("diff")
    d.add_argument("avant")
    d.add_argument("apres")
    d.add_argument("--tol", type=float, default=1e-6, help="écart minimal compté comme changement (0-1)")
    d.add_argument("--zones", type=int, default=1, help="nombre de zones attendues (défaut 1)")

    e = s.add_parser("ecran")
    e.add_argument("fusion")
    e.add_argument("calque1")
    e.add_argument("calque2")
    e.add_argument("--tol", type=float, default=1.0, help="écart max en ADU (défaut 1)")

    x = s.add_parser("export")
    x.add_argument("image")
    x.add_argument("fit", nargs="?")
    x.add_argument("--autre", help="autre FIT final, pour vérifier que l'export n'est pas interverti")
    x.add_argument("--bits", type=int, help="profondeur attendue (8 ou 16)")
    x.add_argument("--tol-corresp", type=float, default=5.0)
    x.add_argument("--tol-ecretage", type=float, default=0.2)

    n = s.add_parser("notes")
    n.add_argument("notes")
    n.add_argument("--dossier")

    a = p.parse_args()
    try:
        {"fit": cmd_fit, "diff": cmd_diff, "ecran": cmd_ecran,
         "export": cmd_export, "notes": cmd_notes}[a.cmd](a)
    except FileNotFoundError as err:
        print(f"ERREUR    fichier introuvable : {err.filename}")
        sys.exit(2)
    print()
    if ATTENTIONS:
        print(f"BILAN     {len(ATTENTIONS)} point(s) à examiner")
        sys.exit(1)
    print("BILAN     aucun point à examiner")


if __name__ == "__main__":
    main()

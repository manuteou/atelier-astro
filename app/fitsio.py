"""Lecture / écriture FITS, aperçus, mesures communes.

Conventions (identiques au pipeline) :
  - données en float32 sur 0-1, forme (C, H, W) ; une image mono est (1, H, W) ;
  - les tableaux sont dans l'ordre des lignes FITS (ligne 0 = BAS de l'image affichée,
    sauf ROWORDER = 'TOP-DOWN') ; `display()` retourne l'image dans le sens affiché ;
  - toutes les coordonnées échangées avec l'interface sont celles de l'image affichée
    (x depuis la gauche, y depuis le HAUT), en pixels pleine résolution ;
  - médianes de fond calculées zéros compris (pieges.md : `stat` les ignore).
"""
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image, ImageDraw, ImageFont

from .config import FONTS_DIR


# ----------------------------------------------------------------- lecture --
def read(path):
    with fits.open(str(path), memmap=False) as h:
        hdu = next(x for x in h if x.data is not None)
        data = np.asarray(hdu.data, dtype=np.float32)
        header = hdu.header.copy()
    if data.ndim == 2:
        data = data[None]
    scale = 65535.0 if data.max() > 1.5 else 1.0
    return data / scale, header


def header(path):
    with fits.open(str(path), memmap=False) as h:
        hdu = next((x for x in h if x.header.get("NAXIS", 0) >= 2), h[0])
        return hdu.header.copy()


def write(path, data, hdr=None):
    """Écrit en float32 0-1 (Siril lit ce format)."""
    data = np.clip(np.asarray(data, np.float32), 0, 1)
    if data.shape[0] == 1:
        data = data[0]
    h = fits.Header()
    if hdr is not None:
        for card in hdr.cards:
            if card.keyword in ("SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "NAXIS3", "EXTEND",
                                "BZERO", "BSCALE", ""):
                continue
            try:
                h.append(card)
            except Exception:
                pass
    fits.PrimaryHDU(data, h).writeto(str(path), overwrite=True)


def top_down(hdr):
    return str(hdr.get("ROWORDER", "")).strip().upper() == "TOP-DOWN"


def display(data, hdr):
    """(C,H,W) ordre FITS -> (H,W,3) sens affiché."""
    x = data if top_down(hdr) else data[:, ::-1, :]
    if x.shape[0] == 1:
        x = np.repeat(x, 3, 0)
    return np.transpose(x[:3], (1, 2, 0))


def y_top_to_row(y_top, height, hdr):
    """y affiché (depuis le haut) -> indice de ligne du tableau FITS."""
    return int(y_top) if top_down(hdr) else int(height - 1 - y_top)


# --------------------------------------------------------------- étirement --
def mtf(m, x):
    x = np.clip(x, 0, 1)
    return ((m - 1) * x) / np.maximum((2 * m - 1) * x - m, -1e9) if m != 0.5 else x


def autostretch_params(data, shadows=-2.8, target=0.25):
    """Réplique l'autostretch lié de Siril : point noir médiane + shadows*1.4826*MAD, MTF au fond cible."""
    sub = data[:, ::4, ::4]
    meds, mads = [], []
    for c in range(sub.shape[0]):
        v = sub[c][sub[c] > 0]
        if v.size == 0:
            v = sub[c].ravel()
        med = float(np.median(v))
        meds.append(med)
        mads.append(float(np.median(np.abs(v - med))))
    med, mad = float(np.mean(meds)), float(np.mean(mads))
    c0 = min(max(med + shadows * 1.4826 * mad, 0.0), 1.0)
    x = med - c0
    m = float(mtf(target, x)) if x > 0 else 0.5
    return c0, m


def apply_stretch(data, c0, m):
    x = np.clip((data - c0) / max(1 - c0, 1e-6), 0, 1)
    return np.clip(mtf(m, x), 0, 1).astype(np.float32)


def autostretch(data, shadows=-2.8, target=0.25):
    c0, m = autostretch_params(data, shadows, target)
    return apply_stretch(data, c0, m)


# ----------------------------------------------------------------- mesures --
def stats(data):
    """Mesures de contrôle : médianes zéros compris (ADU 0-65535), % de zéros, % écrêtés, dimensions."""
    sub = data[:, ::2, ::2]
    med = [float(np.median(sub[c])) * 65535 for c in range(sub.shape[0])]
    zeros = [float((sub[c] <= 0).mean() * 100) for c in range(sub.shape[0])]
    clip = float((sub >= 0.9999).any(0).mean() * 100)
    return {
        "medianes": [round(v, 1) for v in med],
        "zeros_pct": [round(v, 2) for v in zeros],
        "ecretes_pct": round(clip, 3),
        "max": round(float(data.max()), 4),
        "taille": [int(data.shape[2]), int(data.shape[1])],
    }


def sky_level(channel):
    """Niveau du ciel d'un canal (0-1) : médiane des pixels non nuls sous le 60e percentile (hors objet et étoiles)."""
    v = channel[::2, ::2]
    v = v[v > 0]
    if v.size == 0:
        return 0.0
    return float(np.median(v[v <= np.percentile(v, 60)]))


def screen(a, b):
    return np.minimum(1 - (1 - a) * (1 - b), 1).astype(np.float32)


def sky_mask(data, part=0.5):
    """Pixels de ciel : la part la plus sombre de la luminance lissée (l'objet et les étoiles sont exclus).
    Indispensable quand la nébuleuse occupe une grande partie du cadre : sinon sa couleur fausse les médianes."""
    import cv2
    L = data[:3].mean(0) if data.shape[0] >= 3 else data[0]
    ls = cv2.GaussianBlur(L, (0, 0), 8)
    return ls <= np.percentile(ls, part * 100)


def neutralize(data, mask=None):
    """Neutralisation du fond par canal (post-2-etoiles.md §5) : médianes zéros compris, cible = leur moyenne.
    mask : pixels de ciel sur lesquels mesurer (par défaut l'image entière, comme le pipeline d'origine)."""
    m = mask if mask is not None else np.ones(data.shape[1:], bool)
    med = np.array([float(np.median(data[c][m])) for c in range(data.shape[0])])
    target = med.mean()
    off = target - med
    out = np.stack([np.clip(data[c] + off[c], 0, 1) for c in range(data.shape[0])]).astype(np.float32)
    after = [float(np.median(out[c][m])) for c in range(out.shape[0])]
    return out, (med * 65535).round(1).tolist(), (off * 65535).round(1).tolist(), (np.array(after) * 65535).round(1).tolist()


# ----------------------------------------------------------------- aperçus --
def to_uint8(rgb):
    return (np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)


def preview(src, out_jpg, linear, width=1200, zoom=None, quality=85):
    """Aperçu JPEG d'un FITS. linear=True : autostretch lié (comme `autostretch -linked`), sinon tel quel.
    zoom = (x, y, w, h) en coordonnées affichées pleine résolution -> recadrage agrandi.
    Retourne {"w","h","scale"} : taille pleine résolution et facteur aperçu/pleine résolution."""
    data, hdr = read(src)
    H, W = data.shape[1], data.shape[2]
    if linear:
        c0, m = autostretch_params(data)
        data = apply_stretch(data, c0, m)
    rgb = display(data, hdr)
    if zoom:
        x, y, w, h = [int(v) for v in zoom]
        x, y = max(0, min(x, W - 2)), max(0, min(y, H - 2))
        w, h = max(2, min(w, W - x)), max(2, min(h, H - y))
        rgb = rgb[y:y + h, x:x + w]
        im = Image.fromarray(to_uint8(rgb))
        k = min(3.0, 600 / max(im.size))
        k = max(k, 1.0)
        im = im.resize((int(im.size[0] * k), int(im.size[1] * k)), Image.LANCZOS)
        scale = k
    else:
        im = Image.fromarray(to_uint8(rgb))
        scale = 1.0
        if im.size[0] > width:
            scale = width / im.size[0]
            im = im.resize((width, int(im.size[1] * scale)), Image.LANCZOS)
    Path(out_jpg).parent.mkdir(parents=True, exist_ok=True)
    im.save(str(out_jpg), "JPEG", quality=quality)
    return {"w": W, "h": H, "scale": scale}


def label_strip(paths, labels, out_jpg, height=500):
    """Assemble des JPEG côte à côte (même hauteur, étiquettes, fond sombre)."""
    ims = [Image.open(p).convert("RGB") for p in paths]
    ims = [im.resize((int(im.size[0] * height / im.size[1]), height), Image.LANCZOS) for im in ims]
    pad = 12
    W = sum(im.size[0] for im in ims) + pad * (len(ims) + 1)
    canvas = Image.new("RGB", (W, height + 2 * pad + 28), (13, 19, 33))
    d = ImageDraw.Draw(canvas)
    try:
        f = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans-Bold.ttf"), 18)
    except Exception:
        f = ImageFont.load_default()
    x = pad
    for im, lab in zip(ims, labels):
        canvas.paste(im, (x, pad + 28))
        d.text((x, pad), lab, fill=(220, 225, 240), font=f)
        x += im.size[0] + pad
    canvas.save(str(out_jpg), "JPEG", quality=88)


# ----------------------------------------------------------------- exports --
def srgb_icc():
    from PIL import ImageCms
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def orient(rgb, rotation=0, miroir=False):
    """Rotation exacte (multiples de 90°, sans interpolation) puis miroir horizontal."""
    k = {0: 0, 90: 3, 180: 2, 270: 1}[int(rotation) % 360]   # 90 = sens horaire
    out = np.rot90(rgb, k)
    if miroir:
        out = out[:, ::-1]
    return np.ascontiguousarray(out)


def save_jpeg(rgb, path, quality=100, width=None):
    im = Image.fromarray(to_uint8(rgb))
    if width and im.size[0] > width:
        im = im.resize((width, int(im.size[1] * width / im.size[0])), Image.LANCZOS)
    im.save(str(path), "JPEG", quality=quality, icc_profile=srgb_icc(), subsampling=0 if quality >= 95 else 2)
    return im.size


def save_tiff16(rgb, path):
    import tifffile
    arr = (np.clip(rgb, 0, 1) * 65535 + 0.5).astype(np.uint16)
    tifffile.imwrite(str(path), arr, photometric="rgb", extratags=[(34675, 7, None, srgb_icc(), True)])
    return arr.shape[1], arr.shape[0]


def suggest_crop(data, hdr, tol=0.03):
    """Recadrage proposé (post-1-lineaire.md §0) : retire les bords peu couverts de -framing=max.
    Pour chaque bord, on avance tant que la bande contient des pixels vides, ou que sa luminosité OU sa teinte
    (rapport de chaque canal à la luminance) s'écarte de plus de `tol` d'une bande de référence plus à l'intérieur :
    chute de signal ou liseré coloré (souvent magenta) du bord. Un gradient global n'est pas un bord : il est
    laissé à GraXpert. Retourne (x, y, w, h) affichés."""
    rgb = display(data, hdr)
    L = rgb.mean(2)
    H, W = L.shape
    step = max(4, min(H, W) // 100)
    gap = 6 * step

    def med(a):
        v = a[a > 0]
        return float(np.median(v)) if v.size else 0.0

    def bad(strip, ref):
        Ls, Lr = strip.mean(2), ref.mean(2)
        if (Ls <= 0).mean() > 0.02:
            return True
        ms, mr = med(Ls), med(Lr)
        if mr <= 0:
            return False
        if abs(ms - mr) / mr > tol:
            return True
        for c in range(3):
            rs, rr = med(strip[..., c]) / max(ms, 1e-9), med(ref[..., c]) / mr
            if abs(rs - rr) > tol:
                return True
        return False

    def margin(get, n):
        m = 0
        lim = int(n * 0.2)
        while m < lim and bad(get(m, m + step), get(m + gap, m + gap + step)):
            m += step
        return m

    # chaque bande n'est jugée que sur la partie centrale de l'autre axe : une bande du haut ne doit pas être
    # comptée « vide » simplement parce qu'elle croise le bord vide de gauche
    r0, r1, c0, c1 = int(H * 0.2), int(H * 0.8), int(W * 0.2), int(W * 0.8)
    g = margin(lambda a, b: rgb[r0:r1, a:b], W)
    d = margin(lambda a, b: rgb[r0:r1, W - b:W - a], W)
    t = margin(lambda a, b: rgb[a:b, c0:c1], H)
    b_ = margin(lambda a, b: rgb[H - b:H - a, c0:c1], H)
    sec = step
    x, y = g + sec, t + sec
    w, h = W - x - d - sec, H - y - b_ - sec
    return [int(x), int(y), int(max(w, 16)), int(max(h, 16))]

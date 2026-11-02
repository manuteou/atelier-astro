"""Signature et nom de l'objet posés sur une image d'export (JPEG), avec une ombre légère pour rester lisibles sur
le ciel comme sur la nébuleuse. Les fichiers de travail (FIT, TIFF) ne sont jamais signés."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import FONTS_DIR

POSITIONS = (("bas_droite", "en bas à droite"), ("bas_gauche", "en bas à gauche"),
             ("haut_droite", "en haut à droite"), ("haut_gauche", "en haut à gauche"))


def _police(nom, taille):
    try:
        return ImageFont.truetype(str(FONTS_DIR / nom), max(8, int(taille)))
    except OSError:
        return ImageFont.load_default()


def signer(rgb, titre="", signature="", position="bas_droite", taille=1.0, opacite=0.85):
    """rgb : (H, W, 3) 0-1, sens affiché. Retourne une copie avec le titre (au-dessus, plus grand) et la signature."""
    lignes = [(t.strip(), f) for t, f in ((titre, 1.0), (signature, 0.7)) if t and t.strip()]
    if not lignes:
        return rgb
    H, W = rgb.shape[:2]
    base = max(W, H) * 0.024 * float(taille)                 # hauteur du titre : 2,4 % du grand côté à la taille 1
    marge = int(base * 0.9)
    im = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
    calque = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ombre = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d, do = ImageDraw.Draw(calque), ImageDraw.Draw(ombre)
    blocs = []
    for texte, f in lignes:
        police = _police("DejaVuSans-Bold.ttf" if f == 1.0 else "DejaVuSans.ttf", base * f)
        x0, y0, x1, y1 = d.textbbox((0, 0), texte, font=police)
        blocs.append((texte, police, x1 - x0, y1 - y0, y0))
    gap = int(base * 0.25)
    total_h = sum(b[3] for b in blocs) + gap * (len(blocs) - 1)
    haut = position.startswith("haut")
    droite = position.endswith("droite")
    y = marge if haut else H - marge - total_h
    a = int(255 * float(np.clip(opacite, 0.1, 1.0)))
    for texte, police, w, h, off in blocs:
        x = W - marge - w if droite else marge
        do.text((x + 2, y - off + 2), texte, font=police, fill=(0, 0, 0, int(a * 0.8)))
        d.text((x, y - off), texte, font=police, fill=(255, 255, 255, a))
        y += h + gap
    ombre = ombre.filter(ImageFilter.GaussianBlur(max(1.0, base * 0.08)))
    out = Image.alpha_composite(Image.alpha_composite(im.convert("RGBA"), ombre), calque).convert("RGB")
    return np.asarray(out, np.float32) / 255

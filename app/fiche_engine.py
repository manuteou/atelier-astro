#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moteur de la fiche PDF (repris du gabarit fiche_pdf_template.py du plugin astro-siril).

Ce fichier est un POINT DE DEPART A COPIER ET ADAPTER dans le scratchpad pour chaque
projet, pas un script generique parametrable en ligne de commande. Le moteur de mise
en page (polices, couleurs, helpers) est stable et ne doit normalement pas changer ;
seule la section "CONTENU A ADAPTER PAR PROJET" tout en bas est reecrite a chaque fois,
avec les faits verifies en recherche (voir references/fiche-pdf.md) et les bons
chemins d'images.

Rendu de reference : projet NGC 7380 (7 pages : couverture, localisation, histoire
et anecdote, stack brut, deux versions finales, fiche technique).

Les donnees de prise de vue (date, poses, integration, centre, champ, echelle,
logiciels, etapes) et les chemins des images viennent de NOTES.md : ne rien
recalculer ni deviner ici.
"""

import os
import re
import html
import math
import json
import subprocess
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ============================================================================
# MOTEUR DE MISE EN PAGE — a garder tel quel d'un projet a l'autre
# ============================================================================

# ---------------------------------------------------------------- fonts ----
FONT_DIR_DEJAVU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")   # polices fournies avec l'appli
FONT_DIR_CROS = FONT_DIR_DEJAVU

pdfmetrics.registerFont(TTFont("DejaVuSans", f"{FONT_DIR_DEJAVU}/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", f"{FONT_DIR_DEJAVU}/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique", f"{FONT_DIR_DEJAVU}/DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSerif", f"{FONT_DIR_DEJAVU}/DejaVuSerif.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSerif-Bold", f"{FONT_DIR_DEJAVU}/DejaVuSerif-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSerif-Italic", f"{FONT_DIR_DEJAVU}/DejaVuSerif-Italic.ttf"))
pdfmetrics.registerFont(TTFont("Carlito", f"{FONT_DIR_CROS}/Carlito-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Carlito-Bold", f"{FONT_DIR_CROS}/Carlito-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Carlito-Italic", f"{FONT_DIR_CROS}/Carlito-Italic.ttf"))

# ---------------------------------------------------------------- colours --
INK = colors.HexColor("#1b1f2b")
NIGHT = colors.HexColor("#0d1321")
ACCENT = colors.HexColor("#7c5cff")
ACCENT2 = colors.HexColor("#3fa6ff")
MUTED = colors.HexColor("#5b6478")
PAPER = colors.HexColor("#fbfbfd")
LINE = colors.HexColor("#d8dae3")

PAGE_W, PAGE_H = A4
MARGIN = 2.1 * cm

# ---------------------------------------------------------------- styles ---
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="Kicker", fontName="Carlito-Bold", fontSize=9.5, leading=12,
                           textColor=ACCENT, spaceAfter=2))
styles.add(ParagraphStyle(name="DocTitle", fontName="DejaVuSerif-Bold", fontSize=27, leading=31,
                           textColor=INK, spaceAfter=4))
styles.add(ParagraphStyle(name="DocSubtitle", fontName="Carlito-Italic", fontSize=12.5, leading=16,
                           textColor=MUTED, spaceAfter=0))
styles.add(ParagraphStyle(name="H1", fontName="DejaVuSerif-Bold", fontSize=15.5, leading=19,
                           textColor=INK, spaceBefore=6, spaceAfter=8))
styles.add(ParagraphStyle(name="H1Num", fontName="Carlito-Bold", fontSize=15.5, leading=19,
                           textColor=ACCENT))
styles.add(ParagraphStyle(name="Body", fontName="Carlito", fontSize=10.3, leading=15.4,
                           textColor=INK, alignment=TA_JUSTIFY, spaceAfter=7))
styles.add(ParagraphStyle(name="BodyItalic", fontName="Carlito-Italic", fontSize=10.3, leading=15.4,
                           textColor=INK, alignment=TA_JUSTIFY, spaceAfter=7))
styles.add(ParagraphStyle(name="FactLabel", fontName="Carlito-Bold", fontSize=9, leading=12,
                           textColor=MUTED))
styles.add(ParagraphStyle(name="FactValue", fontName="Carlito-Bold", fontSize=11.3, leading=14,
                           textColor=INK))
styles.add(ParagraphStyle(name="Caption", fontName="Carlito-Italic", fontSize=9, leading=12.5,
                           textColor=MUTED, alignment=TA_CENTER, spaceBefore=5, spaceAfter=2))
styles.add(ParagraphStyle(name="ImgTitle", fontName="Carlito-Bold", fontSize=10.5, leading=13,
                           textColor=ACCENT2, alignment=TA_CENTER, spaceBefore=0, spaceAfter=2))
styles.add(ParagraphStyle(name="Footer", fontName="Carlito", fontSize=7.8, leading=10,
                           textColor=MUTED))

# ------------------------------------------------------------ page frame --
# PAGE_FOOTER_TEXT est repris par draw_background() : le fixer avant doc.build().
PAGE_FOOTER_TEXT = "<CIBLE> — <nom usuel> · Fiche d'observation"  # TODO adapter

def draw_background(c: canvas.Canvas, doc):
    c.saveState()
    c.setFillColor(PAPER)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(ACCENT)
    c.rect(0, PAGE_H - 0.22 * cm, PAGE_W, 0.22 * cm, fill=1, stroke=0)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(MARGIN, 1.45 * cm, PAGE_W - MARGIN, 1.45 * cm)
    c.setFillColor(MUTED)
    c.setFont("Carlito", 7.8)
    c.drawString(MARGIN, 1.05 * cm, PAGE_FOOTER_TEXT)
    c.drawRightString(PAGE_W - MARGIN, 1.05 * cm, f"Page {doc.page}")
    c.restoreState()

# ------------------------------------------------------------- helpers ----
def section_heading(number, title):
    t = Table([[Paragraph(number, styles["H1Num"]), Paragraph(title, styles["H1"])]],
              colWidths=[1.1 * cm, None])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t

def fact_row(cells):
    """cells: liste de tuples (label, valeur) -> une ligne de tableau 'fiche'."""
    data = [[Paragraph(lbl, styles["FactLabel"]) for lbl, _ in cells],
            [Paragraph(val, styles["FactValue"]) for _, val in cells]]
    n = len(cells)
    colw = (PAGE_W - 2 * MARGIN) / n
    t = Table(data, colWidths=[colw] * n)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t

def divider(space_before=8, space_after=10):
    return [Spacer(1, space_before),
            HRFlowable(width="100%", thickness=0.6, color=LINE, spaceBefore=0, spaceAfter=space_after)]

def full_width_image(path, caption_title, caption_text, max_h_cm):
    from PIL import Image as PILImage
    iw, ih = PILImage.open(path).size
    ratio = iw / ih
    avail_w = PAGE_W - 2 * MARGIN
    max_h = max_h_cm * cm
    w = avail_w
    h = w / ratio
    if h > max_h:
        h = max_h
        w = h * ratio
    img = Image(path, width=w, height=h)
    img.hAlign = "CENTER"
    frame = Table([[img]], colWidths=[avail_w])
    frame.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("BOX", (0, 0), (-1, -1), 0.8, NIGHT), ("BACKGROUND", (0, 0), (-1, -1), NIGHT),
    ]))
    elems = [frame]
    if caption_title:
        elems.append(Paragraph(caption_title, styles["ImgTitle"]))
    if caption_text:
        elems.append(Paragraph(caption_text, styles["Caption"]))
    # KeepTogether : sans ca, reportlab peut laisser l'image en bas d'une page
    # et renvoyer ses legendes seules sur la page suivante.
    return [KeepTogether(elems)]

CELESTIAL_URLS = [
    "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/{f}",
    "https://cdn.jsdelivr.net/gh/ofrohn/d3-celestial@master/data/{f}",
]


def _fetch_celestial(cache_dir, timeout=30):
    """Telecharge (une fois, mis en cache) les donnees d3-celestial : lignes et noms des
    constellations, etoiles jusqu'a la magnitude 6. Retourne un dict ou None si aucune
    source ne repond (code HTTP != 200) : dans ce cas, pas de carte, jamais d'etoiles inventees."""
    os.makedirs(cache_dir, exist_ok=True)
    out = {}
    for key, fname in (("lines", "constellations.lines.json"), ("names", "constellations.json"),
                       ("stars", "stars.6.json")):
        path = os.path.join(cache_dir, fname)
        if not (os.path.exists(path) and os.path.getsize(path) > 1000):
            ok = False
            for tpl in CELESTIAL_URLS:
                try:
                    import urllib.request
                    with urllib.request.urlopen(tpl.format(f=fname), timeout=timeout) as resp:
                        if resp.status == 200:
                            data = resp.read()
                            if len(data) > 1000:
                                with open(path, "wb") as fh:
                                    fh.write(data)
                                ok = True
                                break
                except Exception:
                    pass
            if not ok:
                return None
        with open(path, encoding="utf-8") as fh:
            out[key] = json.load(fh)
    return out


def make_constellation_map(ra_deg, dec_deg, out_path, fov_deg=60.0, target_label="", size=1400,
                           cache_dir=None):
    """
    Carte du ciel large, centree sur la cible : etoiles jusqu'a la magnitude 6, lignes et noms
    (en francais) des constellations, quadrillage AD/Dec, repere rouge sur la cible, boussole
    N en haut / E a gauche, echelle en degres. Donnees d3-celestial (telechargees, mises en cache).
    Retourne le nom francais de la constellation de la cible (ou "") si la carte est produite,
    None si les donnees sont injoignables (dans ce cas, ne pas inclure de carte).
    fov_deg : champ total (30 a 90).
    """
    from PIL import Image, ImageDraw, ImageFont
    cache_dir = cache_dir or os.path.join(os.path.dirname(os.path.abspath(out_path)), "_celestial")
    data = _fetch_celestial(cache_dir)
    if data is None:
        return None
    S = 2  # sur-echantillonnage pour des traits lisses
    W = size * S
    cx = cy = W / 2.0
    a0, d0 = math.radians(ra_deg), math.radians(dec_deg)
    half = math.radians(fov_deg / 2.0)
    scale = (W / 2.0) / (2.0 * math.tan(half / 2.0))   # projection stereographique

    def proj(ra, dec):
        a, d = math.radians(ra), math.radians(dec)
        c = math.sin(d0) * math.sin(d) + math.cos(d0) * math.cos(d) * math.cos(a - a0)
        if c < -0.2:
            return None
        k = 2.0 / (1.0 + c)
        x = k * math.cos(d) * math.sin(a - a0)
        y = k * (math.cos(d0) * math.sin(d) - math.sin(d0) * math.cos(d) * math.cos(a - a0))
        return cx - x * scale, cy - y * scale      # E a gauche, N en haut

    NIGHT, SKY2 = (13, 19, 33), (20, 28, 48)
    im = Image.new("RGB", (W, W), NIGHT)
    d = ImageDraw.Draw(im, "RGBA")

    def font(px, bold=True):
        try:
            return ImageFont.truetype(f"{FONT_DIR_DEJAVU}/DejaVuSans{'-Bold' if bold else ''}.ttf", int(px * S))
        except Exception:
            return ImageFont.load_default()

    # quadrillage AD / Dec
    for dec in range(-80, 90, 10):
        pts = [proj(ra, dec) for ra in range(0, 361, 2)]
        for p, q in zip(pts, pts[1:]):
            if p and q and abs(p[0] - q[0]) < W / 3 and abs(p[1] - q[1]) < W / 3:
                d.line([p, q], fill=(90, 110, 160, 55), width=S)
    for ra in range(0, 360, 15):
        pts = [proj(ra, dec) for dec in range(-85, 86, 2)]
        for p, q in zip(pts, pts[1:]):
            if p and q and abs(p[0] - q[0]) < W / 3 and abs(p[1] - q[1]) < W / 3:
                d.line([p, q], fill=(90, 110, 160, 55), width=S)

    # constellation de la cible (pour la mettre en valeur)
    mine = None
    try:
        from astropy.coordinates import SkyCoord, get_constellation
        import astropy.units as u
        mine = get_constellation(SkyCoord(ra_deg * u.deg, dec_deg * u.deg))
    except Exception:
        pass
    name_of = {}
    for f in data["names"]["features"]:
        p = f["properties"]
        names = {p.get("en", ""), p.get("la", ""), p.get("name", "")}
        name_of[f["id"]] = (names, p.get("fr", p.get("en", "")).replace("\u2005", " "), f["geometry"]["coordinates"])
    mine_id = next((k for k, v in name_of.items() if mine in v[0]), None)

    # lignes de constellations
    for f in data["lines"]["features"]:
        hot = f["id"] == mine_id
        col = (120, 175, 255, 235) if hot else (110, 140, 200, 140)
        for line in f["geometry"]["coordinates"]:
            pts = [proj(lo % 360, la) for lo, la in line]
            for p, q in zip(pts, pts[1:]):
                if p and q and abs(p[0] - q[0]) < W / 2 and abs(p[1] - q[1]) < W / 2:
                    d.line([p, q], fill=col, width=int((2.6 if hot else 1.6) * S))

    # etoiles
    stars = sorted(data["stars"]["features"], key=lambda f: -f["properties"]["mag"])
    for f in stars:
        mag = f["properties"]["mag"]
        lo, la = f["geometry"]["coordinates"]
        p = proj(lo % 360, la)
        if not p or not (0 <= p[0] <= W and 0 <= p[1] <= W):
            continue
        r = max(0.9, (6.4 - mag) * 0.95) * S
        a = 255 if mag < 4.5 else 200
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=(235, 240, 255, a))

    # noms de constellations (francais), celle de la cible en plus clair
    for cid, (en, fr, (lo, la)) in name_of.items():
        p = proj(lo % 360, la)
        if not p or not (0.05 * W < p[0] < 0.95 * W and 0.05 * W < p[1] < 0.95 * W):
            continue
        fnt = font(15 if cid == mine_id else 12)
        txt = fr.upper()
        tw = d.textlength(txt, font=fnt)
        d.text((p[0] - tw / 2, p[1] - 8 * S), txt, font=fnt,
               fill=(170, 205, 255, 255) if cid == mine_id else (140, 160, 205, 190))

    # repere de la cible
    t = proj(ra_deg, dec_deg)
    rr = size * 0.022 * S
    red = (255, 90, 90, 240)
    d.ellipse([t[0] - rr, t[1] - rr, t[0] + rr, t[1] + rr], outline=red, width=3 * S)
    for ang in (0, 90, 180, 270):
        a = math.radians(ang)
        d.line([t[0] + (rr + 5 * S) * math.cos(a), t[1] + (rr + 5 * S) * math.sin(a),
                t[0] + (rr + 16 * S) * math.cos(a), t[1] + (rr + 16 * S) * math.sin(a)], fill=red, width=3 * S)
    if target_label:
        fnt = font(18)
        tw = d.textlength(target_label, font=fnt)
        lx = t[0] + rr + 20 * S
        if lx + tw > W - 10 * S:
            lx = t[0] - rr - 20 * S - tw
        d.text((lx, t[1] - 24 * S), target_label, font=fnt, fill=(255, 140, 140, 255))

    # boussole + echelle (10 deg, mesuree au centre)
    pad = int(size * 0.035) * S
    wh = (255, 255, 255, 230)
    f18 = font(18)
    d.line([pad + 18 * S, pad + 60 * S, pad + 18 * S, pad + 10 * S], fill=wh, width=3 * S)
    d.polygon([(pad + 18 * S, pad), (pad + 11 * S, pad + 14 * S), (pad + 25 * S, pad + 14 * S)], fill=wh)
    d.text((pad + 26 * S, pad + 4 * S), "N", fill=wh, font=f18)
    d.line([pad + 60 * S, pad + 78 * S, pad + 10 * S, pad + 78 * S], fill=wh, width=3 * S)
    d.polygon([(pad, pad + 78 * S), (pad + 14 * S, pad + 71 * S), (pad + 14 * S, pad + 85 * S)], fill=wh)
    d.text((pad + 66 * S, pad + 66 * S), "E", fill=wh, font=f18)
    p1, p2 = proj(ra_deg, dec_deg), proj(ra_deg, dec_deg + 10)
    bar = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
    bx0, by0 = W - pad - bar, W - pad - 10 * S
    d.line([bx0, by0, bx0 + bar, by0], fill=wh, width=3 * S)
    d.line([bx0, by0 - 8 * S, bx0, by0 + 8 * S], fill=wh, width=3 * S)
    d.line([bx0 + bar, by0 - 8 * S, bx0 + bar, by0 + 8 * S], fill=wh, width=3 * S)
    d.text((bx0 + bar / 2 - 18 * S, by0 - 34 * S), "10°", fill=wh, font=font(16))

    im = im.resize((size, size), Image.LANCZOS)
    im.save(out_path, quality=92)
    return name_of[mine_id][1] if mine_id else ""


def prepare_image(src, dst_dir, max_side=2000, quality=85):
    """
    Reduit une image avant integration pour garder un PDF leger : cote long
    <= max_side, JPEG qualite `quality`. Ecrit dans dst_dir, ne touche JAMAIS
    a l'export d'origine. Retourne le chemin de la copie reduite.
    """
    from PIL import Image as PILImage
    os.makedirs(dst_dir, exist_ok=True)
    im = PILImage.open(src).convert("RGB")
    w, h = im.size
    long_side = max(w, h)
    if long_side > max_side:
        k = max_side / long_side
        im = im.resize((round(w * k), round(h * k)), PILImage.LANCZOS)
    dst = os.path.join(dst_dir, os.path.basename(src))
    if os.path.abspath(dst) == os.path.abspath(src):
        raise ValueError("dst_dir doit etre different du dossier des exports")
    # profil sRGB (comme Siril) : sans profil, les couleurs changent d'un logiciel a l'autre
    try:
        from PIL import ImageCms
        icc = im.info.get("icc_profile") or ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:
        icc = None
    im.save(dst, "JPEG", quality=quality, optimize=True, **({"icc_profile": icc} if icc else {}))
    return dst

def check_glyphs(text, font_name="Carlito"):
    """
    Liste les caracteres de `text` absents de la police (ils s'afficheraient
    en carre vide dans le PDF). Balises et entites HTML sont interpretees
    avant le test. Retourne une liste de caracteres manquants ([] si tout va bien).
    """
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    face = pdfmetrics.getFont(font_name).face
    return sorted({ch for ch in plain if ch not in "\n\r\t" and ord(ch) not in face.charToGlyph})

def check_pdf_pages(pdf_path, min_chars=200):
    """
    Signale les pages presque vides (peu de texte ET aucune image), typiquement
    un tableau qui a deborde seul sur une page. Necessite pdftotext et pdfimages
    (poppler). Retourne la liste des numeros de page suspects. A completer,
    jamais a remplacer, par la relecture visuelle de chaque page.
    """
    import shutil as _sh
    if not (_sh.which("pdfimages") and _sh.which("pdftotext") and _sh.which("pdfinfo")):
        return []   # poppler absent (Windows) : relecture visuelle seulement
    out = subprocess.run(["pdfimages", "-list", pdf_path], capture_output=True, text=True).stdout
    pages_with_img = {int(l.split()[0]) for l in out.splitlines()[2:] if l.split() and l.split()[0].isdigit()}
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf_path], capture_output=True,
                                                          text=True).stdout).group(1))
    suspects = []
    for i in range(1, n + 1):
        txt = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), pdf_path, "-"],
                             capture_output=True, text=True).stdout
        if len(txt.strip()) < min_chars and i not in pages_with_img:
            suspects.append(i)
    return suspects


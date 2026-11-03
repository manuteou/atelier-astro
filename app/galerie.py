"""Exploration des travaux terminés : pour chaque cible, ses images finales, sa fiche PDF et ses notes.

Où chercher : le réglage « dossier_finaux » s'il est rempli, sinon <racine>/FINAUX TRAITES s'il existe, sinon la
racine elle-même (où « Finaliser le travail » range les dossiers). Un travail est un dossier rangé par « Finaliser
le travail » (« Cible - Lieu - date ») qui contient au moins une image finale JPEG ou une fiche PDF ; les anciens
dossiers du pipeline (CIBLE_combined/keep) ne sont pas affichés.
Rien n'est jamais modifié : lecture seule, vignettes mises en cache à part."""
import hashlib
import re
from datetime import datetime
from pathlib import Path

from . import config

IMG = {".jpg", ".jpeg", ".png"}
SOUS_DOSSIERS = ("keep", "final", "finaux")
VIGNETTES = config.CONFIG_PATH.parent / "cache" / "vignettes"

# ordre d'affichage des images d'un travail
GENRES = (("colorise", "Colorisée"), ("naturel", "Naturelle"), ("stack_brut", "Stack brut"), ("partage", "Partage"))


def racine():
    cfg = config.load()
    r = str(cfg.get("dossier_finaux") or "").strip()
    if r:
        return Path(r)
    base = Path(cfg["astro_root"])
    f = base / "FINAUX TRAITES"
    return f if f.is_dir() else base


def _cle(cible):
    """Clé de regroupement : Sh2-132 et SH2-132 donnent la même cible, IC 1396 et IC 1396A deux cibles."""
    return re.sub(r"[^A-Z0-9]", "", cible.upper())


def _genre(nom):
    n = nom.lower()
    if "stack_brut" in n or "stack" in n and "brut" in n:
        return "stack_brut"
    for g in ("colorise", "naturel", "partage"):
        if g in n:
            return g
    return "autre"


def _version(nom):
    m = re.search(r"_v(\d+)$", Path(nom).stem) or re.search(r"FINAL(\d+)", nom)
    return int(m.group(1)) if m else 1


def _cible_de(dossier, fichiers):
    nom = dossier.name if dossier.name.lower() not in SOUS_DOSSIERS else dossier.parent.name
    if " - " in nom:
        return nom.split(" - ")[0].strip()
    nom = re.sub(r"_(combined|sub)(_v\d+)?$", "", nom, flags=re.I)
    nom = re.sub(r"_mosai[cq]u?e?$", "", nom, flags=re.I)
    if nom:
        return nom
    for f in fichiers:
        m = re.match(r"(.+?)_(FINAL|fiche|stack)", f.name)
        if m:
            return m.group(1)
    return dossier.name


def _lieu_date(dossier):
    nom = dossier.name if dossier.name.lower() not in SOUS_DOSSIERS else dossier.parent.name
    parts = [x.strip() for x in re.split(r"\s+-\s*|\s*-\s+", nom)]
    if len(parts) >= 3:
        return parts[1], " - ".join(parts[2:])
    return "", ""


def _faits(notes):
    """Quelques faits lus dans NOTES.md (format de l'appli ; les anciens formats donnent ce qu'ils peuvent)."""
    out = {}
    try:
        t = notes.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out, ""
    pats = (("appareil", r"Appareil\s*:\s*(.+)"), ("type", r"Type de cible\s*:\s*(\w+)"),
            ("integration", r"intégration\s*:\s*([\dh min]+?)\s{2,}"), ("poses", r"STACKCNT\s+(\d+)"),
            ("ciel", r"Ciel mesuré\s*:\s*([^\n(]+)"), ("filtres", r"Mode filtres\s*:\s*(\w+)"))
    for k, p in pats:
        m = re.search(p, t)
        if m:
            out[k] = m.group(1).strip()
    if "type" not in out:
        m = re.search(r"Type\s*:\s*(galaxie|n[ée]buleuse|amas)", t, re.I)
        if m:
            out["type"] = m.group(1).lower()
    return out, t


def _travail(dossier, base):
    fichiers = [f for f in dossier.iterdir() if f.is_file() and not f.name.startswith(".")]
    imgs = [f for f in fichiers if f.suffix.lower() in IMG]
    pdfs = sorted(f for f in fichiers if f.suffix.lower() == ".pdf")
    if not imgs and not pdfs:
        return None
    notes = next((f for f in fichiers if f.name.upper().endswith("NOTES.MD")), None)
    faits, _ = _faits(notes) if notes else ({}, "")
    rel = lambda f: f.relative_to(base).as_posix()
    ordre = {g: i for i, (g, _) in enumerate(GENRES)}
    images = sorted(({"chemin": rel(f), "nom": f.name, "genre": _genre(f.name), "version": _version(f.name),
                      "taille": f.stat().st_size} for f in imgs),
                    key=lambda i: (-i["version"], ordre.get(i["genre"], 9), i["nom"]))
    couverture = next((i for g in ("colorise", "naturel", "partage") for i in images if i["genre"] == g), None) \
        or (images[0] if images else None)
    lieu, date = _lieu_date(dossier)
    quand = max(f.stat().st_mtime for f in fichiers)
    cible = _cible_de(dossier, fichiers)
    return {"id": rel(dossier), "cible": cible, "cle": _cle(cible), "lieu": lieu, "date": date,
            "modifie": datetime.fromtimestamp(quand).strftime("%Y-%m-%d"), "images": images,
            "fiches": [{"chemin": rel(f), "nom": f.name} for f in pdfs],
            "notes": rel(notes) if notes else None, "faits": faits,
            "couverture": couverture["chemin"] if couverture else None,
            "fichiers": sorted(f.name for f in fichiers)}


def explorer():
    """Travaux regroupés par cible, la plus récemment traitée d'abord."""
    base = racine()
    if not base.is_dir():
        return {"racine": str(base), "cibles": [], "erreur": f"dossier introuvable : {base}"}
    trav = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if re.search(r"_(combined|sub)(_v\d+)?$", d.name, re.I):
            continue                              # ancien format du pipeline (CIBLE_combined/keep) : non affiché
        try:
            t = _travail(d, base)
        except OSError:
            t = None
        if t:
            trav.append(t)
    cibles = {}
    for t in trav:
        c = cibles.setdefault(t["cle"], {"cle": t["cle"], "cible": t["cible"], "travaux": []})
        c["travaux"].append(t)
    for c in cibles.values():
        c["travaux"].sort(key=lambda t: t["modifie"], reverse=True)
        c["cible"] = c["travaux"][0]["cible"]
        c["couverture"] = next((t["couverture"] for t in c["travaux"] if t["couverture"]), None)
        c["modifie"] = c["travaux"][0]["modifie"]
        c["type"] = next((t["faits"].get("type") for t in c["travaux"] if t["faits"].get("type")), "")
    return {"racine": str(base), "cibles": sorted(cibles.values(), key=lambda c: c["modifie"], reverse=True)}


def chemin_sur(rel):
    """Fichier de la galerie à partir de son chemin relatif, sans pouvoir sortir du dossier exploré."""
    base = racine().resolve()
    f = (base / rel).resolve()
    if base not in f.parents or not f.is_file():
        raise FileNotFoundError(rel)
    return f


def vignette(rel, largeur=480):
    """Vignette JPEG en cache (les JPEG HD font 5 à 10 Mo : trop lourds pour une grille)."""
    from PIL import Image
    f = chemin_sur(rel)
    st = f.stat()
    largeur = max(120, min(int(largeur), 1600))
    k = hashlib.sha1(f"{f}|{st.st_mtime_ns}|{st.st_size}|{largeur}".encode()).hexdigest()[:20]
    out = VIGNETTES / f"{k}.jpg"
    if not out.exists():
        VIGNETTES.mkdir(parents=True, exist_ok=True)
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(f) as im:
            im.draft("RGB", (largeur, largeur))
            im = im.convert("RGB")
            im.thumbnail((largeur, largeur * 3))
            im.save(out, "JPEG", quality=85)
    return out

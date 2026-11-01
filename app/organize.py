"""Import d'un dossier quelconque : lit l'en-tête de chaque pose et range tout en sessions propres.

Une session = une cible + un appareil + un filtre + une nuit (+ une taille d'image), dans
<racine>\\<CIBLE>_<APPAREIL>_<FILTRE>_<NUIT>\\lights\\. Les fichiers d'origine ne sont jamais modifiés :
par défaut on crée des liens physiques (aucune place disque en plus, possible sur le même disque),
sinon une copie ; « déplacer » seulement si tu le demandes.
"""
import os
import re
import shutil
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from astropy.io import fits

from .inventory import EXTS, device_family, norm_filter

SKIP_NAMES = ("stacked", "stack_", "master")
CALIB = {"DARKFLAT": "darkflats", "FLATDARK": "darkflats", "DARK": "darks", "FLAT": "flats", "BIAS": "offsets",
         "OFFSET": "offsets", "ZERO": "offsets"}


def _slug(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "", s) or "Cible"


def _night(date_obs):
    """Nuit d'observation : la date du soir (une pose prise à 2 h du matin appartient à la nuit de la veille)."""
    try:
        t = datetime.fromisoformat(str(date_obs).strip()[:19])
    except ValueError:
        return "date-inconnue"
    return (t - timedelta(hours=12)).date().isoformat()


def _calib_kind(typ, name):
    t = (typ or "").upper().replace(" ", "").replace("_", "")
    for k in ("DARKFLAT", "FLATDARK", "DARK", "FLAT", "BIAS", "OFFSET", "ZERO"):
        if k in t:
            return CALIB[k]
    if not t or "LIGHT" in t:
        n = name.lower()
        for k, v in (("darkflat", "darkflats"), ("flatdark", "darkflats"), ("dark", "darks"), ("flat", "flats"),
                     ("bias", "offsets"), ("offset", "offsets")):
            if n.startswith(k) or f"_{k}" in n:
                return v
    return None


def classify(path, root=None):
    """Retourne (infos de la pose, None) ou (None, raison du rejet). infos["kind"] : light, darks, flats, offsets, darkflats."""
    name = path.name.lower()
    if any(name.startswith(k) or f"_{k}" in name for k in SKIP_NAMES):
        return None, "nom de fichier d'empilement ou de maître"
    try:
        h = fits.getheader(str(path))
    except Exception as e:
        return None, f"illisible ({e.__class__.__name__})"
    if int(h.get("NAXIS", 2)) != 2:
        return None, "image déjà en couleur (empilée ou traitée)"
    if int(h.get("STACKCNT", 1) or 1) > 1:
        return None, "déjà empilée (STACKCNT)"
    typ = str(h.get("IMAGETYP", h.get("FRAMETYP", "")) or "")
    kind = _calib_kind(typ, path.name) or ("light" if not typ or "LIGHT" in typ.upper() else None)
    if kind is None:
        return None, f"type d'image non géré ({typ.strip()})"
    inst = str(h.get("INSTRUME", h.get("TELESCOP", ""))).strip()
    if kind == "light" and not str(h.get("BAYERPAT", "") or "").strip():
        return None, "pas de matrice de Bayer (BAYERPAT) : caméra mono, non gérée (l'atelier traite les caméras couleur)"
    obj = str(h.get("OBJECT", "")).strip() or (path.parent.parent.name if path.parent.name.lower() == "lights" else path.parent.name)
    return {
        "path": str(path), "kind": kind, "object": obj, "device": device_family(inst, h.get("FOCALLEN")),
        "instrument": inst, "filter": norm_filter(h.get("FILTER"), path.name),
        "filter_name": str(h.get("FILTER", "") or "").strip(), "night": _night(h.get("DATE-OBS", "")),
        "exptime": h.get("EXPTIME") or h.get("EXPOSURE"), "size": f"{h.get('NAXIS1')}x{h.get('NAXIS2')}",
        "focal": h.get("FOCALLEN"),
    }, None


def _match_calib(g, calibs):
    """Fichiers de calibration pour un groupe de poses : même appareil et même taille ; darks à la même durée de pose
    (±0.5 s) ; flats du même filtre, de la nuit la plus proche ; offsets et darks de flats, tous."""
    out = {}
    same = [c for c in calibs if c["size"] == g["size"] and (c["device"] == g["device"] or c["device"].startswith("inconnu"))]
    exps = [float(e) for e in g["exptimes"] if e is not None]
    darks = [c for c in same if c["kind"] == "darks" and c["exptime"] is not None and exps
             and min(abs(float(c["exptime"]) - e) for e in exps) <= 0.5]
    if darks:
        out["darks"] = [c["path"] for c in darks]
    flats = [c for c in same if c["kind"] == "flats" and c["filter"] == g["filter"]]
    if flats:
        def dist(c):
            try:
                return abs((datetime.fromisoformat(c["night"]) - datetime.fromisoformat(g["night"])).days)
            except ValueError:
                return 999
        best = min(dist(c) for c in flats)
        out["flats"] = [c["path"] for c in flats if dist(c) == best]
    for k in ("offsets", "darkflats"):
        lst = [c["path"] for c in same if c["kind"] == k]
        if lst:
            out[k] = lst
    return out


def scan(src, limit=20000):
    src = Path(src)
    if not src.is_dir():
        raise ValueError(f"dossier introuvable : {src}")
    groups, rejects, n, calibs = {}, {}, 0, []
    for f in sorted(src.rglob("*")):
        if f.suffix.lower() not in EXTS or not f.is_file():
            continue
        rel_parts = f.relative_to(src).parts[:-1]
        if any(x.endswith("_combined") or x.startswith(("process", "essais", "_scripts")) for x in rel_parts):
            continue                                # projets de l'atelier : jamais repris comme poses
        n += 1
        if n > limit:
            raise ValueError(f"plus de {limit} fichiers FITS : choisis un dossier plus précis")
        info, why = classify(f)
        if info is None:
            rejects[why] = rejects.get(why, 0) + 1
            continue
        if info["kind"] != "light":
            calibs.append(info)
            continue
        key = (info["object"], info["device"], info["filter"], info["night"], info["size"])
        g = groups.setdefault(key, {"object": info["object"], "device": info["device"], "filter": info["filter"],
                                    "filter_name": info["filter_name"],
                                    "night": info["night"], "size": info["size"], "instrument": info["instrument"],
                                    "focal": info["focal"], "files": [], "exptimes": set()})
        g["files"].append(info["path"])
        g["exptimes"].add(info["exptime"])
    out = []
    for i, g in enumerate(sorted(groups.values(), key=lambda g: (g["object"], g["night"], g["device"], g["filter"]))):
        warn = []
        if g["device"].startswith("inconnu"):
            warn.append("instrument et focale absents de l'en-tête")
        if not g["filter_name"]:
            warn.append("filtre absent de l'en-tête : classé large bande")
        if g["night"] == "date-inconnue":
            warn.append("DATE-OBS absente")
        cal = _match_calib(g, calibs)
        out.append({"id": i, "object": g["object"], "device": g["device"], "filter": g["filter"], "night": g["night"],
                    "filter_name": g["filter_name"], "calib": {k: len(v) for k, v in cal.items()}, "calib_files": cal,
                    "size": g["size"], "instrument": g["instrument"], "focal": g["focal"], "count": len(g["files"]),
                    "exptimes": sorted(e for e in g["exptimes"] if e is not None), "files": g["files"], "warnings": warn,
                    "folder": f"{_slug(g['object'])}_{g['device']}_{g['filter']}_{g['night']}"})
    # deux tailles d'image dans un même groupe logique : suffixe pour ne pas mélanger
    seen = {}
    for g in out:
        seen.setdefault(g["folder"], []).append(g)
    for folder, gs in seen.items():
        if len(gs) > 1:
            for g in gs:
                g["folder"] += f"_{g['size']}"
                g["warnings"].append("tailles d'image différentes la même nuit : sessions séparées")
    used = {f for g in out for v in g["calib_files"].values() for f in v}
    left = [c for c in calibs if c["path"] not in used]
    if left:
        rejects["calibration sans poses correspondantes (appareil, taille, durée ou filtre)"] = len(left)
    return {"groups": out, "rejects": rejects, "total": n}


def _place(src, dst, mode):
    if dst.exists():
        return "déjà là"
    if mode == "deplacer":
        shutil.move(str(src), str(dst))
        return "déplacé"
    if mode == "lien":
        try:
            os.link(str(src), str(dst))
            return "lien"
        except OSError:
            pass                                    # autre disque, ou système de fichiers sans liens : copie
    shutil.copy2(str(src), str(dst))
    return "copié"


def apply(groups, astro_root, mode="lien", log=print):
    """Crée les dossiers de session. Retourne la liste des dossiers créés ou complétés."""
    root = Path(astro_root)
    done = []
    for g in groups:
        d = root / g["folder"] / "lights"
        d.mkdir(parents=True, exist_ok=True)
        counts = {}
        for f in g["files"]:
            src = Path(f)
            dst = d / src.name
            if dst.exists() and not os.path.samefile(src, dst) and src.stat().st_size != dst.stat().st_size:
                dst = d / f"{src.stem}_{abs(hash(str(src))) % 10000}{src.suffix}"
            r = _place(src, dst, mode)
            counts[r] = counts.get(r, 0) + 1
        cal = []
        for kind, lst in (g.get("calib_files") or {}).items():
            cd = root / g["folder"] / kind
            cd.mkdir(exist_ok=True)
            for f in lst:
                src = Path(f)
                _place(src, cd / src.name, "copie" if mode == "deplacer" else mode)   # une calibration sert à plusieurs nuits
            cal.append(f"{len(lst)} {kind}")
        log(f"{g['folder']} : {len(g['files'])} poses (" + ", ".join(f"{v} {k}" for k, v in counts.items()) + ")"
            + (" + calibration : " + ", ".join(cal) if cal else ""))
        done.append(str(root / g["folder"]))
    return done

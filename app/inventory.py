"""Inventaire des sessions : <racine>\\<SESSION>\\lights\\*.fit"""
from pathlib import Path

import numpy as np
from astropy.io import fits

EXTS = (".fit", ".fits", ".fts")


# Filtres bi-bande (Hα + OIII) : codés « LP » ; large bande (UV/IR cut, sans filtre, anti-pollution large) : « IRCUT ».
BIBANDE = ("DUO", "DUAL", "EXTREME", "ENHANCE", "ULTIMATE", "ALP", "NBZ", "HA/OIII", "HAOIII", "HA-OIII", "HA+OIII",
           "TRIAD", "TRIBAND", "TRI-BAND", "QUAD", "UHC", "L-E", "NB1", "NB2", "MULTIBAND", "MULTI-BAND", "H-ALPHA",
           "HALPHA", "OIII", "SII", "NARROW")
LARGE = ("IRCUT", "UV/IR", "UVIR", "IR-CUT", "IR CUT", "UV-IR", "L-PRO", "LPRO", "CLS", "NONE", "CLEAR", "OPEN", "SANS")


def norm_filter(raw, filename=""):
    """Classe du filtre : « LP » (bi-bande, bande étroite) ou « IRCUT » (large bande). Le nom réel reste dans
    l'en-tête (filter_name) ; un nom inconnu est classé large bande."""
    r = str(raw or "").upper().strip()
    s = f"{r} {filename}".upper()
    if r in ("LP", "HA", "HB") or "_LP_" in s or r.startswith("LP ") or any(k in r for k in BIBANDE):
        return "LP"
    if any(k in s for k in LARGE) or "_IR_" in s or not r:
        return "IRCUT"
    if "DUO" in s or "DUAL" in s or " LP" in s:
        return "LP"
    return "IRCUT"


def _slug(x, n=24):
    import re
    return re.sub(r"[^A-Za-z0-9]+", "", str(x))[:n]


def device_family(instrument="", focal=None):
    """Clé d'appareil : « S50 » / « S30 » pour les Seestar (valeurs connues), sinon instrument + focale
    (« ZWOASI2600MCPro_400 ») : la même caméra sur deux instruments donne deux appareils."""
    s = str(instrument or "").upper().replace(" ", "")
    for fam in ("S50", "S30"):
        if fam in s and ("SEESTAR" in s or s.startswith(fam)):
            return fam
    try:
        f = float(focal)
    except (TypeError, ValueError):
        f = None
    if not s and f:
        if 240 <= f <= 270:
            return "S50"
        if 140 <= f <= 170:
            return "S30"
    base = _slug(instrument) or "inconnu"
    return f"{base}_{f:.0f}" if f else base


def lights_of(session_dir):
    d = Path(session_dir)
    ld = d / "lights" if (d / "lights").is_dir() else d
    return sorted(f for f in ld.iterdir() if f.suffix.lower() in EXTS and not f.name.startswith("."))


def scan(astro_root):
    root = Path(astro_root)
    out = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.endswith("_combined") or not (d / "lights").is_dir():
            continue
        files = lights_of(d)
        if not files:
            continue
        out.append(describe(d, files))
    return out


def describe(d, files=None):
    files = files or lights_of(d)
    info = {"path": str(d), "name": Path(d).name, "count": len(files)}
    try:
        h = fits.getheader(str(files[0]))
        info.update(
            filter=norm_filter(h.get("FILTER"), files[0].name),
            exptime=h.get("EXPTIME") or h.get("EXPOSURE"),
            date=str(h.get("DATE-OBS", ""))[:19],
            instrument=str(h.get("INSTRUME", h.get("TELESCOP", ""))).strip(),
            object=str(h.get("OBJECT", "")).strip(),
            ra=h.get("RA"), dec=h.get("DEC"),
            bayer=str(h.get("BAYERPAT", "")).strip(),
            size=[h.get("NAXIS1"), h.get("NAXIS2")],
            focal=h.get("FOCALLEN"),
            lat=h.get("SITELAT"), lon=h.get("SITELONG"),
            filter_name=str(h.get("FILTER", "") or "").strip(),
            pixel=h.get("XPIXSZ") or h.get("PIXSIZE1"),
        )
        info["device"] = device_family(info["instrument"], info["focal"])
        exps, devs, filts = set(), set(), set()
        for f in files[:: max(1, len(files) // 12)] + [files[-1]]:
            try:
                hh = fits.getheader(str(f))
                exps.add(hh.get("EXPTIME"))
                devs.add(device_family(str(hh.get("INSTRUME", hh.get("TELESCOP", ""))).strip(), hh.get("FOCALLEN")))
                filts.add(norm_filter(hh.get("FILTER"), f.name))
            except Exception:
                pass
        info["exptimes"] = sorted(e for e in exps if e is not None)
        if len(devs) > 1 or len(filts) > 1:
            info["mixed"] = (f"dossier mélangé ({' + '.join(sorted(devs))} ; {' + '.join(sorted(filts))}) : "
                             "utilise « Importer un dossier » pour le trier")
    except Exception as e:
        info["error"] = str(e)
    return info


def quick_rgb(path):
    """Aperçu rapide d'une pose brute CFA : binning 2x2 selon la matrice de Bayer -> (3, H/2, W/2), 0-1."""
    with fits.open(str(path), memmap=False) as h:
        hdu = next(x for x in h if x.data is not None)
        raw = np.asarray(hdu.data, np.float32)
        hdr = hdu.header.copy()
    if raw.ndim == 3:
        return raw / (65535.0 if raw.max() > 1.5 else 1.0), hdr
    raw = raw / (65535.0 if raw.max() > 1.5 else 1.0)
    pat = str(hdr.get("BAYERPAT", "GRBG")).strip().upper() or "GRBG"
    H, W = raw.shape[0] // 2 * 2, raw.shape[1] // 2 * 2
    cells = {(0, 0): raw[0:H:2, 0:W:2], (0, 1): raw[0:H:2, 1:W:2], (1, 0): raw[1:H:2, 0:W:2], (1, 1): raw[1:H:2, 1:W:2]}
    q = {"R": [], "G": [], "B": []}
    for i, (dy, dx) in enumerate([(0, 0), (0, 1), (1, 0), (1, 1)]):
        q.setdefault(pat[i], []).append(cells[(dy, dx)])
    rgb = np.stack([np.mean(q["R"], 0), np.mean(q["G"], 0), np.mean(q["B"], 0)]).astype(np.float32)
    return rgb, hdr

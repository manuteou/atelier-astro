"""Données synthétiques : sessions Seestar (S50 en LP et IRCUT, et en option un S30 de focale plus courte,
champ plus large et tourné), poses CFA GRBG avec nébuleuse, filament, étoiles, amas, gradient, bruit."""
import math
import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

FOCAL = {"S50": 260.0, "S30": 160.0}


def sky(seed=1, n=1800):
    rng = np.random.default_rng(seed)
    stars = [(rng.uniform(-350, 830), rng.uniform(-300, 660), rng.pareto(1.6) * 0.02 + 0.01) for _ in range(n)]
    stars += [(rng.normal(380, 12), rng.normal(90, 12), 0.05) for _ in range(40)]       # amas
    return stars


def render(stars, dev, H, W, rot_deg=0.0, shift=(0, 0)):
    """Image du ciel vue par un appareil. Unités du ciel = pixels du S50 ; le S30 voit 260/160 fois plus de ciel par pixel."""
    s = FOCAL["S50"] / FOCAL[dev]
    th = math.radians(rot_deg)
    c, si = math.cos(th), math.sin(th)
    cx, cy = 240 + shift[0], 180 + shift[1]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dx, dy = xx - W / 2, yy - H / 2
    u = cx + s * (c * dx - si * dy)
    v = cy + s * (si * dx + c * dy)
    neb = 0.05 * np.exp(-(((u - 260) / 70) ** 2 + ((v - 170) / 50) ** 2))
    fil = 0.03 * np.exp(-(((u - 150) - 0.5 * (v - 100)) / 6) ** 2) * (v > 60) * (v < 300)
    img = np.zeros((H, W), np.float32)
    flux_k = (30 / 50) ** 2 if dev == "S30" else 1.0
    for (su, sv, f) in stars:
        # ciel -> pixel (inverse de la similitude)
        a, b = (su - cx) / s, (sv - cy) / s
        x = c * a + si * b + W / 2
        y = -si * a + c * b + H / 2
        if -5 < x < W + 5 and -5 < y < H + 5:
            x0, x1, y0, y1 = int(max(x - 6, 0)), int(min(x + 7, W)), int(max(y - 6, 0)), int(min(y + 7, H))
            img[y0:y1, x0:x1] += f * flux_k * np.exp(-((xx[y0:y1, x0:x1] - x) ** 2 + (yy[y0:y1, x0:x1] - y) ** 2) / (2 * 1.3 ** 2))
    return neb + fil, img, u


def catalogue(path, seed=1, ra0=314.7, dec0=44.5, dev="S50", W=480, H=360, n_etoiles=1800):
    """Faux extrait Gaia (JSON ra, dec, g, bp_rp) des étoiles de sky() vues par make() : pour mesurer la qualité du
    ciel sans Internet (ATELIER_CATALOGUE). Magnitude G = 10 pour un pic de 0,05."""
    import json
    s_raw = 206.265 * 2.9 / FOCAL[dev]
    rows = []
    d0 = math.radians(dec0)
    for su, sv, f in sky(seed, n_etoiles):
        xi, eta = math.radians((su - W / 2) * s_raw / 3600), math.radians((sv - H / 2) * s_raw / 3600)
        rho = math.hypot(xi, eta)
        c = math.atan(rho)
        dec = math.asin(math.cos(c) * math.sin(d0) + (eta * math.sin(c) * math.cos(d0) / rho if rho else 0))
        ra = ra0 + math.degrees(math.atan2(xi * math.sin(c), rho * math.cos(d0) * math.cos(c) - eta * math.sin(d0) * math.sin(c)))
        rows.append({"ra": ra, "dec": math.degrees(dec), "g": 10 - 2.5 * math.log10(f / 0.05), "bp_rp": 0.8})
    Path(path).write_text(json.dumps(rows))
    return path


def make(root, n_lp=8, n_ir=6, H=360, W=480, seed=1, s30=0, s30_filter="LP", n_etoiles=1800, bruit=0.006):
    rng = np.random.default_rng(seed)
    root = Path(root)
    stars = sky(seed, n_etoiles)
    sessions = [("NGC7000_LP_s1", "LP", n_lp, "S50", 0.0, (0, 0)), ("NGC7000_IR_s2", "IRCUT", n_ir, "S50", 0.0, (0, 0))]
    if s30:                                             # s30_filter : "LP", "IRCUT" ou "LP+IRCUT" (les deux)
        for f30 in s30_filter.split("+"):
            sessions.append((f"NGC7000_S30_{f30}", f30, s30, "S30", 3.0, (6, -4)))
    for name, filt, n, dev, rot, shift in sessions:
        neb, st, u = render(stars, dev, H, W, rot, shift)
        grad = 0.02 * (u - u.min()) / (u.max() - u.min())
        d = root / name / "lights"
        d.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            col = {"R": 1.0, "G": 0.55 if filt == "LP" else 0.8, "B": 0.5 if filt == "LP" else 0.7}
            skyb = 0.06 + grad + (0.06 if (filt == "LP" and dev == "S50" and i == 3) else 0)   # pose 4 du LP S50 : voile
            if filt == "LP" and dev == "S50":                  # pose 6 : un peu plus claire (mitigée), pose 7 : à la limite
                skyb = skyb + {5: 0.016, 6: 0.009}.get(i, 0)
            raw = np.zeros((H, W), np.float32)
            pat = {(0, 0): "G", (0, 1): "R", (1, 0): "B", (1, 1): "G"}
            for (dy, dx), cc in pat.items():
                sig = skyb + col[cc] * neb + st * (1.0 if cc != "B" else 0.9)
                raw[dy::2, dx::2] = sig[dy::2, dx::2]
            raw = raw + rng.normal(0, bruit, raw.shape)
            h = fits.Header()
            h["FILTER"] = filt
            h["EXPTIME"] = 10.0
            h["DATE-OBS"] = f"2026-09-1{2 if filt == 'LP' else 3}T21:{10 + i:02d}:00"
            h["INSTRUME"] = f"Seestar {dev}"
            h["BAYERPAT"] = "GRBG"
            h["RA"], h["DEC"] = 314.7, 44.5
            h["SITELAT"], h["SITELONG"] = 48.85, 2.35
            h["FOCALLEN"], h["XPIXSZ"] = FOCAL[dev], 2.9
            h["OBJECT"] = "NGC 7000"
            h["BIAS"] = 0                                   # piédestal du capteur (le Seestar l'écrit ; 0 ici)
            fits.PrimaryHDU((np.clip(raw, 0, 1) * 65535).astype(np.uint16), h).writeto(
                d / f"Light_NGC7000_10.0s_{filt}_{i:04d}.fit", overwrite=True)
    return root


if __name__ == "__main__":
    make(sys.argv[1], s30=int(sys.argv[2]) if len(sys.argv) > 2 else 0)


def make_generic(dump, seed=3):
    """Même ciel vu par une caméra astro couleur quelconque (pas un Seestar) : en-têtes d'une ASI533MC sur une
    lunette de 400 mm, filtre bi-bande nommé « L-eXtreme » et une session sans filtre, poses en vrac avec darks
    (même durée), offsets et flats (vignetage) à appliquer ; plus une pose de caméra mono à écarter."""
    import shutil
    import tempfile
    rng = np.random.default_rng(seed)
    dump = Path(dump)
    dump.mkdir(parents=True, exist_ok=True)
    gen = Path(tempfile.mkdtemp(prefix="gen_")) / "g"
    make(gen, n_lp=8, n_ir=6)
    H, W = 360, 480
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vign = 1 - 0.25 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    bias = 0.03 + 0.002 * rng.standard_normal((H, W)).astype(np.float32)
    hot = np.zeros((H, W), np.float32)
    hot[rng.integers(0, H, 60), rng.integers(0, W, 60)] = 0.4
    def hdr(typ, filt, i, exp=10.0, night="2026-09-12"):
        h = fits.Header()
        h["IMAGETYP"] = typ
        h["INSTRUME"] = "ZWO ASI533MC Pro"
        h["TELESCOP"] = "Lunette 80/400"
        h["FOCALLEN"], h["XPIXSZ"] = 400.0, 3.76
        h["BAYERPAT"] = "GRBG"
        h["EXPTIME"] = exp
        h["DATE-OBS"] = f"{night}T21:{10 + i:02d}:00"
        if filt is not None:
            h["FILTER"] = filt
        h["OBJECT"] = "NGC 7000"
        h["SITELAT"], h["SITELONG"] = "+45 45 00", "+4 50 00"
        h["RA"], h["DEC"] = 314.7, 44.5
        return h
    for ses, filt, night in (("NGC7000_LP_s1", "L-eXtreme", "2026-09-12"), ("NGC7000_IR_s2", None, "2026-09-13")):
        for i, f in enumerate(sorted((gen / ses / "lights").glob("*.fit"))):
            raw = fits.getdata(f).astype(np.float32) / 65535
            raw = raw * vign + bias + hot
            fits.PrimaryHDU((np.clip(raw, 0, 1) * 65535).astype(np.uint16), hdr("Light Frame", filt, i, night=night)).writeto(
                dump / f"Light_{ses}_{i:03d}.fits", overwrite=True)
    for i in range(5):
        d = bias + hot + 0.002 * rng.standard_normal((H, W)).astype(np.float32)
        fits.PrimaryHDU((np.clip(d, 0, 1) * 65535).astype(np.uint16), hdr("Dark Frame", None, i)).writeto(dump / f"Dark_{i}.fits")
        b = bias + 0.002 * rng.standard_normal((H, W)).astype(np.float32)
        fits.PrimaryHDU((np.clip(b, 0, 1) * 65535).astype(np.uint16), hdr("Bias Frame", None, i, exp=0.001)).writeto(dump / f"Bias_{i}.fits")
        for filt, night in (("L-eXtreme", "2026-09-12"), (None, "2026-09-13")):
            fl = 0.5 * vign + bias + 0.003 * rng.standard_normal((H, W)).astype(np.float32)
            fits.PrimaryHDU((np.clip(fl, 0, 1) * 65535).astype(np.uint16), hdr("Flat Field", filt, i, exp=0.5, night=night)).writeto(
                dump / f"Flat_{filt or 'sans'}_{i}.fits")
    h = hdr("Light Frame", "L", 0)
    del h["BAYERPAT"]
    fits.PrimaryHDU(np.zeros((H, W), np.uint16), h).writeto(dump / "Light_mono_000.fits")
    shutil.rmtree(gen.parent, ignore_errors=True)
    return dump

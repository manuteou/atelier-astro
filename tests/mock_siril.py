#!/usr/bin/env python3
"""Faux siril-cli pour les tests : interprète le sous-ensemble de commandes utilisé par l'atelier.
Volontairement « hostile » sur un point : `crop` compte y depuis le BAS (lignes FITS), pour vérifier
que l'atelier détecte et corrige la convention. Usage : mock_siril.py -d <dossier> -s <script.ssf>"""
import glob
import os
import re
import shlex
import sys

import numpy as np
from astropy.io import fits
from scipy import ndimage as ndi

cwd = None
cur = None      # (data (C,H,W) 0-1, header, nom)
PSF = {}


def log(s):
    print("log: " + s, flush=True)


def die(s):
    print("Error in line : " + s, flush=True)
    sys.exit(1)


def rd(path):
    with fits.open(path) as h:
        d = h[0].data.astype(np.float32)
        hd = h[0].header.copy()
    if d.ndim == 2:
        d = d[None]
    if d.max() > 1.5:
        d = d / 65535
    return d, hd


def wr(path, d, hd):
    if not os.path.splitext(path)[1]:
        path += ".fit"
    hd = hd.copy()
    for k in ("NAXIS3", "BZERO", "BSCALE"):
        hd.pop(k, None)
    fits.PrimaryHDU(np.clip(d, 0, 1).astype(np.float32).squeeze(), hd).writeto(path, overwrite=True)
    log(f"Saving FITS: file {os.path.basename(path)}")


def P(p):
    return p if os.path.isabs(p) else os.path.join(cwd, p)


def seq_read(name):
    f = P(name + ".seq")
    lines = open(f).read().splitlines() if os.path.exists(f) else []
    I = [l for l in lines if l.startswith("I ")]
    R = [l for l in lines if l.startswith("R")]
    return f, I, R


def seq_write(f, I, R):
    open(f, "w").write("#Siril sequence file (mock)\nS 'x' 1 %d 0 0 0\n" % len(I) + "\n".join(I + R) + "\n")


def seq_files(prefix):
    return sorted(glob.glob(P(prefix + "[0-9]*.fit")))


def stretch(d, shadows=-2.8, target=0.25):
    meds = [np.median(c[c > 0]) for c in d]
    mads = [np.median(np.abs(c[c > 0] - m)) for c, m in zip(d, meds)]
    med, mad = np.mean(meds), np.mean(mads)
    c0 = max(med + shadows * 1.4826 * mad, 0)
    x = med - c0
    m = ((target - 1) * x) / ((2 * target - 1) * x - target)
    return mtf(d, c0, m)


def mtf(d, b, m):
    x = np.clip((d - b) / (1 - b), 0, 1)
    return ((m - 1) * x) / ((2 * m - 1) * x - m)


def cmd(line):
    global cwd, cur
    if re.search(r'\s-[\w-]+="', line):
        # comportement du vrai Siril : les guillemets après « = » font partie de la valeur
        die(f"Échec de la création du répertoire « {line} » : Invalid argument")
    a = shlex.split(line)
    c, args = a[0], a[1:]
    opts = {x.split("=")[0]: (x.split("=", 1)[1] if "=" in x else True) for x in args if x.startswith("-")}
    pos = [x for x in args if not x.startswith("-") or re.match(r"^-\d", x)]
    if c == "requires":
        return
    if c == "cd":
        cwd = P(args[0])
        log("cd " + cwd)
    elif c == "convert":
        base = pos[0]
        start = int(opts.get("-start", 1))
        out = P(opts.get("-out", "."))
        os.makedirs(out, exist_ok=True)
        files = sorted(f for f in os.listdir(cwd) if f.lower().endswith((".fit", ".fits")))
        f, I, R = seq_read(os.path.join(out, base + "_"))
        for i, fn in enumerate(files):
            n = start + i
            d = fits.open(os.path.join(cwd, fn))
            d.writeto(os.path.join(out, f"{base}_{n:05d}.fit"), overwrite=True)
            I.append(f"I {n} 1")
        seq_write(os.path.join(out, base + "_.seq"), I, [])
        log(f"Conversion: {len(files)} files")
    elif c == "calibrate":
        seq = pos[0]
        files = seq_files(seq)
        ext = lambda x: x if os.path.splitext(x)[1] else x + ".fit"
        dark = rd(P(ext(opts["-dark"])))[0][0] if "-dark" in opts else None
        bias = rd(P(ext(opts["-bias"])))[0][0] if "-bias" in opts else None
        flat = rd(P(ext(opts["-flat"])))[0][0] if "-flat" in opts else None
        I = []
        for k, fn in enumerate(files, 1):
            d, hd = rd(fn)
            x = d[0]
            if dark is not None:
                x = x - dark
            elif bias is not None:
                x = x - bias
            if flat is not None:
                x = x / np.maximum(flat / np.median(flat), 0.05)
            wr(P(f"pp_{seq}{k:05d}.fit"), np.clip(x + 0.002, 0, 1)[None], hd)
            I.append(f"I {k} 1")
        seq_write(P(f"pp_{seq}.seq"), I, [])
        log(f"Calibration: {len(files)} images")
    elif c == "register":
        f, I, _ = seq_read(pos[0])
        R = []
        for l in I:
            n = int(l.split()[1])
            raw = fits.getdata(P(f"combined_{n:05d}.fit")).astype(np.float32)
            bg = float(np.median(raw))
            stars = int((raw > bg + 8 * raw.std() * 0.2).sum() // 4)
            R.append(f"R0 2.1 2.2 0.9 0.5 {bg:.2f} {stars} H 1 0 0 0 1 0 0 0 1")
        seq_write(f, I, R)
        log("Registration done")
    elif c in ("select", "unselect"):
        f, I, R = seq_read(pos[0])
        a0, a1 = int(pos[1]), int(pos[2])
        val = 1 if c == "select" else 0
        for i in range(a0 - 1, min(a1, len(I))):
            p = I[i].split()
            I[i] = f"I {p[1]} {val}"
        seq_write(f, I, R)
        log(f"{c} {a0}-{a1}")
    elif c == "seqapplyreg":
        f, I, R = seq_read(pos[0])
        k = 0
        newI = []
        for l in I:
            _, n, incl = l.split()
            if "-filter-included" in opts and incl == "0":
                continue
            with fits.open(P(f"combined_{int(n):05d}.fit")) as h:
                raw, hd = h[0].data.astype(np.float32), h[0].header.copy()
            raw = raw / 65535 if raw.max() > 1.5 else raw
            H, W = raw.shape[0] // 2 * 2, raw.shape[1] // 2 * 2
            rgb = np.stack([raw[0:H:2, 1:W:2], (raw[0:H:2, 0:W:2] + raw[1:H:2, 1:W:2]) / 2, raw[1:H:2, 0:W:2]])
            rgb = np.stack([ndi.zoom(x, 2, order=1) for x in rgb])
            rgb[:, :12, :] = 0
            rgb[:, :, -10:] = 0
            k += 1
            wr(P(f"r_combined_{k:05d}.fit"), rgb, hd)
            newI.append(f"I {k} 1")
        seq_write(P("r_combined_.seq"), newI, [f"R0 2.1 2.2 0.9 0.5 0 0 H 1 0 0 0 1 0 0 0 1" for _ in newI])
        log(f"{k} images registered")
    elif c == "stack":
        prefix = pos[0]
        # comme Siril 1.4 sur un gros projet : plantage au calcul des pondérations d'une sélection
        _, _, Rlines = seq_read(prefix)
        if ("-maximize" in args or any(a.startswith("-feather") for a in args)) and not Rlines:
            log("Calcul de la normalisation...")
            log("Memory per image: 161 MB. Max memory: 14889 MB")
            log("Le cadrage maximal nécessite une séquence alignée (données d'alignement manquantes)")
            print("progress: Échec du traitement de la séquence. Vérifier les log., 0.00%", flush=True)
            log("L'exécution du script a échoué.")
            sys.exit(1)
        if "-weight=noise" in args and ("-filter-included" in opts or os.environ.get("MOCK_CRASH_WEIGHT")):
            log("Calcul des pondérations en fonction du bruit...")
            print("Segmentation fault (access violation)", flush=True)
            sys.exit(139)
        f, I, _ = seq_read(prefix)
        files = seq_files(prefix)
        if "-filter-included" in opts:
            keep = [i for i, l in enumerate(I) if l.split()[2] == "1"]
            files = [files[i] for i in keep]
        ds, hd0, live = [], None, 0
        for k, fn in enumerate(files, 1):
            print(f"progress: Empilement..., {100 * k / len(files):.2f}%", flush=True)
            if os.environ.get("MOCK_SLOW"):
                import time
                time.sleep(float(os.environ["MOCK_SLOW"]))
            d, hd = rd(fn)
            ds.append(d)
            hd0 = hd0 or hd
            live += float(hd.get("EXPTIME", 10))
        st = np.median(ds, 0) if "rej" in pos else np.mean(ds, 0)
        if os.environ.get("MOCK_FRAMING") and "-filter-included" in opts and "-maximize" not in args:
            dy, dx = 3 + len(files) % 4, 5 + 2 * (len(files) % 3)      # cadre propre à la sélection, décalé
            st = st[:, dy:, dx:]
        if "-maximize" in args and "-filter-included" in opts:      # comme Siril : cadre propre à la sélection
            cut = 2 + len(files) % 5
            st = st[:, cut:, :]
        if "-norm=mul" in args:
            st = st / max(float(np.median(st)), 1e-6) * 0.5
        hd0["STACKCNT"] = len(files)
        hd0["LIVETIME"] = live
        out = opts["-out"]
        wr(P(out), st, hd0)
        log(f"Stacked {len(files)} images")
    elif c == "load":
        d, hd = rd(P(args[0]))
        cur = [d, hd, os.path.splitext(os.path.basename(args[0]))[0]]
        log("Reading FITS: " + args[0])
    elif c == "save":
        wr(P(args[0]), cur[0], cur[1])
    elif c == "boxselect":
        return
    elif c == "crop":
        x, y, w, h = [int(v) for v in pos[:4]]
        cur[0] = cur[0][:, y:y + h, x:x + w]       # y depuis le BAS (lignes FITS)
    elif c == "pyscript":
        name = args[0]
        rest = args[1:]
        d, hd = cur[0], cur[1]
        if "GraXpert" in name and "-denoise" in rest:
            k = float(rest[rest.index("-strength") + 1])
            cur[0] = (1 - k) * d + k * ndi.gaussian_filter(d, (0, 1.2, 1.2))
        elif "GraXpert" in name:
            bg = np.stack([ndi.gaussian_filter(ndi.median_filter(x[::4, ::4], 9), 6) for x in d])
            bg = np.stack([ndi.zoom(b, (x.shape[0] / b.shape[0], x.shape[1] / b.shape[1]), order=1) for b, x in zip(bg, d)])
            cur[0] = np.clip(d - bg + np.median(bg), 0, 1) * (d > 0)
        elif "BlurX" in name:
            cur[0] = np.clip(d + 0.3 * (d - ndi.gaussian_filter(d, (0, 1, 1))), 0, 1)
        elif "NoiseX" in name:
            if not rest:
                die("NoiseXTerminator without arguments opens a window (blocked)")
            dn = float(rest[rest.index("--dn") + 1])
            cur[0] = (1 - dn) * d + dn * ndi.gaussian_filter(d, (0, 1.2, 1.2))
        elif "StarX" in name:
            if "--difference" in rest:
                die("unrecognized arguments: --difference")
            sm = np.stack([ndi.median_filter(x, 7) for x in d])
            stars = np.clip(d - sm, 0, 1)
            stars[stars < 0.02] = 0
            starless = np.clip(d - stars, 0, 1)
            if "--unscreen" in rest:
                stars = np.clip(1 - (1 - d) / np.maximum(1 - starless, 1e-4), 0, 1)
            wr(P("stars_" + cur[2]), stars, hd)
            cur[0] = starless
        elif "Statistical" in name:
            if not rest:
                die("window opened")
            cur[0] = stretch(d, -2.8, float(rest[rest.index("-median") + 1]))
        else:
            die("unknown script " + name)
        log(f"script {name} ok")
    elif c == "subsky":
        d = cur[0]
        bg = np.stack([ndi.gaussian_filter(ndi.median_filter(x[::4, ::4], 9), 8) for x in d])
        bg = np.stack([ndi.zoom(b, (x.shape[0] / b.shape[0], x.shape[1] / b.shape[1]), order=1) for b, x in zip(bg, d)])
        cur[0] = np.clip(d - bg + np.median(bg), 0, 1) * (d > 0)
    elif c == "makepsf":
        PSF["ok"] = True
    elif c == "rl":
        if not PSF.get("ok"):
            die("no PSF: run makepsf first")
        cur[0] = np.clip(cur[0] + 0.2 * (cur[0] - ndi.gaussian_filter(cur[0], (0, 1, 1))), 0, 1)
    elif c == "denoise":
        m = float(opts.get("-mod", 1))
        cur[0] = (1 - m) * cur[0] + m * ndi.gaussian_filter(cur[0], (0, 1.2, 1.2))
    elif c == "starnet":
        d = cur[0]
        sm = np.stack([ndi.median_filter(x, 7) for x in d])
        cur[0] = np.minimum(d, sm)
    elif c == "pcc":
        cur[0] = cur[0] * np.array([1.04, 1.0, 0.96], np.float32)[:, None, None]
        log("PCC done")
    elif c == "platesolve":
        cur[1]["CRVAL1"], cur[1]["CRVAL2"] = 314.7, 44.5
        cur[1]["CDELT1"], cur[1]["CDELT2"] = -0.000665, 0.000665
        cur[1]["PLTSOLVD"] = True
        log("Plate solved")
    elif c == "spcc":
        cur[0] = cur[0] * np.array([1.05, 1.0, 0.95], np.float32)[:, None, None]
        log("SPCC done")
    elif c == "autostretch":
        nums = [float(x) for x in pos]
        cur[0] = stretch(cur[0], *(nums or [-2.8, 0.25]))
    elif c == "mtf":
        b, m, h = [float(x) for x in pos[:3]]
        cur[0] = mtf(cur[0], b, m)
    elif c == "autoghs":
        cur[0] = np.arcsinh(cur[0] * 50) / np.arcsinh(50)
    elif c == "satu":
        amt = float(pos[0])
        L = cur[0].mean(0, keepdims=True)
        cur[0] = np.clip(L + (1 + amt) * (cur[0] - L), 0, 1)
    elif c in ("savejpg", "savetif"):
        log(c + " ok")
    else:
        print(f"Unknown command: '{c}'", flush=True)
        sys.exit(1)


def main():
    global cwd
    a = sys.argv
    if "--version" in a:
        print("siril-cli 1.4.0 (mock)")
        return
    cwd = a[a.index("-d") + 1]
    script = a[a.index("-s") + 1]
    for line in open(script, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            cmd(line)
    log("Script execution finished successfully.")


if __name__ == "__main__":
    main()

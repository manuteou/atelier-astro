"""Calibration facultative des poses (darks, flats, offsets, darks de flats rangés dans la session) avant
l'alignement : maîtres dans <session>/_maitres, poses calibrées dans <session>/_calibrees."""
import shutil
from pathlib import Path

from . import inventory
from .siril import opt, q


CAL_DIRS = ("offsets", "darkflats", "flats", "darks")


def calib_sets(session_dir):
    sdir = Path(session_dir)
    return {k: inventory.lights_of(sdir / k) for k in CAL_DIRS if (sdir / k).is_dir() and inventory.lights_of(sdir / k)}


def calib_signature(s):
    return {k: len(v) for k, v in calib_sets(s["path"]).items()}


def calibrate_session(ctx, s):
    """Darks / flats / offsets rangés dans le dossier de la session : maîtres dans _maitres, poses calibrées
    dans _calibrees (reprises telles quelles si rien n'a changé). Retourne (dossier à convertir, lignes d'info)."""
    import json
    sdir = Path(s["path"])
    sets = calib_sets(sdir)
    lights = sdir / "lights"
    if not ({"darks", "flats", "offsets"} & set(sets)):
        return lights, []
    n = len(inventory.lights_of(sdir))
    sig = {**{k: len(v) for k, v in sets.items()}, "lights": n}
    out, masters, work = sdir / "_calibrees", sdir / "_maitres", sdir / "_calib"
    mark = out / "calibration.json"
    desc = ", ".join(f"{v} {k}" for k, v in sig.items() if k != "lights")
    if mark.exists() and json.loads(mark.read_text()) == sig and len(inventory.lights_of(out)) == n:
        return out, [f"{s['name']} : poses déjà calibrées ({desc}), reprises telles quelles"]
    for d in (work, out):
        if d.exists():
            shutil.rmtree(d)
    work.mkdir()
    out.mkdir()
    masters.mkdir(exist_ok=True)
    cmds = []

    def conv(folder, base):
        cmds.extend([f"cd {q(sdir / folder)}", f"convert {base} {opt('-out', '../_calib')}", f"cd {q(work)}"])
    if "offsets" in sets:
        conv("offsets", "offset")
        cmds.append(f"stack offset_ rej 3 3 -nonorm {opt('-out', '../_maitres/offset')}")
    if "darkflats" in sets:
        conv("darkflats", "darkflat")
        cmds.append(f"stack darkflat_ rej 3 3 -nonorm {opt('-out', '../_maitres/darkflat')}")
    if "flats" in sets:
        conv("flats", "flat")
        pre = "-dark=../_maitres/darkflat" if "darkflats" in sets else ("-bias=../_maitres/offset" if "offsets" in sets else "")
        if pre:
            cmds += [f"calibrate flat_ {pre}", f"stack pp_flat_ rej 3 3 -norm=mul {opt('-out', '../_maitres/flat')}"]
        else:
            cmds.append(f"stack flat_ rej 3 3 -norm=mul {opt('-out', '../_maitres/flat')}")
    if "darks" in sets:
        conv("darks", "dark")
        cmds.append(f"stack dark_ rej 3 3 -nonorm {opt('-out', '../_maitres/dark')}")
    conv("lights", "light")
    args = []
    if "darks" in sets:
        args.append("-dark=../_maitres/dark")
    elif "offsets" in sets:
        args.append("-bias=../_maitres/offset")
    if "flats" in sets:
        args.append("-flat=../_maitres/flat")
    cmds.append("calibrate light_ " + " ".join(args) + (" -cc=dark" if "darks" in sets else "") + " -cfa -equalize_cfa")
    ctx.sir(cmds, cwd=sdir, name=f"calibration_{inventory._slug(s['name'], 30)}")
    pp = sorted(work.glob("pp_light_*.f*t*"))
    if len(pp) != n:
        raise RuntimeError(f"calibration de {s['name']} : {len(pp)} poses calibrées sur {n} (voir le journal de Siril)")
    for f in pp:
        shutil.move(str(f), str(out / f.name))
    shutil.rmtree(work, ignore_errors=True)
    mark.write_text(json.dumps(sig))
    return out, [f"{s['name']} : calibration faite ({desc}) ; maîtres dans {masters.name}"]

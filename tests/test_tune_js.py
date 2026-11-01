"""Réglage fin (P8F) : l'aperçu en direct (web/js/etapes/tune.js, exécuté avec Node) doit donner la même image que
la pleine résolution (app/color_ops.py:tune), et chaque curseur doit agir dans le bon sens.
Lancer : python tests/test_tune_js.py"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from app import color_ops  # noqa: E402

if not shutil.which("node"):
    print("Node absent : test ignoré")
    raise SystemExit(0)

# image de test 8 bits : ciel sombre, nébuleuse rouge avec une bulle bleue, filaments (détail fin)
H, W = 120, 180
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
neb = np.exp(-((xx - 70) ** 2 + (yy - 60) ** 2) / (2 * 30 ** 2))
bulle = np.exp(-((xx - 130) ** 2 + (yy - 55) ** 2) / (2 * 18 ** 2))
fil = 0.08 * np.sin(xx / 3.0) * np.sin(yy / 4.0) * neb
img = np.stack([0.08 + 0.55 * neb + 0.10 * bulle + fil,
                0.08 + 0.20 * neb + 0.30 * bulle + fil,
                0.08 + 0.22 * neb + 0.45 * bulle + fil])
img8 = np.round(np.clip(img, 0, 1) * 255).astype(np.uint8)
x = img8.astype(np.float32) / 255
sky = float(np.median(x.mean(0)[x.mean(0) < np.percentile(x.mean(0), 30)]))

CAS = [
    {},
    {"temperature": 0.3, "teinte": -0.4, "rotation": -10, "saturation": 0.2, "vibrance": 0.3, "luminosite": 1.1, "noirs": 0.01},
    {"ombres": 0.8},
    {"hautes_lumieres": 0.8},
    {"clarte": 0.8},
    {"sat_rouge": 0.6, "sat_bleu": -0.3},
    {"sat_bleu": 0.8},
    {"ombres": 0.5, "hautes_lumieres": 0.4, "clarte": 0.6, "sat_bleu": 0.5, "proteger_fond": False},
]

tmp = Path(tempfile.mkdtemp())
shutil.copy(ROOT / "web/js/etapes/tune.js", tmp / "tune.mjs")
(tmp / "run.mjs").write_text("""
import { liveTune } from "./tune.mjs";
import { readFileSync } from "fs";
const job = JSON.parse(readFileSync(process.argv[2], "utf8"));
const base = new Uint8ClampedArray(job.rgba);
const res = job.cas.map(prm => { const out = new Uint8ClampedArray(base.length); liveTune(prm, job.sky, base, null, out, false, job.w); return Array.from(out); });
process.stdout.write(JSON.stringify(res));
""")
rgba = np.concatenate([np.moveaxis(img8, 0, 2), np.full((H, W, 1), 255, np.uint8)], 2).ravel().tolist()
(tmp / "job.json").write_text(json.dumps({"rgba": rgba, "sky": sky, "w": W, "cas": CAS}))
js = json.loads(subprocess.run(["node", str(tmp / "run.mjs"), str(tmp / "job.json")], capture_output=True, text=True,
                               check=True).stdout)

obj = x.mean(0) > sky + 0.1
ciel = x.mean(0) <= np.percentile(x.mean(0), 15)          # vrai ciel (la nébuleuse faible, elle, doit s'éclaircir)
bleu = (x[2] > x[0]) & obj
rouge = (x[0] > x[2] + 0.1) & obj
for prm, out in zip(CAS, js):
    j = np.moveaxis(np.array(out, np.uint8).reshape(H, W, 4)[..., :3], 2, 0).astype(int)
    py = color_ops.tune(x, prm, sky)
    p8 = np.round(np.clip(py, 0, 1) * 255).astype(int)
    diff = np.abs(j - p8)
    assert diff.max() <= 2, f"aperçu ≠ pleine résolution pour {prm} : écart max {diff.max()} (moyen {diff.mean():.2f})"
    print(f"  ok  {json.dumps(prm, ensure_ascii=False) or '{}'} : écart aperçu / pleine résolution max {diff.max()}")

ref = color_ops.tune(x, {}, sky)
L = lambda y: y.mean(0)
chroma = lambda y: y.max(0) - y.min(0)
om = color_ops.tune(x, {"ombres": 0.8}, sky)
assert np.median(L(om)[obj]) > np.median(L(ref)[obj]) + 0.02, "ombres : les tons moyens de l'objet doivent monter"
assert abs(np.median(L(om)[ciel]) - np.median(L(ref)[ciel])) < 0.005, "ombres : le ciel ne doit pas bouger"
hl = color_ops.tune(x, {"hautes_lumieres": 0.8}, sky)
assert np.percentile(L(hl)[obj], 99) < np.percentile(L(ref)[obj], 99) - 0.01, "hautes lumières : le cœur doit baisser"
cl = color_ops.tune(x, {"clarte": 0.8}, sky)
hp = lambda y: L(y) - color_ops.box_blur3(L(y), color_ops.box_radius(W))
assert hp(cl)[obj].std() > 1.3 * hp(ref)[obj].std(), "contraste local : le détail de l'objet doit augmenter"
sb = color_ops.tune(x, {"sat_bleu": 0.8}, sky)
assert np.median(chroma(sb)[bleu]) > np.median(chroma(ref)[bleu]) * 1.2, "saturation des bleus : la bulle doit se saturer"
assert abs(np.median(chroma(sb)[rouge]) - np.median(chroma(ref)[rouge])) < 0.01, "saturation des bleus : le rouge ne doit pas bouger"
print("  ok  chaque curseur agit dans le bon sens (ombres, hautes lumières, contraste local, saturation par couleur)")
print("OK")

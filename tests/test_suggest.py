"""Propositions de réglage fin (P8F) : sur des images aux défauts connus, chaque proposition doit corriger son
défaut une fois appliquée avec color_ops.tune, et ne rien proposer sur une image correcte.
Lancer : python tests/test_suggest.py"""
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import color_ops, fitsio  # noqa

rng = np.random.default_rng(5)
H, W = 400, 600
yy, xx = np.mgrid[0:H, 0:W]
env = np.exp(-(((xx - 300) / 170) ** 2 + ((yy - 200) / 110) ** 2))
neb = np.clip(ndi.gaussian_filter(rng.standard_normal((H, W)), 18) * 40 * env + env - 0.25, 0, 1)
stars = np.zeros((H, W))
for x, y, f in zip(rng.uniform(0, W, 500), rng.uniform(0, H, 500), rng.pareto(1.5, 500) * 0.1 + 0.05):
    stars += min(f, 1) * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 3)
sky = 0.065
base = np.stack([sky + 0.70 * neb, sky + 0.22 * neb, sky + 0.30 * neb]) + rng.normal(0, 0.01, (3, H, W))
base = np.clip(1 - (1 - np.clip(base, 0, 1)) * (1 - np.clip(stars, 0, 1)), 0, 1).astype(np.float32)


def sky_med(y):
    m = fitsio.sky_mask(y)
    return [float(np.median(y[c][m])) for c in range(3)]


def obj_chroma(y):
    L = y.mean(0)
    o = L > np.percentile(L, 85)
    return float(np.median(color_ops._chroma(y)[o]))


L = base.mean(0, keepdims=True)
cases = {
    "propre": base,
    "fond_vert": np.clip(base + np.array([-0.002, 0.007, -0.001])[:, None, None] * fitsio.sky_mask(base), 0, 1),
    "delave": np.clip(base * 0.6 + 0.12, 0, 1),
    "terne": np.clip(L + 0.3 * (base - L), 0, 1),
    "chaud": np.clip(base * np.array([1.08, 1.0, 0.93])[:, None, None], 0, 1),
    "froid": np.clip(base * np.array([0.93, 1.0, 1.08])[:, None, None], 0, 1),
    "chaud_fort": np.clip(base * np.array([1.3, 1.0, 0.7])[:, None, None], 0, 1),
}
fails = []
for name, img in cases.items():
    img = img.astype(np.float32)
    prm, lines = color_ops.suggest(img)
    out = color_ops.tune(img, prm, float(np.median(img.mean(0)[fitsio.sky_mask(img)])))
    r0, g0, b0 = sky_med(img)
    r1, g1, b1 = sky_med(out)
    NEUTRE = {"temperature": 0.0, "teinte": 0.0, "saturation": 0.0, "vibrance": 0.0, "luminosite": 1.0, "noirs": 0.0, "proteger_fond": True,
              "sat_rouge": 0.0, "sat_bleu": 0.0, "ombres": 0.0, "hautes_lumieres": 0.0, "clarte": 0.0}
    changed = {k: v for k, v in prm.items() if v != NEUTRE[k] or type(v) != type(NEUTRE[k])}
    print(f"{name:10s}", changed,
          f"| fond {r0:.3f}/{g0:.3f}/{b0:.3f} -> {r1:.3f}/{g1:.3f}/{b1:.3f} | saturation {obj_chroma(img):.2f} -> {obj_chroma(out):.2f}")
    if name == "propre" and changed:
        fails.append("propre : des réglages proposés sur une image correcte")
    if name == "fond_vert" and not (prm["teinte"] > 0 and abs(g1 - (r1 + b1) / 2) < 0.4 * abs(g0 - (r0 + b0) / 2)):
        fails.append("fond_vert non corrigé")
    if name == "delave" and not (prm["noirs"] > 0 and np.mean([r1, g1, b1]) < color_ops.SKY_MAX):
        fails.append("délavé non corrigé")
    if name == "terne" and not (prm["saturation"] > 0 and obj_chroma(out) > 1.5 * obj_chroma(img)):
        fails.append("terne non corrigé")
    if name == "chaud" and not (prm["temperature"] < 0 and abs(r1 - b1) < 0.4 * abs(r0 - b0)):
        fails.append("dominante chaude non corrigée")
    if name == "froid" and not (prm["temperature"] > 0 and abs(r1 - b1) < 0.4 * abs(r0 - b0)):
        fails.append("dominante froide non corrigée")
    if name == "chaud_fort" and not any("trop fort" in l for l in lines):
        fails.append("dominante forte non signalée")
# --- mesure du stack (S4) : alertes avec cause, et réglages d'empilement quand des poses sont en cause
from app.remedies import remedy  # noqa
from app.steps.stacking import mesure_alertes  # noqa


class FakeP:
    state = {"steps": {}, "facts": {}}


cas = {   # diagnostic de mesure_stack.py -> (étape où agir, réglages attendus)
    "inclinaison": (["FWHM médiane : 3.47 px", "Écart de FWHM sur le champ : 36% (> 10 %).",
                     "  Indice : INCLINAISON du capteur (…, côté haut-droite le plus flou)."], [("suite", {})]),
    "vent": (["FWHM médiane : 3.9 px", "Étoiles allongées : excentricité médiane 0.66 (…)", "  Indice : allongement UNIFORME"],
             [("S3", {"filter_round": "-0.5", "filter_fwhm": 2.0})]),
    "optique": (["FWHM médiane : 3.9 px", "Étoiles allongées : excentricité médiane 0.62 (…)", "  Indice : allongement RADIAL"],
                [("suite", {})]),
    "flou": (["FWHM médiane : 5.2 px", "Écart de FWHM sur le champ : 25% (> 10 %).", "  Variation sans motif net"],
             [("S3", {"filter_fwhm": 2.0}), ("S3", {"filter_fwhm": 2.0})]),
    "propre": (["FWHM médiane : 3.2 px", "Champ homogène : écart de FWHM 6% (≤ 10 %), étoiles rondes"], []),
}
for k, (lines, attendu) in cas.items():
    got = [(remedy(FakeP(), "S4", a)["etape"], remedy(FakeP(), "S4", a)["reglages"]) for a in mesure_alertes(lines)]
    print(f"mesure {k:11s}", got)
    if got != attendu:
        fails.append(f"mesure {k} : {got} au lieu de {attendu}")
if fails:
    raise SystemExit("ÉCHEC : " + " ; ".join(fails))
print("OK : propositions de réglage fin et réglages d'empilement après la mesure")

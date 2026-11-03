"""Halos des étoiles brillantes (app/halos.py) sur un calque synthétique : cœur résiduel en croissant, lueur
circulaire, reflet décalé ; la nébuleuse loin de l'étoile ne doit pas bouger. Lancer : python tests/test_halos.py"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import halos  # noqa: E402

rng = np.random.default_rng(0)
H, W = 600, 800
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
ciel = 0.15
neb = 0.12 * np.exp(-(((xx - 150) / 60) ** 2 + ((yy - 450) / 40) ** 2))           # nébuleuse loin de l'étoile
sx, sy = 400.0, 300.0
r = np.hypot(xx - sx, yy - sy)
lueur = 0.10 * np.exp(-r / 45)
croissant = 0.5 * ((r < 22) & (np.hypot(xx - sx - 8, yy - sy + 6) > 18))
gx, gy, gr = 520.0, 260.0, 70.0
reflet = 0.08 * np.clip(1 - (np.hypot(xx - gx, yy - gy) / gr) ** 4, 0, 1)
base = ciel + neb + rng.normal(0, 0.006, (H, W))
sl = np.stack([base + lueur + croissant + reflet * k for k in (0.5, 0.9, 1.3)]).astype(np.float32)
stars = np.zeros((3, H, W), np.float32)
stars[:, r < 25] = 1.0                                                            # l'étoile, dans le calque d'étoiles

out, info = halos.corriger(sl, stars, 1, 1.0, [(gx, gy, gr * 1.15)])
print("\n".join("  " + l for l in info))
ref = np.stack([base] * 3)
def ecart(a, m):
    return float(np.abs(a - ref)[:, m].mean())
coeur = r < 25
autour = (r > 30) & (r < 120) & (np.hypot(xx - gx, yy - gy) > gr * 1.2)
dans_reflet = np.hypot(xx - gx, yy - gy) < gr * 0.9
loin = np.hypot(xx - 150, yy - 450) < 80
for nom, m in (("cœur", coeur), ("lueur", autour), ("reflet", dans_reflet)):
    a, b = ecart(sl, m), ecart(out, m)
    print(f"  {nom} : écart au ciel sans défaut {a * 255:.1f} → {b * 255:.1f} /255")
    assert b < 0.35 * a, f"{nom} insuffisamment corrigé"
assert ecart(out, loin) < 0.002, "la nébuleuse loin de l'étoile ne doit pas bouger"
g_av = float(np.std(sl[1][coeur] - np.median(sl[1][coeur])))
g_ap = float(np.std(out[1][coeur] - (out[1][coeur]).mean()))
assert 0.003 < g_ap < 0.02, f"le cœur remplacé doit garder un grain proche du bruit (std {g_ap:.4f})"
print("OK")

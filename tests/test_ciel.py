"""Qualité du ciel mesurée (app/ciel.py) sur des poses synthétiques dont on connaît la réponse : appariement au faux
catalogue, point zéro, brillance du ciel, tri des poses (voile, Lune), conversion Bortle, graphique.
Lancer : python tests/test_ciel.py"""
import math
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from astropy.io import fits

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from tests.make_data import catalogue, make  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="ciel_"))
make(tmp, n_lp=2, n_ir=4, n_etoiles=500, bruit=0.0006)   # champ moins dense, moins de bruit : des étoiles isolées
os.environ["ATELIER_CATALOGUE"] = str(catalogue(tmp / "cat.json", n_etoiles=500))
from app import ciel, inventory  # noqa: E402

ses = [{"path": str(tmp / "NGC7000_LP_s1"), "filter": "LP"}, {"path": str(tmp / "NGC7000_IR_s2"), "filter": "IRCUT"}]
# une pose voilée : tout le signal (ciel et étoiles) divisé par 4, comme à travers la buée
f = inventory.lights_of(ses[1]["path"])[3]
with fits.open(f) as hd:
    h, d = hd[0].header, hd[0].data.astype(np.float64)
fits.PrimaryHDU((d / 4).astype(np.uint16), h).writeto(f, overwrite=True)

res = ciel.mesurer_sessions(ses, inventory.lights_of, tmp / "cache")
assert list(res) == ["NGC7000_IR_s2"], "les sessions LP ne se mesurent pas"
r = res["NGC7000_IR_s2"]
assert r["erreur"] is None, r
ok = [m for m in r["mesures"] if "erreur" not in m]
assert len(ok) == 4, r["mesures"]

# réponse attendue : flux d'une étoile G=10 (pic 0,05, gaussienne σ=1,3 px, 2x2 pixels dont un bleu à 0,9)
# rapporté au fond d'un superpixel (4 pixels de ciel 0,06 + gradient médian 0,01)
F = 0.05 * 2 * math.pi * 1.3 ** 2 * (3.9 / 4)
Lciel = 4 * 0.07
ech = 2 * 206.265 * 2.9 / 260
V = 10 + 0.02704 - 0.01424 * 0.8 + 0.2156 * 0.64 - 0.01426 * 0.512
attendu = V + 2.5 * math.log10(F / Lciel) + 5 * math.log10(ech)
for m in ok[:3]:
    print(f"  {m['fichier']} : {m['etoiles']} étoiles, ZP {m['zp']:.2f} ± {m['zp_sigma']:.2f}, ciel {m['ciel']:.2f} "
          f"(attendu {attendu:.2f}), hauteur {m['hauteur']}°, zénith {m['zenith']}")
    assert m["etoiles"] >= 10 and m["zp_sigma"] < 0.45, m
    assert abs(m["ciel"] - attendu) < 0.25, (m["ciel"], attendu)
    assert 60 < m["hauteur"] < 90 and m["soleil"] < -15, m           # 13/09 23 h à Paris, cible au zénith
voilee = ok[3]
assert not voilee["retenue"] and voilee["motif"].startswith("voile"), voilee
assert abs(ok[0]["zp"] - voilee["zp"] - 2.5 * math.log10(4)) < 0.15, "4 fois moins de lumière = 1,5 mag perdues"
s = r["resume"]
assert s["poses"] == 3 and s["bortle"] == ciel.bortle_de_sqm(s["sqm"]), s
print(f"  résumé : {s}")

# la Lune levée écarte la pose s'il en existe sans Lune
t = [dict(m) for m in ok[:3]]
t[0]["lune"] = 12.0
ciel.trier(t)
assert not t[0]["retenue"] and t[0]["motif"].startswith("Lune") and t[1]["retenue"], t

lignes, best = ciel.lignes(res, 2)
assert best == s and any("ATTENTION : 1 pose(s) voilée(s)" in l for l in lignes), lignes
assert any("s'écarte de la classe indiquée" in l for l in lignes), "Bortle 2 déclaré, mesure bien plus claire"
assert ciel.graphique(res, tmp / "ciel.png") and (tmp / "ciel.png").stat().st_size > 10000

# sans piédestal dans l'en-tête : refus net, pas de chiffre faux
with fits.open(f) as hd:
    h, d = hd[0].header, hd[0].data
del h["BIAS"]
fits.PrimaryHDU(d, h).writeto(tmp / "sans_bias.fit")
try:
    ciel.mesure_pose(tmp / "sans_bias.fit", ciel.catalogue(0, 0, 1))
    raise AssertionError("une pose sans BIAS ne doit pas être mesurée")
except ValueError as e:
    assert "BIAS" in str(e)

# conversions utilitaires
assert abs(ciel.v_de_gaia(10, 0.0) - 10.027) < 1e-3
assert ciel._coord("+45 45 00") == 45.75 and ciel._coord(-1.5) == -1.5
assert len(ciel.echantillon(list(range(100)))) == ciel.POSES_PAR_SESSION
print("OK")

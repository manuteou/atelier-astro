"""Test de l'import d'un dossier en vrac : poses de deux appareils, deux filtres, deux nuits, mélangées,
avec un sous-dossier et un fichier empilé à ignorer. Lancer : python tests/test_import.py"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from astropy.io import fits

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
tmp = Path(tempfile.mkdtemp(prefix="atelier_import_"))
os.environ["ATELIER_ROOT"] = str(tmp / "Astrophoto")
os.environ["ATELIER_SIRIL"] = str(HERE / "mock_siril.py")
(tmp / "Astrophoto").mkdir()

from tests.make_data import make  # noqa
gen = make(tmp / "gen", s30=5)
dump = tmp / "Seestar_vrac"
(dump / "sous_dossier").mkdir(parents=True)
for i, f in enumerate(sorted(gen.rglob("*.fit"))):
    shutil.copy2(f, (dump / "sous_dossier" if i % 3 == 0 else dump) / f"{f.parent.parent.name}_{f.name}")
fits.PrimaryHDU(np.zeros((3, 20, 20), np.float32), fits.Header({"STACKCNT": 12})).writeto(dump / "Stacked_12_NGC7000.fit")
# un dossier de session mélangé, rangé à la main par erreur
bad = tmp / "Astrophoto" / "Melange" / "lights"
bad.mkdir(parents=True)
src = sorted(gen.rglob("*.fit"))
for f in src[:3] + src[-3:]:
    shutil.copy2(f, bad / f"{f.parent.parent.name}_{f.name}")

from app import config  # noqa
if config.CONFIG_PATH.exists():
    config.CONFIG_PATH.rename(config.CONFIG_PATH.with_suffix(".bak"))
from fastapi.testclient import TestClient  # noqa
from app.main import app  # noqa
c = TestClient(app)

try:
    r = c.post("/api/import/scan", json={"path": str(dump)})
    assert r.status_code == 200, r.text
    scan = r.json()
    for g in scan["groups"]:
        print(f"  {g['folder']:40s} {g['count']} poses {g['warnings']}")
    print("  écartés :", scan["rejects"], "· total", scan["total"])
    assert len(scan["groups"]) == 3, scan["groups"]
    assert sum(g["count"] for g in scan["groups"]) == 19
    assert sum(scan["rejects"].values()) == 1

    r = c.post("/api/projects", json={"target": "NGC 7000", "type": "nebuleuse", "sessions": [str(bad.parent)]})
    print("  dossier mélangé :", r.status_code, r.json()["detail"][:120])
    assert r.status_code == 400 and "mélangé" in r.json()["detail"]

    r = c.post("/api/import/apply", json={"token": scan["token"], "ids": [g["id"] for g in scan["groups"]], "mode": "lien",
                                          "target": "NGC 7000", "type": "nebuleuse", "device": "S50 Pro"})
    assert r.status_code == 200, r.text
    while True:
        j = c.get(f"/api/jobs/{r.json()['job']}").json()
        if j["status"] in ("terminé", "échec"):
            break
        time.sleep(0.2)
    print("\n".join("  " + l for l in j["log"]))
    assert j["status"] == "terminé", j["error"]
    proj = c.get(f"/api/projects/{j['result']['name']}").json()
    ses = proj["state"]["sessions"]
    print("  sessions du projet :", [(s["name"], s["count"], s["device"], s["filter"]) for s in ses])
    assert len(ses) == 3 and not any(s.get("mixed") for s in ses)
    one = Path(ses[0]["path"]) / "lights"
    f = next(one.iterdir())
    print("  liens physiques :", os.stat(f).st_nlink > 1)
    # deuxième import identique : rien n'est dupliqué
    r = c.post("/api/import/apply", json={"token": scan["token"], "ids": [scan["groups"][0]["id"]], "mode": "lien",
                                          "target": "NGC 7000", "type": "nebuleuse"})
    while c.get(f"/api/jobs/{r.json()['job']}").json()["status"] not in ("terminé", "échec"):
        time.sleep(0.2)
    assert len(list(one.iterdir())) == ses[0]["count"]
    print("OK : import en vrac réussi")
finally:
    if config.CONFIG_PATH.exists():
        config.CONFIG_PATH.unlink()
    bak = config.CONFIG_PATH.with_suffix(".bak")
    if bak.exists():
        bak.rename(config.CONFIG_PATH)

"""Annulation et progression : un empilement ralenti est annulé en cours de route ; le processus Siril est arrêté,
l'étape garde son état d'avant, la progression a bien été remontée. Lancer : python tests/test_annulation.py"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
tmp = Path(tempfile.mkdtemp(prefix="atelier_annul_"))
os.environ["ATELIER_ROOT"] = str(tmp / "Astrophoto")
os.environ["ATELIER_SIRIL"] = str(HERE / "mock_siril.py")

from tests.make_data import make  # noqa
make(tmp / "Astrophoto", n_lp=10, n_ir=6)
from app import config  # noqa
if config.CONFIG_PATH.exists():
    config.CONFIG_PATH.rename(config.CONFIG_PATH.with_suffix(".bak"))
from fastapi.testclient import TestClient  # noqa
from app.main import app  # noqa
c = TestClient(app)


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def wait(job, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = ok(c.get(f"/api/jobs/{job}"))
        if j["status"] in ("terminé", "échec", "annulé"):
            return j
        time.sleep(0.2)
    raise SystemExit("délai dépassé")


try:
    ses = ok(c.get("/api/sessions"))
    NAME = ok(c.post("/api/projects", json={"target": "NGC 7000", "type": "nebuleuse", "sessions": [s["path"] for s in ses]}))["name"]
    for sid, prm in (("S1", {"mode": "A"}), ("S2", {})):
        j = wait(ok(c.post(f"/api/projects/{NAME}/steps/{sid}/run", json={"variants": [prm]}))["job"])
        assert j["status"] == "terminé", j
        ok(c.post(f"/api/projects/{NAME}/steps/{sid}/validate", json={"variant": 0}))
    os.environ["MOCK_SLOW"] = "0.4"                  # le faux Siril attend 0,4 s par pose empilée
    job = ok(c.post(f"/api/projects/{NAME}/steps/S3/run", json={"variants": [{}]}))["job"]
    seen = []
    t0 = time.time()
    while time.time() - t0 < 30:
        j = ok(c.get(f"/api/jobs/{job}"))
        if j["progress"]["sous_pct"]:
            seen.append(j["progress"]["sous_pct"])
        if len(seen) >= 3:
            break
        time.sleep(0.2)
    print("progression vue :", seen, "·", j["progress"]["detail"])
    assert seen and seen[-1] > 0 and j["progress"]["pct"] > 0, j["progress"]
    t1 = time.time()
    r = ok(c.post(f"/api/jobs/{job}/cancel"))
    j = wait(job, 20)
    print("annulé en", round(time.time() - t1, 1), "s :", j["status"], "·", j["log"][-1][9:])
    assert j["status"] == "annulé" and time.time() - t1 < 5, j["status"]
    st = next(s for s in ok(c.get(f"/api/projects/{NAME}"))["steps"] if s["id"] == "S3")["state"]
    assert not st.get("variants"), "l'étape annulée ne doit pas enregistrer de résultat"
    assert not ok(c.get(f"/api/jobs/{job}"))["cancellable"]
    # un travail qui suit fonctionne normalement
    os.environ.pop("MOCK_SLOW")
    j = wait(ok(c.post(f"/api/projects/{NAME}/steps/S3/run", json={"variants": [{}]}))["job"])
    assert j["status"] == "terminé", j["error"]
    print("OK : annulation et progression")
finally:
    if config.CONFIG_PATH.exists():
        config.CONFIG_PATH.unlink()
    bak = config.CONFIG_PATH.with_suffix(".bak")
    if bak.exists():
        bak.rename(config.CONFIG_PATH)

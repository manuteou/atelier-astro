"""Test de bout en bout avec le faux Siril : toutes les étapes, en passant par l'API HTTP.
Lancer : python tests/test_e2e.py [mode]   (mode A par défaut, ou B)"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

MODE = sys.argv[1] if len(sys.argv) > 1 else "A"
TTYPE = sys.argv[2] if len(sys.argv) > 2 else "nebuleuse"
MULTI = len(sys.argv) > 3 and sys.argv[3] in ("multi", "multi2")   # ajoute une session S30 Pro (focale 160 mm, tournée)
MULTI2 = len(sys.argv) > 3 and sys.argv[3] == "multi2"             # … avec les deux filtres (LP et IRCUT) sur le S30
GENERIC = len(sys.argv) > 3 and sys.argv[3] == "generique"   # caméra astro quelconque + calibration + outils Siril
tmp = Path(tempfile.mkdtemp(prefix="atelier_"))
os.environ["ATELIER_ROOT"] = str(tmp / "Astrophoto")
os.environ["ATELIER_SIRIL"] = str(HERE / "mock_siril.py")
os.chmod(HERE / "mock_siril.py", 0o755)

from tests.make_data import make, make_generic  # noqa
if GENERIC:
    (tmp / "Astrophoto").mkdir(parents=True)
    make_generic(tmp / "vrac")
else:
    make(tmp / "Astrophoto", s30=6 if MULTI else 0, s30_filter="LP+IRCUT" if MULTI2 else ("IRCUT" if MODE == "C" else "LP"))

from app import config  # noqa
if config.CONFIG_PATH.exists():
    config.CONFIG_PATH.rename(config.CONFIG_PATH.with_suffix(".bak"))
from fastapi.testclient import TestClient  # noqa
from app.main import app  # noqa

c = TestClient(app)


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def wait(job):
    while True:
        j = ok(c.get(f"/api/jobs/{job}"))
        if j["status"] in ("terminé", "échec"):
            return j
        time.sleep(0.2)


def run(sid, variants=None, expect_ok=True):
    r = ok(c.post(f"/api/projects/{NAME}/steps/{sid}/run", json={"variants": variants or [{}]}))
    j = wait(r["job"])
    proj = ok(c.get(f"/api/projects/{NAME}"))
    st = next(s for s in proj["steps"] if s["id"] == sid)
    vs = st["state"]["variants"]
    errs = [v.get("error") for v in vs if v.get("error")]
    if expect_ok and (j["status"] != "terminé" or errs):
        print("\n".join(j["log"][-40:]))
        raise SystemExit(f"{sid} en échec : {j['error']} {errs}")
    for v in vs:
        print(f"  {sid}{v['tag']} {v.get('duree')} s ·", " | ".join(v.get("info", [])[:6])[:400])
    return st, vs


def val(sid, i=0):
    ok(c.post(f"/api/projects/{NAME}/steps/{sid}/validate", json={"variant": i}))


cfg = ok(c.get("/api/config"))
assert cfg["siril_ok"], cfg
if GENERIC:
    ok(c.post("/api/config", json={"outils": {"fond": "siril", "nettete": "siril", "debruitage": "siril", "etoiles": "starnet"}}))
    scan = ok(c.post("/api/import/scan", json={"path": str(tmp / "vrac")}))
    for g in scan["groups"]:
        print(f"  import : {g['folder']} {g['count']} poses, filtre {g['filter_name'] or '—'} ({g['filter']}), calibration {g['calib']}")
    print("  écartés :", scan["rejects"])
    assert len(scan["groups"]) == 2 and all(g["calib"].get("darks") == 5 and g["calib"].get("flats") == 5 and
                                            g["calib"].get("offsets") == 5 for g in scan["groups"]), scan["groups"]
    assert any("mono" in k for k in scan["rejects"]), scan["rejects"]
    r = ok(c.post("/api/import/apply", json={"token": scan["token"], "ids": [g["id"] for g in scan["groups"]],
                                             "mode": "copie", "target": "data", "type": TTYPE}))
    NAME = wait(r["job"])["result"]["name"]
    m = ok(c.get(f"/api/materiel?project={NAME}"))
    print("  matériel :", m["profils"], "nouveaux :", m["nouveaux"])
    dev = m["nouveaux"][0]
    assert dev == "ZWOASI533MCPro_400" and m["profils"][dev]["pixel"] == 3.76
    ok(c.post("/api/materiel", json={"profils": {dev: {**m["profils"][dev], "nom": "ASI533MC + lunette 80/400", "ouverture": 80}}}))
else:
    ses = ok(c.get("/api/sessions"))
    print("sessions :", [(s["name"], s["count"], s["filter"], s.get("device")) for s in ses])
    NAME = ok(c.post("/api/projects", json={"target": "data", "type": TTYPE, "device": "S50 Pro",
                                             "sessions": [s["path"] for s in ses]}))["name"]

run("S1", [{"mode": MODE}]); val("S1")
st, vs = run("S2")
r = ok(c.post(f"/api/projects/{NAME}/steps/S2/run", json={"variants": [{"z": 4}]}))
j = wait(r["job"])
assert any("repris tels quels" in l for l in j["log"]), "la conversion aurait dû être reprise"
print("  S2 relancé : conversion et alignement repris, tri recalculé")
st, vs = run("S2"); val("S2")
flag = vs[0]["extra"]["groups"]["S50"]["flagged"] if MULTI else vs[0]["extra"]["flagged"]
print("  poses signalées :", [(r["index_seq_1"], r["raison"]) for r in flag])
if MODE != "C":
    assert any(r["fichier"] == "4" for r in flag), "la pose voilée aurait dû être signalée"
proj = ok(c.get(f"/api/projects/{NAME}"))
s3 = next(s for s in proj["steps"] if s["id"] == "S3")
niv = [(r["fichier"], r["niveau"]) for g in s3["poses"] for r in g["poses"]]
print("  niveaux du tri :", niv[:8], "· pose typique :", [g["reference"]["fichier"] for g in s3["poses"] if g["reference"]])
assert all(n in ("nette", "mitigee", "limite") for _, n in niv)
if MODE != "C" and not GENERIC:       # mode C : seules les IRCUT ; générique : fond calibré, rapports plus forts
    assert ("4", "nette") in niv and ("6", "mitigee") in niv and ("7", "limite") in niv, niv
g0 = next(g for g in s3["poses"] if g["reference"])
thumb = c.get(f"/api/projects/{NAME}/pose", params={"fichier": g0["reference"]["fichier"], "dev": g0["dev"]})
assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg", thumb.status_code
dyn = s3["dyn"]
print("  exclusions proposées :", dyn)
st, vs = run("S3", [dyn]); val("S3")
if os.environ.get("MOCK_CADRE_GEANT"):
    assert any("cadrage maximal démesuré" in l for l in vs[0]["info"]), vs[0]["info"][:6]
    print("  ", next(l for l in vs[0]["info"] if "démesuré" in l)[:170])
if os.environ.get("MOCK_FRAMING"):
    assert any("recalé sur le principal" in l for l in vs[0]["info"]), vs[0]["info"]
    print("  ", next(l for l in vs[0]["info"] if "recalé" in l)[:160])
if os.environ.get("MOCK_CRASH_WEIGHT"):
    assert any("sans pondération" in l for l in vs[0]["info"]), vs[0]["info"]
    print("  plantage de Siril : empilement refait sans pondération, signalé")
if MULTI:
    st, vs = run("S3B", [{"mode": "combinaison", "poids": 1.0}, {"mode": "combinaison", "poids": 0.5},
                         {"mode": "principal"}, {"mode": "secondaire"}])
    if os.environ.get("MOCK_TROUS"):
        assert not any("sans extraction de fond" in l for v in vs for l in v["info"]), "GraXpert doit passer sur un stack troué"
        assert any("contient des données" in l for l in vs[0]["info"]), vs[0]["info"][:3]
        print("  stack S50 troué : vides remplis pour GraXpert, faible couverture signalée")
    if os.environ.get("MOCK_GRAXPERT_NAN"):
        assert all(any("utilisé sans extraction de fond" in l for l in v["info"]) for v in vs[:2]), vs[0]["info"][:4]
        print("  GraXpert cassé sur le S30 : stack utilisé sans extraction de fond, signalé")
    if MODE == "B":
        from astropy.io import fits as _f
        main_f = "LP" if TTYPE == "nebuleuse" else "IRCUT"
        for v in vs:
            o = v["outputs"]
            assert set(o) == {"stack", "stack2"}, o
            h1, h2 = (_f.getheader(str(tmp / "Astrophoto" / NAME / o[k])) for k in ("stack", "stack2"))
            assert (h1["NAXIS1"], h1["NAXIS2"]) == (h2["NAXIS1"], h2["NAXIS2"]), "les deux stacks du mode B doivent avoir la même taille"
            assert h1["FILTER"] == main_f and h2["FILTER"] != main_f, (h1["FILTER"], h2["FILTER"])
        fl = vs[0]["extra"]["multi"]["filtres"]
        print("  mode B, appareils par filtre :", fl)
        s30_has = {"LP", "IRCUT"} if MULTI2 else {"LP"}
        assert all(("S30" in fl[F]) == (F in s30_has) for F in fl), fl
        assert fl[main_f][0] == "S50" and vs[2]["extra"]["multi"]["filtres"][main_f] == ["S50"], "principal seul"
    if "S30" in vs[0]["extra"]["multi"]["appareils"]:
        det = vs[0]["extra"]["multi"]["appareils"]["S30"]
        print("  alignement S30 → S50 :", {k: det[k] for k in ("echelle", "rotation_deg", "etoiles", "rms_px", "poids_relatif")})
        assert abs(det["echelle"] - 1.625) < 0.02 and abs(abs(det["rotation_deg"]) - 3) < 0.3, det
    val("S3B", 0)
run("S4"); val("S4")
proj = ok(c.get(f"/api/projects/{NAME}"))
rect = next(s for s in proj["steps"] if s["id"] == "P0")["dyn"]["rect"]
print("  recadrage proposé :", rect)
rect2 = [rect[0], rect[1] + 10, rect[2], rect[3] - 30]   # rectangle asymétrique : la convention de y devient décidable
st, vs = run("P0", [{"rect": rect2}]); val("P0")
assert config.load()["crop_y_origin"] == "bas", "la convention inversée du faux Siril aurait dû être détectée"
ok(c.post(f"/api/projects/{NAME}/zoom", json={"rect": [100, 80, 160, 120], "step": "P0"}))
if MULTI and not os.environ.get("MOCK_GRAXPERT_NAN"):
    proj = ok(c.get(f"/api/projects/{NAME}"))
    assert not next(s for s in proj["steps"] if s["id"] == "P1")["applies"], "P1 doit être sans objet après GraXpert par stack"
else:
    run("P1"); val("P1")
if GENERIC:
    st, vs = run("P2", [{"type": "large", "correction": False}]); val("P2")
    assert any("PCC" in l for l in vs[0]["info"]), vs[0]["info"]
elif MODE != "A" or TTYPE == "galaxie":
    run("P2", [{"type": "large", "correction": True}]); val("P2")
else:
    ok(c.post(f"/api/projects/{NAME}/steps/P2/skip"))
st, vs = run("P3", [{"sn": 0.75, "ss": 0.4}, {"sn": 0.5, "ss": 0.25}]); val("P3", 1)
run("P4", [{"dn": 0.5}, {"dn": 0.8}, {"dn": 0.9}]); val("P4", 1)
run("P5", [{"methode": "autostretch", "targetbg": 0.07}, {"methode": "mtf", "fond": "noir", "m": 0.01},
           {"methode": "statistical", "ss_median": 0.2}, {"methode": "autoghs"}]); val("P5", 0)
run("P6"); val("P6")
st, vs = run("P6N", [{"niveau": 18}, {"niveau": 6, "proteger": False, "douceur": 0}, {"niveau": 10}]); val("P6N", 2)
if MODE == "B":
    run("P6B"); val("P6B")
_, vs7 = run("P7", [{"methode": "selection", "n_ciel": 150, "n_objet": 20, "amas": "200,60,30,10"},
           {"methode": "puissance", "k": 2.5}, {"methode": "supprimer"},
           {"methode": "selection", "n_ciel": 80, "n_objet": 10, "source": "ir"},
           {"methode": "garder", "halos": 0.5}]); val("P7", 0)
assert any("Halos atténués" in l for l in vs7[4]["info"]), vs7[4]["info"]
if MODE == "B" and TTYPE == "nebuleuse":
    p7 = next(s for s in ok(c.get(f"/api/projects/{NAME}"))["steps"] if s["id"] == "P7")
    assert p7["dyn"].get("source") == "ir", "mode B nébuleuse : étoiles IRCUT proposées par défaut"
run("P7T"); val("P7T")
run("P7BIS", [{"K": 1.4}, {"K": 1.8}]); val("P7BIS", 1)
p8b = next(s for s in ok(c.get(f"/api/projects/{NAME}"))["steps"] if s["id"] == "P8B")
if p8b["applies"]:
    assert p8b["dyn"]["oiii_debruit"] == 0.2, p8b["dyn"]           # P4 validé à 0.8 : débruitage OIII léger proposé
    st, vs = run("P8B", [{"palette": "perso", "c_ha": "#ff3020", "c_oiii": "#20c0ff", "oiii_debruit": 0.35},
                         {"palette": "cuivre_bleu", "ha_contraste": 0.5}, {"palette": "hoo", "oiii_gain": 2.5},
                         {"palette": "perso", "oiii_debruit": 0.9}])
    for v in vs:
        assert len(v["images"]) == 2 and any("Séparation" in l for l in v["info"]), v["info"][:3]
    assert any("débruitage cumulé fort" in l for l in vs[3]["info"]), vs[3]["info"]
    import numpy as np
    from astropy.io import fits as _f
    b = _f.getdata(str(tmp / "Astrophoto" / NAME / vs[0]["outputs"]["bicolore"])).astype(float)
    print("  bicolore : médianes R/V/B", [round(float(np.median(b[c])), 3) for c in range(3)])
    val("P8B", 0)
    meta8 = next(s for s in ok(c.get(f"/api/projects/{NAME}"))["steps"] if s["id"] == "P8")
    assert meta8["default_variants"][0]["methode"] == "aucune", meta8["default_variants"]
    BICOLORE = True
else:
    assert "séparables" in p8b["why"], p8b["why"]
    print("  bicolore sans objet :", p8b["why"])
    BICOLORE = False
variants = [{"methode": "satu", "satu": 0.3}, {"methode": "dore", "force": 0.3},
            {"methode": "objet", "force": 0.8, "contraste": True},
            {"methode": "froid", "force": 0.4, "aplanir": True, "zone": "120,60,40,40"},
            {"methode": "degrade", "c1": "#2040ff", "c2": "#ffa040", "force": 0.6}, {"methode": "hoo", "force": 0.8}]
if MODE == "B" and TTYPE == "galaxie":
    variants[-1] = {"methode": "hii", "force": 1.0}
_, vs8 = run("P8", variants); val("P8", 1)
if BICOLORE:
    assert vs8[0]["info"][0].startswith("Entrée : bicolore"), vs8[0]["info"][:2]
run("P8", [{"methode": "rose", "force": 0.5}, {"methode": "cuivre_bleu", "force": 1.0}]); val("P8", 0)
lv = ok(c.get(f"/api/projects/{NAME}/live"))
assert lv["base"].endswith(".jpg") and 0 <= lv["sky"] < 0.5, lv
fine = {"temperature": 0.4, "teinte": -0.2, "rotation": 12, "saturation": 0.3, "vibrance": 0.4, "luminosite": 1.1, "noirs": 0.02}
st, vs = run("P8F", [fine]); val("P8F")
assert "G_fin" in ok(c.get(f"/api/projects/{NAME}"))["state"]["files"]
run("P9"); val("P9")
run("P10", [{"dn": 0.3}]); val("P10")
run("P11", [{"liste": "vert 200 150 20\nremplace 300 100 15"}]); val("P11")
st12, vs12 = run("P12", [{"rotation": "90", "partage": 400}]); val("P12")
from PIL import Image as _Im
_ex = ok(c.get(f"/api/projects/{NAME}"))["state"]["facts"]["exports"]
_sz = {k: _Im.open(tmp / "Astrophoto" / NAME / v).size for k, v in _ex.items() if v.endswith(".jpg")}
assert _sz["colorise"][0] < _sz["colorise"][1] and _sz["brut"][0] > _sz["brut"][1], _sz   # finales tournées, brut non
_pv = vs12[0]["previews"]["size"]
assert _pv[0] < _pv[1], _pv                                                                   # aperçu de la carte tourné
assert next(s for s in ok(c.get(f"/api/projects/{NAME}"))["steps"] if s["id"] == "P10")["reference"] == "P9"
print("  export : finales tournées de 90°, stack brut dans son sens, aperçu tourné ; P10 comparé à la fusion")
# --- fiche : champs pré-remplis d'après les données, brouillon par un faux Ollama
import json as _json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, d):
        b = _json.dumps(d).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send({"models": [{"name": "faux:7b"}]})

    def do_POST(self):
        req = _json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "Demande de l'utilisateur" in req["messages"][1]["content"]:      # « dis ce que tu veux »
            assert "assombris" in req["messages"][1]["content"] and "Fond plus noir" in req["messages"][1]["content"]
            self._send({"message": {"content": _json.dumps({"reglages": {"niveau": "-3", "inconnu": 5, "douceur": 9},
                                                            "explication": "Fond visé plus sombre."})}})
            return
        assert req["format"] == "json" and "NGC7000" in req["messages"][1]["content"].replace(" ", "")
        assert req["options"]["num_ctx"] == 8192 and req.get("think") is False, req
        ans = {"nom_usuel": "Nébuleuse North America", "taille": "120' x 100'", "catalogues": "NGC 7000, Caldwell 20",
               "decouverte": "William Herschel, 1786.", "nom": "Sa forme rappelle l'Amérique du Nord.", "nature": "",
               "anecdote": "Test."}
        self._send({"message": {"content": _json.dumps(ans, ensure_ascii=False)}})


srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=srv.serve_forever, daemon=True).start()
ok(c.post("/api/config", json={"ollama_url": f"http://127.0.0.1:{srv.server_port}", "ollama_model": "faux:7b"}))
proj = ok(c.get(f"/api/projects/{NAME}"))
dyn = next(s for s in proj["steps"] if s["id"] == "P13")["dyn"]
print("fiche pré-remplie :", {k: v[:70] for k, v in dyn.items() if isinstance(v, str)})
assert dyn.get("nom_technique") == "NGC 7000" and "data" not in dyn.get("contexte", ""), dyn
assert "Cygne" in dyn.get("contexte", "") and "culmine" in dyn.get("visibilite", "") and "acquises" in dyn.get("intro_brut", ""), dyn
it = ok(c.post(f"/api/projects/{NAME}/steps/P6N/intention", json={"text": "assombris le ciel", "vals": {"niveau": 12}}))
assert it["reglages"] == {"niveau": 9.0, "douceur": 1} and it["refuses"] == ["inconnu"], it
print("  phrase libre -> réglages contrôlés :", it["reglages"], "ignoré :", it["refuses"])
r = ok(c.post(f"/api/projects/{NAME}/fiche/ollama", json={}))
j = wait(r["job"])
assert j["status"] == "terminé", j["error"]
assert j["result"]["fields"]["catalogues"].startswith("NGC 7000") and j["result"]["fields"]["nature"] == ""
print("brouillon Ollama :", j["result"]["fields"])
pr = ok(c.get(f"/api/projects/{NAME}/fiche/prompt"))["text"]
assert "NGC 7000" in pr and "sources" in pr and "Cygne" in pr, pr
ans = ok(c.post(f"/api/projects/{NAME}/fiche/answer", json={"text": "Voici. " + _json.dumps({"nom_usuel": "Nébuleuse North America", "sources": "NASA"})}))
assert ans["fields"] == {"nom_usuel": "Nébuleuse North America", "sources": "NASA"}, ans
print("  demande pour Claude et collage de la réponse : OK")
st, vs = run("P13", [{"nom_technique": dyn["nom_technique"], "nom_usuel": "Nébuleuse North America", "lieu": "Île-de-France",
                      "contexte": "Dans le Cygne, près de Deneb.\n\nDeuxième paragraphe avec Hα & OIII.",
                      "decouverte": "William Herschel, 1786.", "nom": "Sa forme rappelle le continent nord-américain.",
                      "anecdote": "Test.", "sources": "NASA ; Wikipédia"}])
val("P13")
notes = ok(c.get(f"/api/projects/{NAME}/notes"))["text"]
print("\n----- NOTES.md -----\n" + notes)
pf = ok(c.post(f"/api/projects/{NAME}/preset/save", json={"name": "Test nébuleuse"}))["file"]
assert pf == "Testnebuleuse", pf
print("presets :", ok(c.get("/api/presets")))
ok(c.post(f"/api/projects/{NAME}/preset/apply", json={"file": "Testnebuleuse"}))
# retour en arrière : revalider P5 doit marquer la suite « à refaire »
val("P5", 1)
proj = ok(c.get(f"/api/projects/{NAME}"))
stale = [s["id"] for s in proj["steps"] if s["state"].get("status") == "stale"]
print("à refaire après revalidation de P5 :", stale)
assert "P6" in stale and "P12" in stale
r = ok(c.post(f"/api/projects/{NAME}/replay", json={"until": "P7T"}))
j = wait(r["job"])
assert j["status"] == "terminé", j["error"]
proj = ok(c.get(f"/api/projects/{NAME}"))
stat = {s["id"]: s["state"].get("status") for s in proj["steps"]}
print("refaites :", j["result"]["refaites"])
assert stat["P6"] == "done" and stat["P7T"] == "done" and stat["P8"] == "stale", stat
pdf = tmp / "Astrophoto" / NAME / vs[0]["pdf"]
print("PDF :", pdf, pdf.stat().st_size, "octets")
# finalisation : dossier « nom - lieu - date », PDF et images gardés, dossier de travail supprimé, poses intactes
if os.environ.get("ATELIER_SANS_FINAL"):
    print("Dossier de test :", tmp); raise SystemExit(0)
pl = ok(c.get(f"/api/projects/{NAME}/finalize"))
print("finalisation prévue :", pl["nom"], [k["name"] for k in pl["garde"]], f"{pl['taille_liberee'] / 1e6:.1f} Mo libérés")
assert pl["nom"].startswith("NGC 7000 - ") and pl["nom"].endswith("2026-09-12 au 2026-09-13"), pl["nom"]
assert any(k["name"].endswith(".pdf") for k in pl["garde"]) and any("colorise" in k["name"] for k in pl["garde"])
assert all(k["name"].startswith("NGC7000_") for k in pl["garde"]), [k["name"] for k in pl["garde"]]
assert c.post(f"/api/projects/{NAME}/finalize", json={}).status_code == 400          # pas sans confirmation
lights_before = sorted(str(x) for x in (tmp / "Astrophoto").rglob("lights/*"))
j = wait(ok(c.post(f"/api/projects/{NAME}/finalize", json={"confirme": True}))["job"])
assert j["status"] == "terminé", j["error"]
dest = Path(j["result"]["dest"])
assert dest.is_dir() and len(list(dest.iterdir())) == len(pl["garde"]), list(dest.iterdir())
assert not (tmp / "Astrophoto" / NAME).exists(), "le dossier de travail aurait dû être supprimé"
assert sorted(str(x) for x in (tmp / "Astrophoto").rglob("lights/*")) == lights_before, "poses d'origine modifiées !"
assert not list((tmp / "Astrophoto").rglob("_calibrees")), "poses calibrées intermédiaires restantes"
print("finalisé :", dest.name, sorted(x.name for x in dest.iterdir()))
print("Dossier de test :", tmp)
(config.PRESETS_DIR / "Testnebuleuse.json").unlink()
if config.CONFIG_PATH.exists():
    config.CONFIG_PATH.unlink()
bak = config.CONFIG_PATH.with_suffix(".bak")
if bak.exists():
    bak.rename(config.CONFIG_PATH)
print("OK : test de bout en bout réussi (mode", MODE, TTYPE + ")")

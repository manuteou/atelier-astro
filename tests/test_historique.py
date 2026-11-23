"""Historique des choix : noté à la validation (pas pour une étape refaite ou automatique), repris des projets
existants, choix passés les plus comparables montrés au modèle, export du jeu d'entraînement sans la réponse dans la
question. Lancer : python tests/test_historique.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
tmp = Path(tempfile.mkdtemp(prefix="historique_"))
os.environ["ATELIER_ROOT"] = str(tmp / "Astrophoto")
(tmp / "Astrophoto").mkdir()

from app import historique, intentions, pipeline  # noqa: E402
from app.project import Project  # noqa: E402
from app.steps import STEP_MAP  # noqa: E402


def projet(cible, ttype, bortle, heures, dn_gardee, valider=True, appareil="ZWO Seestar S50"):
    p = Project.create(tmp / "Astrophoto", cible, ttype, appareil, [{"path": str(tmp / cible), "filter": "IRCUT"}])
    p.state.update(bortle=bortle, principal=appareil)
    p.state["facts"]["livetime"] = heures * 3600
    st = p.step("P4")
    st["variants"] = [{"tag": t, "params": {**STEP_MAP["P4"].defaults(), "dn": dn}, "outputs": {},
                       "info": [f"Grain du fond : -{int(dn * 70)} % (mesuré)"]}
                      for t, dn in zip("ABC", (0.4, 0.6, 0.8))]
    p.save()
    if valider:
        pipeline.validate(p, "P4", [0.4, 0.6, 0.8].index(dn_gardee))
    return Project.load(p.root)


# un projet validé avant l'historique (repris par l'import au premier usage)
ancien = projet("M 33", "galaxie", 5, 4.0, 0.8, valider=False)
ancien.step("P4").update(status="done", chosen=2, params=ancien.step("P4")["variants"][2]["params"],
                         validated_at="2026-09-01 22:00")
ancien.save()

a = projet("NGC 7380", "nebuleuse", 5, 3.4, 0.4)           # 1re validation : importe M 33 puis note NGC 7380
recs = historique.charger()
assert [r["projet"] for r in recs] == ["M33_combined", "NGC7380_combined"], [r["projet"] for r in recs]
assert recs[0]["origine"] == "import" and recs[1]["origine"] == "validation"
assert recs[1]["params"]["dn"] == 0.4 and recs[1]["gardee"] == 0 and len(recs[1]["variantes"]) == 3
assert "Variante actuellement validée" not in recs[1]["rapport"], "la réponse ne doit pas être dans la question"
assert "Grain du fond" in recs[1]["rapport"]

b = projet("IC 1396", "nebuleuse", 6, 2.0, 0.6)
projet("Sh2-132", "nebuleuse", 5, 3.0, 0.4)
assert len(historique.charger()) == 4

# étape refaite ou validée automatiquement : pas notée
p = Project.load(b.root)
pipeline.validate(p, "P4", 1, trace=False)
assert len(historique.charger()) == 4

# revalidation : l'ancien choix est remplacé pour les exemples
p = Project.load(a.root)
pipeline.validate(p, "P4", 1)
assert len(historique.charger()) == 5
assert len(historique.derniers(historique.charger())) == 4

# exemples pour une nouvelle nébuleuse proche de NGC 7380 : les nébuleuses d'abord, jamais le projet lui-même
neuf = projet("NGC 7000", "nebuleuse", 5, 3.2, 0.6, valider=False)
ex = historique.exemples(neuf, "P4", 3)
assert {r["projet"] for r in ex[:2]} == {"Sh2-132_combined", "NGC7380_combined"}, [r["projet"] for r in ex]
assert ex[-1]["projet"] in ("IC1396_combined",), [r["projet"] for r in ex]
assert all(r["projet"] != neuf.root.name for r in ex)
bloc = historique.bloc_exemples(neuf, "P4")
assert bloc.count("\n- ") == 3 and "gardée B (dn=0.6" in bloc, bloc
pr = intentions.prompt(STEP_MAP["P4"], STEP_MAP["P4"].defaults(), "Moins de grain", "", bloc)
assert "Choix passés de l'utilisateur" in pr
assert historique.bloc_exemples(neuf, "P4", {"historique_choix": True, "ollama_exemples": 0}) == ""
assert historique.bloc_exemples(neuf, "P8F") == ""                     # aucun choix passé à cette étape

# conseil d'Ollama noté et marqué suivi / non suivi
p = Project.load(neuf.root)
p.step("P4")["ollama_propositions"] = [{"objectif": "Moins de grain", "reglages": {"dn": 0.8}, "modele": "gemma4"}]
p.save()
pipeline.validate(p, "P4", 2)
r = historique.charger()[-1]
assert r["ollama"][0]["reglages"] == {"dn": 0.8}
assert "conseil du modèle suivi" in historique.ligne_exemple(r)
assert "ollama_propositions" not in Project.load(neuf.root).step("P4")

# étapes sans choix (S4) ou hors des étapes utiles : rien de noté
n = len(historique.charger())
assert historique.enregistrement(p, "S4") is None and historique.enregistrement(p, "P0") is None
assert len(historique.charger()) == n

# désactivé dans les Réglages
from app import config  # noqa: E402
cfg = config.load()
cfg["historique_choix"] = False
os.environ["ATELIER_HISTORIQUE"] = str(tmp / "coupe.jsonl")
historique.config.load = lambda: {**cfg}
assert historique.noter(p, "P4") is None and not (tmp / "coupe.jsonl").exists()
del os.environ["ATELIER_HISTORIQUE"]
historique.config.load = config.load

# résumé et export
res = historique.resume()
assert res["choix_distincts"] == 5 and res["par_etape"] == {"P4": 5} and not res["pret_entrainement"], res
dest = tmp / "entrainement.jsonl"
assert historique.exporter(dest) == 5
lignes = [json.loads(l) for l in dest.read_text(encoding="utf-8").splitlines()]
m = lignes[0]["messages"]
assert [x["role"] for x in m] == ["system", "user", "assistant"]
assert json.loads(m[2]["content"])["reglages"]["dn"] in (0.4, 0.6, 0.8)
assert all("Variante actuellement validée" not in l["messages"][1]["content"] for l in lignes)

# un import relancé n'ajoute pas de doublons
assert historique.importer() == 0
print("OK")

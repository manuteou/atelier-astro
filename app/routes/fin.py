"""Fiche (brouillon Ollama) et finalisation du travail."""

from fastapi import APIRouter, Body

from .. import config, jobs
from .commun import proj

router = APIRouter()


@router.post("/api/projects/{name}/fiche/ollama")
def fiche_ollama(name: str, data: dict = Body(default={})):
    from .. import fiche_auto, report
    if jobs.busy(proj(name).root):
        raise ValueError("un traitement de ce projet est en cours : attendre qu'il se termine")
    cfg = config.load()
    model = data.get("model") or cfg.get("ollama_model") or (report.ollama_models(cfg["ollama_url"]) or [""])[0]
    if not model:
        raise ValueError("aucun modèle Ollama installé (ex. : ollama pull qwen2.5:7b)")
    p = proj(name)
    fiche_auto.auto_fields(p)               # constellation connue avant de demander
    p.save()

    def work(job):
        job.write(f"Brouillon des textes de la fiche demandé à {model} (Ollama) pour {p.state['target']}")
        fields, date = fiche_auto.ollama_fields(cfg["ollama_url"], model, proj(name))
        empty = [k for k, v in fields.items() if not v]
        job.write(f"Reçu : {len(fields) - len(empty)} champ(s) rempli(s)" + (f", laissés vides par prudence : {', '.join(empty)}" if empty else ""))
        q = proj(name)
        q.state["fiche_ollama"] = {"fields": fields, "model": model, "date": date}
        q.save()
        return {"fields": fields, "model": model}
    return {"job": jobs.submit("Fiche · brouillon Ollama", work, key=p.root).id}


@router.get("/api/projects/{name}/finalize")
def finalize_plan(name: str, nom: str = ""):
    from .. import finalize
    return finalize.plan(proj(name), nom or None)


@router.post("/api/projects/{name}/finalize")
def finalize_run(name: str, data: dict = Body(default={})):
    from .. import finalize
    if not data.get("confirme"):
        raise ValueError("confirmation manquante")
    p = proj(name)
    if jobs.busy(p.root):
        raise ValueError("un traitement de ce projet est en cours : attendre qu'il se termine")
    return {"job": jobs.submit(f"{p.state['target']} · finalisation", lambda j: finalize.run(j, proj(name), data.get("nom")),
                               key=p.root).id}


@router.get("/api/projects/{name}/fiche/prompt")
def fiche_prompt(name: str):
    from .. import fiche_auto
    p = proj(name)
    fiche_auto.auto_fields(p)
    p.save()
    return {"text": fiche_auto.claude_prompt(p)}


@router.post("/api/projects/{name}/fiche/answer")
def fiche_answer(name: str, data: dict = Body(...)):
    from .. import fiche_auto
    return {"fields": fiche_auto.parse_answer(data.get("text", ""))}

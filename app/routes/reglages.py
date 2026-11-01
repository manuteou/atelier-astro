"""Réglages, outils, matériel, Ollama."""
from pathlib import Path

from fastapi import APIRouter, Body

from .. import config
from ..siril import Siril
from .commun import proj

router = APIRouter()


@router.get("/api/config")
def get_config():
    cfg = config.load()
    s = Siril(cfg)
    return {"config": cfg, "siril_ok": s.available(), "siril_version": s.version(),
            "root_ok": Path(cfg["astro_root"]).exists()}


@router.get("/api/outils")
def get_outils():
    from .. import outils
    cfg = config.load()
    return {"fonctions": outils.FONCTIONS, "choix": {k: outils.choix(cfg, k) for k in outils.FONCTIONS},
            "perso": cfg.get("outils_perso") or {}}


@router.get("/api/materiel")
def get_materiel(project: str = ""):
    from .. import materiel
    cfg = config.load()
    if project:
        profs, new = materiel.seen(proj(project))
    else:
        profs, new = {d: materiel.profile(d, cfg) for d in (cfg.get("materiel") or {})}, []
    return {"profils": profs, "nouveaux": new, "champs": materiel.CHAMPS, "corrections": materiel.CORRECTIONS}


@router.post("/api/materiel")
def post_materiel(data: dict = Body(...)):
    from .. import materiel
    profils = data.get("profils") or {}
    materiel.save_profiles(profils)
    return {"ok": True}


@router.post("/api/config")
def post_config(data: dict = Body(...)):
    cfg = config.load()
    cfg.update({k: v for k, v in data.items() if k in config.DEFAULTS})
    config.save(cfg)
    return get_config()


@router.get("/api/ollama")
def ollama_status():
    from .. import report
    cfg = config.load()
    models = report.ollama_models(cfg.get("ollama_url", ""))
    return {"ok": models is not None, "models": models or [], "model": cfg.get("ollama_model") or (models[0] if models else "")}

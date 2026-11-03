"""Exploration des travaux terminés (lecture seule)."""
import os
import webbrowser

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import galerie

router = APIRouter()


@router.get("/api/galerie")
def liste():
    return galerie.explorer()


def _sur(rel):
    try:
        return galerie.chemin_sur(rel)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404)


@router.get("/galerie/fichier/{rel:path}")
def fichier(rel: str):
    return FileResponse(str(_sur(rel)))


@router.get("/galerie/vignette/{rel:path}")
def vignette(rel: str, l: int = 480):
    _sur(rel)
    try:
        return FileResponse(str(galerie.vignette(rel, l)), headers={"Cache-Control": "max-age=86400"})
    except OSError:
        raise HTTPException(415, "image illisible")


@router.get("/api/galerie/notes/{rel:path}")
def notes(rel: str):
    return {"texte": _sur(rel).read_text(encoding="utf-8", errors="replace")}


@router.post("/api/galerie/ouvrir")
def ouvrir(data: dict):
    d = (galerie.racine() / str(data.get("id") or "")).resolve()
    base = galerie.racine().resolve()
    if not (d == base or base in d.parents) or not d.is_dir():
        raise HTTPException(404)
    try:
        if os.name == "nt":
            os.startfile(str(d))  # noqa
        else:
            webbrowser.open(d.as_uri())
    except Exception as e:
        raise ValueError(str(e))
    return {"ok": True}

"""Exploration des travaux terminés (lecture seule)."""
import os
import webbrowser

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import config, galerie, jobs

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


@router.get("/api/galerie/site")
def site_infos():
    from .. import site
    cfg = config.load()
    return {"dossier": str(site.dossier()), "depot": cfg.get("site_depot") or "", "titre": cfg.get("site_titre") or ""}


@router.post("/api/galerie/site")
def site_fabriquer(data: dict):
    """Fabrique le site (et le publie si data.publier) : travail en arrière-plan."""
    from .. import site
    titre = str(data.get("titre") or "").strip()[:80]
    depot = site.normaliser_depot(data.get("depot"))
    publier = bool(data.get("publier"))
    config.set_value("site_titre", titre)
    if depot:
        config.set_value("site_depot", depot)
    dest = site.dossier()

    def work(job):
        if publier:
            return site.publier(depot, dest, titre, job.write)
        return site.construire(dest, titre, job.write)
    return {"job": jobs.submit("Mes travaux · " + ("publication du site" if publier else "fabrication du site"), work,
                               key=dest).id}


@router.post("/api/galerie/site/ouvrir")
def site_ouvrir():
    from .. import site
    f = site.dossier() / "index.html"
    if not f.exists():
        raise HTTPException(404, "site pas encore fabriqué")
    webbrowser.open(f.as_uri())
    return {"ok": True}

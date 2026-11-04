"""Sessions, import, projets, presets, fichiers."""
import os
import webbrowser
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from .. import config, inventory, jobs, pipeline
from ..project import Project, list_projects
from ..steps import ORDER, STEP_MAP
from ..steps.base import refresh_zoom
from .commun import proj

router = APIRouter()

SCANS = {}


@router.get("/api/sessions")
def sessions():
    return inventory.scan(config.load()["astro_root"])


@router.post("/api/import/scan")
def import_scan(data: dict = Body(...)):
    from .. import organize
    path = data.get("path", "").strip().strip('"')
    res = organize.scan(path)
    import secrets
    token = secrets.token_hex(8)
    SCANS[token] = res
    light = [{k: v for k, v in g.items() if k not in ("files", "calib_files")} for g in res["groups"]]
    return {"token": token, "groups": light, "rejects": res["rejects"], "total": res["total"]}


@router.post("/api/import/apply")
def import_apply(data: dict = Body(...)):
    from .. import organize
    res = SCANS.get(str(data.get("token")))
    if not res:
        raise ValueError("analyse expirée : relance « Analyser »")
    ids = set(int(i) for i in data.get("ids", []))
    groups = [g for g in res["groups"] if g["id"] in ids]
    if not groups or not data.get("target"):
        raise ValueError("choisis au moins une session et une cible")
    cfg = config.load()
    if jobs.busy(cfg["astro_root"]):
        raise ValueError("un traitement est déjà en cours dans ce dossier : attendre qu'il se termine")
    mode = data.get("mode", "lien")

    def work(job):
        job.write(f"Rangement de {sum(g['count'] for g in groups)} poses en {len(groups)} sessions ({mode})")
        paths = organize.apply(groups, cfg["astro_root"], mode, job.write)
        ses = [inventory.describe(Path(x)) for x in paths]
        p = Project.create(cfg["astro_root"], data["target"].strip(), data.get("type", "nebuleuse"),
                           data.get("device") or "", ses)
        job.write(f"Projet créé : {p.state['name']}")
        return {"name": p.state["name"]}
    job = jobs.submit("Import et rangement des poses", work, key=cfg["astro_root"])
    return {"job": job.id}


@router.get("/api/projects")
def projects():
    return list_projects(config.load()["astro_root"])


@router.post("/api/projects")
def create_project(data: dict = Body(...)):
    cfg = config.load()
    paths = data.get("sessions") or []
    if not data.get("target") or not paths:
        raise ValueError("cible et au moins une session sont nécessaires")
    ses = [inventory.describe(Path(x)) for x in paths]
    mixed = [f"{s['name']} : {s['mixed']}" for s in ses if s.get("mixed")]
    if mixed:
        raise ValueError(" ; ".join(mixed))
    p = Project.create(cfg["astro_root"], data["target"].strip(), data.get("type", "nebuleuse"),
                       data.get("device") or "", ses)
    return {"name": p.state["name"]}


@router.post("/api/stack/analyse")
def stack_analyse(data: dict = Body(...)):
    from .. import depuis_stack
    return depuis_stack.analyser(data.get("path"))


@router.post("/api/projects/depuis_stack")
def stack_projet(data: dict = Body(...)):
    from .. import depuis_stack
    p, info, rem = depuis_stack.creer(config.load()["astro_root"], data.get("path"), data.get("target"), data.get("type"))
    return {"name": p.state["name"], "remarques": rem}


@router.get("/api/projects/{name}")
def get_project(name: str):
    p = proj(name)
    steps = [pipeline.step_meta(p, sid) for sid in ORDER]
    return {"state": {k: v for k, v in p.state.items() if k != "steps"}, "steps": steps}


@router.post("/api/projects/{name}/zoom")
def set_zoom(name: str, data: dict = Body(...)):
    p = proj(name)
    p.state["zoom"] = data.get("rect")
    p.save()
    sid = data.get("step")
    if sid and sid in p.state["steps"]:
        refresh_zoom(p, p.state["steps"][sid])
        ref = getattr(STEP_MAP[sid], "reference_step", None)
        if ref and ref in p.state["steps"]:
            refresh_zoom(p, p.state["steps"][ref])
        p.save()
    return {"ok": True}


@router.get("/api/projects/{name}/notes")
def notes(name: str):
    p = proj(name)
    pipeline.write_notes(p)
    return {"text": (p.root / "NOTES.md").read_text(encoding="utf-8")}


@router.get("/api/presets")
def presets():
    return pipeline.list_presets()


@router.get("/api/presets/{file}")
def preset(file: str):
    return pipeline.load_preset(file)


@router.delete("/api/presets/{file}")
def del_preset(file: str):
    f = config.PRESETS_DIR / f"{file}.json"
    if f.exists():
        f.unlink()
    return {"ok": True}


@router.post("/api/projects/{name}/preset/save")
def save_preset(name: str, data: dict = Body(...)):
    if not data.get("name"):
        raise ValueError("nom du preset manquant")
    return {"file": pipeline.save_preset(proj(name), data["name"], data.get("description", ""))}


@router.post("/api/projects/{name}/preset/apply")
def apply_preset(name: str, data: dict = Body(...)):
    pipeline.apply_preset(proj(name), data["file"])
    return {"ok": True}


@router.post("/api/projects/{name}/preset/clear")
def clear_preset(name: str):
    p = proj(name)
    p.state.pop("preset", None)
    p.save()
    return {"ok": True}


@router.get("/files/{name}/{path:path}")
def files(name: str, path: str):
    p = proj(name)
    f = (p.root / path).resolve()
    if p.root.resolve() not in f.parents or not f.exists():
        raise HTTPException(404)
    return FileResponse(str(f), headers={"Cache-Control": "no-store"})


@router.post("/api/projects/{name}/open")
def open_folder(name: str):
    p = proj(name)
    try:
        if os.name == "nt":
            os.startfile(str(p.root))  # noqa
        else:
            webbrowser.open(p.root.as_uri())
    except Exception as e:
        raise ValueError(str(e))
    return {"ok": True}

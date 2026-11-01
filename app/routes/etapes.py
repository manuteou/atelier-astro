"""Étapes : lancer, valider, passer, rejouer ; aperçus en direct (P8F, P11) ; rapport et avis."""
import time

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from .. import config, jobs, pipeline
from ..steps import STEP_MAP
from .commun import proj

router = APIRouter()


@router.post("/api/projects/{name}/steps/{sid}/run")
def run_step(name: str, sid: str, data: dict = Body(...)):
    if sid not in STEP_MAP:
        raise HTTPException(404, "étape inconnue")
    variants = data.get("variants") or [{}]
    if len(variants) > 6:
        raise ValueError("6 variantes au maximum")
    p = proj(name)
    if jobs.busy(p.root):
        raise ValueError("un traitement de ce projet est déjà en cours : attendre qu'il se termine")
    job = jobs.submit(f"{p.state['target']} · {STEP_MAP[sid].title}",
                      lambda j: pipeline.run_variants(j, proj(name), sid, variants), key=p.root)
    return {"job": job.id}


@router.get("/api/projects/{name}/live")
def live(name: str):
    """Aperçus réduits pour le réglage fin des couleurs en direct (P8F)."""
    from ..steps.reglage_fin import live_sources
    return live_sources(proj(name), int(config.load().get("live_width", 1400)))


@router.get("/api/projects/{name}/retouch")
def retouch(name: str):
    """Images pleine résolution pour l'éditeur de retouches (P11)."""
    from ..steps.retouches import retouch_sources
    return retouch_sources(proj(name))


@router.post("/api/projects/{name}/steps/{sid}/validate")
def validate(name: str, sid: str, data: dict = Body(...)):
    p = proj(name)
    pipeline.validate(p, sid, int(data.get("variant", 0)))
    return {"ok": True}


@router.post("/api/projects/{name}/replay")
def replay(name: str, data: dict = Body(default={})):
    p = proj(name)
    if jobs.busy(p.root):
        raise ValueError("un traitement de ce projet est déjà en cours")
    todo = pipeline.stale_steps(p)
    if not todo:
        raise ValueError("aucune étape à refaire")
    until = data.get("until")
    job = jobs.submit(f"{p.state['target']} · étapes refaites avec leurs réglages",
                      lambda j: pipeline.replay(j, lambda: proj(name), until), key=p.root)
    return {"job": job.id, "etapes": todo}


@router.post("/api/projects/{name}/steps/{sid}/skip")
def skip(name: str, sid: str):
    pipeline.skip(proj(name), sid)
    return {"ok": True}


@router.post("/api/projects/{name}/steps/{sid}/reopen")
def reopen(name: str, sid: str):
    proj(name).reopen(sid)
    return {"ok": True}


@router.get("/api/projects/{name}/steps/{sid}/report")
def step_report(name: str, sid: str):
    from .. import report
    return {"text": report.build(proj(name), sid)}


@router.post("/api/projects/{name}/steps/{sid}/advice")
def step_advice(name: str, sid: str, data: dict = Body(default={})):
    from .. import report
    if jobs.busy(proj(name).root):
        raise ValueError("un traitement de ce projet est en cours : l'avis attendra qu'il soit fini")
    cfg = config.load()
    model = data.get("model") or cfg.get("ollama_model") or (report.ollama_models(cfg["ollama_url"]) or [""])[0]
    if not model:
        raise ValueError("aucun modèle Ollama installé (ex. : ollama pull qwen2.5:7b)")
    text = report.build(proj(name), sid)

    def work(job):
        job.write(f"Avis demandé à {model} (Ollama) sur {sid} : {len(text)} caractères de rapport")
        ans = report.ollama_advice(cfg["ollama_url"], model, text)
        if not ans:
            raise RuntimeError(f"{model} a renvoyé une réponse vide : réessayer, ou choisir un autre modèle dans Réglages")
        job.write("Avis reçu ; modèle déchargé de la carte graphique.")
        job.write("— Avis —")
        for line in ans.splitlines():
            job.write("  " + line)
        p = proj(name)                       # gardé dans le projet : visible aussi après rechargement
        p.step(sid)["advice"] = {"text": ans, "model": model, "date": time.strftime("%Y-%m-%d %H:%M")}
        p.save()
        return {"advice": ans, "model": model, "step": sid}
    return {"job": jobs.submit(f"Avis Ollama · {sid}", work, key=proj(name).root).id}


@router.get("/api/projects/{name}/fullres")
def fullres(name: str, src: str, linear: int = 0):
    """JPEG pleine résolution d'un FITS du projet (comparaison des variantes), mis en cache dans apercus/."""
    import hashlib
    from .. import fitsio
    p = proj(name)
    f = (p.root / src).resolve()
    if p.root.resolve() not in f.parents or not f.exists():
        raise HTTPException(404, "image introuvable")
    key = hashlib.md5(f"{f}|{f.stat().st_mtime}|{linear}".encode()).hexdigest()[:12]
    out = p.root / "apercus" / f"plein_{key}.jpg"
    if not out.exists():
        fitsio.preview(f, out, bool(linear), width=100000, quality=92)
    return {"image": p.rel(out)}


@router.get("/api/projects/{name}/p8f/suggest")
def p8f_suggest(name: str):
    """Réglages fins proposés d'après des mesures du calque couleur validé (P8)."""
    from .. import color_ops, fitsio
    p = proj(name)
    g = p.file("G_final")
    if not g:
        raise ValueError("valider d'abord les couleurs (P8)")
    d, _ = fitsio.read(g)
    prm, lines = color_ops.suggest(d, p.type)
    return {"reglages": prm, "lignes": lines}


@router.get("/api/projects/{name}/pose")
def pose_thumb(name: str, fichier: int, dev: str = ""):
    """Vignette d'une pose (débayérisée vite, étirée comme les autres aperçus), mise en cache."""
    from .. import fitsio, inventory
    from ..steps.sessions import proc_dir
    p = proj(name)
    src = proc_dir(p, dev) / f"combined_{int(fichier):05d}.fit" if dev else p.root / "process" / f"combined_{int(fichier):05d}.fit"
    if not src.exists():
        for ext in (".fits", ".fts"):
            if src.with_suffix(ext).exists():
                src = src.with_suffix(ext)
                break
        else:
            raise HTTPException(404, "pose introuvable (conversion S2 effacée ?)")
    out = p.root / "apercus" / "poses" / f"{dev or 'p'}_{int(fichier):05d}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        rgb, hdr = inventory.quick_rgb(src)
        c0, m = fitsio.autostretch_params(rgb)
        fitsio.save_jpeg(fitsio.display(fitsio.apply_stretch(rgb, c0, m), hdr), out, quality=82, width=480)
    return FileResponse(str(out), headers={"Cache-Control": "no-store"})


@router.post("/api/projects/{name}/steps/{sid}/intention")
def intention(name: str, sid: str, data: dict = Body(...)):
    """Phrase libre -> réglages de l'étape (modèle Ollama), contrôlés : réglages connus, affichés, dans leurs bornes."""
    from .. import intentions, report
    if sid not in STEP_MAP:
        raise HTTPException(404, "étape inconnue")
    text = str(data.get("text") or "").strip()
    if not text:
        raise ValueError("phrase vide")
    cfg = config.load()
    model = intentions.choose_model(cfg, report.ollama_models(cfg["ollama_url"]))
    if not model:
        raise ValueError("Ollama n'est pas disponible : utilise les phrases toutes faites, ou lance Ollama")
    step = STEP_MAP[sid]
    vals = {**step.defaults(), **{k: v for k, v in (data.get("vals") or {}).items()}}
    out = intentions.traduire(cfg["ollama_url"], model, step, vals, text)
    out["modele"] = model
    return out

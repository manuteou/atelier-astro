"""Orchestration : lancer les variantes d'une étape, valider, passer, NOTES.md, presets."""
import json
from pathlib import Path
import time

from . import config
from .config import PRESETS_DIR
from .project import Project
from .steps import ORDER, STEP_MAP, STEPS
from .steps.base import LETTERS, Ctx, make_previews


def step_meta(p, sid):
    s = STEP_MAP[sid]
    m = s.meta(p)
    m["dyn"] = s.dyn_defaults(p) if hasattr(s, "dyn_defaults") and m["applies"] else {}
    m["reference"] = s.reference_for(p) if hasattr(s, "reference_for") else getattr(s, "reference_step", None)
    m["summary"] = s.summary(p) if hasattr(s, "summary") else None
    from .intentions import AVIS_UTILE, objectifs, phrases
    m["phrases"] = phrases(sid)
    m["objectifs"] = objectifs(sid)
    m["avis"] = sid in AVIS_UTILE
    if hasattr(s, "poses") and m["applies"]:
        try:
            m["poses"] = s.poses(p)
        except Exception:
            m["poses"] = []
    m["state"] = p.state["steps"].get(sid, {"status": "todo", "variants": []})
    from .remedies import for_variant
    for v in m["state"].get("variants", []):
        v["remedes"] = for_variant(p, sid, v)
    return m


def run_variants(job, p: Project, sid, variants):
    """Exécute chaque variante (A, B, C…) puis fabrique les aperçus. Résultat stocké dans project.json."""
    step = STEP_MAP[sid]
    cfg = config.load()
    ok, why = step.applies(p)
    if not ok:
        raise ValueError(why)
    rd, msg = step.ready(p)
    if not rd:
        raise ValueError(msg)
    if (step.single or step.kind == "formulaire") and len(variants) > 1:
        variants = variants[:1]
    run = p.new_run(sid)
    ctx = Ctx(p, cfg, job, sid, run)
    results = []
    from . import jobs as J
    for i, prm in enumerate(variants):
        J.checkpoint()
        J.part(i, len(variants), f"{step.id} · variante {LETTERS[i]} ({i + 1}/{len(variants)})" if len(variants) > 1 else step.id)
        prm = step.clean(prm)
        tag = LETTERS[i]
        job.write(f"— Variante {tag} : " + ", ".join(f"{k}={v}" for k, v in prm.items() if v not in (None, "")))
        var = {"params": prm, "tag": tag, "run": run}
        t0 = time.time()
        try:
            res = step.run(ctx, prm, tag)
            var.update(outputs=res.get("outputs", {}), info=res.get("info", []), images=res.get("images", []),
                       extra=res.get("extra", {}), linear=res.get("linear", step.linear), pdf=res.get("pdf"))
            make_previews(ctx, step, var, i)
        except J.Cancelled:
            raise
        except Exception as e:
            if job.cancel_requested:
                raise J.Cancelled("traitement annulé")
            var["error"] = str(e)
            job.write(f"Variante {tag} en échec : {e}")
            import traceback
            where = [f"{Path(fr.filename).name}:{fr.lineno} ({fr.name})" for fr in traceback.extract_tb(e.__traceback__)[-4:]]
            job.write("  (où : " + " ← ".join(reversed(where)) + ")")
        var["duree"] = round(time.time() - t0, 1)
        results.append(var)
    st = p.step(sid)
    st["variants"] = results
    st["chosen"] = None          # la variante validée auparavant appartenait à l'essai précédent
    if st.get("status") in (None, "todo", "skipped"):
        st["status"] = "essai"
    p.save()
    if all(v.get("error") for v in results):
        raise RuntimeError(results[0]["error"])
    return {"step": sid, "n": len(results)}


def validate(p: Project, sid, idx):
    step = STEP_MAP[sid]
    names = {k: v.format(T=p.T) for k, v in step.canonical.items()}
    var = p.step(sid)["variants"][idx]
    p.validate(sid, idx, names, ORDER)
    if hasattr(step, "on_validate"):
        step.on_validate(p, var)
    p.save()
    write_notes(p)


def stale_steps(p):
    return [sid for sid in ORDER if p.state["steps"].get(sid, {}).get("status") == "stale"]


def replay(job, name_loader, until=None):
    """Refait les étapes « à refaire » avec les réglages qui avaient été retenus, dans l'ordre, et les revalide.
    S'arrête à `until` (incluse), à la première erreur, ou sur une étape dont les réglages ne suffisent pas."""
    from . import jobs as J
    done = []
    for sid in ORDER:
        J.checkpoint()
        p = name_loader()
        st = p.state["steps"].get(sid, {})
        if st.get("status") != "stale":
            if until and sid == until:
                break
            continue
        step = STEP_MAP[sid]
        ok, why = step.applies(p)
        if not ok:
            job.write(f"{sid} : sans objet maintenant ({why}), laissée de côté")
            continue
        prm = dict(st.get("params") or {})
        job.write(f"=== {sid} · {step.title} : refaite avec les réglages retenus")
        run_variants(job, p, sid, [prm])
        p = name_loader()
        var = p.step(sid)["variants"][0]
        if var.get("error"):
            raise RuntimeError(f"{sid} a échoué en la refaisant : {var['error']}")
        validate(p, sid, 0)
        alerts = [l for l in var.get("info", []) if l.startswith("ATTENTION")]
        done.append({"step": sid, "alertes": len(alerts)})
        job.write(f"{sid} revalidée" + (f" — {len(alerts)} alerte(s)" if alerts else " — aucune alerte"))
        if until and sid == until:
            break
    return {"refaites": done}


def skip(p: Project, sid):
    step = STEP_MAP[sid]
    if not step.optional:
        raise ValueError("cette étape ne peut pas être passée")
    p.skip(sid, ORDER, step.produces)
    write_notes(p)


# ------------------------------------------------------------------ NOTES ---
def notes_lines(p, short=False):
    out = []
    for s in STEPS:
        st = p.state["steps"].get(s.id)
        if not st:
            continue
        if st.get("status") == "done":
            line = s.notes(p, st)
            if short:
                line = line.split("\n")[0]
                if s.id in ("S1", "S4", "P12", "P13"):
                    continue
            out.append(line)
        elif st.get("status") == "skipped" and not short:
            out.append(f"{s.title} : passée")
    return out


def write_notes(p):
    f = p.state["facts"]
    L = [f"# {p.state['target']} — NOTES", "",
         f"- Type de cible : {p.type}", f"- Appareil : {p.state.get('device', '')}",
         f"- Mode filtres : {p.mode}", f"- Projet créé : {p.state.get('created')}", "", "## Sessions"]
    for s in p.state.get("sessions", []):
        L.append(f"- {s.get('name')} : {s.get('count')} poses, filtre {s.get('filter')}, {s.get('exptime')} s, {s.get('date')}")
    L += ["", "## Étapes validées (réglages retenus)"]
    L += [f"- {l}" for l in notes_lines(p)]
    if f.get("exports"):
        L += ["", "## Fichiers clés"]
        e = f["exports"]
        for k, lab in (("brut", "Stack brut"), ("naturel", "Finale naturelle"), ("colorise", "Finale colorisée"),
                       ("partage", "JPEG de partage"), ("tiff", "TIFF 16 bits"), ("fit", "FIT final")):
            if k in e:
                L.append(f"- {lab} : {e[k]}")
    if p.state.get("fiche", {}).get("lieu"):
        L += ["", f"Lieu de prise de vue : {p.state['fiche']['lieu']}"]
    L += ["", "## Fichiers en cours"] + [f"- {k} : {v}" for k, v in sorted(p.state["files"].items())]
    (p.root / "NOTES.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- presets ---
def list_presets():
    PRESETS_DIR.mkdir(exist_ok=True)
    out = []
    for f in sorted(PRESETS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({"file": f.stem, "name": d.get("name", f.stem), "type": d.get("type", ""),
                        "description": d.get("description", ""), "steps": sorted(d.get("steps", {}).keys())})
        except Exception:
            pass
    return out


def save_preset(p, name, description="", steps=None):
    """Enregistre les réglages validés du projet (seulement les étapes de rendu, pas le cadrage ni la fiche)."""
    skip_ids = {"S1", "S2", "S3", "S4", "P0", "P11", "P13"}
    data = {"name": name, "type": p.type, "description": description, "source": p.state["target"],
            "created": time.strftime("%Y-%m-%d"), "steps": {}}
    for sid in ORDER:
        if sid in skip_ids or (steps and sid not in steps):
            continue
        st = p.state["steps"].get(sid, {})
        if st.get("status") == "done":
            data["steps"][sid] = [st.get("params", {})]
        elif st.get("status") == "skipped":
            data["steps"][sid] = "passer"
    PRESETS_DIR.mkdir(exist_ok=True)
    from .project import slug
    f = PRESETS_DIR / f"{slug(name) or 'preset'}.json"
    f.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return f.stem


def load_preset(file):
    return json.loads((PRESETS_DIR / f"{file}.json").read_text(encoding="utf-8"))


def apply_preset(p, file):
    """Un preset ne lance rien : il pré-remplit les réglages (variantes) de chaque étape ; chaque étape garde son aperçu et sa validation."""
    d = load_preset(file)
    p.state["preset"] = {"file": file, "name": d.get("name"), "steps": d.get("steps", {})}
    p.save()
    return d

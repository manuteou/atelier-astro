"""Suivi et annulation des travaux en arrière-plan."""

from fastapi import APIRouter, HTTPException

from .. import jobs

router = APIRouter()


def _job(jid):
    return jobs.JOBS.get(jid)


@router.get("/api/jobs")
def liste(actifs: int = 1):
    """Travaux en cours (pour reprendre le suivi après un rechargement de la page)."""
    out = []
    for j in jobs.JOBS.values():
        if _job(j.id) and (not actifs or j.status in ("en cours", "en attente")):
            out.append({"id": j.id, "title": j.title, "status": j.status,
                        "attente": j.queue_position()})
    return out


@router.get("/api/jobs/{jid}")
def job(jid: int, since: int = 0):
    j = _job(jid)
    if not j:
        raise HTTPException(404, "travail inconnu")
    return j.as_dict(since)


@router.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: int):
    j = _job(jid)
    if not j:
        raise HTTPException(404, "travail inconnu")
    return {"ok": j.request_cancel(), "status": j.status}

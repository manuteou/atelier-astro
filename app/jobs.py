"""Travaux en arrière-plan : une seule file, un travail à la fois (Siril ne doit pas tourner deux fois en même temps).

Annulation : `Job.request_cancel()` arrête le processus externe en cours (Siril, script Python, avec ses
processus enfants) et lève `Cancelled` au prochain point de contrôle (`checkpoint()`), appelé entre deux
variantes, entre deux commandes et à chaque ligne de journal. Les phases qui ne doivent pas être coupées
(suppression des fichiers à la finalisation) se protègent avec `uninterruptible()`.

Progression : `progress(pct, texte)` depuis le code des étapes ; les lignes « progress: …, 42.00% » de Siril
alimentent la sous-progression de la variante en cours.
"""
import contextlib
import itertools
import os
import queue
import signal
import subprocess
import threading
import time
import traceback

_ids = itertools.count(1)
JOBS = {}
_q = queue.Queue()
_local = threading.local()


class Cancelled(Exception):
    """Travail arrêté à la demande de l'utilisateur."""


class Job:
    def __init__(self, title, fn, key=None):
        self.id = next(_ids)
        self.title = title
        self.fn = fn
        self.key = str(key) if key else None     # dossier concerné (projet) : un seul travail à la fois par dossier
        self.status = "en attente"
        self.log = []
        self.result = None
        self.error = None
        self.started = None
        self.ended = None
        self.cancel_requested = False
        self.cancellable = True
        self.procs = set()
        self.part = (0, 1)              # (index, nombre) de la partie en cours (variante, étape refaite…)
        self.part_label = ""
        self.sub_pct = None              # progression interne de la partie (Siril)
        self.sub_text = ""
        self.last_output = None          # dernière ligne reçue d'un processus externe (détection des silences)
        self._lock = threading.Lock()

    # ---- journal ---------------------------------------------------------------------------------------------
    def write(self, line):
        self.log.append(f"{time.strftime('%H:%M:%S')} {line}")
        if len(self.log) > 5000:
            del self.log[:1000]

    # ---- progression -----------------------------------------------------------------------------------------
    def set_part(self, i, n, label=""):
        self.part, self.part_label, self.sub_pct, self.sub_text = (i, max(n, 1)), label, None, ""

    def heard(self):
        self.last_output = time.time()

    def set_sub(self, pct=None, text=""):
        self.sub_pct = None if pct is None else max(0.0, min(100.0, float(pct)))
        if text:
            self.sub_text = text

    def progress_dict(self):
        i, n = self.part
        frac = (i + (self.sub_pct or 0) / 100) / n
        return {"pct": round(100 * frac, 1) if self.status == "en cours" else (100 if self.status == "terminé" else None),
                "partie": self.part_label, "detail": self.sub_text,
                "sous_pct": None if self.sub_pct is None else round(self.sub_pct, 1),
                "silence": round(time.time() - self.last_output) if self.last_output and self.procs else 0}

    # ---- annulation ------------------------------------------------------------------------------------------
    def request_cancel(self):
        if self.status not in ("en cours", "en attente"):
            return False
        if not self.cancellable:
            self.write("Annulation demandée pendant une phase qui ne peut pas être coupée : elle s'arrêtera juste après.")
        self.cancel_requested = True
        if self.status == "en attente":
            self.status = "annulé"
            return True
        if self.cancellable:
            with self._lock:
                for p in list(self.procs):
                    kill_tree(p)
        self.write("Annulation demandée…")
        return True

    def checkpoint(self):
        if self.cancel_requested and self.cancellable:
            raise Cancelled("traitement annulé")

    def add_proc(self, p):
        with self._lock:
            self.procs.add(p)
        if self.cancel_requested and self.cancellable:
            kill_tree(p)

    def remove_proc(self, p):
        with self._lock:
            self.procs.discard(p)

    def as_dict(self, since=0):
        return {"id": self.id, "title": self.title, "status": self.status, "error": self.error,
                "log": self.log[since:], "log_len": len(self.log), "result": self.result,
                "progress": self.progress_dict(), "attente": self.queue_position(), "cancellable": self.cancellable and not self.cancel_requested,
                "duree": round((self.ended or time.time()) - self.started, 1) if self.started else 0}


def _queue_position(job):
    if job.status != "en attente":
        return 0
    return sum(1 for j in JOBS.values() if j.id < job.id and j.status in ("en cours", "en attente"))


Job.queue_position = _queue_position


def kill_tree(p):
    """Arrête un processus et ses enfants (siril-cli lance Python pour pyscript)."""
    if p.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def popen_kwargs():
    """Options de Popen : arbre de processus arrêtable, aucune entrée standard, et sous Windows aucune console.
    Une console partagée peut figer Siril : un clic dans la fenêtre noire (mode « Sélection » de Windows)
    suspend tout programme qui y écrit, jusqu'à ce qu'on appuie sur une touche."""
    kw = {"stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200) | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    else:
        kw["start_new_session"] = True
    return kw


# ---- accès depuis le code des étapes (sans faire passer le travail partout) ---------------------------------
def current():
    return getattr(_local, "job", None)


def checkpoint():
    j = current()
    if j:
        j.checkpoint()


def heard():
    j = current()
    if j:
        j.heard()


def part(i, n, label=""):
    j = current()
    if j:
        j.set_part(i, n, label)


def sub(pct=None, text=""):
    j = current()
    if j:
        j.set_sub(pct, text)


@contextlib.contextmanager
def uninterruptible():
    j = current()
    if not j:
        yield
        return
    old = j.cancellable
    j.cancellable = False
    try:
        yield
    finally:
        j.cancellable = old


@contextlib.contextmanager
def tracked(p):
    j = current()
    if j:
        j.add_proc(p)
        j.heard()
    try:
        yield p
    finally:
        if j:
            j.remove_proc(p)


def _worker():
    while True:
        job = _q.get()
        if job.status == "annulé":
            continue
        _local.job = job
        job.status = "en cours"
        job.started = time.time()
        try:
            job.result = job.fn(job)
            job.status = "terminé"
        except Cancelled:
            job.status = "annulé"
            job.error = "annulé"
            job.write("Traitement annulé : les réglages et résultats déjà validés sont intacts.")
        except Exception as e:
            if job.cancel_requested:
                job.status, job.error = "annulé", "annulé"
                job.write("Traitement annulé : les réglages et résultats déjà validés sont intacts.")
            else:
                job.error = str(e)
                job.write("ERREUR : " + str(e))
                job.write(traceback.format_exc(limit=4))
                job.status = "échec"
        job.ended = time.time()
        _local.job = None


threading.Thread(target=_worker, daemon=True).start()


def submit(title, fn, key=None):
    """key : dossier du projet (ou de l'espace) concerné. Les travaux passent l'un après l'autre (une seule file :
    Siril et la carte graphique ne sont pas partagés) ; deux travaux sur le même dossier sont refusés (busy)."""
    job = Job(title, fn, key)
    JOBS[job.id] = job
    _q.put(job)
    return job


def busy(key=None):
    """Un travail en cours ou en attente (sur ce dossier, ou dans ce dossier, si key est donné)."""
    act = [j for j in JOBS.values() if j.status in ("en cours", "en attente")]
    if key is None:
        return bool(act)
    k = str(key)
    return any(j.key and (j.key == k or j.key.startswith(k.rstrip("/\\") + os.sep) or k.startswith(j.key + os.sep))
               for j in act)

"""Pont avec Siril (siril-cli) et avec les scripts Python du pipeline.

Chaque étape écrit un script .ssf dans <projet>/_scripts puis lance
`siril-cli -d <dossier> -s <script>`. Le journal est renvoyé ligne par ligne.
Pas de délai de 60 s ici : l'appli attend la fin réelle de Siril.
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import jobs
from .config import SCRIPTS_DIR

PROGRESS = re.compile(r"^progress:\s*(.*?),?\s*([\d.]+)\s*%\s*$", re.I)

# Seuls les marqueurs d'échec de script comptent, plus le code de retour de Siril. Les mots « échec » ou
# « failed » apparaissent aussi dans les bilans réussis (« 0 échec », « 0 en échec, 694 alignées ») : on ne
# les cherche plus. Chaque étape vérifie ensuite que les fichiers attendus existent vraiment.
ERR_PATTERNS = [
    re.compile(p, re.I) for p in (
        r"error in line", r"erreur (à|a) la ligne", r"traceback \(most recent", r"unrecognized arguments",
        r"unknown command", r"commande inconnue", r"license (has )?expired", r"licence expirée",
    )
]


def is_error(line):
    return any(p.search(line) for p in ERR_PATTERNS)


WARN_PATTERNS = [re.compile(p, re.I) for p in (r"trial license", r"expires in", r"warning")]


def opt(name, value):
    """Option Siril « -nom=valeur ». Siril prend les guillemets placés après le « = » au pied de la lettre
    (il créerait un dossier nommé "…") : sans espace, pas de guillemets ; avec espaces, guillemets autour de
    l'option entière, comme "-oscsensor=ZWO Seestar S50"."""
    v = str(value).replace("\\", "/")
    return f'"{name}={v}"' if " " in v else f"{name}={v}"


GENERIC = re.compile(r"(vérifier les log|check the log|l'exécution du script a échoué|script execution failed|"
                     r"temps d'exécution|execution time|définir le répertoire|setting (the )?working directory|"
                     r"free and close|closing pipes|^log: échec de l'empilement|^log: stacking failed)", re.I)
FAILURE = re.compile(r"(segmentation|access violation|échec|echec|échou|echou|failed|failure|error|erreur|impossible|"
                     r"cannot|can't|unable|not enough|pas assez|insuffisante|out of memory|introuvable|not found|aucune image|"
                     r"no image|invalid|invalide|nécessite|n'est pas|is not|missing|manquant|refus)", re.I)
INFO = re.compile(r"^(log: )?(memory per image|allocating data|max memory|processing all|traitement de|"
                  r"ok ?! ce script|ok! this script|exécution de la commande|running command|\d+: running command)", re.I)


def cause(out):
    """Les lignes qui disent pourquoi Siril a échoué. Les bilans de fin (« Vérifier les log », « L'exécution du
    script a échoué », temps d'exécution) et les lignes d'information (« Memory per image… ») ne disent rien :
    on prend la première vraie ligne d'échec, avec les deux lignes qui la précèdent et les deux qui la suivent."""
    lines = [l for l in out if not l.lower().startswith(("status:", "progress:")) and not GENERIC.search(l)]
    first = next((i for i, l in enumerate(lines) if FAILURE.search(l) and not INFO.search(l)), None)
    if first is None:
        return " | ".join(lines[-6:]) or (out[-1] if out else "aucune sortie")
    return " | ".join(lines[max(0, first - 2):first + 3])


class SirilError(RuntimeError):
    pass


def q(path):
    """Chemin entre guillemets pour un script Siril (barres obliques, compatibles Windows)."""
    return '"' + str(path).replace("\\", "/") + '"'


class Siril:
    def __init__(self, cfg):
        self.cfg = cfg
        self.exe = cfg.get("siril_cli") or ""

    def available(self):
        return bool(self.exe) and Path(self.exe).exists()

    def version(self):
        if not self.available():
            return None
        try:
            r = subprocess.run([self.exe, "--version"], capture_output=True, text=True, timeout=30)
            return (r.stdout or r.stderr).strip().splitlines()[0]
        except Exception as e:
            return f"inconnue ({e})"

    def run(self, commands, cwd, log, name="etape", check=True):
        """Lance une suite de commandes Siril dans `cwd`. Retourne le journal complet."""
        if not self.available():
            raise SirilError("siril-cli introuvable : renseigner son chemin dans Réglages.")
        cwd = Path(cwd)
        sdir = cwd / "_scripts"
        sdir.mkdir(parents=True, exist_ok=True)
        script = sdir / f"{time.strftime('%Y%m%d_%H%M%S')}_{name}.ssf"
        body = ["requires 1.2.0"] + [c for c in commands if c]
        script.write_text("\n".join(body) + "\n", encoding="utf-8")
        log(f"[siril] {name} : {len(body) - 1} commande(s)")
        for c in body[1:]:
            log(f"  > {c}")
        jobs.checkpoint()
        proc = subprocess.Popen([self.exe, "-d", str(cwd), "-s", str(script)], cwd=str(cwd),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", **jobs.popen_kwargs())
        out, errors, warns = [], [], []
        last_pct = None
        with jobs.tracked(proc):
            for line in proc.stdout:
                jobs.heard()
                line = line.rstrip()
                if not line:
                    continue
                out.append(line)
                m = PROGRESS.match(line)
                if m:                                  # barre de progression, pas le journal (des milliers de lignes)
                    pct = float(m.group(2))
                    jobs.sub(pct, m.group(1).strip())
                    if last_pct is None or abs(pct - last_pct) >= 25 or pct >= 100:
                        log("    " + line)
                        last_pct = pct
                    continue
                log("    " + line)
                if is_error(line):
                    errors.append(line)
                elif any(p.search(line) for p in WARN_PATTERNS):
                    warns.append(line)
            proc.wait()
        jobs.checkpoint()
        text = "\n".join(out)
        for w in warns:
            log(f"[attention] {w}")
        if check and (proc.returncode != 0 or errors):
            # la dernière ligne est souvent un bilan générique (« L'exécution du script a échoué ») : on remonte
            # jusqu'aux lignes qui disent pourquoi
            detail = errors[0] if errors else cause(out)
            try:
                script.with_suffix(".log").write_text(text, encoding="utf-8")
                detail += f"  — journal complet : _scripts/{script.with_suffix('.log').name}"
            except OSError:
                pass
            raise SirilError(f"Siril a échoué ({name}, code {proc.returncode}) : {detail}  — script : {script.name}")
        return text


def run_py(script, args, cwd, log, check=True):
    """Lance un script du pipeline (app/scripts) avec le Python de l'appli. Retourne la sortie standard."""
    path = SCRIPTS_DIR / script
    cmd = [sys.executable, str(path)] + [str(a) for a in args]
    log(f"[python] {script} " + " ".join(str(a) for a in args))
    # Windows : sans cela, Python écrit sa sortie et ses fichiers texte en cp1252, qui ne connaît pas ″, ±, α…
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    jobs.checkpoint()
    p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", env=env, **jobs.popen_kwargs())
    with jobs.tracked(p):
        stdout, stderr = p.communicate()
    jobs.checkpoint()
    r = subprocess.CompletedProcess(cmd, p.returncode, stdout, stderr)
    for line in (r.stdout + ("\n" + r.stderr if r.stderr else "")).splitlines():
        if line.strip():
            log("    " + line)
    if check and r.returncode not in (0,) and not (script == "controle.py" and r.returncode == 1):
        raise SirilError(f"{script} a échoué (code {r.returncode}) : "
                         + (r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.stdout[-300:]))
    return r.stdout

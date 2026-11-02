"""Configuration de l'atelier (fichier config.json à la racine de l'appli)."""
import json
import os
import shutil
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
CONFIG_PATH = ROOT_DIR / "config.json"
PRESETS_DIR = ROOT_DIR / "presets"
SCRIPTS_DIR = APP_DIR / "scripts"
FONTS_DIR = APP_DIR / "fonts"

DEFAULTS = {
    # Dossier racine des sessions : <racine>\<SESSION>\lights\*.fit ; les projets y sont créés (<CIBLE>_combined)
    "astro_root": "D:\\Astrophoto",
    # Exécutable Siril en ligne de commande (siril-cli.exe sous Windows)
    "siril_cli": "",
    # Noms des scripts Python installés dans Siril (appelés par pyscript)
    "script_graxpert": "GraXpert-AI.py",
    "script_bxt": "BlurXTerminator.py",
    "script_nxt": "NoiseXTerminator.py",
    "script_starx": "StarXTerminator.py",
    "script_statstretch": "Statistical_Stretch.py",
    # Outil utilisé pour chaque fonction (voir outils.py) : rcastro | graxpert | siril | starnet | perso | aucun
    "outils": {"fond": "graxpert", "nettete": "rcastro", "debruitage": "rcastro", "etoiles": "rcastro"},
    # Commandes Siril personnalisées (outil « perso »), une par ligne ; {force} = réglage de force de l'étape
    "outils_perso": {"fond": "", "nettete": "", "debruitage": "", "etoiles": ""},
    # Fiches du matériel, par appareil détecté (nom, focale, ouverture, pixel, capteur SPCC…) : voir materiel.py
    "materiel": {},
    # Conventions Siril à confirmer au premier vrai essai (l'appli les vérifie et les corrige d'elle-même)
    "crop_y_origin": "haut",          # "haut" : y de crop compté depuis le haut de l'image affichée ; "bas" sinon
    "select_index_base": 1,           # numérotation de select/unselect (1 = première pose)
    "spcc_catalog_local": True,       # catalogue Gaia local installé dans Siril
    "preview_width": 1200, "live_width": 1400,
    # Ollama (facultatif) : avis d'un modèle local sur les chiffres d'une étape
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "",
    "ollama_num_ctx": 8192,
    "ollama_intent_model": "",         # modèle pour « dis ce que tu veux » (vide = le modèle par défaut)           # contexte réservé par Ollama : petit = rapide et tient dans la carte graphique
    "port": 8765,
    # lieux d'observation : [{lat, lon, bortle}] (classe de Bortle retenue par lieu, voir sites.py)
    "sites": [],
    # signature posée sur les JPEG d'export (P12), retenue d'un projet à l'autre
    "signature": "",
}


def _guess_siril():
    for cand in [
        shutil.which("siril-cli"),
        r"C:\Program Files\Siril\bin\siril-cli.exe",
        r"C:\Program Files (x86)\Siril\bin\siril-cli.exe",
        "/usr/bin/siril-cli",
        "/Applications/Siril.app/Contents/MacOS/siril-cli",
    ]:
        if cand and os.path.exists(cand):
            return cand
    return ""


def _raw():
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def load():
    cfg = _raw()
    if not cfg.get("siril_cli"):
        cfg["siril_cli"] = _guess_siril()
    # variable d'environnement prioritaire (tests, installation portable)
    if os.environ.get("ATELIER_SIRIL"):
        cfg["siril_cli"] = os.environ["ATELIER_SIRIL"]
    if os.environ.get("ATELIER_ROOT"):
        cfg["astro_root"] = os.environ["ATELIER_ROOT"]
    return cfg


def save(cfg):
    keep = {k: cfg[k] for k in DEFAULTS if k in cfg}
    CONFIG_PATH.write_text(json.dumps(keep, indent=2, ensure_ascii=False), encoding="utf-8")


def set_value(key, value):
    cfg = load()
    cfg[key] = value
    save(cfg)
    return cfg

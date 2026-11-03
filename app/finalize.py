"""« Finaliser le travail » : copie le PDF et les images finales dans un dossier « <nom> - <lieu> - <date> »,
puis supprime le dossier de travail du projet et les poses calibrées intermédiaires des sessions.
Les poses d'origine (lights, darks, flats, offsets) ne sont jamais touchées. Rien ne se fait sans clic explicite."""
import os
import re
import shutil
import stat
from pathlib import Path

from . import config, jobs

LABELS = {"colorise": "Finale colorisée (JPEG HD)", "naturel": "Finale naturelle (JPEG HD)", "brut": "Stack brut (JPEG HD)",
          "partage": "JPEG de partage", "tiff": "TIFF 16 bits", "fit": "FIT final (pour retravailler)"}
SESSION_TMP = ("_calibrees", "_calib")


def _size(path):
    p = Path(path)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())


def _clean_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(s))
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:120] or "Observation"


def default_name(p):
    from .fiche_auto import technical_name
    from .organize import _night
    fiche = p.state.get("fiche") or {}
    nom = (fiche.get("nom_technique") or technical_name(p) or p.state.get("target") or "").strip()
    lieu = (fiche.get("lieu") if "lieu" in fiche else (p.state.get("fiche_auto") or {}).get("lieu")) or ""
    lieu = lieu.split(",")[0].strip()                     # « Ville, Région » -> « Ville »
    nuits = sorted({_night(s.get("date")) for s in p.state.get("sessions", []) if s.get("date")} - {"date-inconnue"})
    date = nuits[0] if len(nuits) == 1 else (f"{nuits[0]} au {nuits[-1]}" if nuits else "")
    return _clean_name(" - ".join(x for x in (nom, lieu, date) if x))


def file_prefix(p):
    """Préfixe des fichiers finaux : le nom technique sans espaces (« NGC7000 »), pas le nom du dossier de travail."""
    from .fiche_auto import technical_name
    nom = ((p.state.get("fiche") or {}).get("nom_technique") or technical_name(p) or "").strip()
    return re.sub(r"[^A-Za-z0-9-]+", "", nom) or p.T


def plan(p, name=None):
    pre = file_prefix(p)
    ren = lambda n: (pre + n[len(p.T):]) if n.startswith(p.T + "_") else n
    from .galerie import racine
    root = racine()                      # FINAUX TRAITES s'il existe (ou le dossier réglé), sinon la racine
    ex = p.state["facts"].get("exports") or {}
    if not ex:
        raise ValueError("rien à finaliser : valide d'abord l'export (P12)")
    dest = root / _clean_name(name or default_name(p))
    keep = []
    for k, rel in ex.items():
        f = p.abs(rel)
        if f.exists():
            keep.append({"label": LABELS.get(k, k), "src": str(f), "name": ren(f.name), "size": f.stat().st_size})
    pdf = p.state["facts"].get("fiche_pdf")
    if pdf and p.abs(pdf).exists():
        f = p.abs(pdf)
        keep.append({"label": "Fiche PDF", "src": str(f), "name": ren(f.name), "size": f.stat().st_size})
    notes = p.root / "NOTES.md"
    if notes.exists():
        keep.append({"label": "NOTES.md (réglages retenus, quelques Ko)", "src": str(notes), "name": f"{pre}_NOTES.md",
                     "size": notes.stat().st_size})
    delete = [{"label": "Dossier de travail du projet (empilements, essais, aperçus, scripts)", "path": str(p.root),
               "size": _size(p.root)}]
    for s in p.state.get("sessions", []):
        for d in SESSION_TMP:
            t = Path(s.get("path", "")) / d
            if t.is_dir():
                delete.append({"label": f"Poses calibrées intermédiaires de {s.get('name')}", "path": str(t), "size": _size(t)})
    warn = []
    if not pdf:
        warn.append("La fiche PDF n'a pas été générée (P13) : seules les images seront gardées.")
    if dest.exists() and any(dest.iterdir()):
        warn.append(f"Le dossier « {dest.name} » existe déjà : les fichiers y seront ajoutés (sans écraser).")
    return {"dest": str(dest), "nom": dest.name, "garde": keep, "supprime": delete, "avertissements": warn,
            "taille_gardee": sum(k["size"] for k in keep), "taille_liberee": sum(d["size"] for d in delete)}


def _rm(path):
    def onerr(func, pth, _):
        os.chmod(pth, stat.S_IWRITE)            # fichiers en lecture seule sous Windows
        func(pth)
    shutil.rmtree(path, onerror=onerr)


def run(job, p, name=None):
    pl = plan(p, name)
    root = Path(config.load()["astro_root"]).resolve()
    proj = p.root.resolve()
    dest = Path(pl["dest"])
    # garde-fous : on ne supprime qu'un dossier de projet de l'atelier, dans la racine, et jamais la destination
    if proj.parent != root or not (proj / "project.json").exists() or not proj.name.endswith("_combined"):
        raise RuntimeError(f"dossier de projet inattendu ({proj}) : rien n'a été supprimé")
    if dest.resolve() == proj or proj in dest.resolve().parents:
        raise RuntimeError("la destination est dans le dossier de travail : rien n'a été supprimé")
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for k in pl["garde"]:
        out = dest / k["name"]
        i = 2
        while out.exists():
            out = dest / f"{Path(k['name']).stem}_v{i}{Path(k['name']).suffix}"
            i += 1
        jobs.checkpoint()
        shutil.copy2(k["src"], out)
        if out.stat().st_size != k["size"]:
            raise RuntimeError(f"copie incomplète de {k['name']} : rien n'a été supprimé")
        copied.append(out.name)
        job.write(f"Gardé : {out.name}")
    job.write(f"{len(copied)} fichier(s) copiés et vérifiés dans {dest}")
    jobs.checkpoint()                           # dernier moment où l'on peut annuler : ensuite on supprime
    with jobs.uninterruptible():
        _delete(job, pl, proj)
    job.write(f"Terminé : {pl['taille_liberee'] / 1e9:.2f} Go libérés. Les poses d'origine sont intactes.")
    return {"dest": str(dest), "nom": dest.name, "fichiers": copied, "libere": pl["taille_liberee"]}


def _delete(job, pl, proj):
    for d in pl["supprime"]:
        t = Path(d["path"])
        if not t.exists():
            continue
        if t.resolve() != proj and t.name not in SESSION_TMP:
            continue
        _rm(t)
        job.write(f"Supprimé : {d['label']} ({d['size'] / 1e9:.2f} Go)")

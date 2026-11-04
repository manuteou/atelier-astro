"""Projet qui part d'une image déjà empilée (stack du Seestar, d'un autre logiciel, ou d'un ancien projet) : on saute
l'inventaire, l'alignement et l'empilement, et on reprend le traitement à la mesure du stack (S4) ou au cadrage (P0).

L'image est copiée dans le projet sous le nom d'un stack de l'atelier ({T}_true_combined.fit), en 32 bits flottants
0-1 ; l'original n'est jamais modifié. Le piédestal du capteur (mot-clé BIAS des stacks du Seestar) est retiré : sinon
il fausse la calibration des couleurs et la neutralisation du fond."""
from pathlib import Path

import numpy as np
from astropy.io import fits

from . import fitsio, inventory
from .project import Project


def analyser(path):
    """Ce qu'on sait de l'image (dimensions, couleur, poses, filtre, appareil, lieu…) ; ValueError si inutilisable."""
    f = Path(str(path or "").strip().strip('"'))
    if not f.is_file() or f.suffix.lower() not in (".fit", ".fits", ".fts"):
        raise ValueError(f"fichier FITS introuvable : {f}")
    h = fitsio.header(f)
    nax = int(h.get("NAXIS", 0))
    if nax < 2:
        raise ValueError("ce fichier ne contient pas d'image")
    canaux = int(h.get("NAXIS3", 1)) if nax == 3 else 1
    if canaux not in (1, 3):
        raise ValueError(f"image à {canaux} plans : attendu 3 (couleur) ou 1")
    if canaux == 1 and str(h.get("BAYERPAT", "")).strip() and not h.get("STACKCNT"):
        raise ValueError("c'est une pose brute non dématricée, pas une image empilée : crée plutôt un projet à partir "
                         "des sessions")
    instrument = str(h.get("INSTRUME") or h.get("TELESCOP") or h.get("CREATOR") or "").strip()
    focal = h.get("FOCALLEN")
    n = h.get("STACKCNT") or h.get("NCOMBINE")
    exp = h.get("EXPTIME") or h.get("EXPOSURE")
    total = h.get("LIVETIME") or h.get("TOTALEXP") or (float(n) * float(exp) if n and exp else None)
    if total and n and exp and float(total) <= float(exp) * 1.01 and int(n) > 1:
        total = float(n) * float(exp)                       # TOTALEXP du Seestar : parfois la durée d'une seule pose
    return {
        "path": str(f), "name": f.name, "taille": [h.get("NAXIS1"), h.get("NAXIS2")], "canaux": canaux,
        "poses": int(n) if n else None, "exptime": float(exp) if exp else None,
        "integration_s": float(total) if total else None,
        "filter": inventory.norm_filter(h.get("FILTER"), f.name), "filter_name": str(h.get("FILTER") or "").strip(),
        "object": str(h.get("OBJECT") or "").strip(), "instrument": instrument, "focal": focal,
        "device": inventory.device_family(instrument, focal), "date": str(h.get("DATE-OBS") or "")[:19],
        "lat": h.get("SITELAT"), "lon": h.get("SITELONG"), "pixel": h.get("XPIXSZ") or h.get("PIXSIZE1"),
        "ra": h.get("RA") or h.get("CRVAL1"), "dec": h.get("DEC") or h.get("CRVAL2"),
        "bias": h.get("BIAS"), "plate_solve": bool(h.get("CTYPE1")),
    }


def creer(astro_root, path, target, ttype):
    info = analyser(path)
    target = (target or info["object"] or Path(info["path"]).stem).strip()
    ses = {k: info[k] for k in ("filter", "filter_name", "exptime", "date", "instrument", "object", "ra", "dec", "focal",
                                "lat", "lon", "pixel", "device")}
    ses.update(path=str(Path(info["path"]).parent), name=f"Image empilée importée : {info['name']}",
               count=info["poses"] or 1, size=info["taille"], stack_importe=info["path"])
    from .project import slug
    deja = Path(astro_root) / f"{slug(target)}_combined" / "project.json"
    if deja.exists() and Project.load(deja.parent).state.get("source") != "stack":
        raise ValueError(f"un projet {deja.parent.name} existe déjà pour cette cible, parti des poses : choisis un "
                         "autre nom de cible (ex. « NGC 7000 stack »)")
    if deja.exists():
        old = Project.load(deja.parent)
        old.state["sessions"] = []                         # nouvelle image pour ce projet : elle remplace l'ancienne
        old.save()
    p = Project.create(astro_root, target, ttype or "nebuleuse", info["instrument"], [ses])
    d, h = fitsio.read(info["path"])
    remarques = []
    with fits.open(info["path"], memmap=False) as hd:
        brut = next(x for x in hd if x.data is not None).data
        entier = np.issubdtype(brut.dtype, np.integer) or float(np.nanmax(brut)) > 1.5
    if info["bias"] and entier:
        ped = float(info["bias"]) / 65535.0
        if float(np.percentile(d, 0.5)) > ped:              # le piédestal est bien encore dans l'image
            d = np.clip((d - ped) / (1 - ped), 0, 1)
            remarques.append(f"piédestal du capteur retiré (BIAS {int(info['bias'])})")
    d = np.nan_to_num(d, nan=0.0).astype(np.float32)
    if d.shape[0] == 1:
        remarques.append("image monochrome : les étapes de couleur seront limitées")
    out = p.root / f"{p.T}_true_combined.fit"
    h["STACKCNT"] = info["poses"] or h.get("STACKCNT", 1)
    if info["integration_s"]:
        h["LIVETIME"] = info["integration_s"]
    fitsio.write(out, d, h)
    p.state.update(source="stack", stack_origine=info["path"], mode="unique", devices=[info["device"]],
                   principal=info["device"], device=info["instrument"] or info["device"])
    p.state["files"]["stack"] = p.rel(out)
    # faits que l'inventaire et l'empilement auraient notés (fiche technique, fiche PDF, NOTES)
    for k, v in (("date", info["date"]), ("total", info["poses"]), ("stackcnt", info["poses"]),
                 ("livetime", info["integration_s"]), ("ra", info["ra"]), ("dec", info["dec"]),
                 ("focal", info["focal"]), ("pix", info["pixel"])):
        if v not in (None, ""):
            p.state["facts"][k] = v
    p.state["facts"]["stack_importe"] = {"fichier": info["path"], "poses": info["poses"],
                                         "integration_s": info["integration_s"], "remarques": remarques}
    from . import sites
    connu = sites.connu(sites.position(p))
    if connu and connu.get("bortle"):
        p.state["bortle"] = int(connu["bortle"])            # classe déjà retenue pour ce lieu (S1 d'un autre projet)
    p.save()
    from .pipeline import write_notes
    write_notes(p)
    return p, info, remarques


def parti_d_un_stack(p):
    return p.state.get("source") == "stack"

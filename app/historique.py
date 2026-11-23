"""Historique des choix : à chaque validation d'une étape où l'avis du modèle local sert (AVIS_UTILE), l'appli note
le contexte de l'image, les variantes proposées avec leurs mesures, celle que l'utilisateur a gardée, et ce
qu'Ollama avait proposé s'il a été consulté.

À quoi ça sert :
- tout de suite : quand on demande un avis ou des réglages à Ollama, on lui montre les choix passés de l'utilisateur
  à la même étape sur les images les plus comparables (même type de cible, même appareil, ciel et temps de pose
  proches). Le modèle suit ainsi le goût de l'utilisateur sans aucun entraînement (« few-shot ») ;
- plus tard : ce fichier est le jeu de données d'un éventuel entraînement (fine-tuning) d'un modèle pour l'appli ;
  exporter() l'écrit au format conversationnel attendu par les outils d'entraînement.

Fichier : <racine des sessions>\\atelier_choix.jsonl (une ligne JSON par validation), qui reste avec les données.
Rien ne quitte la machine. Une étape revalidée sur le même projet remplace l'ancien choix pour les exemples.
Le texte saisi par l'utilisateur (titres, signature, noms) n'est jamais repris dans les exemples."""
import json
import math
import os
import re
import time
from pathlib import Path

from . import config

FICHIER = "atelier_choix.jsonl"
VERSION = 1


def chemin():
    f = os.environ.get("ATELIER_HISTORIQUE")
    return Path(f) if f else Path(config.load()["astro_root"]) / FICHIER


def actif(cfg=None):
    return bool((cfg or config.load()).get("historique_choix", True))


def _propre(t, n=160):
    return re.sub(r"[`\"<>{}\[\]]", "", re.sub(r"\s+", " ", str(t)))[:n].strip()


def _heures(p):
    f = p.state.get("facts") or {}
    for k in ("livetime", "integration_s"):
        try:
            if f.get(k):
                return round(float(f[k]) / 3600, 2)
        except (TypeError, ValueError):
            pass
    return None


def contexte(p):
    """Ce qui rend deux images comparables (aucun texte saisi par l'utilisateur, sauf le nom de la cible)."""
    devs = p.state.get("devices") or [p.state.get("device", "")]
    return {"cible": _propre(p.state.get("target", ""), 60), "type": p.type, "appareil": str(p.state.get("principal") or devs[0] or ""),
            "mode": p.mode, "bortle": p.state.get("bortle"), "heures": _heures(p),
            "source": p.state.get("source") or "poses"}


def _variantes(step, st):
    libres = {q.name for q in step.params if q.type in ("text", "textarea", "rect")}
    out = []
    for v in st.get("variants") or []:
        prm = {k: x for k, x in step.visible(v.get("params") or {}).items() if k not in libres}
        info = [_propre(l, 140) for l in v.get("info") or [] if any(c.isdigit() for c in str(l))]
        out.append({"tag": v.get("tag"), "params": prm, "erreur": bool(v.get("error")),
                    "alertes": sum(1 for l in v.get("info") or [] if str(l).startswith("ATTENTION")),
                    "mesures": info[:4], "stats": v.get("stats")})
    return out


def enregistrement(p, sid, origine="validation"):
    """Ligne d'historique pour l'étape validée `sid` du projet (None si rien d'utile à noter)."""
    from .intentions import AVIS_UTILE
    from .steps import STEP_MAP
    if sid not in AVIS_UTILE or sid == "S4":         # S4 : simple mesure, rien n'y est choisi
        return None
    step = STEP_MAP[sid]
    st = p.state["steps"].get(sid) or {}
    if st.get("chosen") is None or not st.get("variants"):
        return None
    var = _variantes(step, st)
    i = int(st["chosen"])
    if i >= len(var):
        return None
    rapport = ""
    try:
        from . import report
        rapport = report.build(p, sid, pour_modele=True)
        rapport = re.sub(r"\n*Variante actuellement validée.*$", "", rapport)[:8000]   # la réponse ne doit pas y figurer
    except Exception:
        pass
    return {"v": VERSION, "date": st.get("validated_at") or time.strftime("%Y-%m-%d %H:%M"), "origine": origine,
            "projet": p.root.name, "etape": sid, "contexte": contexte(p), "variantes": var, "gardee": i,
            "params": var[i]["params"], "ollama": (st.get("ollama_propositions") or [])[-3:],
            "avis": bool(st.get("advice")), "rapport": rapport}


def noter(p, sid, origine="validation"):
    """Ajoute la validation à l'historique ; ne bloque jamais la validation (best-effort)."""
    try:
        if not actif():
            return None
        rec = enregistrement(p, sid, origine)
        if rec is None:
            return None
        f = chemin()
        if not f.exists():
            importer(f, sauf=(rec["projet"], sid))       # premier usage : reprendre les choix déjà faits
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec
    except Exception:
        return None


def charger():
    f = chemin()
    if not f.exists():
        return []
    out = []
    for l in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(l))
        except ValueError:
            continue
    return out


def importer(f=None, sauf=None):
    """Reprend les choix déjà faits dans les projets existants (premier usage) ; renvoie le nombre ajouté."""
    from .project import Project
    f = f or chemin()
    deja = {(r.get("projet"), r.get("etape"), r.get("date")) for r in charger()} if f.exists() else set()
    racine = Path(config.load()["astro_root"])
    n = 0
    lignes = []
    for pj in sorted(racine.glob("*/project.json")) if racine.is_dir() else []:
        try:
            p = Project.load(pj.parent)
        except Exception:
            continue
        for sid, st in (p.state.get("steps") or {}).items():
            if st.get("status") not in ("done", "stale"):
                continue
            try:
                rec = enregistrement(p, sid, "import")
            except Exception:
                rec = None
            if rec and (rec["projet"], sid, rec["date"]) not in deja and (rec["projet"], sid) != sauf:
                lignes.append(json.dumps(rec, ensure_ascii=False))
                n += 1
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        for l in lignes:
            fh.write(l + "\n")
    return n


def derniers(recs):
    """Le dernier choix par (projet, étape) : une revalidation remplace l'ancien."""
    d = {}
    for r in recs:
        d[(r.get("projet"), r.get("etape"))] = r
    return list(d.values())


def proximite(a, b):
    """Plus c'est grand, plus les deux images se ressemblent pour cette étape."""
    s = 0.0
    s += 3 if a.get("type") == b.get("type") else 0
    s += 1 if a.get("appareil") and a.get("appareil") == b.get("appareil") else 0
    s += 1 if a.get("mode") == b.get("mode") else 0
    s += 0.5 if a.get("source") == b.get("source") else 0
    try:
        s -= 0.4 * abs(int(a["bortle"]) - int(b["bortle"]))
    except (KeyError, TypeError, ValueError):
        s -= 0.6
    try:
        s -= 0.6 * abs(math.log2(max(float(a["heures"]), 0.05) / max(float(b["heures"]), 0.05)))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        s -= 0.6
    return s


def exemples(p, sid, k=3, recs=None):
    """Les k choix passés les plus comparables à cette étape (autres projets seulement)."""
    if k <= 0:
        return []
    ctx = contexte(p)
    cand = [r for r in derniers(recs if recs is not None else charger())
            if r.get("etape") == sid and r.get("projet") != p.root.name and r.get("params") is not None]
    cand.sort(key=lambda r: (proximite(ctx, r.get("contexte") or {}), r.get("date") or ""), reverse=True)
    return cand[:k]


def _prm(d):
    return ", ".join(f"{k}={str(v).replace(chr(10), ' ; ')}" for k, v in (d or {}).items()) or "réglages par défaut"


def ligne_exemple(r):
    c = r.get("contexte") or {}
    tete = ", ".join(x for x in (
        _propre(c.get("cible", ""), 40), c.get("type"), _propre(c.get("appareil", ""), 30),
        f"Bortle {c['bortle']}" if c.get("bortle") else None,
        f"{str(c['heures']).replace('.', ',')} h" if c.get("heures") else None,
        "parti d'un stack importé" if c.get("source") == "stack" else None) if x)
    vs = r.get("variantes") or []
    g = int(r.get("gardee", 0))
    props = " | ".join(f"{v.get('tag')} {_prm(v.get('params'))}" for v in vs[:6]) if len(vs) > 1 else ""
    choisi = vs[g] if g < len(vs) else {}
    mes = "; ".join(choisi.get("mesures") or [])[:220]
    out = f"- {tete} : " + (f"proposées {props} → gardée {choisi.get('tag')} ({_prm(r.get('params'))})" if props
                             else f"gardé {_prm(r.get('params'))}")
    if mes:
        out += f" ; mesures de la gardée : {mes}"
    olla = r.get("ollama") or []
    if olla:
        o = olla[-1]
        suivi = all(r.get("params", {}).get(kk) == vv for kk, vv in (o.get("reglages") or {}).items())
        out += " ; (conseil du modèle " + ("suivi" if suivi else "non suivi") + ")"
    return out


def bloc_exemples(p, sid, cfg=None):
    """Texte à ajouter à la demande faite au modèle (vide s'il n'y a pas d'exemple ou si c'est désactivé)."""
    cfg = cfg or config.load()
    try:
        k = int(cfg.get("ollama_exemples", 3))
    except (TypeError, ValueError):
        k = 3
    if not actif(cfg) or k <= 0:
        return ""
    try:
        ex = exemples(p, sid, k)
    except Exception:
        return ""
    if not ex:
        return ""
    return ("Choix passés de l'utilisateur à cette même étape, sur ses images les plus comparables (ils montrent son "
            "goût) :\n" + "\n".join(_propre(ligne_exemple(r), 700) for r in ex) +
            "\nSi les mesures d'aujourd'hui sont proches de ces cas, propose des réglages dans le même esprit ; si elles "
            "diffèrent nettement, privilégie les mesures et dis-le.")


def resume():
    recs = charger()
    par = {}
    for r in derniers(recs):
        par[r.get("etape")] = par.get(r.get("etape"), 0) + 1
    return {"fichier": str(chemin()), "validations": len(recs), "choix_distincts": sum(par.values()),
            "par_etape": dict(sorted(par.items())), "projets": len({r.get("projet") for r in recs}),
            "pret_entrainement": sum(par.values()) >= 300}


def exporter(dest):
    """Jeu d'entraînement au format conversationnel (JSONL « messages ») : rapport de l'étape → réglages gardés.
    Seuls les choix avec un rapport sont repris ; le dernier choix par projet et par étape."""
    from .report import system_pour
    n = 0
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        for r in derniers(charger()):
            if not r.get("rapport"):
                continue
            vs = r.get("variantes") or []
            g = int(r.get("gardee", 0))
            rep = {"variante": vs[g].get("tag") if g < len(vs) else None, "reglages": r.get("params") or {}}
            fh.write(json.dumps({"messages": [
                {"role": "system", "content": system_pour(r.get("etape"))},
                {"role": "user", "content": r["rapport"] + "\n\nQuelle variante et quels réglages garderais-tu ?"},
                {"role": "assistant", "content": json.dumps(rep, ensure_ascii=False)}],
                "etape": r.get("etape"), "projet": r.get("projet")}, ensure_ascii=False) + "\n")
            n += 1
    return n

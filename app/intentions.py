"""Piloter les réglages d'une étape avec des phrases.

- PHRASES : phrases toutes faites par étape, chacune liée à un changement de réglages connu (aucun modèle, instantané).
  Valeur « +0.1 » / « -3 » : ajustement relatif à la valeur actuelle ; autre valeur : valeur imposée. Les réglages
  d'une autre méthode que celle choisie sont ignorés à l'application (seuls les champs affichés changent).
- traduire() : une phrase libre -> réglages, par un modèle Ollama qui connaît les réglages de l'étape, leurs bornes et
  les phrases toutes faites (exemples). Le résultat est contrôlé : réglages inconnus retirés, bornes respectées.
"""
import json
import re

PHRASES = {
    "P3": [("Plus net", {"sn": "+0.1", "ss": "+0.1", "iters": "+3"}),
           ("Plus doux, moins d'artefacts", {"sn": "-0.15", "ss": "-0.1", "iters": "-3"}),
           ("Étoiles plus fines seulement", {"ss": "+0.15"}),
           ("Ne pas toucher aux étoiles", {"ss": 0})],
    "P4": [("Moins de grain", {"dn": "+0.1"}),
           ("Plus naturel, moins lissé", {"dn": "-0.15"})],
    "P5": [("Fond plus sombre", {"targetbg": "-0.03", "m": "+0.0005", "ghs_amount": "-20", "ss_median": "-0.03"}),
           ("Plus de détails dans les zones faibles", {"targetbg": "+0.03", "m": "-0.0005", "ghs_amount": "+30", "ss_median": "+0.03"}),
           ("Cœur moins brûlé, étirement plus doux", {"targetbg": "-0.02", "m": "+0.0005", "ghs_amount": "-30", "ss_median": "-0.03"}),
           ("Fond neutre, sans teinte", {"mesure": "ciel"})],
    "P6N": [("Fond plus noir", {"niveau": "-3"}),
            ("Fond moins noir, plus naturel", {"niveau": "+3"}),
            ("Préserver les zones faibles", {"proteger": True, "seuil_objet": "-10", "douceur": "+0.2"}),
            ("Transition plus douce", {"douceur": "+0.2"})],
    "P7": [("Moins d'étoiles", {"n_ciel": "-500", "plancher": "+0.03", "k": "+0.5"}),
           ("Garder plus d'étoiles", {"n_ciel": "+500", "plancher": "-0.02", "k": "-0.5"}),
           ("Grosses étoiles plus discrètes", {"halo": "-3", "k": "+0.5"}),
           ("Garder toutes les étoiles telles quelles", {"methode": "garder"})],
    "P7BIS": [("Étoiles plus colorées", {"K": "+0.3"}),
              ("Étoiles plus naturelles", {"K": "-0.3"}),
              ("Enlever le vert des étoiles", {"vert": True})],
    "P8": [("Couleurs plus vives", {"satu": "+0.1", "force": "+0.15"}),
           ("Couleurs plus discrètes", {"satu": "-0.1", "force": "-0.15"}),
           ("Plus de relief (contraste local)", {"contraste": True, "c_force": "+0.1"}),
           ("Aplanir un fond irrégulier", {"aplanir": True})],
    "P8F": [("Fond plus sombre", {"noirs": "+0.02", "proteger_fond": False}),
            ("Couleurs plus vives", {"vibrance": "+0.15", "saturation": "+0.05"}),
            ("Plus chaud", {"temperature": "+0.15"}),
            ("Plus froid", {"temperature": "-0.15"}),
            ("Moins vert", {"teinte": "+0.15"}),
            ("Éclaircir les tons moyens", {"luminosite": "+0.08"}),
            ("Assombrir un peu", {"luminosite": "-0.08"})],
    "P10": [("Moins de grain", {"dn": "+0.1"}),
            ("Plus naturel, moins lissé", {"dn": "-0.15"})],
}


def phrases(sid):
    return [{"texte": t, "reglages": r} for t, r in PHRASES.get(sid, [])]


def _visible(p, vals):
    return not p.show_if or all(vals.get(k) in v for k, v in p.show_if.items())


def schema(step, vals):
    """Description des réglages affichés, pour le modèle."""
    out = []
    for p in step.params:
        if p.type in ("text", "textarea", "rect", "color") or not _visible(p, vals):
            continue
        d = {"nom": p.name, "libelle": p.label, "valeur": vals.get(p.name, p.default)}
        if p.type in ("float", "int"):
            d.update(min=p.min, max=p.max, type=p.type)
        elif p.type == "bool":
            d["type"] = "oui/non"
        elif p.type == "choice":
            d["choix"] = {c[0]: c[1] for c in p.choices}
        if p.help:
            d["aide"] = p.help
        out.append(d)
    return out


SYSTEM = """Tu règles une étape de traitement d'image d'astrophotographie à la demande de l'utilisateur.
Tu reçois la liste des réglages de l'étape (nom, libellé, valeur actuelle, bornes) et sa demande en français.
Réponds UNIQUEMENT par un objet JSON : {"reglages": {nom: valeur, ...}, "explication": "une phrase"}.
- Ne change que les réglages utiles à la demande, avec des pas modérés (comme dans les exemples).
- Une valeur numérique peut être relative, écrite en texte : "+0.1", "-3" (ajout à la valeur actuelle), ou absolue.
- Reste dans les bornes ; n'invente aucun réglage absent de la liste.
- Si la demande ne correspond à aucun réglage de cette étape, renvoie {"reglages": {}, "explication": "…"} en disant
  à quelle autre étape la demande correspond si tu le sais."""


def clean(step, vals, changes):
    """Ne garde que des réglages connus, affichés et dans leurs bornes ; renvoie (réglages, refusés)."""
    params = {p.name: p for p in step.params}
    ok, refus = {}, []
    for k, v in (changes or {}).items():
        p = params.get(k)
        if not p or not _visible(p, vals) or p.type in ("text", "textarea", "rect"):
            refus.append(k)
            continue
        if p.type in ("float", "int"):
            cur = vals.get(k, p.default)
            try:
                if isinstance(v, str) and re.match(r"^[+-]\d", v.strip()):
                    nv = float(cur) + float(v)
                else:
                    nv = float(v)
            except (TypeError, ValueError):
                refus.append(k)
                continue
            if p.min is not None:
                nv = max(p.min, nv)
            if p.max is not None:
                nv = min(p.max, nv)
            ok[k] = int(round(nv)) if p.type == "int" else round(nv, 4)
        elif p.type == "bool":
            ok[k] = v in (True, "true", "oui", 1, "1")
        elif p.type == "choice":
            keys = [c[0] for c in p.choices]
            if v in keys:
                ok[k] = v
            else:                            # le modèle écrit parfois le libellé affiché (« autoghs (noyau brillant) »)
                lab = {str(c[1]).lower(): c[0] for c in p.choices}
                hit = lab.get(str(v).lower()) or next((c[0] for c in p.choices if str(v).lower().startswith(c[0].lower())), None)
                if hit:
                    ok[k] = hit
                else:
                    refus.append(k)
        elif p.type == "color" and isinstance(v, str) and re.match(r"^#[0-9a-fA-F]{6}$", v):
            ok[k] = v
    return ok, refus


def prompt(step, vals, text):
    sch = schema(step, vals)
    names = {d["nom"] for d in sch}
    ex = "\n".join(f"- « {t} » -> {json.dumps({k: v for k, v in r.items() if k in names}, ensure_ascii=False)}"
                   for t, r in PHRASES.get(step.id, []) if any(k in names for k in r))
    return (f"Étape : {step.id} · {step.title}\n{step.help}\n\nRéglages :\n"
            + json.dumps(sch, ensure_ascii=False, indent=1)
            + (f"\n\nExemples de demandes et de réglages pour cette étape :\n{ex}" if ex else "")
            + f"\n\nDemande de l'utilisateur : « {text} »")


def choose_model(cfg, installed):
    """Modèle pour les phrases libres : réglage explicite, sinon gemma4 s'il est installé (14 phrases sur 16 justes
    au test du 1er novembre 2026, contre 12 pour qwen2.5:7b et 6 pour qwen3:4b), sinon le modèle par défaut."""
    if cfg.get("ollama_intent_model"):
        return cfg["ollama_intent_model"]
    g = next((m for m in installed or [] if m.startswith("gemma4")), None)
    return g or cfg.get("ollama_model") or ((installed or [""])[0])


def traduire(url, model, step, vals, text, timeout=180):
    from .report import ollama_chat
    txt = ollama_chat(url, model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(step, vals, text)}],
                      fmt="json", timeout=timeout)
    m = re.search(r"\{.*\}", txt, re.S)
    d = json.loads(m.group(0)) if m else {}
    reglages, refus = clean(step, vals, d.get("reglages") or {})
    return {"reglages": reglages, "explication": str(d.get("explication") or "").strip(), "refuses": refus}

"""Rapport chiffré d'une étape (à copier pour Claude, ou à donner à un modèle local Ollama pour un avis).

Le rapport ne contient que des faits mesurés : réglages de chaque variante, mesures, alertes des contrôles,
et le contexte du projet (cible, appareils, étapes déjà validées). Le modèle local ne voit pas les images :
ses conseils portent sur les chiffres, et l'appli le présente comme un avis indicatif.
"""
import json
import urllib.error
import urllib.request

from .steps import ORDER, STEP_MAP

SYSTEM = """Tu es l'assistant de contrôle d'un astrophotographe amateur (caméra couleur, traitement dans Siril).
On te donne le rapport chiffré d'UNE étape de traitement : réglages de chaque variante (A, B, C…), mesures et
alertes automatiques. Tu ne vois pas les images.

Règles :
- Appuie-toi uniquement sur les chiffres et alertes du rapport ; cite-les. N'invente aucune valeur.
- Explique en clair ce que signifient les alertes (lignes ATTENTION) et si elles sont graves ou bénignes.
- Dis quelle variante est techniquement la plus saine et pourquoi, mais rappelle que le choix esthétique revient
  à l'utilisateur (regarder le zoom).
- Si les chiffres ne permettent pas de trancher, dis-le et indique quoi regarder sur l'image.
- Réponds en français, en 10 lignes au plus, sans titre ni markdown lourd.

Repères :
- Fond du ciel neutre : médianes R/V/B à moins de ~25 ADU l'une de l'autre. Plus de 5 % de pixels à zéro = noir
  écrasé (signal faible perdu).
- Débruitage : le grain du fond doit baisser ; au-delà de -60 % risque d'aspect « plastique ».
- Mesure du stack : « Surface du champ par palier de S/N : < 1 72% » veut dire que 72 % du champ est sous S/N 1 :
  c'est le ciel sans nébuleuse, c'est normal, pas un défaut. Un écart de FWHM sur le champ vient de l'optique ou de la
  rotation de champ (coins du stack faits des bords du capteur) : il ne se corrige ni en refaisant le stack ni par
  « une autre variante » ; on le traite au cadrage (P0) et par BlurXTerminator (P3).
- Alignement entre appareils : écart résiduel < 1 px = bon ; échelle proche du rapport des échelles de pixel (focales et pixels).
- Combinaison d'appareils : un gain théorique sur le bruit inférieur à x1,10 est peu visible, alors que le stack
  agrandi adoucit les petits détails ; dans ce cas « principal seul » est souvent le meilleur choix.
- Écho d'étoiles : s'il existe déjà dans l'image de référence seule, c'est la forme des étoiles, pas un doublement.
- Étoiles : moins de ~10 % des pixels du calque au-dessus du plancher.
"""


# consignes propres à une étape (ajoutées au message système)
SYSTEM_ETAPE = {
    "S4": """Étape S4 (mesure du stack) : il n'y a rien à choisir entre variantes, n'en parle pas. Ton avis doit être une
DÉCISION, en trois points, chacun en une ou deux lignes :
1. Faut-il refaire des poses ? Reprends la ligne « VERDICT » du rapport (elle est calculée par l'appli) et explique-la
   avec les S/N de la nébulosité faible et moyenne et les temps donnés. Seuils : S/N 3 = visible mais bruité, 5 =
   correct, 10 = propre. Un temps marqué « irréaliste » veut dire : ne pas compter dessus.
2. Les étoiles : grave ou pas ? (alertes FWHM / excentricité et le conseil de l'appli qui suit ; une inclinaison ou
   une rotation de champ ne justifient pas de refaire des poses, sauf écart de FWHM au-delà de 60 %).
3. Le ciel : la ligne « Ciel mesuré » (mag/arcsec², Bortle) si elle existe ; s'il est clair (Bortle 6 et plus) et la
   nébulosité faible insuffisante, dis qu'un ciel plus noir rapporterait plus que des heures en plus.
Si une zone dessinée a un S/N sous 0,5, signale qu'elle est mal placée (presque du ciel vide).
Rappel : « < 1 89% » du champ sous S/N 1, c'est le ciel autour de l'objet, ni bon ni mauvais : ne le commente pas
comme une qualité.""",
}


def _model(p, d):
    from .steps.stacking import model
    try:
        return model(p, d)
    except Exception:
        return str(d)


def build(p, sid):
    step = STEP_MAP[sid]
    st = p.state["steps"].get(sid, {})
    L = [f"Projet : {p.state['target']} ({p.type}), appareil(s) : " +
         " + ".join(_model(p, d) for d in (p.state.get("devices") or [p.state.get("device", "")])),
         f"Mode filtres : {p.mode}",
         f"Étape : {step.id} — {step.title}",
         f"But de l'étape : {step.help.splitlines()[0][:400]}", ""]
    done = []
    for o in ORDER[:ORDER.index(sid)]:
        so = p.state["steps"].get(o, {})
        if so.get("status") == "done" and o not in ("S1", "S4"):
            done.append(STEP_MAP[o].notes(p, so).split("\n")[0])
    if done:
        L.append("Déjà validé avant :")
        L += [f"  - {l[:220]}" for l in done[-8:]]
        L.append("")
    variants = st.get("variants") or []
    if not variants:
        L.append("(aucune variante lancée pour cette étape)")
    for v in variants:
        prm = step.visible(v.get("params") or {})
        L.append(f"Variante {v.get('tag')} : " + ", ".join(f"{k}={str(x).replace(chr(10), ' ; ')}" for k, x in prm.items()))
        if v.get("error"):
            L.append(f"  ÉCHEC : {v['error']}")
            continue
        s = v.get("stats")
        if s:
            L.append(f"  mesures : médianes R/V/B {s['medianes']}, zéros {s['zeros_pct']} %, écrêtés {s['ecretes_pct']} %, "
                     f"taille {s['taille'][0]}x{s['taille'][1]}")
        from .remedies import remedy
        for line in v.get("info", [])[:60]:
            L.append(f"  {line}")
            if line.startswith("ATTENTION"):
                rm = remedy(p, sid, line)
                L.append(f"    → conseil de l'appli : {rm['conseil']}" + (f" [{rm['etape']}]" if rm["etape"] else ""))
        L.append("")
    if st.get("status") in ("done", "stale") and st.get("chosen") is not None:
        L.append(f"Variante actuellement validée : {variants[st['chosen']]['tag'] if st['chosen'] < len(variants) else '?'}")
    return "\n".join(L)


def ollama_models(url, timeout=3):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=timeout) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return None


def ollama_chat(url, model, messages, fmt=None, timeout=600):
    """Appel à Ollama pour nos demandes courtes. Mesuré chez l'utilisateur (bonsai-2:27b, RTX 5070) :
    - contexte limité (num_ctx, 8192 par défaut) : sans lui, Ollama réserve la mémoire du contexte maximal du
      modèle (256 000 jetons) : 27 Go au lieu de 8,5, la moitié hors carte graphique, 7 fois plus lent ;
    - réflexion coupée (think=false) : avec, plus de 8 minutes pour une fiche ; sans, 9 secondes ;
    - keep_alive 0 : le modèle libère la carte graphique tout de suite (Siril en a besoin)."""
    from . import config
    num_ctx = int(config.load().get("ollama_num_ctx") or 8192)
    base = {"model": model, "stream": False, "keep_alive": 0, "options": {"temperature": 0.2, "num_ctx": num_ctx},
            "messages": messages}
    if fmt:
        base["format"] = fmt
    for think in (False, None):                 # un modèle sans mode réflexion peut refuser le paramètre
        body = dict(base, **({"think": think} if think is not None else {}))
        req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            if think is not None and "think" in msg.lower():
                continue
            raise RuntimeError(f"Ollama a refusé la demande ({e.code}) : {msg[:200]}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama injoignable ({e.reason}) : est-il lancé ?")


def system_pour(sid=None):
    return SYSTEM + ("\n" + SYSTEM_ETAPE[sid] if sid in SYSTEM_ETAPE else "")


def ollama_advice(url, model, text, timeout=600, sid=None):
    return ollama_chat(url, model, [{"role": "system", "content": system_pour(sid)}, {"role": "user", "content": text}],
                       timeout=timeout)
"""Fiche PDF : champs remplis d'après les données (lieu, visibilité, phrases sur les images) et brouillon des textes
par un modèle Ollama local (à vérifier : un petit modèle sans internet se trompe facilement de date ou de distance)."""
import datetime
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONST_FR = {
    "Andromeda": "Andromède", "Antlia": "la Machine pneumatique", "Apus": "l'Oiseau de paradis", "Aquarius": "le Verseau",
    "Aquila": "l'Aigle", "Ara": "l'Autel", "Aries": "le Bélier", "Auriga": "le Cocher", "Bootes": "le Bouvier",
    "Caelum": "le Burin", "Camelopardalis": "la Girafe", "Cancer": "le Cancer", "Canes Venatici": "les Chiens de chasse",
    "Canis Major": "le Grand Chien", "Canis Minor": "le Petit Chien", "Capricornus": "le Capricorne", "Carina": "la Carène",
    "Cassiopeia": "Cassiopée", "Centaurus": "le Centaure", "Cepheus": "Céphée", "Cetus": "la Baleine",
    "Chamaeleon": "le Caméléon", "Circinus": "le Compas", "Columba": "la Colombe", "Coma Berenices": "la Chevelure de Bérénice",
    "Corona Australis": "la Couronne australe", "Corona Borealis": "la Couronne boréale", "Corvus": "le Corbeau",
    "Crater": "la Coupe", "Crux": "la Croix du Sud", "Cygnus": "le Cygne", "Delphinus": "le Dauphin", "Dorado": "la Dorade",
    "Draco": "le Dragon", "Equuleus": "le Petit Cheval", "Eridanus": "l'Éridan", "Fornax": "le Fourneau",
    "Gemini": "les Gémeaux", "Grus": "la Grue", "Hercules": "Hercule", "Horologium": "l'Horloge", "Hydra": "l'Hydre",
    "Hydrus": "l'Hydre mâle", "Indus": "l'Indien", "Lacerta": "le Lézard", "Leo": "le Lion", "Leo Minor": "le Petit Lion",
    "Lepus": "le Lièvre", "Libra": "la Balance", "Lupus": "le Loup", "Lynx": "le Lynx", "Lyra": "la Lyre",
    "Mensa": "la Table", "Microscopium": "le Microscope", "Monoceros": "la Licorne", "Musca": "la Mouche",
    "Norma": "la Règle", "Octans": "l'Octant", "Ophiuchus": "Ophiuchus", "Orion": "Orion", "Pavo": "le Paon",
    "Pegasus": "Pégase", "Perseus": "Persée", "Phoenix": "le Phénix", "Pictor": "le Peintre", "Pisces": "les Poissons",
    "Piscis Austrinus": "le Poisson austral", "Puppis": "la Poupe", "Pyxis": "la Boussole", "Reticulum": "le Réticule",
    "Sagitta": "la Flèche", "Sagittarius": "le Sagittaire", "Scorpius": "le Scorpion", "Sculptor": "le Sculpteur",
    "Scutum": "l'Écu de Sobieski", "Serpens": "le Serpent", "Sextans": "le Sextant", "Taurus": "le Taureau",
    "Telescopium": "le Télescope", "Triangulum": "le Triangle", "Triangulum Australe": "le Triangle austral",
    "Tucana": "le Toucan", "Ursa Major": "la Grande Ourse", "Ursa Minor": "la Petite Ourse", "Vela": "les Voiles",
    "Virgo": "la Vierge", "Volans": "le Poisson volant", "Vulpecula": "le Petit Renard",
}
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
CAT_RE = re.compile(r"^\s*(NGC|IC|M|C|Caldwell|Sh\s*2|LBN|LDN|Abell|Barnard|B|Cr|Mel|UGC|PGC|vdB|Ced|Arp|Hickson)[\s_-]*(\d+[A-Za-z]?)(?:[\s_-].*)?$", re.I)
CAT_CASE = {"ngc": "NGC", "ic": "IC", "m": "M", "c": "C", "caldwell": "Caldwell", "lbn": "LBN", "ldn": "LDN", "abell": "Abell",
            "barnard": "Barnard", "b": "B", "cr": "Cr", "mel": "Mel", "ugc": "UGC", "pgc": "PGC", "vdb": "vdB", "ced": "Ced",
            "arp": "Arp", "hickson": "Hickson"}


def catalog_name(txt):
    """« ngc281 » / « NGC_281 » / « Sh2-184 » -> « NGC 281 » / « Sh2-184 » ; None si ce n'est pas une désignation de catalogue."""
    m = CAT_RE.match(str(txt or ""))
    if not m:
        return None
    cat = re.sub(r"\s", "", m.group(1)).lower()
    if cat == "sh2":
        return f"Sh2-{m.group(2)}"
    if cat in ("m", "c"):                                  # usage : M31, C34
        return f"{cat.upper()}{m.group(2).upper()}"
    return f"{CAT_CASE.get(cat, m.group(1).upper())} {m.group(2).upper()}"


def technical_name(p):
    """Désignation de catalogue : en-tête OBJECT des poses, sinon nom du projet s'il en est une. "" si inconnue."""
    for cand in [s.get("object") for s in p.state.get("sessions", [])] + [p.state.get("target"), p.state.get("name")]:
        n = catalog_name(cand)
        if n:
            return n
    return ""


AUTO_KEYS = ("nom_technique", "lieu", "contexte", "visibilite", "intro_brut", "intro_finales")
OLLAMA_KEYS = ("nom_usuel", "taille", "catalogues", "decouverte", "nom", "nature", "anecdote")


def _num(v):
    """45.5 | "45.5" | "+45 30 00" | "45:30:00" -> degrés décimaux."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        pass
    m = re.findall(r"[-+]?\d+(?:\.\d+)?", str(v))
    if not m:
        return None
    d, mi, se = (float(x) for x in (m + ["0", "0"])[:3])
    sign = -1 if str(v).strip().startswith("-") else 1
    return sign * (abs(d) + mi / 60 + se / 3600)


def site(p):
    """Latitude, longitude du lieu de prise de vue (en-têtes SITELAT / SITELONG des poses)."""
    from astropy.io import fits
    from .inventory import lights_of
    for s in p.state.get("sessions", []):
        lat, lon = _num(s.get("lat")), _num(s.get("lon"))
        if lat is None and s.get("path"):
            try:
                files = lights_of(Path(s["path"]))
                h = fits.getheader(str(files[0])) if files else {}
                lat, lon = _num(h.get("SITELAT")), _num(h.get("SITELONG"))
            except Exception:
                pass
        if lat is not None and lon is not None and not (lat == 0 and lon == 0):
            return lat, lon
    return None, None


def place_name(lat, lon, timeout=8):
    """Ville et région (OpenStreetMap Nominatim, internet). None si injoignable."""
    q = urllib.parse.urlencode({"lat": f"{lat:.3f}", "lon": f"{lon:.3f}", "format": "jsonv2", "zoom": 10,
                                "accept-language": "fr"})
    req = urllib.request.Request("https://nominatim.openstreetmap.org/reverse?" + q,
                                 headers={"User-Agent": "AtelierAstro/1.0 (fiche d'observation)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            a = json.load(r).get("address", {})
    except Exception:
        return None
    ville = a.get("city") or a.get("town") or a.get("village") or a.get("municipality")
    region = a.get("state") or a.get("region") or a.get("county")
    parts = [x for x in (ville, region) if x]
    if not parts and a.get("country"):
        parts = [a["country"]]
    return ", ".join(parts) or None


def de(nom):
    """« le Cygne » -> « du Cygne », « Andromède » -> « d'Andromède »."""
    for a, b in (("le ", "du "), ("les ", "des "), ("la ", "de la "), ("l'", "de l'")):
        if nom.startswith(a):
            return b + nom[len(a):]
    return ("d'" if nom[0].lower() in "aeiouyéèêoôâ" else "de ") + nom


def constellation(ra, dec):
    try:
        from astropy.coordinates import SkyCoord, get_constellation
        import astropy.units as u
        lat = get_constellation(SkyCoord(ra * u.deg, dec * u.deg))
        return CONST_FR.get(lat, lat)
    except Exception:
        return None


def visibility(target, ra, dec, lat, lieu=""):
    """Hauteur maximale au-dessus de l'horizon et mois où l'objet passe au méridien vers minuit (calcul, pas de recherche)."""
    if ra is None or dec is None or lat is None:
        return ""
    alt = 90 - abs(lat - dec)
    where = f"Depuis {lieu}" if lieu else f"Depuis le lieu de prise de vue (latitude {lat:.0f}°)"
    target = target or "cet objet"
    if alt <= 0:
        return f"{where}, {target} ne se lève jamais au-dessus de l'horizon."
    # le Soleil est à l'opposé (AD + 180°) quand l'objet culmine à minuit ; AD du Soleil ≈ 0° vers le 20 mars
    day = (80 + ((ra + 180) % 360) / 0.9856) % 365.25
    m = (datetime.date(2025, 1, 1) + datetime.timedelta(days=int(day))).month - 1
    side = "au sud" if dec < lat else "au nord"
    txt = (f"{where}, {target} culmine à environ {alt:.0f}° au-dessus de l'horizon, {side}. Elle passe au méridien vers "
           f"minuit en {MOIS[m]} : la meilleure période va de {MOIS[(m - 1) % 12]} à {MOIS[(m + 1) % 12]}.")
    if dec > 90 - abs(lat) and lat > 0:
        txt += " Elle est circumpolaire : elle ne se couche jamais à cette latitude."
    elif alt < 25:
        txt += " Elle reste basse sur l'horizon : un horizon dégagé et une nuit sans brume sont nécessaires."
    return txt


def auto_fields(p, network=True):
    """Champs déduits des données. Résultat gardé dans le projet (pas de requête internet à chaque affichage)."""
    from .steps.export import tech_facts
    from .steps import STEP_MAP
    cache = p.state.get("fiche_auto") or {}
    tf = tech_facts(p)
    tn = technical_name(p)
    T, t = (tn, tn) if tn else ("Cet objet", "cet objet")     # jamais le nom du dossier (« data »…) dans les textes
    lat, lon = site(p)
    out = {"nom_technique": tn} if tn else {}
    if "lieu" in cache:
        out["lieu"] = cache["lieu"]
    elif lat is not None and network:
        out["lieu"] = place_name(lat, lon) or ""
        cache["lieu"] = out["lieu"]
    ra, dec = tf.get("ra"), tf.get("dec")
    const = constellation(ra, dec) if ra is not None else None
    if const:
        cache["constellation"] = const
        out["contexte"] = (f"{T} se trouve dans la constellation {de(const)}, aux coordonnées {tf['centre'].replace('·', ',')} "
                           "(J2000).")
    vis = visibility(t, ra, dec, lat, out.get("lieu", ""))
    if vis:
        out["visibilite"] = vis
    if tf.get("poses"):
        out["intro_brut"] = (f"Voici l'empilement brut : {tf.get('integration') or '?'} d'intégration (poses : {tf['poses']}). "
                             "Il est seulement recadré et étiré automatiquement, sans aucun autre traitement : c'est le point "
                             "de départ de tout le travail.")
    st = p.state["steps"]
    col = []
    for sid in ("P8", "P8F"):
        if st.get(sid, {}).get("status") == "done":
            col.append(STEP_MAP[sid].notes(p, st[sid]).split(" : ", 1)[-1])
    out["intro_finales"] = ("Les deux versions partagent le même traitement (fond, calibration des couleurs, netteté, débruitage, "
                            "étirement). La version naturelle garde les couleurs mesurées ; la version colorisée ajoute "
                            + ("; ".join(col) if col else "un renfort de couleur") + ".")
    p.state["fiche_auto"] = cache
    return out


FIELDS_DOC = """nom_usuel (nom courant de l'objet ; "" s'il n'en a pas),
taille (taille apparente en minutes d'arc),
catalogues (autres désignations de catalogue),
decouverte (2 à 3 phrases : qui, quand, avec quel instrument),
nom (2 phrases : origine du nom courant),
nature (2 à 4 phrases : nature physique, distance en années-lumière, taille réelle),
anecdote (2 à 3 phrases : un fait marquant sur l'objet lui-même, pas sur l'astronomie en général)"""

# Pas d'exemple concret dans la consigne : testé chez l'utilisateur, bonsai-2 recopiait « Sh2-184, LBN 616 »
# (l'exemple du Pacman) dans les catalogues de NGC 6960 et de NGC 7000.
SYSTEM = ("Tu rédiges, en français, les textes d'une fiche d'observation astronomique pour un astrophotographe amateur.\n"
          "Réponds UNIQUEMENT par un objet JSON avec ces clés (valeurs = chaînes) :\n" + FIELDS_DOC + "\n"
          "Règles : n'invente rien. Si tu n'es pas sûr d'un fait (date, nom, distance), mets \"\" pour cette clé plutôt "
          "que de deviner. Si tu ne reconnais pas l'objet avec certitude, laisse toutes les clés vides. "
          "Pas de sources, pas de liens, pas de markdown. Phrases simples, ton de vulgarisation.")


def facts_lines(p):
    from .steps.export import tech_facts
    tf = tech_facts(p)
    cache = p.state.get("fiche_auto") or {}
    tn = technical_name(p)
    out = [f"Objet : {tn}" if tn else "Objet : désignation inconnue (identifier d'après les coordonnées et le type)",
           f"Type : {p.type}"]
    if tf.get("centre"):
        out.append(f"Coordonnées J2000 (centre de l'image) : {tf['centre']}")
    if cache.get("constellation"):
        out.append(f"Constellation : {cache['constellation']}")
    return out


def claude_prompt(p):
    """Demande à coller dans une conversation avec Claude (recherche web, faits sourcés) ; la réponse JSON se
    colle ensuite dans la page de la fiche."""
    return ("Prépare les textes d'une fiche d'observation pour une astrophotographie que j'ai faite.\n"
            + "\n".join(facts_lines(p)) + "\n\n"
            "Fais une recherche sur le web et vérifie chaque fait (dates, découvreur, instrument, distance, taille) dans "
            "des sources fiables. Réponds en français, avec à la fin un objet JSON (et rien après) contenant ces clés, "
            "valeurs = chaînes :\n" + FIELDS_DOC + ",\nnom_technique (désignation principale, ex. de la forme NGC 1234),\n"
            "sources (liste courte des sources utilisées, une par ligne).\n"
            "Une ligne vide sépare deux paragraphes dans une valeur. Si un fait n'est pas établi, laisse la clé vide.")


def parse_answer(txt):
    """Réponse collée (JSON seul, ou texte terminé par un objet JSON) -> champs de la fiche."""
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        raise ValueError("aucun objet JSON trouvé dans la réponse collée")
    d = json.loads(m.group(0))
    keys = OLLAMA_KEYS + ("nom_technique", "sources")
    return {k: str(d.get(k) or "").strip() for k in keys if str(d.get(k) or "").strip()}


def ollama_fields(url, model, p, timeout=600):
    from .steps.export import tech_facts
    tf = tech_facts(p)
    cache = p.state.get("fiche_auto") or {}
    tn = technical_name(p)
    facts = [f"Objet : {tn}" if tn else
             "Objet : désignation inconnue (le dossier porte un nom sans rapport) : identifie l'objet d'après les "
             "coordonnées et le type, et donne sa désignation principale en premier dans « catalogues »",
             f"Type : {p.type}"]
    if tf.get("centre"):
        facts.append(f"Coordonnées J2000 : {tf['centre']}")
    if cache.get("constellation"):
        facts.append(f"Constellation : {cache['constellation']}")
    from .report import ollama_chat
    txt = ollama_chat(url, model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(facts)}],
                      fmt="json", timeout=timeout)
    try:
        d = json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            raise RuntimeError(f"{model} n'a pas répondu au format attendu : réessayer ou choisir un autre modèle")
        d = json.loads(m.group(0))
    out = {k: str(d.get(k) or "").strip() for k in OLLAMA_KEYS}
    if not tn and out["catalogues"]:
        out["nom_technique"] = catalog_name(re.split(r"[,;/]", out["catalogues"])[0]) or re.split(r"[,;/]", out["catalogues"])[0].strip()
    return out, time.strftime("%Y-%m-%d %H:%M")

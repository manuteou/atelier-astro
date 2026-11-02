"""Lieux d'observation : classe de Bortle retenue par lieu (config « sites »), lien vers la carte de pollution
lumineuse, conversion d'une luminosité du ciel mesurée (mag/arcsec²) en classe de Bortle approximative."""
import math

from . import config

RAYON_KM = 5.0          # deux sessions à moins de 5 km : même lieu

# luminosité du ciel au zénith (mag/arcsec², type SQM) -> classe de Bortle : bornes basses usuelles, approximatives
SQM_BORTLE = ((21.75, 1), (21.6, 2), (21.3, 3), (20.8, 4), (20.3, 5), (19.25, 6), (18.5, 7), (18.0, 8))


def position(p):
    """(lat, lon) de la première session qui en a (en-têtes SITELAT / SITELONG), sinon None."""
    for s in p.state.get("sessions", []):
        try:
            lat, lon = float(s.get("lat")), float(s.get("lon"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(lat) and math.isfinite(lon) and (lat, lon) != (0.0, 0.0):
            return lat, lon
    return None


def distance_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(min(1.0, math.sqrt(h)))


def connu(pos):
    """Lieu déjà enregistré à moins de RAYON_KM : dict {lat, lon, bortle}, sinon None."""
    if not pos:
        return None
    best = None
    for s in config.load().get("sites") or []:
        try:
            d = distance_km(pos, (float(s["lat"]), float(s["lon"])))
        except (KeyError, TypeError, ValueError):
            continue
        if d <= RAYON_KM and (best is None or d < best[0]):
            best = (d, s)
    return best[1] if best else None


def enregistrer(pos, bortle):
    """Retient la classe de Bortle de ce lieu (met à jour le lieu proche s'il existe)."""
    if not pos or not bortle:
        return
    cfg = config.load()
    sites = list(cfg.get("sites") or [])
    for s in sites:
        try:
            if distance_km(pos, (float(s["lat"]), float(s["lon"]))) <= RAYON_KM:
                s["bortle"] = int(bortle)
                break
        except (KeyError, TypeError, ValueError):
            continue
    else:
        sites.append({"lat": round(pos[0], 4), "lon": round(pos[1], 4), "bortle": int(bortle)})
    config.set_value("sites", sites)


def carte_url(pos):
    return f"https://www.lightpollutionmap.info/#zoom=10&lat={pos[0]:.4f}&lon={pos[1]:.4f}" if pos else ""


def bortle_de_sqm(m):
    for borne, b in SQM_BORTLE:
        if m >= borne:
            return b
    return 9

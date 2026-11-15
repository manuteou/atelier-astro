"""Ciel des prochaines nuits : couverture nuageuse pendant la nuit noire, Lune, vent, risque de buée, et prochain soir
favorable pour une prise de vue.

Prévisions : Open-Meteo (gratuit, sans compte), pour la ville saisie dans Réglages (géocodée par le même service) ou,
à défaut, pour le dernier lieu d'observation connu de l'appli. Le Soleil et la Lune sont calculés sur place (app.ciel).
Une nuit = les heures où le Soleil est sous -18° (nuit astronomique), rattachées au soir où elles commencent.
La note ne juge que ce qui est prévisible : ciel dégagé, durée, Lune, vent, buée. Ni turbulence ni transparence.
Fiabilité : bonne à 2-3 jours, simple tendance au-delà (marquée comme telle)."""
import json
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ciel, config

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
PREVISION = "https://api.open-meteo.com/v1/forecast"
CHAMPS = ("cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,wind_gusts_10m,relative_humidity_2m,"
          "temperature_2m,dew_point_2m,precipitation_probability")
DEGAGE = 25               # % de nuages au plus pour qu'une heure compte comme dégagée
JOURS_FIABLES = 3         # au-delà : tendance
_CACHE = {}


def _get(url, params, timeout=20):
    with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def geocoder(ville):
    """(nom affiché, lat, lon) d'une ville ; « Buc, Yvelines » ou « Buc 78 » précisent en cas d'homonymes."""
    ville = str(ville or "").strip()[:80]
    if not ville:
        raise ValueError("aucune ville indiquée")
    nom, _, precision = ville.partition(",")
    d = _get(GEOCODE, {"name": nom.strip(), "count": 10, "language": "fr"})
    res = d.get("results") or []
    if not res:
        raise ValueError(f"ville introuvable : {ville}")
    exacts = [r for r in res if str(r.get("name") or "").lower() == nom.strip().lower()]
    res = exacts or res                               # « Buc » : la commune de ce nom avant Bucarest
    pr = precision.strip().lower()
    if pr:
        for r in res:
            if any(pr in str(r.get(k) or "").lower() for k in ("admin1", "admin2", "admin3", "country", "country_code")) \
                    or any(str(c).startswith(pr) for c in r.get("postcodes") or []):
                res = [r]
                break
    r = res[0]
    lieu = ", ".join(x for x in (r.get("name"), r.get("admin2") or r.get("admin1"), r.get("country")) if x)
    return lieu, float(r["latitude"]), float(r["longitude"])


def lieu():
    """(nom, lat, lon, origine) : la ville des Réglages, sinon le dernier lieu d'observation connu."""
    cfg = config.load()
    ville = str(cfg.get("meteo_ville") or "").strip()
    if ville:
        k = ("geo", ville.lower())
        if k not in _CACHE:
            _CACHE[k] = geocoder(ville)
        return (*_CACHE[k], "ville des Réglages")
    sites = cfg.get("sites") or []
    if sites:
        s = sites[-1]
        return f"lieu d'observation ({float(s['lat']):.2f}°, {float(s['lon']):.2f}°)", float(s["lat"]), float(s["lon"]), \
            "dernier lieu d'observation connu"
    raise ValueError("indique ta ville dans Réglages (« Ville pour les prévisions du ciel »)")


def previsions(lat, lon):
    f = os.environ.get("ATELIER_METEO")               # tests et usage hors ligne : réponse enregistrée
    if f:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    k = ("prev", round(lat, 2), round(lon, 2))
    if k not in _CACHE or time.time() - _CACHE[k][0] > 3600:
        _CACHE[k] = (time.time(), _get(PREVISION, {"latitude": round(lat, 4), "longitude": round(lon, 4), "hourly": CHAMPS,
                                                   "forecast_days": 8, "timezone": "auto"}))
    return _CACHE[k][1]


def lune_eclairee(jd):
    """Fraction éclairée de la Lune (0-1), d'après son écart angulaire au Soleil."""
    ra1, d1 = (math.radians(v) for v in ciel._soleil(jd))
    ra2, d2 = (math.radians(v) for v in ciel._lune(jd))
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(ra1 - ra2)
    return (1 - max(-1.0, min(1.0, c))) / 2


JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def nuits(data, lat, lon, maintenant=None):
    """Liste des nuits à venir, notées. data : réponse Open-Meteo (heures locales + utc_offset_seconds)."""
    off = timedelta(seconds=int(data.get("utc_offset_seconds") or 0))
    H = data["hourly"]
    maintenant = maintenant or datetime.now(timezone.utc)
    par_nuit = {}
    for i, ts in enumerate(H["time"]):
        loc = datetime.fromisoformat(ts)
        utc = (loc - off).replace(tzinfo=timezone.utc)
        jd = ciel._jd(utc + timedelta(minutes=30))          # l'heure compte si son milieu est en nuit noire
        if ciel._hauteur(*ciel._soleil(jd), lat, lon, jd) > -18 or utc + timedelta(hours=1) <= maintenant:
            continue
        nuage = H["cloud_cover"][i]
        if nuage is None:
            continue
        par_nuit.setdefault((loc - timedelta(hours=12)).date(), []).append({
            "heure": loc, "nuages": float(nuage), "hauts": float(H["cloud_cover_high"][i] or 0),
            "rafales": float(H["wind_gusts_10m"][i] or 0), "pluie": float(H["precipitation_probability"][i] or 0),
            "ecart_rosee": float(H["temperature_2m"][i] - H["dew_point_2m"][i]),
            "lune": ciel._hauteur(*ciel._lune(jd), lat, lon, jd), "lune_pct": lune_eclairee(jd) * 100})
    out = []
    aujourd_hui = ((maintenant + off).replace(tzinfo=None) - timedelta(hours=12)).date()     # la nuit en cours compte
    for jour in sorted(par_nuit):
        hs = par_nuit[jour]
        if len(hs) < 2:
            continue
        # plus longue plage d'heures consécutives dégagées et sans pluie probable
        best, cur = [], []
        for h in hs:
            if h["nuages"] <= DEGAGE and h["pluie"] < 30 and (not cur or h["heure"] - cur[-1]["heure"] == timedelta(hours=1)):
                cur.append(h)
            else:
                cur = [h] if h["nuages"] <= DEGAGE and h["pluie"] < 30 else []
            if len(cur) > len(best):
                best = list(cur)
        ref = best or hs
        moy = sum(h["nuages"] for h in hs) / len(hs)
        lune_pct = sum(h["lune_pct"] for h in hs) / len(hs)
        lune_gene = sum(1 for h in ref if h["lune"] > 0) / len(ref) * lune_pct / 100       # 0 (absente) à 1 (pleine, toute la plage)
        rafales = max(h["rafales"] for h in ref)
        rosee = min(h["ecart_rosee"] for h in ref)
        note = (min(len(best), 6) / 6 * 70 + (100 - moy) / 100 * 10 + (1 - lune_gene) * 10
                + 5 * max(0.0, min(1.0, (45 - rafales) / 20)) + 5 * max(0.0, min(1.0, rosee / 2.5)))
        if not best:
            note = min(note, 25)
        rang = (jour - aujourd_hui).days
        details = []
        if best:
            fin = best[-1]["heure"] + timedelta(hours=1)
            details.append(f"dégagé de {best[0]['heure']:%H h} à {fin:%H h} ({len(best)} h)")
        else:
            details.append("pas d'heure dégagée")
        haut = sum(h["hauts"] for h in hs) / len(hs)
        if moy <= DEGAGE and haut > 40:
            details.append("voile d'altitude possible")
        if lune_pct < 8:
            details.append("pas de Lune")
        else:
            lev = sum(1 for h in ref if h["lune"] > 0)
            details.append(f"Lune {lune_pct:.0f} %" + (", couchée pendant la plage" if lev == 0 else
                                                        f", levée {lev} h sur {len(ref)}"))
        if rafales >= 35:
            details.append(f"rafales {rafales:.0f} km/h")
        if rosee < 1.5:
            details.append("buée probable (pare-buée conseillé)")
        out.append({"date": jour.isoformat(), "jour": ("ce soir" if rang == 0 else "demain soir" if rang == 1 else
                                                         f"{JOURS[jour.weekday()]} {jour.day}"),
                    "nuages": round(moy), "heures_nuit": len(hs), "heures_degagees": len(best),
                    "debut": f"{best[0]['heure']:%H:%M}" if best else None,
                    "fin": f"{best[-1]['heure'] + timedelta(hours=1):%H:%M}" if best else None,
                    "lune_pct": round(lune_pct), "rafales": round(rafales), "note": round(note),
                    "avis": "favorable" if note >= 75 else "possible" if note >= 50 else "défavorable",
                    "tendance": rang >= JOURS_FIABLES, "details": details,
                    "heures": [{"h": f"{h['heure']:%H}", "nuages": round(h["nuages"])} for h in hs]})
    return out


def prochain_soir(ns):
    """Le prochain soir favorable ; à défaut le meilleur soir « possible » ; sinon None."""
    for n in ns:
        if n["avis"] == "favorable":
            return {**n, "choix": "favorable"}
    possibles = [n for n in ns if n["avis"] == "possible"]
    return {**max(possibles, key=lambda n: n["note"]), "choix": "possible"} if possibles else None


def ciel_a_venir():
    nom, lat, lon, origine = lieu()
    ns = nuits(previsions(lat, lon), lat, lon)
    return {"lieu": nom, "origine": origine, "nuits": ns, "prochain": prochain_soir(ns),
            "source": "Open-Meteo", "maj": f"{datetime.now():%H:%M}"}

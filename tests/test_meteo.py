"""Ciel des prochaines nuits (app/meteo.py) sur des prévisions fabriquées : nuit noire, plage dégagée, Lune, note,
prochain soir favorable, tendance au-delà de 3 jours ; route /api/meteo sans Internet (ATELIER_METEO).
Lancer : python tests/test_meteo.py"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import meteo  # noqa: E402

LAT, LON = 48.78, 2.13
t0 = datetime(2026, 11, 15, 0, 0)                      # heure locale (UTC+1), 8 jours
heures = [t0 + timedelta(hours=i) for i in range(8 * 24)]


def nuage(t):
    nuit = (t - timedelta(hours=12)).date().day        # soir auquel l'heure appartient
    if nuit == 15:
        return 95                                      # ce soir : couvert
    if nuit == 16:
        return 4 if 22 <= t.hour or t.hour < 1 else (3 if t.hour == 4 else 80)    # demain : créneaux de 3 h et de 1 h
    if nuit == 17:
        return 5                                       # mardi : dégagé toute la nuit
    if nuit == 19:
        return 0                                       # jeudi : dégagé, mais à plus de 3 jours
    return 70


data = {"utc_offset_seconds": 3600, "hourly": {
    "time": [t.strftime("%Y-%m-%dT%H:%M") for t in heures],
    "cloud_cover": [nuage(t) for t in heures], "cloud_cover_low": [0] * len(heures), "cloud_cover_mid": [0] * len(heures),
    "cloud_cover_high": [0] * len(heures), "wind_gusts_10m": [15] * len(heures), "relative_humidity_2m": [70] * len(heures),
    "temperature_2m": [8] * len(heures), "dew_point_2m": [3] * len(heures), "precipitation_probability": [0] * len(heures)}}
maintenant = datetime(2026, 11, 15, 11, 0, tzinfo=timezone.utc)          # dimanche midi, heure locale
ns = {n["date"]: n for n in meteo.nuits(data, LAT, LON, maintenant)}
for n in ns.values():
    print(f"  {n['jour']:12s} note {n['note']:3d} {n['avis']:12s} {n['nuages']:3d} % · {' · '.join(n['details'])}")
a, b, c, d = ns["2026-11-15"], ns["2026-11-16"], ns["2026-11-17"], ns["2026-11-19"]
assert a["jour"] == "ce soir" and b["jour"] == "demain soir" and c["jour"] == "mardi 17", (a["jour"], b["jour"], c["jour"])
assert 10 <= a["heures_nuit"] <= 12, "nuit astronomique de mi-novembre à Paris : 11 à 12 h"
assert a["avis"] == "défavorable" and a["heures_degagees"] == 0 and a["nuages"] == 95
assert b["heures_degagees"] == 3 and (b["debut"], b["fin"]) == ("22:00", "01:00") and b["avis"] != "favorable", b
assert b["heures_observables"] == 4 and [(x["debut"], x["fin"], x["heures"]) for x in b["creneaux"]] == \
    [("22:00", "01:00", 3), ("04:00", "05:00", 1)], b["creneaux"]
assert "4 h observables : 22 h–01 h (3 h), 04 h–05 h (1 h)" in b["details"][0], b["details"]
# seuil : 5 % par défaut (ciel dégagé à 95 %) ; à 6 % de nuages l'heure ne compte pas, sauf seuil relevé
d6 = {**data, "hourly": {**data["hourly"], "cloud_cover": [6] * len(heures)}}
assert all(n["heures_observables"] == 0 for n in meteo.nuits(d6, LAT, LON, maintenant))
assert all(n["heures_observables"] == n["heures_nuit"] for n in meteo.nuits(d6, LAT, LON, maintenant, degage=10))
assert c["avis"] == "favorable" and c["heures_degagees"] == c["heures_nuit"] and not c["tendance"], c
assert d["avis"] == "favorable" and d["tendance"], "à plus de 3 jours : tendance"
p = meteo.prochain_soir(list(ns.values()))
assert p["date"] == "2026-11-17" and p["choix"] == "favorable", p
sans = [n for n in ns.values() if n["avis"] == "défavorable"]
assert meteo.prochain_soir(sans) is None
# Lune : nouvelle le 9 novembre 2026, pleine le 24 : la fraction éclairée croît sur la période
l15, l22 = ns["2026-11-15"]["lune_pct"], ns["2026-11-21"]["lune_pct"]
assert 20 < l15 < 55 and l22 > 80, (l15, l22)
# la nuit en cours compte encore après minuit, amputée des heures passées
n2 = meteo.nuits(data, LAT, LON, datetime(2026, 11, 18, 1, 30, tzinfo=timezone.utc))
assert n2[0]["date"] == "2026-11-17" and n2[0]["jour"] == "ce soir" and n2[0]["heures_nuit"] < c["heures_nuit"], n2[0]

# route sans Internet
f = Path(tempfile.mkdtemp()) / "meteo.json"
f.write_text(json.dumps(data))
os.environ["ATELIER_METEO"] = str(f)
from app import config  # noqa: E402
config.load = lambda: {**config.DEFAULTS, "meteo_ville": "", "sites": [{"lat": LAT, "lon": LON, "bortle": 7}]}
r = meteo.ciel_a_venir()
assert r["origine"] == "dernier lieu d'observation connu" and len(r["nuits"]) >= 1, r["origine"]
config.load = lambda: {**config.DEFAULTS, "meteo_ville": "", "sites": []}
try:
    meteo.ciel_a_venir()
    raise AssertionError("sans ville ni lieu connu : doit demander la ville")
except ValueError as e:
    assert "Réglages" in str(e)
print("OK")

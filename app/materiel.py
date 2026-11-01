"""Fiches du matériel : un appareil = un instrument (INSTRUME / TELESCOP des poses) à une focale donnée.

Rien n'est propre à une marque : la fiche est créée d'après les en-têtes FITS la première fois qu'un appareil est vu,
puis tu la corriges dans « Matériel » (nom affiché, ouverture, capteur pour la calibration des couleurs…).
Les Seestar ont des valeurs connues, reprises par défaut.
"""
from . import config

CONNUS = {
    "S50": {"nom": "ZWO Seestar S50", "focale": 250, "ouverture": 50, "pixel": 2.9,
            "capteur_spcc": "ZWO Seestar S50", "filtre_spcc": "UV/IR Block", "correction": "aucune"},
    "S30": {"nom": "ZWO Seestar S30", "focale": 150, "ouverture": 30, "pixel": 2.9,
            "capteur_spcc": "ZWO Seestar S50", "filtre_spcc": "UV/IR Block", "correction": "aucune"},
}
CHAMPS = [
    ("nom", "Nom affiché (fiche, notes)", "text"),
    ("focale", "Focale (mm)", "float"),
    ("ouverture", "Ouverture (mm)", "float"),
    ("pixel", "Taille des pixels (µm)", "float"),
    ("capteur_spcc", "Capteur pour SPCC (nom dans la base de Siril ; vide = calibration photométrique PCC)", "text"),
    ("filtre_spcc", "Filtre large bande pour SPCC (nom dans la base de Siril)", "text"),
    ("correction", "Correction de couleur après SPCC", "choice"),
]
CORRECTIONS = [["aucune", "Aucune"], ["s50pro", "Seestar S50 Pro, capteur OS08B10 (rouge x1.128, bleu x1.041)"]]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def defaults_for(dev, sample=None):
    """Fiche par défaut d'un appareil, complétée par une session de cet appareil (instrument, focale, pixel)."""
    sample = sample or {}
    d = dict(CONNUS.get(dev, {}))
    if not d:
        inst = str(sample.get("instrument") or "").strip()
        f = _num(sample.get("focal"))
        d = {"nom": (inst or dev) + (f" @ {f:.0f} mm" if f else ""), "focale": f, "ouverture": None,
             "pixel": _num(sample.get("pixel")), "capteur_spcc": "", "filtre_spcc": "UV/IR Block", "correction": "aucune"}
    return d


def profile(dev, cfg=None, sample=None, p=None):
    cfg = cfg or config.load()
    out = defaults_for(dev, sample)
    out.update({k: v for k, v in (cfg.get("materiel") or {}).get(dev, {}).items() if v not in (None, "")})
    # anciens projets : modèle choisi à l'inventaire (« S50 Pro »)
    if p is not None and dev not in (cfg.get("materiel") or {}):
        old = (p.state.get("models") or {}).get(dev)
        if old in ("S50 Pro", "S30 Pro"):
            out["nom"] = f"ZWO Seestar {old}"
            if old == "S50 Pro":
                out["correction"] = "s50pro"
    return out


def name(p, dev):
    return profile(dev, p=p, sample=_sample(p, dev))["nom"]


def _sample(p, dev):
    for s in p.state.get("sessions", []):
        if s.get("device") == dev:
            return s
    return None


def seen(p):
    """Appareils du projet : {clé: fiche}, et la liste de ceux qui n'ont pas encore de fiche enregistrée."""
    cfg = config.load()
    devs = []
    for s in p.state.get("sessions", []):
        d = s.get("device") or "inconnu"
        if d not in devs:
            devs.append(d)
    known = cfg.get("materiel") or {}
    return {d: profile(d, cfg, _sample(p, d), p) for d in devs}, [d for d in devs if d not in known]


def save_profiles(data):
    cfg = config.load()
    m = dict(cfg.get("materiel") or {})
    for dev, prof in (data or {}).items():
        clean = {}
        for k, _, t in CHAMPS:
            if k in prof:
                v = prof[k]
                clean[k] = _num(v) if t == "float" else str(v or "").strip()
        m[dev] = clean
    cfg["materiel"] = m
    config.save(cfg)
    return m


def pixel_scale(prof):
    """Échelle en secondes d'arc par pixel (focale + pixel) ; None si inconnue."""
    f, px = _num(prof.get("focale")), _num(prof.get("pixel"))
    return 206.265 * px / f if f and px else None

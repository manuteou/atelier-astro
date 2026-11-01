"""Outils de traitement au choix, fonction par fonction (Réglages > Outils).

Chaque fonction (fond, netteté, débruitage, étoiles) peut être faite par RC Astro, GraXpert, les outils intégrés à
Siril, une commande Siril personnalisée, ou pas du tout (l'étape est alors sans objet). Les commandes renvoyées sont
exécutées entre « load » et « save » de l'image (lineaire.tool).
"""

FONCTIONS = {
    "fond": {"label": "Extraction du fond", "choix": [
        ["graxpert", "GraXpert (IA)"], ["siril", "Siril intégré (subsky RBF)"], ["perso", "Commande personnalisée"],
        ["aucun", "Aucun : étape passée"]]},
    "nettete": {"label": "Netteté (déconvolution)", "choix": [
        ["rcastro", "BlurXTerminator (RC Astro)"], ["siril", "Siril intégré (déconvolution Richardson-Lucy)"],
        ["perso", "Commande personnalisée"], ["aucun", "Aucun : étape passée"]]},
    "debruitage": {"label": "Débruitage", "choix": [
        ["rcastro", "NoiseXTerminator (RC Astro)"], ["graxpert", "GraXpert (IA, débruitage)"],
        ["siril", "Siril intégré (denoise)"], ["perso", "Commande personnalisée"], ["aucun", "Aucun : étape passée"]]},
    "etoiles": {"label": "Séparation des étoiles", "choix": [
        ["rcastro", "StarXTerminator (RC Astro)"], ["starnet", "StarNet (via Siril, StarNet installé)"],
        ["perso", "Commande personnalisée"], ["aucun", "Aucun : étoiles gardées dans l'image"]]},
}
NOMS = {f: dict(v["choix"]) for f, v in FONCTIONS.items()}
COURT = {"rcastro": {"nettete": "BlurXTerminator", "debruitage": "NoiseXTerminator", "etoiles": "StarXTerminator"},
         "graxpert": {"fond": "GraXpert", "debruitage": "GraXpert"}, "siril": {"fond": "Siril subsky", "nettete": "Siril (RL)",
         "debruitage": "Siril denoise"}, "starnet": {"etoiles": "StarNet"}, "perso": {}}


def choix(cfg, fonction):
    v = (cfg.get("outils") or {}).get(fonction)
    ok = [c[0] for c in FONCTIONS[fonction]["choix"]]
    if v in ok:
        return v
    return {"fond": "graxpert", "nettete": "rcastro", "debruitage": "rcastro", "etoiles": "rcastro"}[fonction]


def nom(cfg, fonction):
    c = choix(cfg, fonction)
    return COURT.get(c, {}).get(fonction) or NOMS[fonction][c]


def actif(cfg, fonction):
    return choix(cfg, fonction) != "aucun"


def sans_objet(cfg, fonction):
    """(applique, raison) pour Step.applies."""
    if actif(cfg, fonction):
        return True, ""
    return False, f"aucun outil choisi pour « {FONCTIONS[fonction]['label']} » (Réglages > Outils)"


def commandes(cfg, fonction, force=None, **kw):
    """Lignes Siril à exécuter sur l'image chargée. force : smoothing (fond), sn (netteté), dn (débruitage)."""
    c = choix(cfg, fonction)
    if c == "aucun":
        return []
    if c == "perso":
        tpl = (cfg.get("outils_perso") or {}).get(fonction, "").strip()
        if not tpl:
            raise ValueError(f"commande personnalisée vide pour « {FONCTIONS[fonction]['label']} » (Réglages > Outils)")
        vals = {"force": force if force is not None else "", **kw}
        return [l.strip().format(**vals) for l in tpl.replace(";", "\n").splitlines() if l.strip()]
    if fonction == "fond":
        sm = 1.0 if force is None else force
        if c == "graxpert":
            return [f'pyscript "{cfg["script_graxpert"]}" -bge -correction subtraction -smoothing {sm}']
        return [f"subsky -rbf -samples=20 -tolerance=1.0 -smooth={max(0.0, min(1.0, float(sm))):.2f}"]
    if fonction == "nettete":
        sn = 0.75 if force is None else force
        if c == "rcastro":
            ss = kw.get("ss", 0.4)
            return [f'pyscript "{cfg["script_bxt"]}" --sn {sn}' + (" --ansp" if kw.get("ansp", True) else "") + f" --ss {ss}"]
        iters = int(kw.get("iters") or round(5 + 15 * float(sn)))
        return ["makepsf stars -sym", f"rl -iters={iters}"]
    if fonction == "debruitage":
        dn = 0.8 if force is None else force
        if c == "rcastro":
            return [f'pyscript "{cfg["script_nxt"]}" --dn {dn}']
        if c == "graxpert":
            return [f'pyscript "{cfg["script_graxpert"]}" -denoise -strength {dn}']
        return [f"denoise -mod={max(0.0, min(1.0, float(dn))):.2f}"]
    if fonction == "etoiles":
        if c == "rcastro":
            return [f'pyscript "{cfg["script_starx"]}" --stars --unscreen']
        return ["starnet -nostarmask"]
    raise ValueError(fonction)

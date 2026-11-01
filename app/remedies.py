"""Que faire d'une alerte : chaque ligne ATTENTION reçoit un conseil, l'étape où agir et, quand c'est possible,
les réglages à essayer (appliqués d'un clic dans l'interface, sans rien lancer).

etape : « ici » = refaire cette étape ; un identifiant = y revenir (les étapes suivantes passeront « à refaire ») ;
« suite » = une étape plus loin s'en charge. reglages : {paramètre: valeur} ; une chaîne « +0.2 » / « -30 »
est un ajustement relatif à la valeur actuelle de chaque variante.
"""
import re


def _done(p, sid):
    return p.state["steps"].get(sid, {}).get("status") in ("done", "stale")


def _crop_rect(p):
    st = p.state["steps"].get("P0", {})
    return (st.get("params") or {}).get("rect") or p.state["facts"].get("crop")


def _sides(line):
    """« gauche ~20 px, droite ~48 px » -> {"gauche": 20, "droite": 48}"""
    return {k: int(v) for k, v in re.findall(r"(gauche|droite|haut|bas) ~(\d+) px", line)}


def remedy(p, sid, line):
    l = line.lower()
    fond_src = "P6N" if _done(p, "P6N") else "P5"
    stretch_up = {"mesure": "ciel", "targetbg": "+0.03", "ss_median": "+0.03"}

    def r(conseil, etape=None, reglages=None):
        return {"conseil": conseil, "etape": etape, "reglages": reglages or {}}

    # --- réglage fin des couleurs ---------------------------------------------------
    if sid == "P8F" and "saturées après réglage fin" in l:
        return r("Des zones lumineuses sont poussées au maximum : baisse la luminosité ou la saturation et réapplique.",
                 "ici", {"luminosite": "-0.08", "saturation": "-0.1"})
    if sid == "P8F" and "noir écrasé" in l:
        return r("Le fond part au noir : baisse « Noirs » ou coche « Protéger le fond », puis réapplique.",
                 "ici", {"noirs": "-0.02", "proteger_fond": True})
    if sid == "P11" and "hors des cercles" in l:
        return r("Anomalie : relance les retouches ; si l'alerte reste, « Copier le rapport » et demande à Claude.", "ici")
    # --- fond du ciel ----------------------------------------------------------
    if "canal presque nul" in l:
        if fond_src == "P6N":
            return r("Un canal du fond a été poussé à zéro par un point noir trop fort. Relance P6N (point noir réglé "
                     "canal par canal, mesuré sur le ciel), un peu moins sombre et avec plus de douceur.",
                     "P6N", {"niveau": "+4", "douceur": "+0.2", "proteger": True})
        return r("Un canal du fond a été poussé à zéro. Relance P5 en neutralisant d'après le ciel seul, avec un fond un peu plus haut.",
                 "P5", stretch_up)
    if re.search(r"ciel( hors étoiles)?, médianes r/v/b", l) or "médianes encore écartées" in l:
        if sid == "P5":
            return r("Fond pas tout à fait neutre : neutralise d'après le ciel seul et relance.", "ici", {"mesure": "ciel"})
        if fond_src == "P6N":
            return r("Le fond est teinté (un canal s'écarte des deux autres). Relance P6N : il neutralise maintenant canal "
                     "par canal sur le ciel. Si la teinte reste, reviens à P5 (neutraliser d'après le ciel seul).",
                     "P6N", {"proteger": True})
        return r("Le fond est teinté (un canal s'écarte des deux autres). Relance P5 en neutralisant d'après le ciel seul.",
                 "P5", {"mesure": "ciel"})
    if "fond, grille" in l:
        return r("Le fond n'est pas uniforme d'une zone à l'autre. Si la nébuleuse remplit une grande partie du cadre, "
                 "c'est souvent elle qui est mesurée, pas un défaut : regarde l'image. S'il y a de vraies plaques ou un "
                 "dégradé : option « Aplanir le fond » à l'étape Couleurs (P8).", "P8", {"aplanir": True})
    if "noir écrasé" in l or "zones faibles sont devenues noires" in l:
        if sid == "P6N":
            return r("Fond moins sombre, plus de douceur et nébuleuse protégée, puis relance.", "ici",
                     {"niveau": "+4", "douceur": "+0.2", "proteger": True})
        if sid == "P5":
            return r("Fond cible un peu plus haut, puis relance.", "ici", stretch_up)
        if fond_src == "P6N":
            return r("Trop de pixels du fond à zéro : remonte le niveau du fond à l'étape P6N.", "P6N",
                     {"niveau": "+4", "douceur": "+0.2"})
        return r("Trop de pixels du fond à zéro : remonte le fond à l'étape P5.", "P5", stretch_up)
    if "décalage négatif sur un canal" in l:
        return r("Neutralise d'après le ciel seul avec un fond un peu plus haut, et relance.", "ici",
                 {"mesure": "ciel", "targetbg": "+0.02", "ss_median": "+0.02"})
    if "siril a refusé l'empilement avec toutes les options" in l:
        return r("Le stack est utilisable : continue. Les options retirées changent peu le résultat (pondération : les "
                 "poses comptent toutes autant ; adoucissement : bords un peu plus marqués, retirés au cadrage). "
                 "Le journal montre pourquoi Siril les a refusées.", "suite")
    # --- mesure du stack (S4) : retour à l'empilement quand des poses sont en cause -------------------------
    stricter = {"filter_round": "-0.5", "filter_fwhm": 2.0}
    if "étoiles larges" in l:
        return r("Si seule une partie des poses est floue (turbulence passagère, buée), les écarter affine le stack : "
                 "refais l'empilement avec un filtre FWHM à 2 (écarte les poses nettement plus floues que la moyenne, "
                 "au prix d'un peu d'intégration) et compare la FWHM. Si elle ne baisse pas, toutes les poses sont "
                 "concernées : mise au point ou buée à surveiller la prochaine fois.", "S3", {"filter_fwhm": 2.0})
    if "étoiles allongées" in l:
        if "optique" in l:
            return r("Allongement d'origine optique (pointé vers le centre) : l'empilement n'y peut rien. BlurXTerminator "
                     "(P3) corrige la forme des étoiles zone par zone ; le cadrage (P0) peut retirer les bords les pires.",
                     "suite")
        why = {"suivi ou vent": "des poses bougées (vent, suivi)", "rotation de champ": "des poses prises quand le champ "
               "tourne le plus vite (près du zénith)"}.get(l.split("cause probable : ")[-1].strip(), "les poses les plus déformées")
        return r(f"Une partie des poses est probablement en cause : {why}. Refais l'empilement avec des filtres plus "
                 "stricts : rondeur 0,5 plus bas (écarte les poses aux étoiles allongées) et FWHM à 2. Compare "
                 "l'excentricité à la nouvelle mesure ; si elle reste haute, BlurXTerminator (P3) arrondira les étoiles.",
                 "S3", stricter)
    if "finesse des étoiles inégale" in l:
        if "sans motif net" in l:
            return r("Variation sans motif optique : souvent quelques poses floues ou voilées. Refais l'empilement avec un "
                     "filtre FWHM à 2, puis compare la carte de finesse.", "S3", {"filter_fwhm": 2.0})
        return r("Rien à refaire à l'empilement : c'est l'optique et la rotation de champ (les coins du stack viennent des "
                 "bords du capteur). Deux corrections plus loin : 1) BlurXTerminator (P3) corrige la forme des étoiles "
                 "zone par zone, c'est son point fort : regarde le coin flou sur le zoom après P3 ; 2) au cadrage (P0), "
                 "retire ce coin s'il reste visiblement flou. Pour les prochaines nuits : mise au point refaite à chaque "
                 "session, cible haute dans le ciel ; un Seestar n'a pas de réglage d'inclinaison.", "suite")
    # --- recadrage ---------------------------------------------------------------
    if "bords d'alignement restants" in l or "bande vide sur le bord" in l:
        rect, sides = _crop_rect(p), _sides(line)
        new = None
        if rect and sides:
            x, y, w, h = rect
            g, d, t, b = (sides.get(k, 0) + (8 if sides.get(k) else 0) for k in ("gauche", "droite", "haut", "bas"))
            if sid == "P0":           # le contrôle mesure sur l'image recadrée : mêmes axes que le rectangle
                new = [x + g, y + t, w - g - d, h - t - b]
            else:
                new = [x + g, y + t, w - g - d, h - t - b]
        regl = {"rect": new} if new and new[2] > 64 and new[3] > 64 else {}
        txt = "Resserre le cadre du côté indiqué" + (" (cadre proposé : " + " ".join(map(str, new)) + ")" if regl else "")
        return r(txt + " et relance.", "ici" if sid == "P0" else "P0", regl)
    if "dépasse du cadre" in l or "halo sera coupé" in l:
        rect = _crop_rect(p) if sid != "P0" else (p.state["steps"].get("P0", {}).get("variants") or [{}])[0].get("params", {}).get("rect")
        regl = {}
        if rect:
            x, y, w, h = rect
            mx, my = int(w * 0.08), int(h * 0.08)
            regl = {"rect": [max(0, x - mx), max(0, y - my), w + 2 * mx, h + 2 * my]}
        return r("Agrandis ou déplace le cadre pour inclure l'objet (ou l'étoile et son halo), puis relance. "
                 "Le cadre proposé est agrandi de 8 % de chaque côté.", "ici" if sid == "P0" else "P0", regl)
    # --- débruitage, grain --------------------------------------------------------
    if "le débruitage n'a presque rien changé" in l:
        return r("Vérifie la licence NoiseXTerminator dans le journal, ou augmente la force et relance.", "ici", {"dn": "+0.2"})
    if "plus granuleux" in l:
        if sid == "P8":
            return r("Normal avec une saturation ou un contraste local forts. Le débruitage final (P10) peut le corriger ; "
                     "sinon baisse la force ici.", "suite")
        return r("Le grain augmente : un débruitage final (P10) peut le corriger.", "suite")
    # --- étoiles --------------------------------------------------------------------
    if "étoiles doublées" in l:
        if sid == "S3B":
            return r("Le second appareil est mal superposé : garde le principal seul (ou baisse son poids) et vérifie sur un zoom.",
                     "ici", {"mode": "principal"})
        return r("Les deux calques ne se superposent pas : prends les étoiles du stack principal.", "ici", {"source": "principal"})
    if "au-delà de ~10 %" in l or "monter le plancher" in l:
        return r("Trop de pixels gardés dans le calque d'étoiles : monte le plancher et relance.", "ici", {"plancher": "+0.04"})
    # --- alignement entre appareils -----------------------------------------------------
    if "échelle mesurée" in l or "écart résiduel au-dessus" in l:
        return r("Alignement douteux : vérifie le zoom ; en cas de doute, garde le principal seul.", "ici", {"mode": "principal"})
    # --- couleurs, export ---------------------------------------------------------------
    if "aucun mode spcc" in l:
        return r("Avec LP et IRCUT empilés ensemble, passe cette étape (bouton « Passer l'étape »).", "ici")
    if "écrêt" in l or "pixels >= 254" in l:
        return r("Des zones sont brûlées : étirement moins fort à l'étape P5.", "P5",
                 {"targetbg": "-0.03", "ss_median": "-0.03", "ghs_amount": "-30"})
    if "jpeg" in l and ("ne correspond pas" in l or "interverties" in l):
        return r("Relance l'export ; si l'alerte reste, colle le rapport à Claude.", "ici")
    if "licence" in l or "n'a rien modifié" in l:
        return r("Vérifie la licence et l'installation du script dans Siril (journal), puis relance.", "ici")
    return r("Regarde le zoom : si le défaut se voit, « Copier le rapport » et demande à Claude.")


def for_variant(p, sid, variant):
    out = {}
    for line in variant.get("info", []) or []:
        if line.startswith("ATTENTION"):
            out[line] = remedy(p, sid, line)
    return out

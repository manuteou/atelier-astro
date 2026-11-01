#!/usr/bin/env python3
"""tri_fond_ciel.py : repère les poses dont le fond de ciel est anormalement haut
(nuages, Lune, aube, pollution passagère) à partir du fichier .seq de Siril, AVANT
seqapplyreg (fond plus de 2 fois celui des autres, raison affichée).

S'exécute hors de Siril (l'appli le lance à l'étape S2) sur le fichier .seq :
  python3 tri_fond_ciel.py combined_.seq [--facteur 2.0] [--z 5] [--piedestal 0]

Pré-requis : `register combined_ -2pass` déjà lancé (il écrit, pour chaque pose,
une ligne R avec FWHM, FWHM pondérée, rondeur, qualité, NIVEAU DE FOND, nb d'étoiles).

Critères (une pose est signalée si l'un est vrai) :
  - rapport : (fond - piédestal) > facteur x (médiane des fonds - piédestal)   [défaut 2]
  - écart robuste : z = (fond - médiane) / (1.4826 x MAD) > z               [défaut 5]
    ... et seulement si le fond dépasse aussi la médiane d'au moins 15 % (`--ecart-min`) :
    un écart de quelques % est déjà compensé par -weight=noise
  - étoiles : moins de 40 % du nombre médian d'étoiles (voile nuageux), signalé à part
Plusieurs sessions (nuits) : `--plages 1-309,310-430` (numéros de fichier, ceux de la
conversion, notés dans NOTES.md) calcule médiane et dispersion PAR SESSION, pour ne pas
écarter toute une nuit simplement plus claire que l'autre.
`--piedestal` : offset du capteur dans l'unité du .seq (0 par défaut : le critère de
rapport est alors prudent, l'offset gonfle le dénominateur). Le critère z attrape les
nuages même quand le rapport ne bouge pas.

Le script NE MODIFIE RIEN : il écrit un rapport et propose les commandes `unselect`.
L'utilisateur valide au point de contrôle 2, puis l'agent lance les commandes et
`seqapplyreg ... -filter-included`.

Format .seq (vérifié sur un .seq de Siril, version 6 du format) : toutes les lignes
« I <num_fichier> <incl> », puis toutes les lignes « R<couche> fwhm wfwhm rondeur qualité
fond nb_étoiles H ... » dans le même ordre (le format intercalé ancien est aussi lu).
Si le format diffère, le script s'arrête avec un message clair au lieu de deviner.
Sortie : rapport texte sur la sortie standard, + tri_fond_ciel.csv à côté du .seq.
"""
import argparse
import csv
import os
import statistics
import sys


def lire_seq(chemin):
    """Lit les lignes I (une par pose) et R (données d'alignement). Siril >= 1.2 écrit
    toutes les lignes I puis toutes les lignes R, dans le même ordre (k-ième ligne R d'une
    couche = k-ième pose) ; les versions plus anciennes les intercalent. Les deux cas sont
    gérés ; si les nombres ne collent pas, arrêt avec un message plutôt qu'une supposition."""
    poses = []
    lignes_r = {}       # couche -> liste des mesures dans l'ordre du fichier
    intercale = {}      # couche -> {index de la pose précédente: mesure}
    with open(chemin, encoding="utf-8", errors="replace") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#"):
                continue
            if ligne.startswith("I "):
                champs = ligne.split()
                try:
                    poses.append({"index": len(poses), "fichier": int(champs[1]),
                                  "incl": int(champs[2]) if len(champs) > 2 else 1,
                                  "R": {}})
                except ValueError:
                    sys.exit(f"Ligne I illisible : {ligne!r}")
            elif ligne.startswith("R") and len(ligne) > 1 and ligne[1] in "0123*":
                champs = ligne.split()
                try:
                    valeurs = [float(x) for x in champs[1:6]]
                    nb = int(float(champs[6]))
                except (ValueError, IndexError):
                    continue  # ligne R d'un autre format : ignorée
                mesure = {"fwhm": valeurs[0], "wfwhm": valeurs[1], "rondeur": valeurs[2],
                          "qualite": valeurs[3], "fond": valeurs[4], "etoiles": nb}
                lignes_r.setdefault(ligne[1], []).append(mesure)
                if poses:
                    intercale.setdefault(ligne[1], {})[len(poses) - 1] = mesure
    for couche, liste in lignes_r.items():
        if len(liste) == len(poses):          # format groupé (Siril >= 1.2) ou intercalé complet
            for p, m in zip(poses, liste):
                p["R"][couche] = m
        elif len(intercale.get(couche, {})) == len(liste):  # intercalé partiel
            for idx, m in intercale[couche].items():
                poses[idx]["R"][couche] = m
        else:
            sys.exit(f"Couche {couche} : {len(liste)} lignes R pour {len(poses)} poses, "
                     f"impossible de les associer sans deviner. Format de .seq inattendu.")
    return poses


def choisir_couche(poses):
    compte = {}
    for p in poses:
        for c, r in p["R"].items():
            if r["fond"] > 0:
                compte[c] = compte.get(c, 0) + 1
    if not compte:
        return None
    return max(compte, key=compte.get)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seq")
    ap.add_argument("--facteur", type=float, default=2.0)
    ap.add_argument("--z", type=float, default=5.0)
    ap.add_argument("--piedestal", type=float, default=0.0)
    ap.add_argument("--ecart-min", type=float, default=0.15)
    ap.add_argument("--plages", default="",
                    help="sessions en numéros de fichier, ex. 1-309,310-430")
    ap.add_argument("--etoiles-min", type=float, default=0.4,
                    help="fraction du nombre médian d'étoiles sous laquelle on signale")
    a = ap.parse_args()

    poses = lire_seq(a.seq)
    if not poses:
        sys.exit("Aucune ligne I trouvée : ce n'est pas un .seq Siril, ou format inconnu.")
    couche = choisir_couche(poses)
    if couche is None:
        sys.exit("Aucune donnée de fond dans le .seq : lancer d'abord `register <seq> -2pass` "
                 "(sans données d'alignement, pas de niveau de fond par pose).")
    mesurees = [p for p in poses if couche in p["R"] and p["R"][couche]["fond"] > 0]
    if not mesurees:
        sys.exit("Aucune pose avec un niveau de fond > 0.")
    groupes = {}
    if a.plages:
        for k, pl in enumerate(a.plages.split(",")):
            d, f = (int(x) for x in pl.split("-"))
            for p in mesurees:
                if d <= p["fichier"] <= f:
                    groupes.setdefault(f"{d}-{f}", []).append(p)
        hors = [p for p in mesurees if not any(p in g for g in groupes.values())]
        if hors:
            groupes["hors plages"] = hors
    else:
        groupes["toutes"] = mesurees

    lignes = []
    signalees = []
    resume = []
    for nom, groupe in groupes.items():
        fonds = [p["R"][couche]["fond"] for p in groupe]
        etoiles = [p["R"][couche]["etoiles"] for p in groupe]
        med = statistics.median(fonds)
        mad = statistics.median([abs(x - med) for x in fonds]) or 1e-12
        sig = 1.4826 * mad
        med_et = statistics.median(etoiles) if etoiles else 0
        ref = med - a.piedestal
        if ref <= 0:
            sys.exit(f"Piédestal {a.piedestal} >= fond médian {med:.4g} : piédestal trop grand.")
        resume.append(f"  session {nom} : {len(groupe)} poses, fond médian {med:.5g}, "
                      f"dispersion {sig:.3g}, min/max {min(fonds):.5g}/{max(fonds):.5g}, "
                      f"étoiles médianes {med_et:g}")
        for p in groupe:
            r = p["R"][couche]
            rapport = (r["fond"] - a.piedestal) / ref
            z = (r["fond"] - med) / sig
            raisons = []
            if rapport > a.facteur:
                raisons.append(f"fond x{rapport:.2f} (> x{a.facteur:g})")
            elif z > a.z and rapport > 1 + a.ecart_min:
                raisons.append(f"fond +{z:.1f} sigma, x{rapport:.2f}")
            if med_et and r["etoiles"] < a.etoiles_min * med_et:
                raisons.append(f"{r['etoiles']} étoiles (< {a.etoiles_min:.0%} de {med_et:g})")
            lignes.append({"session": nom, "index_seq_0": p["index"],
                           "index_seq_1": p["index"] + 1,
                           "fichier": p["fichier"], "incluse": p["incl"],
                           "fond": r["fond"], "rapport": round(rapport, 3), "z": round(z, 2),
                           "etoiles": r["etoiles"], "fwhm": r["fwhm"], "rondeur": r["rondeur"],
                           "raison": " ; ".join(raisons)})
            if raisons:
                signalees.append(lignes[-1])
    lignes.sort(key=lambda l: l["index_seq_0"])
    signalees.sort(key=lambda l: l["index_seq_0"])

    sortie = os.path.join(os.path.dirname(os.path.abspath(a.seq)), "tri_fond_ciel.csv")
    with open(sortie, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0].keys()))
        w.writeheader()
        w.writerows(lignes)

    print(f"Séquence : {os.path.basename(a.seq)}   poses : {len(poses)}   "
          f"avec mesure de fond (couche {couche}) : {len(mesurees)}")
    print("\n".join(resume))
    if not signalees:
        print("Aucune pose signalée.")
    else:
        print(f"Poses signalées : {len(signalees)} ({len(signalees) / len(mesurees):.1%})")
        print("index(1)  fichier  fond        rapport  z      étoiles  raison")
        for l in signalees:
            print(f"{l['index_seq_1']:>8}  {l['fichier']:>7}  {l['fond']:<10.5g}  "
                  f"{l['rapport']:<7}  {l['z']:<5}  {l['etoiles']:>7}  {l['raison']}")
        print("\nCommandes proposées (index de séquence, numérotation 1 = première pose ;"
              " à confirmer avec `help unselect` au premier essai) :")
        for l in signalees:
            print(f"unselect combined_ {l['index_seq_1']} {l['index_seq_1']}")
        print("puis : seqapplyreg combined_ -filter-round=2.5k -filter-included "
              "-framing=max -drizzle -scale=1.0 -pixfrac=1.0 -kernel=square")
        print(f"Contrôle : le journal de seqapplyreg doit annoncer au plus "
              f"{len(mesurees) - len(signalees)} images sélectionnées avant le filtre de rondeur.")
    print(f"Tableau complet : {sortie}")


if __name__ == "__main__":
    main()

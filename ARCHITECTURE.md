# Architecture de l'Atelier astro

Une appli web locale : un serveur Python (FastAPI) pilote Siril et les scripts du pipeline, une interface en
JavaScript sans compilation (modules ES) affiche les étapes. Tout tourne sur la machine de l'utilisateur.

## Serveur (`app/`)

| Fichier | Rôle |
|---|---|
| `main.py` | crée l'appli, branche les routeurs et l'interface ; `python -m app.main` |
| `routes/` | l'API, un fichier par thème : `reglages` (config, outils, matériel, Ollama), `projets` (sessions, import, projets, presets, fichiers), `etapes` (lancer, valider, passer, rejouer, aperçus en direct, pleine résolution, rapport, avis), `travaux` (suivi, annulation), `fin` (brouillon de fiche, finalisation) |
| `pipeline.py` | lancer les variantes d'une étape, valider, rejouer les étapes « à refaire », NOTES.md, presets |
| `jobs.py` | file de travaux (un à la fois), journal, progression, **annulation** (arrêt de l'arbre de processus, points de contrôle) |
| `siril.py` | écrit un script `.ssf`, lance `siril-cli`, lit le journal (erreurs strictes, lignes `progress:`) ; `run_py` pour les scripts Python |
| `project.py` | dossier et `project.json` d'un projet : fichiers par clé, validation, étapes à refaire |
| `steps/` | les étapes (voir plus bas) |
| `inventory.py`, `organize.py` | lecture des en-têtes FITS, classes de filtres, clés d'appareil ; import en vrac et rangement (calibration comprise) |
| `calibration.py` | maîtres et poses calibrées avant l'alignement |
| `materiel.py`, `outils.py` | fiches du matériel ; outil choisi pour chaque fonction (RC Astro, GraXpert, Siril, StarNet, perso, aucun) |
| `fitsio.py`, `color_ops.py`, `align.py` | lecture/écriture FITS, aperçus, étirement ; opérations de couleur ; alignement entre appareils |
| `checks.py`, `remedies.py`, `report.py` | contrôles automatiques ; que faire de chaque alerte ; rapport et avis Ollama |
| `fiche_engine.py`, `fiche_auto.py`, `finalize.py` | fiche PDF ; champs pré-remplis et brouillon Ollama ; finalisation |
| `scripts/` | scripts Python du pipeline astro-siril (appelés comme sous-processus) |

### Une étape

Chaque étape est une classe `Step` (`steps/base.py`) : `params` (champs affichés), `run(ctx, prm, tag)` (fabrique
une variante et renvoie ses sorties et lignes d'info), `canonical` (noms définitifs à la validation), `applies` /
`ready` (sans objet / pas encore possible), `notes` (ligne de NOTES.md), et au besoin `dyn_defaults`,
`compose_preview`, `on_validate`, `interaction` (`crop`, `point`, `live`, `retouche`). Les lignes `ATTENTION` des
infos deviennent des alertes ; `remedies.remedy` dit où agir et quels réglages essayer.

| Module | Étapes |
|---|---|
| `stacking.py` (+ `sessions.py`) | S1 inventaire, S2 conversion/alignement/tri, S3 empilement, S4 mesure |
| `combine.py` | S3B combinaison de plusieurs appareils |
| `lineaire.py` | P0 cadrage, P1 fond, P2 calibration des couleurs, P3 netteté, P4 débruitage |
| `etoiles.py` | P5 étirement, P6 séparation, P6N noirs, P6B piste secondaire, P7 étoiles, P7T naturel |
| `couleurs.py`, `reglage_fin.py` | P7BIS couleur des étoiles, P8 couleurs ; P8F réglage fin en direct |
| `fusion.py`, `retouches.py` | P9 fusion, P10 débruitage final ; P11 retouches |
| `export.py` | P12 export, P13 fiche PDF |

L'ordre est fixé dans `steps/__init__.py`. Pour ajouter une étape : une classe dans le module de sa phase,
l'ajouter à son `STEPS`, un test dans `tests/test_e2e.py`.

### Annulation

Le code d'une étape n'a rien à faire de spécial : `siril.run` et `run_py` enregistrent leur processus auprès du
travail en cours et vérifient l'annulation avant et après ; `pipeline.run_variants` vérifie entre deux variantes.
Une étape annulée n'enregistre aucun résultat. `jobs.uninterruptible()` protège une phase qui ne doit pas être
coupée (suppression des fichiers à la finalisation).

## Interface (`web/`)

`index.html` charge `js/main.js` (module ES). Pas de compilation, pas de dépendance.

| Fichier | Rôle |
|---|---|
| `js/core.js` | `h()` (création d'éléments), `api()`, état partagé `S`, messages, fenêtres |
| `js/projet.js` | démarrage, liste et ouverture des projets, navigation |
| `js/page.js`, `js/editeur.js`, `js/actions.js` | page d'une étape ; champs et variantes ; lancer/valider/passer/rejouer/remèdes |
| `js/travaux.js` | suivi d'un travail : journal, barre de progression, bouton Annuler |
| `js/comparer.js` | rideau avant/après, zoom synchronisé des cartes de résultats |
| `js/visionneuse.js` | plein écran (zoom, zone, cadre, point) |
| `js/etapes/` | interfaces propres à une étape : cadrage (P0), réglage fin (P8F), retouches (P11), fiche (P13) |
| `js/fenetres/` | nouveau projet, réglages, matériel, presets, NOTES, finalisation |

`window.atelier` expose les fonctions principales pour la console du navigateur et les tests.

## Tests (`tests/`)

Tout tourne avec un **faux Siril** (`mock_siril.py`) qui imite les commandes utilisées (et refuse les erreurs de
syntaxe connues du vrai), sur des données synthétiques (`make_data.py`).

- `run_all.py` : toute la batterie (≈ 6 min) ; `--rapide` : un seul scénario de bout en bout.
- `test_e2e.py MODE TYPE [multi|generique]` : un projet complet par l'API, de l'import à la finalisation.
- `test_import.py` : import en vrac ; `test_annulation.py` : progression et annulation d'un empilement ralenti.
- `test_ui.py` : l'interface dans Chromium (chaque page, chaque fenêtre, cadrage, réglage en direct, retouches,
  comparaison, annulation) ; échoue à la moindre erreur JavaScript.

Le faux Siril ne garantit pas le comportement du vrai : toute nouvelle commande Siril doit être essayée une fois
dans le vrai Siril.

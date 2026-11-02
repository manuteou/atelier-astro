# Atelier astro

Un pipeline de traitement Siril dans une interface web locale, pour **toute caméra couleur**
(Seestar, autres télescopes intelligents, lunette ou télescope + caméra astro couleur, avec ou sans darks/flats) :
la technique est automatisée, chaque choix de rendu se fait sur des **variantes côte à côte** avec curseurs,
et tes réglages préférés s'enregistrent en **presets**. De l'inventaire des sessions jusqu'à la fiche PDF.

## Installation

Il te faut :
1. **Python 3.10 ou plus récent** (python.org ; sous Windows, cocher « Add to PATH »).
2. **Siril 1.4** (siril.org). L'appli pilote `siril-cli`, l'outil en ligne de commande installé avec Siril.
3. **En option**, les outils de traitement que tu utilises déjà, installés comme scripts dans Siril : GraXpert
   (`GraXpert-AI.py`), les outils RC Astro (`BlurXTerminator.py`, `NoiseXTerminator.py`, `StarXTerminator.py`,
   licence payante), `Statistical_Stretch.py`, StarNet… Aucun n'est obligatoire : pour chaque fonction, tu choisis
   l'outil dans Réglages, ou les outils intégrés à Siril (voir « Outils de traitement au choix »).

Puis :
1. Récupère l'appli : `git clone <adresse du dépôt>`, ou « Code › Download ZIP » sur la page du dépôt.
2. Lance-la : double-clic sur **`lancer.bat`** (Windows), ou `./lancer.sh` (macOS, Linux). Le premier lancement
   installe les bibliothèques Python (quelques minutes), puis le navigateur s'ouvre sur `http://127.0.0.1:8765`.
3. **Réglages** (en haut à droite) : dossier des sessions (`D:\Astrophoto` par défaut) et chemin de
   `siril-cli` (cherché tout seul dans les dossiers d'installation habituels de Siril).

Tes réglages sont enregistrés dans `config.json` et tes presets dans `presets/`, à côté de l'appli : ils ne
sont jamais envoyés sur le dépôt.

Rien ne sort de ton PC : le serveur n'écoute que sur ta machine (127.0.0.1). Seule la carte du ciel de la
fiche télécharge une fois les données d3-celestial.

## Importer tes poses : « Nouveau projet » → « Importer un dossier »

Tu indiques n'importe quel dossier (copie son chemin depuis l'Explorateur) : le dossier du Seestar, une clé,
un dossier en vrac avec des sous-dossiers, plusieurs appareils, filtres et nuits mélangés. L'appli lit l'en-tête
de **chaque** pose (appareil par INSTRUME ou focale, filtre, date, cible, taille) et propose des sessions :
une cible + un appareil + un filtre + une nuit (une pose prise après minuit compte pour la nuit de la veille).
Les fichiers empilés, darks et flats sont écartés et comptés. Tu coches les sessions, puis « Ranger et créer
le projet » crée `D:\Astrophoto\<CIBLE>_<APPAREIL>_<FILTRE>_<NUIT>\lights\` :

- **Liens** (par défaut) : aucune place disque en plus, fichiers d'origine intacts. Possible seulement sur le
  même disque que `D:\Astrophoto` ; sinon l'appli copie automatiquement.
- **Copier** : originaux intacts, mais la place est doublée.
- **Déplacer** : vide le dossier d'origine.

Réimporter le même dossier ne duplique rien ; ajouter une nouvelle nuit à une cible existante l'ajoute au projet
(les étapes déjà validées passent « à refaire »). Un dossier de session rangé à la main qui mélange deux
appareils ou deux filtres est refusé à la création du projet, avec la raison.

## Organisation des fichiers

Comme le pipeline : sessions dans `D:\Astrophoto\<SESSION>\lights\*.fit`, projet créé dans
`D:\Astrophoto\<CIBLE>_combined\` avec `process\` (séquences), `essais\` (une sortie par variante, jamais
écrasée), `apercus\`, `exports\`, `fiche\`, `NOTES.md` (réécrit à chaque validation) et `project.json` (l'état).
Les scripts Siril générés sont gardés dans `_scripts\` : on peut toujours voir exactement ce qui a été lancé.

## Déroulé

| Phase | Étapes |
|---|---|
| Stacking | S1 inventaire, choix des filtres (A / B / C) et des appareils · S2 conversion, `register -2pass`, tri du fond de ciel · S3 `seqapplyreg` + `stack` (mode B : deux stacks contrôlés par STACKCNT) · S3B combinaison des appareils (seulement avec plusieurs appareils ; en mode B, filtre par filtre) · S4 mesure FWHM / S/N (facultatif) |
| 1 · Linéaire | P0 recadrage (rectangle dessiné sur le stack) · P1 GraXpert · P2 SPCC + correction S50 Pro · P3 BXT · P4 NXT linéaire |
| 2 · Étirement et étoiles | P5 étirement (autostretch, mtf calé sur le fond, autoghs, Statistical Stretch) + neutralisation par canal · P6 StarX · P6N noirs du fond sur le calque sans étoiles (facultatif) · P6B piste secondaire (mode B) · P7 étoiles (sélection étoile par étoile, puissance, garder, supprimer ; amas protégé par un clic) · P7T image naturelle |
| 3 · Couleurs et export | P7BIS couleur des étoiles · P8B bicolore Hα / OIII (facultatif, filtre LP : chaque gaz traité à part, puis réuni avec les couleurs choisies) · P8 couleurs (satu, objet entier, doré/lave, bleu froid, rose/magenta, rouge Hα, émeraude, dégradé de deux couleurs au choix, palettes HOO et cuivre-bleu tirées du LP, régions HII du LP) + aplanissement et contraste local · P8F réglage fin en direct (température, teinte, rotation, saturation, saturation des rouges et des bleus, vibrance, luminosité, ombres et hautes lumières de la nébuleuse, contraste local, noirs ; l'aperçu change à chaque mouvement de curseur, puis application en pleine résolution ; bouton « Proposer des réglages » : curseurs placés d'après des mesures du fond, de la dominante et de la saturation, avec l'explication) · P9 fusion en écran · P10 NXT final · P11 retouches locales (éditeur : outil point vert ou anneau d'étoile, zoom à la molette, clic sur le défaut, correction visible tout de suite) · P12 export (JPEG HD/partage, TIFF 16 bits, sRGB, rotation exacte) |
| Fiche | P13 fiche PDF (carte du ciel, histoire, anecdote, images, fiche technique depuis le projet). Pré-remplis d'après les données : lieu (SITELAT/SITELONG des poses -> ville et région via OpenStreetMap), constellation et coordonnées, visibilité calculée pour ton lieu, phrases sur les images. Bouton « Brouillon des textes (Ollama) » : nom usuel, taille, catalogues, découverte, nom, nature, anecdote, à vérifier |

Sur chaque étape : tu règles une ou plusieurs variantes (A, B, C… jusqu'à 6), **Lancer**, puis tu compares
les aperçus (image complète + même zone de zoom pour toutes, mesures chiffrées, alertes de `controle.py`)
et tu **valides** celle que tu gardes. « Affiner » repart des réglages d'une variante pour en créer une autre
(« un peu plus noir »). Les étapes facultatives peuvent être passées.

**Revenir en arrière** : clique sur n'importe quelle étape validée, relance-la, valide une autre variante :
toutes les étapes suivantes passent « à refaire » (orange), rien n'est perdu.

**Visionneuse** (clic sur un aperçu) : « Zone de zoom » (zone de détail commune à toutes les variantes),
« Cadrer » (rectangle de recadrage en P0, zone de contrôle de l'aplanissement en P8, zones mesurées en S4),
« Point » (centre d'un amas en P7, défaut à retoucher en P11). Les coordonnées sont celles de l'image
affichée, pleine résolution, y depuis le haut ; l'appli fait la conversion en lignes FITS là où il faut.

**Presets** : enregistre les réglages validés d'un projet sous un nom (« nébuleuse sans étoiles, fond noir »).
Appliqué à un autre projet, un preset **pré-remplit** les réglages des étapes de rendu ; il ne lance rien et
chaque étape garde aperçu et validation. Le cadrage, les retouches et la fiche n'y sont jamais enregistrés.
Fichiers JSON dans `presets\`.

## Choisir les poses à écarter (S3)

Le tri de S2 classe les poses en trois niveaux : **rejets nets** (fond au moins deux fois plus clair, ou presque plus
d'étoiles : cochés d'office), **mitigées** (fond nettement inhabituel, voile léger : à toi de décider) et **proches de
la limite** (fond +10 %, étoiles moins nombreuses ou moins fines : gardées, mais montrées). Une liste compacte par
niveau : une case par pose (cochée = écartée), une case par bloc pour tout cocher ou décocher, et « voir » pour ouvrir
l'image d'une pose ou la pose typique de la nuit. Les cases remplissent « Poses à écarter ».

## Suivre, annuler, comparer

- La barre du bas montre le traitement en cours : étape, variante, progression de Siril. **Annuler** arrête
  Siril (et ses scripts) aussitôt ; l'étape n'enregistre rien, les étapes validées restent intactes.
- **Comparer** (sur chaque étape) : rideau avant/après entre la référence et les variantes, zoom identique des
  deux côtés, en option en pleine résolution.
- Dans les résultats, la molette sur une image zoome **toutes** les variantes au même endroit (glisser pour se
  déplacer, double-clic pour revenir).

## Matériel, filtres, calibration : rien n'est propre à une marque

- **Matériel** : l'appli lit l'instrument (`INSTRUME` / `TELESCOP`), la focale (`FOCALLEN`) et la taille des pixels
  (`XPIXSZ`) dans les poses. Un appareil = un instrument à une focale. Sa fiche (bouton **Matériel**) est créée
  d'elle-même et se corrige : nom affiché, ouverture, pixels, capteur et filtre pour SPCC (noms de la base de
  Siril ; capteur vide = calibration photométrique PCC), correction de couleur éventuelle (Seestar S50 Pro).
  Les fiches valent pour tous les projets.
- **Filtres** : classés **bi-bande** (codé « LP » : LP du Seestar, L-eXtreme, L-eNhance, ALP-T, Duo, tribande…)
  ou **large bande** (codé « IRCUT » : UV/IR cut, IRCUT, L-Pro, CLS, sans filtre). Le vrai nom reste affiché.
  Un nom inconnu est classé large bande (affiché en avertissement à l'import).
- **Calibration** : l'import range les darks (même durée de pose, ±0,5 s), flats (même filtre, nuit la plus
  proche), offsets et darks de flats avec les poses correspondantes (même appareil, même taille d'image), dans
  `darks\`, `flats\`, `offsets\`, `darkflats\` de chaque session. S2 fabrique alors les maîtres (`_maitres\`)
  et calibre les poses (`_calibrees\`, `calibrate … -cfa -equalize_cfa`, `-cc=dark` avec des darks) avant
  l'alignement. Sans fichiers de calibration (cas du Seestar), les poses sont utilisées telles quelles.
  Attention à la place disque : les poses calibrées sont des copies en 32 bits.
- **Caméras mono** (roue à filtres LRGB / SHO) : **pas gérées** ; les poses sans matrice de Bayer sont écartées
  à l'import avec la raison.

## Outils de traitement au choix (Réglages > Outils)

| Fonction | Choix |
|---|---|
| Extraction du fond (P1, S3B, piste B) | GraXpert (IA) · Siril intégré (`subsky -rbf`) · commande perso · aucun |
| Netteté (P3) | BlurXTerminator · Siril intégré (`makepsf stars` + `rl`, itérations réglables) · commande perso · aucun |
| Débruitage (P4, P10) | NoiseXTerminator · GraXpert (`-denoise -strength`) · Siril intégré (`denoise -mod=`) · commande perso · aucun |
| Séparation des étoiles (P6) | StarXTerminator · StarNet (via Siril, StarNet installé et déclaré dans Siril) · commande perso · aucun |

« Commande perso » : une ou plusieurs commandes Siril (par exemple le `pyscript` d'un autre outil), `{force}`
est remplacé par le réglage de force de l'étape. « Aucun » rend l'étape sans objet (pour les étoiles : elles
restent dans l'image, les couleurs se font sur l'image entière). Avec un autre outil que StarXTerminator, le
calque d'étoiles est déduit exactement (inverse de la fusion en écran).

## Plusieurs appareils sur la même cible (ex. S50 Pro + S30 Pro, ou deux lunettes)

L'appareil de chaque session est lu dans l'en-tête des poses (INSTRUME, sinon la focale : ~260 mm = S50,
~160 mm = S30). Avec plusieurs appareils dans un projet :

1. **S1** : tu choisis l'appareil principal (sa géométrie sert de référence, en général le S50) et les modèles
   (S50 Pro ou S50, S30 Pro ou S30 : la correction de capteur OS08B10 ne s'applique qu'au S50 Pro).
2. **S2 / S3** : une séquence et un stack par appareil (`process_S50`, `process_S30`, `<CIBLE>_S50_stack.fit`…),
   chacun avec son propre tri du fond. « Poses à écarter » s'écrit par appareil : `S50: 4,7 ; S30: 2`.
3. **S3B, combinaison** : chaque stack est recadré de ses bords peu couverts puis passe dans GraXpert (une fois
   par appareil, réutilisé d'une variante à l'autre) ; le S30 est aligné sur le S50 par les étoiles, échelle
   (x1,625 attendu) et rotation comprises, remis à sa géométrie, égalisé sur lui canal par canal (même fond,
   même réponse couleur), puis combiné en linéaire. Poids : inverse du bruit mesuré, divisé par l'agrandissement²
   (un pixel du S30 couvre ~2,6 pixels du S50, donc moins de mesures indépendantes à surface égale). Les zones que
   le S30 ne couvre pas gardent le S50 seul. Variantes proposées : combinaison poids x1, poids x0,5, principal seul.
4. La suite est inchangée. P1 (GraXpert) est sautée, déjà faite par appareil. SPCC se fait une fois, sur le
   résultat, avec le profil du principal. La fiche donne poses et intégration par appareil.

À regarder au premier essai réel : le nombre d'étoiles communes et l'écart résiduel (au-dessus de 1 px, alerte),
l'échelle mesurée comparée aux focales (alerte au-delà de 5 %), et surtout le zoom « combinaison / principal seul »
sur des étoiles et une zone fine : si la combinaison adoucit trop, baisse le poids ou garde le principal seul.

**Plusieurs appareils et mode B** (deux stacks LP / IRCUT) : en S3, chaque appareil empile chacun de ses filtres à
part (un appareil qui n'a qu'un des deux filtres ne fait que celui-là). En S3B, la combinaison se fait **filtre par
filtre** : les stacks LP de tous les appareils ensemble, les stacks IRCUT ensemble, chacun égalisé seulement sur un
stack du même filtre. Tous sont remis sur la grille du stack principal de l'appareil principal (LP pour une
nébuleuse, IRCUT pour une galaxie) : les deux résultats ont exactement la même taille, comme l'exige la piste
secondaire du mode B (P6B). Les variantes « principal seul » et « autre(s) appareil(s) seul(s) » s'appliquent à
chaque filtre ; si l'appareil choisi n'a pas l'un des filtres, l'appli prend celui d'un autre appareil et le dit.

## Ce qui a été vérifié, ce qui reste à vérifier

L'appli a été testée de bout en bout (modes A, B nébuleuse, B galaxie, et deux appareils S50 + S30 en modes A
et C) avec un **faux Siril** qui imite les commandes utilisées, sur des données synthétiques (S30 rendu à
l'échelle 160/260 et tourné de 3° : alignement retrouvé à x1,624 et 3,0°, écart résiduel 0,6 px). Elle **n'a pas encore tourné avec le vrai Siril**. Au
premier projet réel, regarde en particulier :

1. **Scripts Python dans `siril-cli`** (GraXpert, BXT, NXT, StarX) : le pipeline les lançait jusqu'ici
   par l'outil Siril de Claude. Si `siril-cli` refuse `pyscript` sans interface, P1 échouera avec le message
   de Siril : c'est le point le plus incertain.
2. **Convention de `crop`** (y depuis le haut ou le bas) : l'appli compare la sortie de Siril à la zone
   demandée et corrige d'elle-même au premier recadrage non symétrique (message dans P0).
3. **`select` / `unselect`** : numérotation à confirmer (Réglages). En mode B, le contrôle STACKCNT arrête
   tout si la sélection n'a pas été prise en compte ; en mode A, compare « poses retenues » au journal.
4. **StarX** : le calque `stars_*.fit` est cherché dans le dossier du projet ; si StarX n'a rien fait
   (licence), l'étape s'arrête au lieu de continuer avec une image non séparée.
5. **SPCC** : commandes reprises de `couleurs.md`, jamais exécutées dans le pipeline. Regarde les médianes.
6. **Ouverture à d'autres matériels et outils** : testée avec une caméra astro fictive (ASI533MC + lunette
   400 mm, darks/flats/offsets, outils Siril + StarNet) et le faux Siril seulement. Les commandes Siril
   intégrées (`subsky`, `makepsf`/`rl`, `denoise`, `starnet`, `pcc`, `calibrate`) et l'option `-denoise` de
   GraXpert-AI.py sont écrites d'après la documentation, **jamais exécutées dans le vrai Siril** : en cas
   d'erreur, le message de Siril s'affiche, et « commande perso » permet de corriger sans toucher au code.

Les étapes déjà marquées « non validées » dans le plugin le restent ici : mode B, `combiner_filtres.py`,
DBXtract (absent de l'appli), étoile marquante (absente).

## « Dis ce que tu veux » (étapes de rendu)

Sur les étapes de rendu (netteté, débruitage, étirement, noirs, étoiles, couleurs, réglage fin), des **phrases toutes
faites** (« Fond plus noir », « Moins d'étoiles », « Plus chaud »…) changent les réglages d'un pas connu, sans modèle,
instantanément ; et une case accepte une **phrase libre**, traduite en réglages par Ollama (gemma4 par défaut s'il est
installé, réglable : `ollama_intent_model`). Les réglages proposés sont contrôlés (réglages connus, affichés, dans
leurs bornes) ; rien n'est lancé, la page dit ce qui a changé. Test du 1er novembre 2026 sur 16 phrases réelles :
gemma4 14 justes (2 s), qwen2.5:7b 12, qwen3:4b 6. Les phrases toutes faites sont dans `app/intentions.py`.

## Modèles locaux (Ollama) : ce qu'ils valent

Testés le 1er novembre 2026 sur le PC de l'auteur (RTX 5070 12 Go) :
- **Faits de la fiche** : qwen2.5:7b et bonsai-2:27b se trompent sur la plupart des faits (NGC 6960 pris pour une
  région de formation d'étoiles, NGC 7000 pour une nébuleuse planétaire, M33 « découverte par Halley en 1725 »).
  La fiche propose donc d'abord **« Copier la demande pour Claude »** (recherche web, faits sourcés) puis de coller
  sa réponse ; le brouillon Ollama reste en option.
- **Défauts visibles sur une image** (6 défauts fabriqués) : bonsai-2:27b et d3:4b repèrent les défauts grossiers
  (fond teinté, cœur brûlé, bande de bord, image délavée) sans fausse alerte, mais pas les étoiles doublées ni le
  fond écrasé. Les contrôles chiffrés de l'appli détectent déjà ces six défauts : pas d'intégration pour l'instant.
- **Proposer des réglages fins** d'après l'image : sur 5 défauts corrigeables (fond vert, délavé, couleurs ternes,
  dominantes chaude et froide), aucun des deux n'en corrige plus de deux, et ni l'un ni l'autre ne voit les dominantes.
  Le bouton « Proposer des réglages » de P8F calcule donc ses propositions par des mesures (`color_ops.suggest`,
  testé par `tests/test_suggest.py`).
- **Réglages appliqués à toutes les demandes** : contexte limité à 8 192 jetons (`ollama_num_ctx`) et réflexion
  coupée. Sans cela, bonsai-2:27b occupait 27 Go au lieu de 8,5 Go et répondait 7 fois plus lentement ; avec la
  réflexion, plus de 8 minutes pour une fiche.

## Bicolore Hα / OIII (P8B, filtre LP)

Avec le filtre bi-bande (LP), l'Hα et l'OIII n'ont pas les mêmes besoins : l'OIII est plus faible et plus bruité,
l'Hα supporte du contraste. L'étape sépare le calque sans étoiles en deux calques mono, montrés en noir et blanc sous
chaque variante :
- **Hα** = canal rouge ; **OIII** = moyenne du vert et du bleu, **moins la part d'Hα qui s'y mêle** (mesurée sur les
  zones où l'Hα domine). Sans ce retrait, les deux gaz se superposent partout et deux couleurs opposées (rouge et
  turquoise) se mélangent en gris ou blanc.
- **Traitement de chaque gaz** : débruitage (l'OIII d'abord, avant son gain, pour ne pas grossir son bruit), gain du
  signal au-dessus du fond, luminosité, contraste local pour l'Hα. Le fond du ciel garde son niveau.
- **Débruitage de l'OIII adapté à P4** : la force proposée baisse quand P4 était fort (P4 à 0,8 → 0,2), et une
  alerte signale un débruitage cumulé trop fort (risque d'aspect « plastique »).
- **Recombinaison** : deux couleurs au choix (une par gaz), ou les palettes HOO et cuivre-bleu.

Le résultat sert d'entrée à P8, qui propose alors « aucune » couleur (tu peux la passer ou y ajouter une touche).
Sans poses LP (ou en mode C avec le large bande), l'étape est sans objet. En mode A (LP et large bande mélangés), la
séparation est moins nette : l'appli le signale.

## Finaliser le travail

Sur les pages Export (P12) et Fiche (P13), « Finaliser le travail » ouvre un récapitulatif : nom du dossier final
(nom technique - lieu - date de la nuit, modifiable), fichiers gardés (fiche PDF, finales colorisée et naturelle,
stack brut, JPEG de partage, TIFF, FIT final, NOTES.md), ce qui sera supprimé et la place libérée. Rien ne se fait
sans cocher la confirmation. Les fichiers sont copiés et vérifiés **avant** toute suppression ; puis le dossier de
travail du projet et les poses calibrées intermédiaires (`_calibrees`) sont supprimés. Les poses d'origine
(lights, darks, flats, offsets) ne sont jamais touchées. Les fichiers finaux portent le nom technique (NGC7000_…).

## Contrôles automatiques

Chaque résultat porte un badge « ✓ contrôles » ou « ⚠ n alertes » ; les alertes s'affichent en orange sous
l'aperçu, avec ce qu'elles veulent dire. Ce sont des mesures, toujours faites de la même façon :

| Étape | Contrôle |
|---|---|
| P0 recadrage | l'objet principal ou une étoile très brillante coupé par le cadre ; bords d'alignement restants |
| P3 / P4 / P10 | évolution du grain du fond (un débruitage qui ne débruite pas est signalé) |
| P5 étirement | fond mal neutralisé, noir écrasé (signal faible perdu) |
| P6N noirs | part des zones faibles tombées au noir, noir écrasé |
| P7 / P9 (mode B), S3B | étoiles doublées ou décalées entre deux calques ou deux appareils |
| P7T, P9 | `controle.py` : neutralité du fond, régularité, écrêtage, exactitude de la fusion |
| P8B bicolore | débruitage de l'OIII sans effet, débruitage cumulé fort (P4 + OIII), pixels saturés, grain du fond qui augmente |
| P8 couleurs | grain du fond qui augmente nettement |
| P8F réglage fin | zones poussées au maximum, fond écrasé au noir (si le fond n'est pas protégé) |
| P12 export | JPEG conforme à la version choisie, naturelle et colorisée non interverties, bande vide sur un bord, profil sRGB |

Ils ne jugent pas l'esthétique : le choix entre deux rendus reste le tien.

## Différences avec le plugin

- Pas d'agent de contrôle indépendant : `controle.py` tourne automatiquement (image naturelle, fusion,
  retouches, export) et ses alertes s'affichent sous les aperçus. Le jugement visuel reste le tien.
- La fiche PDF ne fait pas de recherche : tu écris les textes, ou tu les demandes à Claude (faits sourcés)
  et tu les colles. La fiche technique, elle, est remplie depuis le projet.
- Les calculs simples se font en Python plutôt qu'en PixelMath (neutralisation du fond, correction S50 Pro,
  fusion en écran, couleur des étoiles), avec les mêmes formules, ce qui évite les pièges `pm` 0–1, `rgbcomp`
  et `stat`. Les scripts du plugin sont copiés dans `app\scripts` : si tu les mets à jour dans le plugin,
  recopie-les ici.
- Pas encore : DBXtract et palettes narrowband (cuivre et bleu, HOO), halo d'étoile marquante, HDR.

## Remerciements

Certaines idées de cet atelier viennent du travail d'autres passionnés, que je remercie chaleureusement :
- **AstroWizard**, pour l'ordre des étapes du post-traitement et sa façon de les enchaîner ;
- **COSMO**, pour le tri des poses selon le fond de ciel et les cartes de mesure du stack (FWHM, S/N).

Aucun code de ces projets n'est repris ici : ce sont leurs idées qui m'ont inspiré.

## Développement

Voir `ARCHITECTURE.md` (organisation du code, ajout d'une étape, annulation, tests).
Tous les tests : `python tests/run_all.py` (≈ 6 min, faux Siril + navigateur) ; après une petite modification :
`python tests/run_all.py --rapide`. Dépendances des tests : `pip install -r requirements-dev.txt` puis
`playwright install chromium`.

## Licence

Atelier astro est un logiciel libre, distribué sous licence **GNU GPL version 3 ou ultérieure** (GPL-3.0-or-later, voir `LICENSE`) : tu peux
l'utiliser, l'étudier, le modifier et le redistribuer ; toute version modifiée que tu redistribues doit rester
sous la même licence, avec son code source.

Les polices du dossier `app/fonts` (DejaVu, Carlito) gardent leurs propres licences libres, voir `app/fonts/LICENCES.txt`.

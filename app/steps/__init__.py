"""Les étapes, dans l'ordre du pipeline. Chaque module contient une phase ; ORDER fixe la navigation."""
from . import combine, couleurs, etoiles, export, fusion, lineaire, reglage_fin, retouches, stacking

STEPS = (stacking.STEPS[:3] + combine.STEPS + stacking.STEPS[3:] + lineaire.STEPS + etoiles.STEPS
         + couleurs.STEPS + reglage_fin.STEPS + fusion.STEPS + retouches.STEPS + export.STEPS)
STEP_MAP = {s.id: s for s in STEPS}
ORDER = [s.id for s in STEPS]

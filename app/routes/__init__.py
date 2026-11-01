"""Routes de l'API, une par thème."""
from . import etapes, fin, projets, reglages, travaux

ROUTERS = [reglages.router, projets.router, etapes.router, travaux.router, fin.router]

"""Atelier astro : serveur web local (FastAPI). Lancer : python -m app.main

Copyright (C) 2026 manu. Logiciel libre sous licence GNU GPL version 3 ou ultérieure : voir le fichier LICENSE.

Les routes sont dans app/routes (une par thème), les étapes du pipeline dans app/steps, l'interface dans web/."""
import os
import webbrowser

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .routes import ROUTERS
from .routes.commun import proj  # noqa: F401 (compatibilité des tests et scripts)

app = FastAPI(title="Atelier astro")
WEB = config.ROOT_DIR / "web"


@app.exception_handler(ValueError)
async def value_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(PermissionError)
async def permission_error(_, exc):
    return JSONResponse({"detail": str(exc) or "non autorisé"}, status_code=403)


@app.middleware("http")
async def toujours_a_jour(request, call_next):
    """Pages et scripts de l'interface : le navigateur revalide à chaque chargement (ETag), pour qu'une mise à jour
    de l'appli (git pull) soit visible sans vider son cache."""
    rep = await call_next(request)
    if not request.url.path.startswith(("/api/", "/files/", "/galerie/")):
        rep.headers["Cache-Control"] = "no-cache"
    return rep


for r in ROUTERS:
    app.include_router(r)

app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")


def no_quickedit():
    """Windows : un clic dans la fenêtre noire passe la console en mode « Sélection » et suspend le serveur
    (et tout ce qui y écrit) jusqu'à une touche. On désactive ce mode pour la fenêtre de l'appli."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-10)                    # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)   # sans QUICK_EDIT, avec EXTENDED_FLAGS
    except Exception:
        pass


def main():
    import uvicorn
    no_quickedit()
    port = int(os.environ.get("ATELIER_PORT", config.load().get("port", 8765)))
    if not os.environ.get("ATELIER_NO_BROWSER"):
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

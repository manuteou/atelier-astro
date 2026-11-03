"""Exploration des travaux terminés : lecture d'un dossier FINAUX TRAITES (dossiers de l'appli et anciens
« _combined/keep »), regroupement par cible, vignettes, fichiers servis sans sortir du dossier, page dans un vrai
navigateur (Chromium + Playwright), sans erreur JavaScript. Lancer : python tests/test_galerie.py"""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
tmp = Path(tempfile.mkdtemp(prefix="galerie_"))
base = tmp / "Astrophoto"
fin = base / "FINAUX TRAITES"


def jpg(path, couleur, w=900, h=600):
    path.parent.mkdir(parents=True, exist_ok=True)
    yy, xx = np.mgrid[0:h, 0:w]
    g = np.exp(-((xx - w / 2) ** 2 + (yy - h / 2) ** 2) / (2 * (w / 6) ** 2))
    a = (np.stack([g * c for c in couleur], 2) * 255).astype(np.uint8)
    Image.fromarray(a).save(path, quality=90)


def pdf(path):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    c.drawString(100, 750, path.stem)
    c.save()


d1 = fin / "NGC 7380 - Buc - 2026-09-25"
for g, col in (("colorise_HD", (1, .4, .5)), ("naturel_HD", (.9, .6, .6)), ("partage", (1, .4, .5))):
    jpg(d1 / f"NGC7380_FINAL_{g}.jpg", col)
jpg(d1 / "NGC7380_stack_brut_HD.jpg", (.5, .5, .5))
pdf(d1 / "NGC7380_fiche.pdf")
(d1 / "NGC7380_FINAL.fit").write_bytes(b"0" * 100)
(d1 / "NGC7380_NOTES.md").write_text("# NGC 7380 — NOTES\n\n- Type de cible : nebuleuse\n- Appareil : ZWO Seestar S50\n"
                                     "- Empilement : 203 poses retenues, STACKCNT 203\n  Fichier : x.fit   2360x4012 px   "
                                     "intégration : 3 h 23   échelle : 2.30″/px\n", encoding="utf-8")
d2 = fin / "Sh2-132 - Buc - 2026-10-05 au 2026-10-17"
jpg(d2 / "Sh2-132_FINAL_colorise_HD.jpg", (1, .7, .3))
pdf(d2 / "Sh2-132_fiche.pdf")
d3 = fin / "SH2-132_mosaic_combined" / "keep"                 # ancien format du pipeline, même cible
jpg(d3 / "SH2-132_FINAL_colorise_HD.jpg", (.8, .5, .9))
jpg(d3 / "SH2-132_FINAL2_colorise_HD.jpg", (.8, .6, .9))
d4 = fin / "IC 1396A - Buc - 2026-08-30"                       # IC 1396A ≠ IC 1396
jpg(d4 / "IC1396A_FINAL_colorise_HD_v3.jpg", (.9, .3, .3))
jpg(d4 / "IC1396A_FINAL_colorise_HD.jpg", (.9, .3, .3))
d5 = fin / "IC1396_combined" / "keep"
jpg(d5 / "IC1396_FINAL_colorise_HD.jpg", (.6, .3, .3))
(fin / "vide").mkdir()
(base / "secret.txt").write_text("hors du dossier")

os.environ["ATELIER_ROOT"] = str(base)
os.environ["ATELIER_VIGNETTES"] = str(tmp / "vignettes")          # pas de cache dans le dépôt
sys.path.insert(0, str(ROOT))
from app import config, galerie  # noqa: E402

if config.CONFIG_PATH.exists():
    config.CONFIG_PATH.rename(config.CONFIG_PATH.with_suffix(".bak_galerie"))
try:
    assert galerie.racine() == fin, "FINAUX TRAITES pris d'office quand il existe"
    r = galerie.explorer()
    cibles = {c["cle"]: c for c in r["cibles"]}
    assert set(cibles) == {"NGC7380", "SH2132", "IC1396A"}, "anciens dossiers _combined/keep non affichés"
    assert len(cibles["SH2132"]["travaux"]) == 1
    t = cibles["NGC7380"]["travaux"][0]
    assert (t["lieu"], t["date"]) == ("Buc", "2026-09-25"), t
    assert [i["genre"] for i in t["images"]] == ["colorise", "naturel", "stack_brut", "partage"], t["images"]
    assert t["fiches"] and t["faits"]["integration"] == "3 h 23" and t["faits"]["appareil"] == "ZWO Seestar S50", t["faits"]
    assert cibles["IC1396A"]["travaux"][0]["images"][0]["version"] == 3, "la dernière version d'abord"
    v = galerie.vignette(t["couverture"], 300)
    assert max(Image.open(v).size) == 300
    for mauvais in ("../secret.txt", "NGC 7380 - Buc - 2026-09-25/../../secret.txt"):
        try:
            galerie.chemin_sur(mauvais)
            raise AssertionError(f"{mauvais} : on ne doit pas sortir du dossier exploré")
        except FileNotFoundError:
            pass
    print(f"  {len(r['cibles'])} cibles, regroupement et lecture des notes corrects")

    # site statique à publier : construction, incrémental, envoi sur un dépôt git
    from app import site  # noqa: E402
    dsite = tmp / "site"
    r1 = site.construire(dsite, "Test galerie", log=lambda *a: None)
    assert r1["cibles"] == 3 and r1["convertis"] > 0, r1
    noms = {f.relative_to(dsite).as_posix() for f in dsite.rglob("*") if f.is_file()}
    assert "index.html" in noms and any(n.startswith("fiches/") for n in noms) and "img/ngc-7380/colorise.jpg" in noms, noms
    assert not any(n.endswith((".fit", ".tif", ".md")) for n in noms), "jamais de FIT, TIFF ni NOTES publiés"
    assert max(Image.open(dsite / "img/ngc-7380/colorise.jpg").size) <= site.LARGEUR_WEB
    assert site.construire(dsite, "Test galerie", log=lambda *a: None)["convertis"] == 0, "rien à refaire la 2e fois"
    import subprocess as _sp
    nu = tmp / "depot.git"
    _sp.run(["git", "init", "--bare", "-q", str(nu)], check=True)
    rp = site.publier(f"file://{nu}", dsite, "Test galerie", log=lambda *a: None)
    assert rp["publie"] == "envoyé", rp
    lst = _sp.run(["git", "--git-dir", str(nu), "ls-tree", "-r", "--name-only", "main"], capture_output=True, text=True).stdout
    assert "index.html" in lst and "img/ngc-7380/colorise.jpg" in lst, lst
    assert site.publier(f"file://{nu}", dsite, "Test galerie", log=lambda *a: None)["publie"] == "inchangé"
    try:
        site.publier("ignore; rm -rf /", dsite)
        raise AssertionError("adresse de dépôt farfelue acceptée")
    except ValueError:
        pass
    print(f"  site statique : {r1['cibles']} cibles, {r1['taille_mo']} Mo, envoyé sur un dépôt git, 2e envoi inchangé")

    # dans le navigateur
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=ROOT,
                           env=dict(os.environ, ATELIER_NO_BROWSER="1", ATELIER_PORT=str(port),
                                    ATELIER_SIRIL=str(HERE / "mock_siril.py")))
    errors = []
    try:
        time.sleep(2.5)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 900})
            pg.on("pageerror", lambda e: errors.append(f"pageerror : {e}"))
            pg.on("console", lambda m: errors.append(f"console : {m.text}") if m.type == "error" else None)
            pg.goto(f"http://127.0.0.1:{port}")
            pg.wait_for_timeout(800)
            pg.click("#btnExplorer")
            pg.wait_for_selector(".ex-carte")
            assert pg.locator(".ex-carte").count() == 3
            pg.wait_for_timeout(600)
            assert pg.evaluate("() => [...document.querySelectorAll('.ex-carte img')].every(i => i.complete && i.naturalWidth > 0)")
            pg.screenshot(path=str(tmp / "grille.png"))
            pg.fill(".ex-bar input", "sh2")
            assert pg.locator(".ex-carte").count() == 1
            pg.click(".ex-carte")
            pg.wait_for_selector(".ex-travail")
            assert pg.locator(".ex-travail").count() == 1
            pg.click("text=← Toutes les cibles")
            pg.fill(".ex-bar input", "")
            pg.click(".ex-carte >> text=NGC 7380")
            pg.wait_for_selector(".ex-images figure")
            pg.click(".ex-thead button:has-text(\"Fiche PDF\")")
            pg.wait_for_selector(".ex-pdf iframe")
            pg.click(".ex-thead button:has-text(\"Notes\")")
            pg.wait_for_function("() => document.querySelector('.ex-notes').textContent.includes('Seestar')")
            pg.wait_for_timeout(500)
            pg.screenshot(path=str(tmp / "detail.png"), full_page=False)
            pg.click(".ex-images figure >> nth=1")
            pg.wait_for_selector(".ex-lb img")
            pg.keyboard.press("ArrowRight")
            assert "(3/4)" in pg.inner_text(".ex-lb .viewer-bar")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(tmp / "visionneuse.png"))
            pg.keyboard.press("Escape")
            assert pg.locator(".ex-lb").count() == 0
            pg.click("text=← Toutes les cibles")
            pg.click(".ex-bar button:has-text(\"Publier le site\")")
            pg.wait_for_selector("#dlg:not(.hidden) button:has-text(\"Publier sur GitHub\")")
            pg.click("#dlgClose")
            pg.click(".ex-bar button:has-text(\"Fermer\")")
            assert pg.locator("#explorer.hidden").count() == 1
            n_err = len(errors)
            st = pg.evaluate("async () => (await fetch('/galerie/fichier/..%2Fsecret.txt')).status")
            assert st == 404, st
            pg.wait_for_timeout(200)
            del errors[n_err:]                    # le 404 voulu ci-dessus n'est pas une erreur de la page
            sp = b.new_page(viewport={"width": 1200, "height": 900})
            sp.on("pageerror", lambda e: errors.append(f"site pageerror : {e}"))
            sp.goto((tmp / "site" / "index.html").as_uri())
            sp.wait_for_selector(".carte")
            assert sp.locator(".carte").count() == 3
            sp.click(".carte >> text=NGC 7380")
            sp.wait_for_selector(".images figure")
            assert sp.locator("a.fiche").count() == 1
            sp.click(".images figure >> nth=0")
            sp.wait_for_selector(".lb img")
            sp.screenshot(path=str(tmp / "site_detail.png"))
            sp.keyboard.press("Escape")
            sp.click("text=← Toutes les cibles")
            sp.wait_for_selector(".carte")
            sp.screenshot(path=str(tmp / "site_accueil.png"))
            b.close()
    finally:
        srv.terminate()
    assert not errors, "\n".join(errors)
    print(f"  page d'exploration sans erreur ; captures dans {tmp}")
finally:
    bak = config.CONFIG_PATH.with_suffix(".bak_galerie")
    if bak.exists():
        if config.CONFIG_PATH.exists():
            config.CONFIG_PATH.unlink()
        bak.rename(config.CONFIG_PATH)
print("OK")

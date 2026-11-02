"""Test de l'interface dans un vrai navigateur (Chromium + Playwright) : chaque page d'étape, chaque fenêtre,
le cadrage, le réglage fin en direct, l'éditeur de retouches, la comparaison des variantes, l'annulation.
Échoue à la moindre erreur JavaScript. Prépare ses données avec test_e2e.py (sans finalisation).
Lancer : python tests/test_ui.py"""
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


print("Préparation des données (test de bout en bout sans finalisation)…")
env = dict(os.environ, ATELIER_SANS_FINAL="1")
out = subprocess.run([sys.executable, str(HERE / "test_e2e.py"), "A", "nebuleuse"], capture_output=True, text=True, env=env, cwd=ROOT)
m = re.findall(r"Dossier de test : (\S+)", out.stdout)
assert m, out.stdout[-2000:] + out.stderr[-2000:]
data = Path(m[-1]) / "Astrophoto"
port = free_port()
srv = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=ROOT,
                       env=dict(os.environ, ATELIER_ROOT=str(data), ATELIER_SIRIL=str(HERE / "mock_siril.py"),
                                ATELIER_NO_BROWSER="1", ATELIER_PORT=str(port), MOCK_SLOW="0.5"))
errors = []
try:
    time.sleep(2.5)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1500, "height": 1000})
        pg.on("pageerror", lambda e: errors.append(f"pageerror : {e}"))
        pg.on("console", lambda msg: errors.append(f"console : {msg.text}") if msg.type == "error" else None)
        pg.goto(f"http://127.0.0.1:{port}")
        pg.wait_for_timeout(1200)
        pg.evaluate("async () => { await openProject('data_combined'); }")
        pg.wait_for_timeout(500)

        # 1. toutes les pages d'étape
        ids = pg.evaluate("() => S.data.steps.map(s => s.id)")
        for sid in ids:
            pg.evaluate(f"() => {{ S.sid = '{sid}'; renderSteps(); renderMain(); }}")
            pg.wait_for_timeout(250)
        print(f"  {len(ids)} pages d'étape affichées")

        # 2. fenêtres
        for btn in ("#btnSettings", "#btnMateriel", "#btnPresets", "#btnNotes", "#btnNew"):
            pg.click(btn)
            pg.wait_for_selector("#dlg:not(.hidden)")
            pg.wait_for_timeout(500)
            pg.evaluate("() => closeDlg()")
        pg.evaluate("() => { S.sid = 'P13'; renderSteps(); renderMain(); }")
        assert pg.evaluate("() => document.querySelector('#main').lastElementChild.classList.contains('finaliser')"), \
            "« Finaliser le travail » doit être tout en bas de la page"
        assert pg.evaluate("() => { const f = document.querySelector('.finaliser'); return [...document.querySelectorAll('#main textarea, #main input[type=text]')].every(t => t.compareDocumentPosition(f) & Node.DOCUMENT_POSITION_FOLLOWING); }"), \
            "« Finaliser le travail » doit venir après les champs de la fiche"
        pg.click("text=Finaliser le travail")
        pg.wait_for_selector(".fin-list li")
        assert pg.is_disabled("button.danger"), "le bouton de suppression doit attendre la case à cocher"
        pg.evaluate("() => closeDlg()")
        print("  fenêtres Réglages, Matériel, Presets, NOTES, Nouveau projet, Finaliser ouvertes")

        # 2b. choix des poses (S3) : blocs par niveau, cases, « voir » ouvre l'image
        pg.evaluate("() => { S.sid = 'S3'; S.edit = {}; renderSteps(); renderMain(); }")
        pg.wait_for_selector(".pose-bloc")
        assert pg.locator(".pose-bloc").count() >= 2 and pg.locator("img.pose-thumb").count() == 0
        ex0 = pg.evaluate("() => S.edit.S3[0].exclure")
        pg.locator(".pose-bloc.niv-mitigee summary input").click()          # écarter toutes les mitigées
        ex1 = pg.evaluate("() => S.edit.S3[0].exclure")
        pg.locator(".pose-bloc.niv-nette .pose-table input").first.click()  # garder un rejet net
        ex2 = pg.evaluate("() => S.edit.S3[0].exclure")
        assert ex0 != ex1 != ex2, (ex0, ex1, ex2)
        pg.locator(".pose-table .linkbtn").first.click()
        pg.wait_for_selector("#viewer:not(.hidden)")
        pg.wait_for_function("() => document.querySelector('#viewerImg').naturalWidth > 0", timeout=10000)
        if os.environ.get("CAPTURES"):
            pg.evaluate("() => document.querySelector('#viewer').classList.add('hidden')")
            pg.screenshot(path=os.path.join(os.environ["CAPTURES"], "poses.png"))
        pg.evaluate("() => document.querySelector('#viewer').classList.add('hidden')")
        print(f"  choix des poses : {ex0!r} -> {ex1!r} -> {ex2!r}, image ouverte sur demande")

        # 2c. « dis ce que tu veux » : une phrase toute faite change les réglages sans rien lancer
        pg.evaluate("() => { S.sid = 'P6N'; S.edit = {}; renderSteps(); renderMain(); }")
        pg.wait_for_selector(".intent .chip")
        before = pg.evaluate("() => S.edit.P6N.map(v => v.niveau)")
        pg.click(".intent .chip:has-text('Fond plus noir')")
        after = pg.evaluate("() => S.edit.P6N.map(v => v.niveau)")
        assert all(a == b - 3 for a, b in zip(after, before)), (before, after)
        assert "Niveau" in pg.inner_text(".intent-msg")
        print(f"  phrases toutes faites : niveau {before} -> {after}")

        # 2d. P7 : amas protégé dessiné à la souris
        pg.evaluate("() => { S.sid = 'P7'; S.edit = {}; renderSteps(); renderMain(); }")
        if pg.locator("text=Retirer la protection").count():
            pg.click("text=Retirer la protection")
            assert pg.evaluate("() => S.edit.P7.every(v => v.amas === '')")
        assert pg.locator(".amas-stage img").count() == 1, "l'image de l'amas doit être ouverte d'office"
        pg.wait_for_function("() => document.querySelector('.amas-stage img').naturalWidth > 0", timeout=10000)
        ab = pg.query_selector(".amas-stage img").bounding_box()
        pg.mouse.move(ab["x"] + ab["width"] * 0.5, ab["y"] + ab["height"] * 0.5)
        pg.mouse.down()
        pg.mouse.move(ab["x"] + ab["width"] * 0.6, ab["y"] + ab["height"] * 0.5, steps=5)
        pg.mouse.up()
        am = pg.evaluate("() => S.edit.P7.filter(v => v.methode === 'selection').map(v => v.amas)")
        x, y, r, n = (float(v) for v in am[0].split(","))
        assert all(a == am[0] for a in am) and 150 < x < 330 and r > 20 and n == 30, am   # image de test : 480 px
        print("  amas protégé dessiné :", am[0])

        # 2e. S4 : zone de mesure dessinée à la souris, pas de barre « Dis ce que tu veux » (étape de mesure)
        pg.evaluate("() => { S.sid = 'S4'; S.edit = {}; renderSteps(); renderMain(); }")
        pg.wait_for_selector(".zones .amas-stage img")
        pg.wait_for_function("() => document.querySelector('.zones .amas-stage img').naturalWidth > 0", timeout=10000)
        assert pg.locator(".intent-bar, .intent-msg").count() == 0 and pg.locator("text=Dis ce que tu veux").count() == 0, \
            "pas de barre d'intentions sur une étape de mesure"
        zb = pg.query_selector(".zones .amas-stage img").bounding_box()
        pg.mouse.move(zb["x"] + zb["width"] * 0.2, zb["y"] + zb["height"] * 0.3)
        pg.mouse.down()
        pg.mouse.move(zb["x"] + zb["width"] * 0.4, zb["y"] + zb["height"] * 0.5, steps=5)
        pg.mouse.up()
        zt = pg.evaluate("() => S.edit.S4[0].zones")
        assert zt.startswith("zone1:") and len(zt.split(":")[1].split(",")) == 4, zt
        print("  zone de mesure dessinée :", zt)

        # 3. cadrage : un cadre dessiné à la souris arrive dans les réglages
        pg.evaluate("() => { S.sid = 'P0'; S.edit = {}; renderSteps(); renderMain(); }")
        stage = pg.wait_for_selector(".crop-stage img, .cstage img, .cropper img")
        bb = stage.bounding_box()
        pg.mouse.move(bb["x"] + bb["width"] * 0.2, bb["y"] + bb["height"] * 0.2)
        pg.mouse.down()
        pg.mouse.move(bb["x"] + bb["width"] * 0.7, bb["y"] + bb["height"] * 0.8, steps=6)
        pg.mouse.up()
        rect = pg.evaluate("() => S.edit.P0[0].rect")
        assert rect and rect[2] > 50, rect
        print("  cadrage à la souris :", rect)

        # 4. réglage fin en direct : l'aperçu change quand un curseur bouge
        pg.evaluate("() => { S.sid = 'P8F'; S.edit = {}; renderSteps(); renderMain(); }")
        pg.wait_for_timeout(1500)
        sig = "() => { const c = document.querySelector('.live-canvas'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let s = 0; for (let i = 0; i < d.length; i += 97) s += d[i]; return s; }"
        a = pg.evaluate(sig)
        pg.eval_on_selector_all(".live-row input[type=range]", "els => { els[0].value = 0.8; els[0].dispatchEvent(new Event('input')); }")
        pg.wait_for_timeout(300)
        assert pg.evaluate(sig) != a, "l'aperçu en direct n'a pas changé"
        pg.click("text=Proposer des réglages")
        pg.wait_for_selector(".suggest-why div")
        print("  réglage fin : propositions affichées :", pg.inner_text(".suggest-why").replace("\n", " | ")[:140])
        print("  réglage fin : l'aperçu suit le curseur")

        # 5. retouches : un clic qui tremble pose un cercle
        pg.evaluate("() => { S.sid = 'P11'; S.edit = {}; renderSteps(); renderMain(); }")
        pg.wait_for_timeout(1500)
        cb = pg.query_selector(".ret-canvas").bounding_box()
        before = pg.evaluate("() => (S.edit.P11[0].liste || '').split('\\n').filter(Boolean).length")
        x, y = cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2
        pg.mouse.move(x, y)
        pg.mouse.down()
        pg.mouse.move(x + 5, y + 5, steps=3)
        pg.mouse.up()
        after = pg.evaluate("() => (S.edit.P11[0].liste || '').split('\\n').filter(Boolean).length")
        assert after == before + 1, (before, after)
        print("  retouches : cercle posé")

        # 6. comparaison : rideau avant/après et zoom synchronisé
        pg.evaluate("() => { S.sid = 'P5'; renderSteps(); renderMain(); }")
        pg.wait_for_timeout(500)
        pg.click("text=Comparer")
        pg.wait_for_selector(".cmp-stage")
        pg.wait_for_timeout(800)
        cs = pg.query_selector(".cmp-box").bounding_box()
        pg.mouse.click(cs["x"] + cs["width"] * 0.3, cs["y"] + cs["height"] / 2)
        split = pg.evaluate("() => document.querySelector('.cmp-stage').dataset.split")
        assert abs(float(split) - 0.3) < 0.05, split
        pg.mouse.move(cs["x"] + cs["width"] / 2, cs["y"] + cs["height"] / 2)
        pg.mouse.wheel(0, -300)
        pg.wait_for_timeout(200)
        assert float(pg.evaluate("() => document.querySelector('.cmp-stage').dataset.zoom")) > 1
        if os.environ.get("CAPTURES"):
            pg.screenshot(path=os.path.join(os.environ["CAPTURES"], "comparer.png"))
        pg.evaluate("() => closeDlg()")
        print("  comparaison : rideau et zoom")
        cards = pg.query_selector_all(".rcard .thumb-wrap")
        cards[0].scroll_into_view_if_needed()
        pg.wait_for_timeout(200)
        tb = cards[0].bounding_box()
        pg.mouse.move(tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2)
        pg.mouse.wheel(0, -300)
        pg.wait_for_timeout(200)
        tr = pg.evaluate("() => [...document.querySelectorAll('.rcard .thumb-wrap img')].map(i => i.style.transform)")
        assert len(set(tr)) == 1 and "scale" in tr[0] and tr[0] != "scale(1)", tr
        if os.environ.get("CAPTURES"):
            pg.screenshot(path=os.path.join(os.environ["CAPTURES"], "zoom_sync.png"))
        print(f"  zoom synchronisé sur {len(tr)} images")

        # 7. annulation depuis la barre d'état
        pg.evaluate("() => { S.sid = 'S3'; renderSteps(); renderMain(); }")
        pg.wait_for_timeout(300)
        pg.click("button:has-text('Lancer')")
        pg.wait_for_selector("#jobCancel:not([disabled])", timeout=10000)
        pg.wait_for_function("() => parseFloat(document.querySelector('#jobBar').style.width) > 0", timeout=15000)
        if os.environ.get("CAPTURES"):
            pg.wait_for_timeout(1500)
            pg.screenshot(path=os.path.join(os.environ["CAPTURES"], "progression.png"))
        pg.click("#jobCancel")
        pg.wait_for_function("() => document.querySelector('#jobStatus').textContent === 'annulé'", timeout=15000)
        print("  annulation : barre de progression puis arrêt")
        b.close()
finally:
    srv.terminate()
real = [e for e in errors if "favicon" not in e and "400 (Bad Request)" not in e]
if real:
    print("\n".join(real[:20]))
    raise SystemExit("ÉCHEC : erreurs JavaScript")
print("OK : interface vérifiée dans le navigateur")

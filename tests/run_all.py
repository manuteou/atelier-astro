"""Lance toute la batterie de tests (faux Siril) et résume. Lancer : python tests/run_all.py [--rapide]
--rapide : un scénario de bout en bout au lieu de six (pour une vérification après une petite modification)."""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
E2E = [["A", "nebuleuse"], ["B", "nebuleuse"], ["B", "galaxie"], ["A", "nebuleuse", "multi"], ["C", "galaxie", "multi"],
       ["B", "nebuleuse", "multi"], ["B", "galaxie", "multi"], ["B", "nebuleuse", "multi2"],
       ["A", "nebuleuse", "generique"]]
SUITE = [("import en vrac", ["test_import.py"]), ("annulation et progression", ["test_annulation.py"]),
         ("propositions de réglage fin", ["test_suggest.py"])]
SUITE += [("bout en bout " + " ".join(a), ["test_e2e.py"] + a) for a in (E2E[:1] if "--rapide" in sys.argv else E2E)]
if "--rapide" not in sys.argv:
    SUITE += [("bout en bout B nebuleuse, Siril qui plante", ["test_e2e.py", "B", "nebuleuse"], {"MOCK_CRASH_WEIGHT": "1"}),
              ("bout en bout B galaxie, cadres différents", ["test_e2e.py", "B", "galaxie"], {"MOCK_FRAMING": "1"}),
              ("bout en bout B nebuleuse multi, GraXpert cassé", ["test_e2e.py", "B", "nebuleuse", "multi"], {"MOCK_GRAXPERT_NAN": "1"})]
SUITE += [("interface dans le navigateur", ["test_ui.py"])]

fails = []
import os
for label, cmd, *env in SUITE:
    t0 = time.time()
    r = subprocess.run([sys.executable, str(HERE / cmd[0])] + cmd[1:], capture_output=True, text=True, cwd=HERE.parent,
                       env=dict(os.environ, **(env[0] if env else {})))
    ok = r.returncode == 0 and "OK" in r.stdout.splitlines()[-1] if r.stdout.strip() else False
    print(f"{'OK  ' if ok else 'ÉCHEC'} {label:42s} {time.time() - t0:5.0f} s")
    if not ok:
        fails.append(label)
        print("\n".join((r.stdout + r.stderr).splitlines()[-25:]))
print("\n" + ("Tout est vert." if not fails else f"{len(fails)} échec(s) : " + ", ".join(fails)))
sys.exit(1 if fails else 0)

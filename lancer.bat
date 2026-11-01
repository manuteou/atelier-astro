@echo off
REM Atelier astro : premier lancement = creation de l environnement Python (quelques minutes)
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist .venv (
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --disable-pip-version-check -q -r requirements.txt
python -m app.main
pause

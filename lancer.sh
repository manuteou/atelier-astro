#!/bin/sh
# Atelier astro (macOS / Linux)
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
python -m pip install --disable-pip-version-check -q -r requirements.txt
python -m app.main

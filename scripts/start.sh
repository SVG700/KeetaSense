#!/usr/bin/env bash
# KeetaSense: 'start' mode in this terminal (see scripts/launcher.py for options). Ctrl+C stops everything.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe   # Git Bash on Windows
[ -x "$PY" ] || { echo "[start] .venv not found - run scripts/setup.sh first."; exit 1; }
exec "$PY" scripts/launcher.py start "$@"

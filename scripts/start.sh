#!/usr/bin/env bash
# Start the backend (port 8000) and the dashboard (port 5173). Ctrl+C stops both.
# Run:  bash scripts/start.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe
[ -x "$PY" ] || { echo "[start] .venv not found - run scripts/setup.sh first."; exit 1; }
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

PIDS=()
cleanup() { echo; echo "[start] stopping..."; kill "${PIDS[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

"$PY" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
PIDS+=($!)
# run vite directly (not via npm) so stopping this script really stops it
(cd frontend && exec node node_modules/vite/bin/vite.js) &
PIDS+=($!)

echo "[start] Backend:   http://127.0.0.1:8000/docs"
echo "[start] Dashboard: http://localhost:5173   (Ctrl+C to stop)"
wait

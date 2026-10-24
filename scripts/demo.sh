#!/usr/bin/env bash
# Full live demo: fresh simulated history + backend + dashboard + edge device in mock mode.
# The mock trap sends a new tape section every 20 s; switch "Live" on in the dashboard.
# Run:  bash scripts/demo.sh        (Ctrl+C stops everything)
# Optional: CYCLES=2 bash scripts/demo.sh   -> stop the edge after 2 cycles (used for testing)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe
[ -x "$PY" ] || { echo "[demo] .venv not found - run scripts/setup.sh first."; exit 1; }
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 MOCK_HARDWARE=1

[ -f demo/sample_tape/tape_01.jpg ] || "$PY" -m demo.generate_sample_tape
echo "[demo] Loading 14 days of SIMULATED history ..."
"$PY" -m demo.seed --reset

PIDS=()
cleanup() { echo; echo "[demo] stopping..."; kill "${PIDS[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

"$PY" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
PIDS+=($!)
# run vite directly (not via npm) so stopping this script really stops it
(cd frontend && exec node node_modules/vite/bin/vite.js) &
PIDS+=($!)

echo "[demo] waiting for the backend ..."
for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
  sleep 1
done

echo "[demo] Dashboard: http://localhost:5173  (switch Live on). Ctrl+C to stop."
if [ -n "${CYCLES:-}" ]; then
  "$PY" -m edge.main --demo --cycles "$CYCLES"
else
  "$PY" -m edge.main --demo
fi

#!/usr/bin/env bash
# KeetaSense one-time setup for Linux / macOS (and Raspberry Pi - see edge/PI_SETUP.md).
# Run:  bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  PYTHON=$(command -v python3.12 || command -v python3 || true)
  if [ -z "$PYTHON" ]; then
    echo "[setup] ERROR: Python 3 not found. Install Python 3.12 and run again."; exit 1
  fi
  echo "[setup] Creating .venv with $PYTHON"
  "$PYTHON" -m venv .venv
fi
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe   # Git Bash on Windows
"$PY" -m pip --version >/dev/null 2>&1 || "$PY" -m ensurepip --upgrade

echo "[setup] Installing Python packages (CPU PyTorch first) ..."
"$PY" -m pip install --disable-pip-version-check torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
"$PY" -m pip install --disable-pip-version-check -r requirements.txt

[ -f .env ] || { cp .env.example .env; echo "[setup] Created .env from .env.example"; }

echo "[setup] Installing frontend packages ..."
npm --prefix frontend ci --no-fund --no-audit

[ -f demo/sample_tape/tape_01.jpg ] || "$PY" -m demo.generate_sample_tape

echo "[setup] Done. Next:  bash scripts/demo.sh  (full live demo)  or  bash scripts/start.sh  or  bash scripts/replay.sh"

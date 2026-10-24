"""KeetaSense ML package: dataset prep, training, evaluation and inference.

Importing this package:
  - loads settings from the project's .env file (if present), and
  - keeps Ultralytics' settings file inside the project (ml/.ultralytics)
    instead of the user's home folder, and
  - keeps Ultralytics offline at runtime (YOLO_OFFLINE=1), and
  - makes console output UTF-8 so Kannada text never crashes a print on Windows.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ML_DIR = Path(__file__).resolve().parent
load_dotenv(_ML_DIR.parent / ".env")  # never overrides variables already set
os.environ.setdefault("YOLO_CONFIG_DIR", str(_ML_DIR / ".ultralytics"))
# The running app must work with Wi-Fi off: stop Ultralytics' internet checks and
# usage statistics. ml/train.py switches this back on (it downloads pretrained weights).
os.environ.setdefault("YOLO_OFFLINE", "1")

# Windows consoles default to an old code page that cannot print Kannada or arrows;
# print UTF-8 instead (and replace anything unprintable rather than crash).
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream and (_stream.encoding or "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # not a normal text stream (e.g. captured by a test runner)

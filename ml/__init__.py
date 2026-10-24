"""KeetaSense ML package: dataset prep, training, evaluation and inference.

Importing this package:
  - loads settings from the project's .env file (if present), and
  - keeps Ultralytics' settings file inside the project (ml/.ultralytics)
    instead of the user's home folder, and
  - keeps Ultralytics offline at runtime (YOLO_OFFLINE=1).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

_ML_DIR = Path(__file__).resolve().parent
load_dotenv(_ML_DIR.parent / ".env")  # never overrides variables already set
os.environ.setdefault("YOLO_CONFIG_DIR", str(_ML_DIR / ".ultralytics"))
# The running app must work with Wi-Fi off: stop Ultralytics' internet checks and
# usage statistics. ml/train.py switches this back on (it downloads pretrained weights).
os.environ.setdefault("YOLO_OFFLINE", "1")

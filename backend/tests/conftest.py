"""Test setup: every test gets a fresh, empty SQLite database.

Environment variables are set BEFORE the app is imported so nothing touches
the real database, media folder or Telegram.
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="keetasense_tests_"))
os.environ["KEETA_MEDIA_DIR"] = str(_TMP / "media")
os.environ["KEETA_DB_PATH"] = str(_TMP / "unused.db")
os.environ["KEETA_WEIGHTS"] = str(_TMP / "no_weights.pt")   # force the demo detector
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""

import cv2  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import db  # noqa: E402
from ml import infer  # noqa: E402
from ml.synthetic import render_tape  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KEETA_DB_PATH", str(tmp_path / "test.db"))
    db.reset_engine()
    infer.reset_detector()
    from backend.main import app
    with TestClient(app) as c:   # "with" runs the startup code (tables + traps)
        yield c
    db.reset_engine()


def tape_jpeg(whitefly: int, macrolophus: int = 0, nesidiocoris: int = 0, seed: int = 1) -> bytes:
    """A synthetic tape image as JPEG bytes."""
    img, _ = render_tape({"whitefly": whitefly, "macrolophus": macrolophus,
                          "nesidiocoris": nesidiocoris}, 640, 640, seed=seed)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()

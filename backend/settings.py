"""Backend settings: paths from .env and the YAML config files.

Everything configurable lives in .env (secrets, paths) or config/*.yaml
(traps, insect classes, thresholds). This module just reads them.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # does not override variables that are already set


def _path(env_name: str, default: str) -> Path:
    p = Path(os.environ.get(env_name, default))
    return p if p.is_absolute() else ROOT / p


def db_path() -> Path:
    return _path("KEETA_DB_PATH", "backend/data/keetasense.db")


def media_dir() -> Path:
    return _path("KEETA_MEDIA_DIR", "backend/data/media")


def dashboard_dir() -> Path:
    """Built dashboard (npm run build). If it exists, the backend serves it at "/"."""
    return _path("KEETA_DASHBOARD_DIR", "frontend/dist")


def allow_demo_reset() -> bool:
    """POST /api/reset-demo wipes all data - allowed by default for the hackathon demo."""
    return os.environ.get("KEETA_ALLOW_RESET", "1").strip() == "1"


def cors_origins() -> list[str]:
    raw = os.environ.get("KEETA_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def telegram_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def telegram_chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def alert_languages() -> list[str]:
    return [l.strip() for l in os.environ.get("ALERT_LANGUAGES", "en,kn").split(",") if l.strip()]


@lru_cache(maxsize=1)
def traps_config() -> list[dict]:
    with open(ROOT / "config" / "traps.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["traps"]


def pests_yaml_path() -> Path:
    from ml.common import pests_yaml_path as path  # one definition for ML and backend
    return path()


@lru_cache(maxsize=1)
def pests_config() -> dict:
    with open(pests_yaml_path(), encoding="utf-8") as f:
        return yaml.safe_load(f)


def pest_display_name(pest: str, lang: str = "en") -> str:
    for c in pests_config()["classes"]:
        if c["name"] == pest:
            return c.get(f"display_{lang}") or c["name"]
    return pest


def reload_config() -> None:
    """Forget cached YAML so the next read sees edits (Settings page saves)."""
    from ml.common import load_pests_config
    pests_config.cache_clear()
    traps_config.cache_clear()
    load_pests_config.cache_clear()

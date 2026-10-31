"""Who uses the Telegram bot: chat id -> chosen trap and language.

A small JSON file (backend/data/bot_users.json) - enough for a few hundred
farmers, no extra database table needed. Used by the bot (to answer in the
right language) and by alerts.py (to send each subscriber the alerts for
their own trap, in their own language).
"""
from __future__ import annotations

import json
import threading

from backend import settings

_lock = threading.Lock()


def _file():
    return settings.db_path().parent / "bot_users.json"


def load() -> dict[str, dict]:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def get(chat_id: int | str) -> dict:
    return load().get(str(chat_id), {"lang": "en", "trap_id": None})


def update(chat_id: int | str, **changes) -> dict:
    with _lock:
        users = load()
        user = users.get(str(chat_id), {"lang": "en", "trap_id": None})
        user.update(changes)
        users[str(chat_id)] = user
        path = _file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(users, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
        return user


def subscribers(trap_id: str) -> list[tuple[str, str]]:
    """[(chat_id, lang)] of everyone following this trap."""
    return [(cid, u.get("lang", "en")) for cid, u in load().items() if u.get("trap_id") == trap_id]

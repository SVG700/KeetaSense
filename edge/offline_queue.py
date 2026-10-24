"""Local SQLite queue so no data is lost when the farm has no internet.

Every tape section and climate reading is first saved here. The sync step
tries to send pending items to the backend; on failure an item stays in the
queue and is retried later with exponential backoff (10 s, 20 s, 40 s ...
up to 10 minutes).
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

BACKOFF_BASE_S = 10
BACKOFF_MAX_S = 600


@dataclass
class QueueItem:
    id: int
    kind: str            # "section" or "climate"
    payload: dict
    image_path: str | None
    attempts: int


class OfflineQueue:
    def __init__(self, db_file: Path):
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_file))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pending (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                image_path TEXT,
                created REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_try REAL NOT NULL DEFAULT 0,
                last_error TEXT
            )""")
        self.conn.commit()

    def add(self, kind: str, payload: dict, image_path: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO pending (kind, payload, image_path, created) VALUES (?, ?, ?, ?)",
            (kind, json.dumps(payload), image_path, time.time()))
        self.conn.commit()
        return cur.lastrowid

    def due(self, now: float | None = None, limit: int = 50) -> list[QueueItem]:
        """Items whose retry time has come, oldest first."""
        rows = self.conn.execute(
            "SELECT id, kind, payload, image_path, attempts FROM pending "
            "WHERE next_try <= ? ORDER BY id LIMIT ?", (now or time.time(), limit)).fetchall()
        return [QueueItem(r[0], r[1], json.loads(r[2]), r[3], r[4]) for r in rows]

    def mark_sent(self, item_id: int) -> None:
        self.conn.execute("DELETE FROM pending WHERE id = ?", (item_id,))
        self.conn.commit()

    def mark_failed(self, item_id: int, error: str, now: float | None = None) -> float:
        """Record a failure and schedule the next attempt. Returns the delay in seconds."""
        attempts = self.conn.execute("SELECT attempts FROM pending WHERE id = ?", (item_id,)).fetchone()[0] + 1
        delay = backoff_seconds(attempts)
        self.conn.execute("UPDATE pending SET attempts = ?, next_try = ?, last_error = ? WHERE id = ?",
                          (attempts, (now or time.time()) + delay, error[:300], item_id))
        self.conn.commit()
        return delay

    def size(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM pending").fetchone()[0]

    def close(self) -> None:
        self.conn.close()


def backoff_seconds(attempts: int) -> float:
    """10 s after the 1st failure, 20 s after the 2nd, 40 s ... capped at 10 minutes."""
    return min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (attempts - 1))

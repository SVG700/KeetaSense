"""SQLite database connection. Works fully offline - it is just a file."""
from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from backend import settings

_engine = None


def get_engine():
    """Create the engine on first use (so tests can set KEETA_DB_PATH first)."""
    global _engine
    if _engine is None:
        path = settings.db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI handles requests on several threads
        _engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    return _engine


def reset_engine() -> None:
    """Drop the cached engine (used by tests to switch to a fresh database)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def init_db() -> None:
    from backend import models  # noqa: F401  (registers the tables)
    SQLModel.metadata.create_all(get_engine())
    _add_missing_columns()


# Columns added after the first release. create_all() does not change existing
# tables, so add them here; old databases keep working without a reset.
NEW_COLUMNS = {
    "tapesection": {
        "source": "VARCHAR NOT NULL DEFAULT 'live'",
        "quality_status": "VARCHAR",          # F1 image quality gate
        "quality_reasons": "JSON",
        "quality_metrics": "JSON",
        "detections": "JSON",                 # F3 scout corrections
        "corrected_counts": "JSON",
        "corrected_pest_total": "INTEGER",
        "corrected_predator_total": "INTEGER",
    },
    "alertlog": {
        "acknowledged_at": "DATETIME",        # F4 action logging
        "ack_action": "VARCHAR",
        "held_until": "DATETIME",             # F6 alert hygiene
        "realerted_at": "DATETIME",
    },
}


def _add_missing_columns() -> None:
    with get_engine().begin() as conn:
        for table, columns in NEW_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def get_session():
    """FastAPI dependency: one database session per request."""
    with Session(get_engine()) as session:
        yield session

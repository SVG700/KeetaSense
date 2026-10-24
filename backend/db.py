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


def get_session():
    """FastAPI dependency: one database session per request."""
    with Session(get_engine()) as session:
        yield session

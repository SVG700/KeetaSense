"""The demo seed script creates 14 simulated days for both traps."""
import sys

from sqlmodel import Session, select

from backend import db
from backend.models import ClimateReading, TapeSection


def test_seed_creates_simulated_history(tmp_path, monkeypatch):
    monkeypatch.setenv("KEETA_DB_PATH", str(tmp_path / "seed.db"))
    monkeypatch.setenv("KEETA_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(sys, "argv", ["seed", "--reset"])
    db.reset_engine()
    from demo import seed
    seed.main()
    with Session(db.get_engine()) as s:
        sections = s.exec(select(TapeSection)).all()
        assert len(sections) == len(seed.TRAPS) * seed.DAYS
        assert all(x.simulated for x in sections)
        assert {x.trap_id for x in sections} == set(seed.TRAPS)
        assert s.exec(select(ClimateReading)).first().simulated
    assert (tmp_path / "media" / "annotated").exists()
    db.reset_engine()

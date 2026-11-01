"""Database tables (SQLModel = SQLAlchemy tables + Pydantic validation).

Trap           - one physical (or simulated) sticky trap
TapeSection    - one photographed piece of tape = one day's catch
ClimateReading - one temperature/humidity reading from the DHT22
Decision       - the recommendation computed for a trap at a moment in time
AlertLog       - every alert we sent (or only logged, if Telegram is not set up)

Timestamps are stored as naive LOCAL time - the system runs offline on one
farm laptop, so there is only one time zone.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class Trap(SQLModel, table=True):
    id: str = Field(primary_key=True)              # e.g. "T1-polyhouse"
    name: str
    location: str = ""
    crop: str = ""
    target_pest: str = "whitefly"                  # key into pests.yaml thresholds
    simulated: bool = False                        # True -> dashboard shows "Simulated data"


class TapeSection(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    trap_id: str = Field(foreign_key="trap.id", index=True)
    timestamp: NaiveDatetime = Field(index=True)
    image_path: str                                # relative to the media folder
    annotated_path: str | None = None
    counts: dict = Field(default_factory=dict, sa_column=Column(JSON))  # per class
    pest_total: int = 0
    predator_total: int = 0
    detector_mode: str = "demo_detector"           # "yolo_sahi" or "demo_detector"
    simulated: bool = False
    # where it came from: live (real trap) | mock (mock hardware) | replay (recorded cycle
    # replayed on stage) | seed (demo/seed.py) | upload (posted by hand, e.g. curl)
    source: str = "live"
    # image quality gate (backend/image_quality.py): OK / WARN / BAD, why, and the measured numbers
    quality_status: str | None = None
    quality_reasons: list = Field(default_factory=list, sa_column=Column(JSON))
    quality_metrics: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # F3 scout corrections: the model's boxes are kept; corrected counts (if any) are used for decisions
    detections: list = Field(default_factory=list, sa_column=Column(JSON))
    corrected_counts: dict | None = Field(default=None, sa_column=Column(JSON))
    corrected_pest_total: int | None = None
    corrected_predator_total: int | None = None

    @property
    def effective_pest_total(self) -> int:
        return self.corrected_pest_total if self.corrected_pest_total is not None else self.pest_total

    @property
    def effective_predator_total(self) -> int:
        return self.corrected_predator_total if self.corrected_predator_total is not None else self.predator_total


SECTION_SOURCES = {"live", "mock", "replay", "seed", "upload"}


class Correction(SQLModel, table=True):
    """One scout edit on a tape section's boxes (F3 human-in-the-loop).

    action: add (new box), remove (a box was wrong), relabel (right box, wrong class).
    target: id of the box it changes - "m3" = model detection no. 3, "c12" = box added by correction 12."""
    id: int | None = Field(default=None, primary_key=True)
    section_id: int = Field(foreign_key="tapesection.id", index=True)
    action: str                                    # add | remove | relabel
    class_name: str | None = None                  # new class (add / relabel)
    bbox: list | None = Field(default=None, sa_column=Column(JSON))   # [x1, y1, x2, y2] pixels
    target: str | None = None                      # box id for remove / relabel
    author: str = "scout"
    created_at: NaiveDatetime = Field(default_factory=datetime.now)


class ClimateReading(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    trap_id: str = Field(foreign_key="trap.id", index=True)
    timestamp: NaiveDatetime = Field(index=True)
    temperature_c: float
    humidity_pct: float
    simulated: bool = False


class Decision(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    trap_id: str = Field(foreign_key="trap.id", index=True)
    timestamp: NaiveDatetime = Field(default_factory=datetime.now, index=True)
    action: str                                    # SPRAY | RELEASE_BIOCONTROL | WAIT
    reason: str
    details: dict = Field(default_factory=dict, sa_column=Column(JSON))


class AlertLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    trap_id: str = Field(foreign_key="trap.id", index=True)
    timestamp: NaiveDatetime = Field(default_factory=datetime.now)
    action: str
    previous_action: str | None = None
    language: str = "en"
    message: str
    status: str = "logged"                         # "sent" | "logged" (no token) | "failed"
    error: str | None = None

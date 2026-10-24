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

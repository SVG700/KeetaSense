"""Edge device settings, read from environment variables / the .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class EdgeConfig:
    mock_hardware: bool = field(default_factory=lambda: _bool("MOCK_HARDWARE", "1"))  # default ON
    trap_id: str = field(default_factory=lambda: os.environ.get("TRAP_ID", "T1-polyhouse"))
    backend_url: str = field(default_factory=lambda: os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/"))
    demo_cycle_seconds: float = field(default_factory=lambda: float(os.environ.get("DEMO_CYCLE_SECONDS", 20)))
    cycle_hours: float = field(default_factory=lambda: float(os.environ.get("CYCLE_HOURS", 24)))
    climate_minutes: float = field(default_factory=lambda: float(os.environ.get("CLIMATE_MINUTES", 30)))
    stepper_pins: list[int] = field(default_factory=lambda: [
        int(p) for p in os.environ.get("STEPPER_PINS", "17,18,27,22").split(",")])
    steps_per_section: int = field(default_factory=lambda: int(os.environ.get("STEPS_PER_SECTION", 2048)))
    step_delay_s: float = field(default_factory=lambda: float(os.environ.get("STEP_DELAY_S", 0.0015)))
    settle_seconds: float = field(default_factory=lambda: float(os.environ.get("SETTLE_SECONDS", 2)))
    dht22_pin: int = field(default_factory=lambda: int(os.environ.get("DHT22_PIN", 4)))
    led_pin: int | None = field(default_factory=lambda: int(os.environ["LED_PIN"]) if os.environ.get("LED_PIN") else None)
    local_detection: bool = field(default_factory=lambda: _bool("LOCAL_DETECTION", "1"))
    # mock camera images are SYNTHETIC drawings: count them with the demo detector even when
    # the real model is installed (set 1 if you put real tape photos in demo/sample_tape/)
    # MOCK only: inject a fault (blur, dark, glare, stuck, motor) to demo the quality gate / health alerts
    inject: str = field(default_factory=lambda: os.environ.get("MOCK_INJECT", "").strip().lower())
    mock_use_model: bool = field(default_factory=lambda: _bool("MOCK_USE_MODEL", "0"))
    data_dir: Path = field(default_factory=lambda: ROOT / os.environ.get("EDGE_DATA_DIR", "edge/data"))
    sample_dir: Path = field(default_factory=lambda: ROOT / "demo" / "sample_tape")

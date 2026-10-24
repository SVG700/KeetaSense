"""Fill the database with 14 days of SIMULATED history for 2 traps.

!!! Everything this script creates is SIMULATED: synthetic tape images,
!!! made-up climate readings. All rows are stored with simulated=True and
!!! the dashboard shows a "Simulated data" badge.

The stories (chosen so the dashboard shows two different decisions):
  T1-polyhouse  whiteflies build up in the warm polyhouse, but Macrolophus
                were released and are keeping pace  -> RELEASE BIOCONTROL
  T2-openfield  whiteflies build up with almost no predators -> SPRAY

Tape images are rendered by ml/synthetic.py and counted by the DEMO DETECTOR
(they are drawings, so the trained AI model would not recognise them), then
stored through the same code path as live data.

Usage:
    python -m demo.seed            # refuses if data already exists
    python -m demo.seed --reset    # wipe all data + images first (also: POST /api/reset-demo)
"""
from __future__ import annotations

import argparse
import logging
import math
import random
import shutil
from datetime import datetime, timedelta

from sqlmodel import Session, select

from backend import services, settings
from backend.db import get_engine, init_db
from backend.models import AlertLog, ClimateReading, Decision, TapeSection, Trap
from ml import infer
from ml.synthetic import render_tape

DAYS = 14

# Per-trap simulation settings
TRAPS = {
    "T1-polyhouse": {
        "temp_mean": 27.5, "temp_swing": 5.0,             # warm polyhouse
        "whitefly": lambda d: 6 * math.exp(0.15 * d),     # ~6 -> ~42 per day
        "macrolophus": lambda d: 0.4 + 0.45 * d,          # released, building up
        "nesidiocoris": lambda d: 0.2 + 0.15 * d,
    },
    "T2-openfield": {
        "temp_mean": 24.5, "temp_swing": 6.5,
        "whitefly": lambda d: 4 * math.exp(0.17 * d),     # ~4 -> ~36 per day
        "macrolophus": lambda d: 0.4,
        "nesidiocoris": lambda d: 0.3,
    },
}


def poisson(rng: random.Random, mean: float) -> int:
    """Random count with the given average (Knuth's method, fine for small means)."""
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def climate_for_day(rng: random.Random, day_start: datetime, cfg: dict, until: datetime):
    """Hourly readings: daily temperature cycle + a random offset for the day."""
    offset = rng.gauss(0, 1.2)
    for hour in range(24):
        t = day_start + timedelta(hours=hour)
        if t > until:
            break
        daily = math.cos((hour - 14) / 24 * 2 * math.pi)
        temp = cfg["temp_mean"] + offset + cfg["temp_swing"] * daily + rng.gauss(0, 0.3)
        hum = 68 - 14 * daily + rng.gauss(0, 2)
        yield t, round(temp, 1), round(min(98, max(25, hum)), 1)


def clear_all(session: Session) -> dict:
    """Delete every tape section, reading, decision and alert, and all stored images.

    Works while the backend is running (deletes rows instead of the database file,
    which Windows would refuse to delete while it is open)."""
    removed = {}
    for model in (AlertLog, Decision, ClimateReading, TapeSection):
        rows = session.exec(select(model)).all()
        removed[model.__name__] = len(rows)
        for row in rows:
            session.delete(row)
    session.commit()
    media = settings.media_dir()
    if media.exists():
        shutil.rmtree(media, ignore_errors=True)
    media.mkdir(parents=True, exist_ok=True)
    return removed


def seed_history(session: Session, seed: int = 7, log=print) -> int:
    """Create the 14-day SIMULATED history. Returns the number of tape sections created.

    The synthetic images are always counted by the DEMO DETECTOR (and labelled so):
    they are drawings, so the real AI model would not recognise them."""
    rng = random.Random(seed)
    now = datetime.now().replace(microsecond=0)
    services.sync_traps(session)
    created = 0
    for trap_id, cfg in TRAPS.items():
        trap = session.get(Trap, trap_id)
        if trap is None:
            log(f"[seed] trap {trap_id} is not in config/traps.yaml - skipped")
            continue
        for i in range(DAYS):
            d = DAYS - 1 - i                                  # days ago
            day_start = (now - timedelta(days=d)).replace(hour=0, minute=0, second=0)
            # the tape is photographed at 07:00 (or a few minutes ago, for today)
            shot = min(day_start.replace(hour=7), now - timedelta(minutes=5))
            for t, temp, hum in climate_for_day(rng, day_start, cfg, until=now):
                services.add_climate(session, trap, t, temp, hum, simulated=True)
            counts = {name: poisson(rng, cfg[name](i)) for name in ("whitefly", "macrolophus", "nesidiocoris")}
            img, _ = render_tape(counts, 1280, 800, seed=seed * 1000 + i + (0 if trap_id.startswith("T1") else 500))
            _, result, decision = services.process_section(
                session, trap, img, shot, simulated=True, notify=False, source="seed",
                detections=infer.demo_detect(img), detector_mode=infer.MODE_DEMO)
            created += 1
            log(f"[seed] {trap_id} {shot:%Y-%m-%d}: drawn {counts} -> counted pests={result.pest_total} "
                f"predators={result.predator_total} -> {decision['action']}")
    return created


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description="Seed 14 days of SIMULATED history.")
    ap.add_argument("--reset", action="store_true", help="delete all existing data and images first")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    init_db()
    with Session(get_engine()) as session:
        if args.reset:
            removed = clear_all(session)
            print(f"[seed] reset: removed {removed} and all images in {settings.media_dir()}")
        elif session.exec(select(TapeSection)).first() is not None:
            print("[seed] the database already has tape sections. Use --reset to start fresh.")
            return
        seed_history(session, args.seed)
    print("[seed] done. All data above is SIMULATED (simulated=True in the database).")


if __name__ == "__main__":
    main()

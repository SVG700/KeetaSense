"""F6 trap health + alert hygiene.

Heartbeats (POST /api/traps/{id}/heartbeat) keep one TrapHealth row per trap. From it:
    online            = last heartbeat within offline_after_intervals x capture interval
    tape remaining %  = 100 x (1 - steps used / total steps)
Problems -> alerts, ONCE per problem until it clears: TRAP_OFFLINE, TAPE_LOW, MOTOR_FAULT.

tick(session, now) runs every minute (scheduler thread in backend/main.py) and also
directly from the tests with a fake clock. It:
  1. checks every trap's health (offline is only noticed by the clock, not by a heartbeat)
  2. delivers alerts held during quiet hours, once quiet hours are over
  3. repeats ONCE any action alert nobody acknowledged within realert_after_hours
  4. sends one daily digest per trap at digest_hour:digest_minute
Limits: config/pests.yaml -> health and alert_hygiene.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import yaml
from sqlmodel import Session, select

from backend import alerts, settings
from backend.models import AlertLog, Trap, TrapHealth

log = logging.getLogger("keetasense.hygiene")

HEALTH_ALERTS = ("TRAP_OFFLINE", "TAPE_LOW", "MOTOR_FAULT")
NEEDS_ACK = ("SPRAY", "RELEASE_BIOCONTROL", "CHECK_TRAP") + HEALTH_ALERTS
TEMPLATES_FILE = Path(__file__).resolve().parent / "alert_templates.yaml"


def health_config() -> dict:
    return settings.pests_config()["health"]


@lru_cache(maxsize=1)
def _texts() -> dict:
    with open(TEMPLATES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Health (pure)
# ---------------------------------------------------------------------------
def health_status(h: TrapHealth | None, now: datetime, cfg: dict | None = None) -> dict:
    cfg = cfg or health_config()
    if h is None:
        return {"known": False, "online": None, "problems": []}
    limit = timedelta(seconds=float(h.capture_interval_s) * float(cfg["offline_after_intervals"]))
    silent = now - h.last_seen
    online = silent <= limit
    tape_pct = round(100 * (1 - h.tape_steps_used / h.tape_total_steps), 1) if h.tape_total_steps else None
    problems = []
    if not online:
        problems.append("TRAP_OFFLINE")
    if tape_pct is not None and tape_pct < float(cfg["tape_low_pct"]):
        problems.append("TAPE_LOW")
    if h.motor_fault:
        problems.append("MOTOR_FAULT")
    return {"known": True, "online": online, "last_seen": h.last_seen.isoformat(timespec="seconds"),
            "offline_minutes": None if online else round(silent.total_seconds() / 60),
            "offline_limit_minutes": round(limit.total_seconds() / 60),
            "queue_depth": h.queue_depth, "tape_remaining_pct": tape_pct,
            "tape_steps_used": h.tape_steps_used, "tape_total_steps": h.tape_total_steps,
            "motor_fault": h.motor_fault, "motor_fault_detail": h.motor_fault_detail,
            "capture_interval_s": h.capture_interval_s, "simulated": h.simulated, "problems": problems,
            "offline_after_intervals": cfg["offline_after_intervals"], "tape_low_pct": cfg["tape_low_pct"]}


def record_heartbeat(session: Session, trap: Trap, *, queue_depth: int, tape_steps_used: int, tape_total_steps: int,
                     motor_fault: bool, motor_fault_detail: str | None, capture_interval_s: float, simulated: bool,
                     now: datetime | None = None) -> dict:
    now = now or datetime.now()
    h = session.get(TrapHealth, trap.id) or TrapHealth(trap_id=trap.id, last_seen=now)
    h.last_seen, h.queue_depth = now, queue_depth
    h.tape_steps_used, h.tape_total_steps = tape_steps_used, tape_total_steps
    h.motor_fault, h.motor_fault_detail = motor_fault, motor_fault_detail if motor_fault else None
    h.capture_interval_s, h.simulated = capture_interval_s, simulated
    session.add(h)
    session.commit()
    check_health(session, trap, now)          # a motor fault / low tape is alerted at once
    return health_status(session.get(TrapHealth, trap.id), now)


# ---------------------------------------------------------------------------
# Alert texts
# ---------------------------------------------------------------------------
def health_text(lang: str, trap: Trap, problem: str, status: dict) -> str:
    t = _texts().get(lang) or _texts()["en"]
    minutes = status.get("offline_minutes") or 0
    duration = (f"{minutes} {t['unit_minutes']}" if minutes < 120
                else f"{round(minutes / 60, 1):g} {t['unit_hours']}")
    return t[problem].format(trap_name=trap.name, duration=duration, pct=f"{status.get('tape_remaining_pct') or 0:g}",
                             detail=status.get("motor_fault_detail") or "-").strip()


def digest_text(lang: str, trap: Trap, decision: dict, status: dict, now: datetime) -> str:
    t = _texts().get(lang) or _texts()["en"]
    pest = settings.pest_display_name(trap.target_pest, lang)
    lines = [t["digest_title"].format(trap_name=trap.name, date=now.strftime("%d-%m-%Y")),
             t["digest_action"].format(action=t[f"word_{decision['action']}"], pests=f"{decision['pests_per_day']:g}",
                                       predators=f"{decision['predators_per_day']:g}", pest_name=pest)]
    if status.get("known"):
        lines.append(t["digest_health"].format(
            state=t["word_online"] if status["online"] else t["word_offline"],
            pct="-" if status["tape_remaining_pct"] is None else f"{status['tape_remaining_pct']:g}",
            queue=status["queue_depth"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The periodic job
# ---------------------------------------------------------------------------
def check_health(session: Session, trap: Trap, now: datetime) -> list[str]:
    """Alert each NEW problem once; forget problems that cleared (so they alert again next time)."""
    h = session.get(TrapHealth, trap.id)
    if h is None:
        return []
    status = health_status(h, now)
    active = set(h.active_problems or [])
    new = [p for p in status["problems"] if p not in active]
    for problem in new:
        for lang in alerts.languages_for(trap.id):
            if lang in _texts():
                alerts.send_alert(session, trap.id, problem, None, lang, health_text(lang, trap, problem, status), now=now)
    h.active_problems = list(status["problems"])
    session.add(h)
    session.commit()
    return new


def release_held(session: Session, now: datetime) -> int:
    if alerts.quiet_until(now):
        return 0
    rows = session.exec(select(AlertLog).where(AlertLog.status == "held", AlertLog.held_until <= now)).all()
    for row in rows:
        alerts.deliver(session, row)
    return len(rows)


def realert(session: Session, now: datetime) -> int:
    """Repeat each unacknowledged action alert ONCE (not during quiet hours)."""
    if alerts.quiet_until(now):
        return 0
    after = timedelta(hours=float(alerts.hygiene_config()["realert_after_hours"]))
    rows = session.exec(select(AlertLog).where(
        AlertLog.action.in_(NEEDS_ACK), AlertLog.status.in_(("sent", "logged", "pending")),
        AlertLog.acknowledged_at.is_(None), AlertLog.realerted_at.is_(None),
        AlertLog.timestamp <= now - after)).all()
    n = 0
    for row in rows:
        if (row.previous_action or "").startswith("reminder:"):
            continue                                   # a reminder is never reminded again
        if row.action in HEALTH_ALERTS:                # fixing the trap counts as the answer
            h = session.get(TrapHealth, row.trap_id)
            if h is None or row.action not in (h.active_problems or []):
                continue
        row.realerted_at = now
        session.add(row)
        session.commit()
        t = _texts().get(row.language) or _texts()["en"]
        alerts.send_alert(session, row.trap_id, row.action, f"reminder:{row.id}", row.language,
                          t["reminder_prefix"] + "\n" + row.message, buttons=row.action in alerts.ACTIONABLE, now=now)
        n += 1
    return n


def send_digest(session: Session, now: datetime) -> int:
    c = alerts.hygiene_config()
    due = now.replace(hour=int(c["digest_hour"]), minute=int(c["digest_minute"]), second=0, microsecond=0)
    if now < due or alerts.quiet_until(now):
        return 0
    from backend import services                        # lazy: services imports alerts
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    n = 0
    for trap in session.exec(select(Trap).order_by(Trap.id)).all():
        done = session.exec(select(AlertLog).where(AlertLog.trap_id == trap.id, AlertLog.action == "DIGEST",
                                                   AlertLog.timestamp >= start)).first()
        if done:
            continue
        decision = services.compute_decision(session, trap)
        status = health_status(session.get(TrapHealth, trap.id), now)
        for lang in alerts.languages_for(trap.id):
            if lang in _texts():
                alerts.send_alert(session, trap.id, "DIGEST", None, lang, digest_text(lang, trap, decision, status, now),
                                  now=now)
        n += 1
    return n


def tick(session: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    new_problems = {}
    for trap in session.exec(select(Trap)).all():
        p = check_health(session, trap, now)
        if p:
            new_problems[trap.id] = p
    return {"new_problems": new_problems, "released": release_held(session, now),
            "reminders": realert(session, now), "digests": send_digest(session, now)}


def start_scheduler(engine, every_s: float = 60) -> threading.Event | None:
    """Run tick() every minute in a background thread (KEETA_SCHEDULER=off disables it)."""
    if os.environ.get("KEETA_SCHEDULER", "on").strip().lower() == "off":
        return None
    stop = threading.Event()

    def loop():
        while not stop.wait(every_s):
            try:
                with Session(engine) as s:
                    result = tick(s)
                if any(result.values()):
                    log.info("hygiene tick: %s", result)
            except Exception:
                log.exception("hygiene tick failed (will retry)")

    threading.Thread(target=loop, daemon=True, name="hygiene").start()
    return stop

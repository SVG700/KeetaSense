"""F4 farmer actions: what was done after an alert (sprayed / released / not yet).

Recorded from the Telegram alert buttons or the dashboard. Used for:
  - acknowledging alerts (the alert row gets acknowledged_at)
  - a cooldown: after sprayed/released, repeat SPRAY / BIOCONTROL alerts for that trap are
    held back for `cooldown_hours` (config/pests.yaml -> actions, PLACEHOLDER)
  - chart markers and an "effect" card: average whiteflies per tape section in the
    `effect_window_days` before vs after the action (pure function effect())
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session, select

from backend import settings
from backend.models import ActionLog, AlertLog, TapeSection

ACTIONS = ("sprayed", "released", "not_yet")
TREATMENTS = ("sprayed", "released")          # actions that start a cooldown and get an effect card
SOURCES = ("dashboard", "telegram", "seed")


class ActionError(ValueError):
    pass


def config() -> dict:
    return settings.pests_config()["actions"]


def record(session: Session, trap_id: str, action: str, quantity: float | None = None, note: str = "",
           source: str = "dashboard", alert_id: int | None = None, now: datetime | None = None,
           simulated: bool = False) -> ActionLog:
    if action not in ACTIONS:
        raise ActionError(f"action must be one of {ACTIONS}")
    if source not in SOURCES:
        raise ActionError(f"source must be one of {SOURCES}")
    if quantity is not None and quantity < 0:
        raise ActionError("quantity cannot be negative")
    now = now or datetime.now()
    row = ActionLog(trap_id=trap_id, action=action, quantity=quantity, note=(note or "")[:500], timestamp=now,
                    source=source, alert_id=alert_id, simulated=simulated)
    session.add(row)
    # acknowledge the alert it answers, or every open alert of this trap
    q = select(AlertLog).where(AlertLog.trap_id == trap_id, AlertLog.acknowledged_at.is_(None),
                               AlertLog.timestamp <= now)
    if alert_id is not None:
        q = q.where(AlertLog.id == alert_id)
    for a in session.exec(q).all():
        a.acknowledged_at, a.ack_action = now, action
        session.add(a)
    session.commit()
    session.refresh(row)
    return row


def cooldown_until(session: Session, trap_id: str, now: datetime | None = None) -> datetime | None:
    """End of the cooldown after the latest sprayed/released action, or None if not in cooldown."""
    now = now or datetime.now()
    last = session.exec(select(ActionLog).where(ActionLog.trap_id == trap_id, ActionLog.action.in_(TREATMENTS),
                                                ActionLog.timestamp <= now)
                        .order_by(ActionLog.timestamp.desc())).first()
    if last is None:
        return None
    until = last.timestamp + timedelta(hours=float(config()["cooldown_hours"]))
    return until if until > now else None


def effect(sections: list[tuple[datetime, float]], when: datetime, days: float) -> dict:
    """Average whiteflies per tape section in the `days` before vs after `when`.

    sections: (timestamp, pests) of the trap's tape sections (each = one day's catch)."""
    before = [p for t, p in sections if when - timedelta(days=days) <= t < when]
    after = [p for t, p in sections if when < t <= when + timedelta(days=days)]
    b = round(sum(before) / len(before), 1) if before else None
    a = round(sum(after) / len(after), 1) if after else None
    status = "ok" if before and after else ("waiting_for_data" if before else "no_data_before")
    change = round((a - b) / b * 100, 1) if (a is not None and b) else None
    return {"before_avg": b, "after_avg": a, "change_pct": change, "n_before": len(before), "n_after": len(after),
            "days": days, "status": status}


def to_dict(row: ActionLog) -> dict:
    return {"id": row.id, "trap_id": row.trap_id, "action": row.action, "quantity": row.quantity, "note": row.note,
            "timestamp": row.timestamp.isoformat(timespec="seconds"), "source": row.source,
            "alert_id": row.alert_id, "simulated": row.simulated}


def history(session: Session, trap_id: str, since: datetime | None = None) -> list[dict]:
    q = select(ActionLog).where(ActionLog.trap_id == trap_id)
    if since:
        q = q.where(ActionLog.timestamp >= since)
    rows = session.exec(q.order_by(ActionLog.timestamp)).all()
    sections = [(s.timestamp, s.effective_pest_total) for s in
                session.exec(select(TapeSection).where(TapeSection.trap_id == trap_id)).all()]
    days = float(config()["effect_window_days"])
    out = []
    for r in rows:
        d = to_dict(r)
        d["effect"] = effect(sections, r.timestamp, days) if r.action in TREATMENTS else None
        out.append(d)
    return out

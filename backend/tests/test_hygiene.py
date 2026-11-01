"""F6 trap health + alert hygiene, driven by a fake clock (hygiene.tick(session, now))."""
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

from backend import alerts, db, hygiene
from backend.models import AlertLog, TapeSection, Trap, TrapHealth

TRAP = "T1-polyhouse"
T0 = datetime(2026, 11, 2, 10, 0)            # a Monday morning, outside quiet hours and after the digest
HOUR = 3600


def beat(s, now, *, used=0, total=1000, motor=False, interval=HOUR, trap=TRAP):
    return hygiene.record_heartbeat(s, s.get(Trap, trap), queue_depth=2, tape_steps_used=used, tape_total_steps=total,
                                    motor_fault=motor, motor_fault_detail="stall" if motor else None,
                                    capture_interval_s=interval, simulated=True, now=now)


def alerts_of(s, action, reminders=True):
    rows = s.exec(select(AlertLog).where(AlertLog.action == action).order_by(AlertLog.id)).all()
    return rows if reminders else [a for a in rows if not (a.previous_action or "").startswith("reminder:")]


@pytest.fixture
def session(client):
    with Session(db.get_engine()) as s:
        yield s


@pytest.fixture
def no_digest(monkeypatch):
    """Keep the daily digest out of tests about other things."""
    monkeypatch.setattr(hygiene, "send_digest", lambda s, now: 0)


# --- health status (pure) ----------------------------------------------------------------
def test_health_status_online_tape_and_problems():
    cfg = {"offline_after_intervals": 2, "tape_low_pct": 15}
    h = TrapHealth(trap_id=TRAP, last_seen=T0, tape_steps_used=900, tape_total_steps=1000, capture_interval_s=HOUR)
    st = hygiene.health_status(h, T0 + timedelta(hours=2), cfg)            # exactly 2 x interval: still online
    assert st["online"] is True and st["tape_remaining_pct"] == 10.0 and st["problems"] == ["TAPE_LOW"]
    st = hygiene.health_status(h, T0 + timedelta(hours=2, minutes=1), cfg)
    assert st["online"] is False and st["offline_minutes"] == 121 and "TRAP_OFFLINE" in st["problems"]
    h.motor_fault, h.tape_steps_used = True, 100
    assert hygiene.health_status(h, T0, cfg)["problems"] == ["MOTOR_FAULT"]
    assert hygiene.health_status(None, T0, cfg) == {"known": False, "online": None, "problems": []}


def test_heartbeat_endpoint_and_trap_summary(client):
    r = client.post(f"/api/traps/{TRAP}/heartbeat", json={"queue_depth": 3, "tape_steps_used": 250,
                                                         "tape_total_steps": 1000, "capture_interval_s": 20,
                                                         "simulated": True})
    assert r.status_code == 200 and r.json()["online"] is True and r.json()["tape_remaining_pct"] == 75.0
    trap = next(t for t in client.get("/api/traps").json() if t["id"] == TRAP)
    assert trap["health"]["queue_depth"] == 3 and trap["health"]["simulated"] is True
    assert client.get("/api/traps/T2-openfield/health").json()["known"] is False
    assert client.post("/api/traps/nope/heartbeat", json={}).status_code == 404
    assert client.post(f"/api/traps/{TRAP}/heartbeat", json={"queue_depth": -1}).status_code == 422


# --- health alerts: once per problem ------------------------------------------------------------
def test_offline_alert_once_then_again_after_recovery(session, no_digest):
    beat(session, T0)
    assert hygiene.tick(session, T0 + timedelta(hours=1, minutes=59))["new_problems"] == {}
    result = hygiene.tick(session, T0 + timedelta(hours=2, minutes=1))
    assert result["new_problems"] == {TRAP: ["TRAP_OFFLINE"]}
    first = alerts_of(session, "TRAP_OFFLINE")
    assert first and {a.language for a in first} == set(alerts.languages_for(TRAP))
    assert "no heartbeat for 2 hours" in [a for a in first if a.language == "en"][0].message
    assert hygiene.tick(session, T0 + timedelta(hours=5))["reminders"] == 0   # 3 h: no repeat yet
    assert len(alerts_of(session, "TRAP_OFFLINE")) == len(first)
    assert hygiene.tick(session, T0 + timedelta(hours=6, minutes=1))["reminders"] == len(first)  # still offline: 1 reminder
    beat(session, T0 + timedelta(hours=7))                                 # back online: problem cleared
    assert session.get(TrapHealth, TRAP).active_problems == []
    hygiene.tick(session, T0 + timedelta(hours=9, minutes=1))              # offline again -> alerted again
    assert len(alerts_of(session, "TRAP_OFFLINE", reminders=False)) == 2 * len(first)


def test_health_alert_not_repeated_after_the_problem_cleared(session, no_digest):
    beat(session, T0, motor=True)
    beat(session, T0 + timedelta(hours=1))                                 # motor fixed
    assert hygiene.tick(session, T0 + timedelta(hours=5))["reminders"] == 0


def test_tape_low_and_motor_fault_alert_at_heartbeat(session):
    st = beat(session, T0, used=860, motor=True)                           # 14 % left (< 15 %)
    assert set(st["problems"]) == {"TAPE_LOW", "MOTOR_FAULT"}
    n = len(alerts.languages_for(TRAP))
    assert len(alerts_of(session, "TAPE_LOW")) == n and len(alerts_of(session, "MOTOR_FAULT")) == n
    en = [a for a in alerts_of(session, "TAPE_LOW") if a.language == "en"][0]
    assert "14%" in en.message
    beat(session, T0 + timedelta(minutes=20), used=870, motor=True)        # same problems: no new alerts
    assert len(alerts_of(session, "TAPE_LOW")) == n and len(alerts_of(session, "MOTOR_FAULT")) == n
    beat(session, T0 + timedelta(minutes=40), used=0)                      # new roll, motor fixed
    assert session.get(TrapHealth, TRAP).active_problems == []


# --- quiet hours ----------------------------------------------------------------------------------
def test_quiet_until_wraps_midnight(monkeypatch):
    monkeypatch.setenv("KEETA_QUIET_HOURS", "on")
    assert alerts.quiet_until(datetime(2026, 11, 2, 20, 59)) is None
    assert alerts.quiet_until(datetime(2026, 11, 2, 21, 0)) == datetime(2026, 11, 3, 6, 0)
    assert alerts.quiet_until(datetime(2026, 11, 3, 3, 0)) == datetime(2026, 11, 3, 6, 0)
    assert alerts.quiet_until(datetime(2026, 11, 3, 6, 0)) is None
    monkeypatch.setenv("KEETA_QUIET_HOURS", "off")
    assert alerts.quiet_until(datetime(2026, 11, 3, 3, 0)) is None


def test_alert_in_quiet_hours_is_held_then_delivered(session, monkeypatch, no_digest):
    monkeypatch.setenv("KEETA_QUIET_HOURS", "on")
    night = datetime(2026, 11, 2, 22, 30)
    row = alerts.send_alert(session, TRAP, "SPRAY", "WAIT", "en", "spray now", now=night)
    assert row.status == "held" and row.held_until == datetime(2026, 11, 3, 6, 0)
    assert hygiene.tick(session, night + timedelta(hours=3))["released"] == 0
    assert hygiene.tick(session, datetime(2026, 11, 3, 6, 1))["released"] == 1
    session.refresh(row)
    assert row.status == "logged"                                           # delivered (no Telegram in tests)


# --- one re-alert if not acknowledged --------------------------------------------------------------
def test_unacknowledged_alert_is_repeated_once(session, no_digest):
    a = alerts.send_alert(session, TRAP, "SPRAY", "WAIT", "en", "Action: SPRAY", buttons=True, now=T0)
    b = alerts.send_alert(session, TRAP, "SPRAY", "WAIT", "kn", "ಕ್ರಮ: ಸಿಂಪಡಿಸಿ", buttons=True, now=T0)
    b.acknowledged_at, b.ack_action = T0 + timedelta(hours=1), "sprayed"
    session.add(b)
    session.commit()
    alerts.send_alert(session, TRAP, "WAIT", "SPRAY", "en", "Action: WAIT", now=T0)   # WAIT never needs an answer
    assert hygiene.tick(session, T0 + timedelta(hours=3, minutes=59))["reminders"] == 0
    assert hygiene.tick(session, T0 + timedelta(hours=4))["reminders"] == 1
    reminder = alerts_of(session, "SPRAY")[-1]
    assert reminder.previous_action == f"reminder:{a.id}" and reminder.message.startswith("🔁")
    assert hygiene.tick(session, T0 + timedelta(hours=20))["reminders"] == 0   # once only; never remind a reminder


def test_no_reminder_during_quiet_hours(session, monkeypatch, no_digest):
    monkeypatch.setenv("KEETA_QUIET_HOURS", "on")
    alerts.send_alert(session, TRAP, "SPRAY", "WAIT", "en", "Action: SPRAY", now=datetime(2026, 11, 2, 16, 0))
    assert hygiene.tick(session, datetime(2026, 11, 2, 23, 0))["reminders"] == 0
    assert hygiene.tick(session, datetime(2026, 11, 3, 6, 0))["reminders"] == 1


# --- daily digest ---------------------------------------------------------------------------------
def test_daily_digest_once_per_day_at_configured_time(session):
    traps = len(session.exec(select(Trap)).all())
    beat(session, datetime(2026, 11, 3, 6, 30), used=500)
    assert hygiene.tick(session, datetime(2026, 11, 3, 6, 59))["digests"] == 0
    assert hygiene.tick(session, datetime(2026, 11, 3, 7, 0))["digests"] == traps
    assert hygiene.tick(session, datetime(2026, 11, 3, 9, 0))["digests"] == 0
    en = [a for a in alerts_of(session, "DIGEST") if a.language == "en" and a.trap_id == TRAP][0]
    assert "03-11-2026" in en.message and "tape left 50%" in en.message
    assert hygiene.tick(session, datetime(2026, 11, 4, 7, 5))["digests"] == traps


def test_health_texts_exist_in_every_language():
    t = hygiene._texts()
    keys = ("TRAP_OFFLINE", "TAPE_LOW", "MOTOR_FAULT", "digest_title", "digest_action", "digest_health",
            "word_SPRAY", "word_RELEASE_BIOCONTROL", "word_WAIT", "word_CHECK_TRAP", "word_online", "word_offline",
            "reminder_prefix", "unit_hours", "unit_minutes")
    for lang in ("en", "kn", "hi", "ta"):
        assert all(k in t[lang] for k in keys), lang


# --- morning summary: yesterday's catch with its time window ---------------------------------------
MORNING = datetime(2026, 11, 3, 7, 0)


def add_section(s, when, pests, predators=0, **extra):
    s.add(TapeSection(trap_id=TRAP, timestamp=when, image_path="x.jpg", pest_total=pests, predator_total=predators,
                      **extra))
    s.commit()


def digest_en(s, now=MORNING):
    hygiene.tick(s, now)
    return [a for a in alerts_of(s, "DIGEST") if a.language == "en" and a.trap_id == TRAP][-1].message


def test_digest_reports_yesterdays_catch_and_window(session):
    add_section(session, datetime(2026, 11, 1, 6, 55), 50, 4)
    add_section(session, datetime(2026, 11, 2, 6, 58), 31, 3)              # the day before yesterday -> yesterday
    add_section(session, datetime(2026, 11, 3, 7, 30), 99)                 # after the summary: not reported yet
    msg = digest_en(session)
    assert msg.splitlines()[0] == "📋 KeetaSense morning summary - Polyhouse trap - 03-11-2026"
    assert "Caught from 06:55 01-11 to 06:58 02-11: 31 Whitefly, 3 predators." in msg
    assert "3-day average" in msg
    kn = [a for a in alerts_of(session, "DIGEST") if a.language == "kn" and a.trap_id == TRAP][-1].message
    assert "06:55 01-11 ರಿಂದ 06:58 02-11 ವರೆಗೆ ಹಿಡಿದವು: 31" in kn


def test_digest_uses_scout_corrected_count(session):
    add_section(session, datetime(2026, 11, 2, 7, 0), 20, 1, corrected_pest_total=17, corrected_predator_total=2)
    msg = digest_en(session)
    assert "Caught from new tape to 07:00 02-11: 17 Whitefly, 2 predators. (corrected by scout)" in msg


def test_digest_bad_photo_and_no_new_photo(session):
    add_section(session, datetime(2026, 11, 1, 7, 0), 20)
    add_section(session, datetime(2026, 11, 2, 7, 0), 0, quality_status="BAD",
                quality_reasons=[{"code": "blur", "level": "BAD"}])
    assert "The photo for 07:00 01-11 to 07:00 02-11 is not usable (" in digest_en(session)
    later = datetime(2026, 11, 4, 7, 0)                                    # 48 h after the last photo (> 36 h)
    assert "No new tape photo since 07:00 02-11 - check the trap." in digest_en(session, later)


def test_digest_without_any_photo(session):
    assert "No tape photo yet." in digest_en(session)

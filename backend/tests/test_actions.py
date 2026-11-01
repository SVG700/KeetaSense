"""F4 action logging: Telegram callback handler, cooldown, before/after effect."""
from datetime import datetime, timedelta

from sqlmodel import Session

from backend import actions, alerts, db, telegram_bot
from backend.tests.conftest import tape_jpeg

TRAP = "T1-polyhouse"
T0 = datetime(2026, 11, 1, 8, 0)


# --- Telegram callback handler (pure) ------------------------------------------------
def test_parse_ack():
    assert telegram_bot.parse_ack("ack|12|T1-polyhouse|sprayed") == (12, "T1-polyhouse", "sprayed")
    for bad in ("ack|x|T1|sprayed", "ack|1|T1|burned", "lang:kn", "ack|1|T1", ""):
        assert telegram_bot.parse_ack(bad) is None, bad


def test_handle_ack_records_and_answers_in_language():
    calls = []
    post = lambda trap, action, alert_id: calls.append((trap, action, alert_id)) or True
    assert telegram_bot.handle_ack("ack|7|T2-openfield|released", "kn", post) == \
        telegram_bot.MESSAGES["kn"]["ack_done"].format(action=telegram_bot.ACTION_WORDS["kn"]["released"])
    assert calls == [("T2-openfield", "released", 7)]
    assert telegram_bot.handle_ack("ack|8|T2-openfield|not_yet", "hi", post) == telegram_bot.MESSAGES["hi"]["ack_not_yet"]
    assert telegram_bot.handle_ack("ack|9|T2|sprayed", "en", lambda *a: False) == telegram_bot.MESSAGES["en"]["offline"]
    assert telegram_bot.handle_ack("rubbish", "ta", post) == telegram_bot.MESSAGES["ta"]["help"]


def test_alert_buttons_fit_telegram_limits():
    buttons = alerts.ack_buttons(123456, "T3-hesaraghatta", "kn")
    assert [d.split("|")[-1] for _, d in buttons] == ["sprayed", "released", "not_yet"]
    assert all(len(d.encode()) <= 64 for _, d in buttons)          # Telegram callback_data limit
    assert buttons[0][0] == "✅ ಸಿಂಪಡಿಸಿದೆ"


# --- before / after effect (pure) --------------------------------------------------------
def test_effect_before_after_three_days():
    sections = [(T0 + timedelta(days=d), p) for d, p in [(-4, 99), (-3, 30), (-2, 40), (-1, 50), (1, 20), (2, 10),
                                                          (3, 0), (4, 99)]]
    e = actions.effect(sections, T0, 3)
    assert (e["before_avg"], e["after_avg"], e["n_before"], e["n_after"]) == (40.0, 10.0, 3, 3)
    assert e["change_pct"] == -75.0 and e["status"] == "ok"
    waiting = actions.effect(sections[:4], T0, 3)
    assert waiting["status"] == "waiting_for_data" and waiting["after_avg"] is None


# --- through the API: record, acknowledge, cooldown -------------------------------------------
def post_section(client, n, seed):
    assert client.post("/api/sections", files={"image": ("t.jpg", tape_jpeg(n, 0, seed=seed), "image/jpeg")},
                       data={"trap_id": TRAP}).status_code == 200


def test_action_api_and_acknowledgement(client):
    for i in range(3):
        post_section(client, 40, 30 + i)                          # SPRAY alert (en + kn)
    alert_id = [a for a in client.get("/api/alerts").json() if a["trap_id"] == TRAP][0]["id"]
    r = client.post(f"/api/traps/{TRAP}/actions", json={"action": "sprayed", "quantity": 1.5, "note": "neem oil",
                                                         "source": "telegram", "alert_id": alert_id})
    assert r.status_code == 200 and r.json()["cooldown_until"] is not None
    acked = {a["id"]: a for a in client.get("/api/alerts").json()}[alert_id]
    assert acked["ack_action"] == "sprayed" and acked["acknowledged_at"]
    body = client.get(f"/api/traps/{TRAP}/actions").json()
    assert body["actions"][0]["note"] == "neem oil" and body["actions"][0]["effect"]["status"] == "waiting_for_data"
    assert client.get(f"/api/traps/{TRAP}/history").json()["actions"][0]["action"] == "sprayed"
    for bad in ({"action": "burned"}, {"action": "sprayed", "quantity": -1}, {"action": "sprayed", "source": "seed"},
                {"action": "sprayed", "source": "fax"}):
        assert client.post(f"/api/traps/{TRAP}/actions", json=bad).status_code == 422, bad
    assert client.post("/api/traps/nope/actions", json={"action": "sprayed"}).status_code == 404


def test_cooldown_suppresses_repeat_alerts_then_expires(client):
    with Session(db.get_engine()) as s:
        actions.record(s, TRAP, "sprayed", now=T0)
        assert actions.cooldown_until(s, TRAP, T0 + timedelta(hours=1)) == T0 + timedelta(hours=48)
        assert actions.cooldown_until(s, TRAP, T0 + timedelta(hours=49)) is None
        actions.record(s, TRAP, "not_yet", now=T0 + timedelta(hours=2))        # does not restart it
        assert actions.cooldown_until(s, TRAP, T0 + timedelta(hours=47)) == T0 + timedelta(hours=48)


def test_alert_is_suppressed_during_cooldown(client):
    client.post(f"/api/traps/{TRAP}/actions", json={"action": "released"})      # cooldown starts now
    for i in range(3):
        post_section(client, 40, 40 + i)                                         # decision -> SPRAY
    spray = [a for a in client.get("/api/alerts").json() if a["trap_id"] == TRAP and a["action"] == "SPRAY"]
    assert spray and all(a["status"] == "suppressed" and a["error"].startswith("cooldown until") for a in spray)

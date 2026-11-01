"""F5 decision intelligence (cost of harm, release dosing) and the What-if simulator."""
import json
from datetime import date, datetime, timedelta

from sqlmodel import Session, func, select

from backend import db, decision_support
from backend.decision_engine import RELEASE_BIOCONTROL, SPRAY, WAIT
from backend.models import AlertLog, Decision, TapeSection
from backend.tests.conftest import tape_jpeg

TRAP = "T1-polyhouse"
CFG = {"area_per_trap_m2": 1000, "predators_in_field_per_trapped": 40, "release_rate_per_m2": 2,
       "release_class": "macrolophus", "recheck_days": 7}


def test_cost_of_harm_and_release_dose():
    today = date(2026, 11, 4)
    s = decision_support.support(SPRAY, 1.5, CFG, today)
    assert s["predators_at_risk"] == 60 and "60 predators" in s["text"]
    r = decision_support.support(RELEASE_BIOCONTROL, 5, CFG, today)
    assert r["release_count"] == 2000 and r["recheck_date"] == "2026-11-11" and "2000 macrolophus" in r["text"]
    w = decision_support.support(WAIT, 3, CFG, today)
    assert w["text"] == "" and w["release_count"] is None


def boxes(n_pests, n_preds, conf):
    out = [{"class_name": "whitefly", "confidence": conf, "bbox": [10.0 * i, 10, 10.0 * i + 8, 18]} for i in range(n_pests)]
    out += [{"class_name": "macrolophus", "confidence": conf, "bbox": [10.0 * i, 40, 10.0 * i + 20, 50]} for i in range(n_preds)]
    return out


def build_live_trap(client, sections):
    day = datetime.now() - timedelta(days=6)
    for i in range(6):                                     # 6 days of climate
        for hour, temp in ((5, 19.0 + i % 3), (14, 31.0 - i % 2)):
            client.post("/api/climate", json={"trap_id": TRAP, "temperature_c": temp, "humidity_pct": 60,
                                              "timestamp": (day + timedelta(days=i)).replace(hour=hour).isoformat()})
    for k, (p, q, conf) in enumerate(sections):
        r = client.post("/api/sections", files={"image": ("t.jpg", tape_jpeg(0, seed=50 + k), "image/jpeg")},
                        data={"trap_id": TRAP, "detections_json": json.dumps(boxes(p, q, conf)),
                              "detector_mode": "yolo_sahi"})
        assert r.status_code == 200


def simulate_body_from_history(client):
    h = client.get(f"/api/traps/{TRAP}/history").json()
    live = client.get(f"/api/traps/{TRAP}/decision").json()
    secs = h["sections"][-3:]
    return live, {"target_pest": "whitefly",
                  "catches": [{"pests": s["effective_pest_total"], "predators": s["effective_predator_total"]} for s in secs],
                  "temps": [{"date": c["date"], "tmin": c["tmin"], "tmax": c["tmax"]} for c in h["climate_daily"]],
                  "pest_confidence": live["uncertainty"]["pest_confidence"],
                  "predator_confidence": live["uncertainty"]["predator_confidence"]}


KEYS = ["action", "reason", "pests_per_day", "predators_per_day", "ratio", "window_days_used", "degree_days",
        "uncertainty", "borderline", "support"]


def test_simulate_equals_live_engine_for_identical_inputs(client):
    for sections in ([(40, 2, 0.9), (42, 2, 0.9), (44, 1, 0.9)],        # SPRAY (cost of harm)
                     [(40, 6, 0.95), (38, 7, 0.95), (36, 6, 0.95)],     # RELEASE BIOCONTROL (dose)
                     [(26, 0, 0.8), (27, 0, 0.8), (28, 0, 0.8)],        # borderline
                     [(4, 1, 0.9), (5, 0, 0.9), (3, 1, 0.9)]):          # WAIT
        build_live_trap(client, sections)
        live, body = simulate_body_from_history(client)
        sim = client.post("/api/decision/simulate", json=body).json()
        assert sim["simulation"] is True
        for k in KEYS:
            assert sim["decision"][k] == live[k], (sections, k)


def test_simulate_slider_mode_writes_nothing(client):
    with Session(db.get_engine()) as s:
        before = [s.exec(select(func.count()).select_from(m)).one() for m in (TapeSection, Decision, AlertLog)]
    r = client.post("/api/decision/simulate", json={"crop": "tomato", "pests_per_day": 60, "predators_per_day": 2,
                                                    "temperature_c": 28, "days": 10, "pest_confidence": 0.9})
    assert r.status_code == 200
    d = r.json()["decision"]
    assert d["action"] == SPRAY and d["ratio"] == 30 and d["support"]["predators_at_risk"] == 80
    assert d["degree_days"]["accumulated"] == 180          # (28 - 10) x 10 days
    with Session(db.get_engine()) as s:
        after = [s.exec(select(func.count()).select_from(m)).one() for m in (TapeSection, Decision, AlertLog)]
    assert before == after


def test_simulate_validation(client):
    assert client.post("/api/decision/simulate", json={"pests_per_day": 5, "predators_per_day": 1}).status_code == 422
    assert client.post("/api/decision/simulate", json={"crop": "mango", "pests_per_day": 5,
                                                       "predators_per_day": 1}).status_code == 422
    assert client.post("/api/decision/simulate", json={"crop": "tomato"}).status_code == 422
    assert client.post("/api/decision/simulate", json={"crop": "tomato", "pests_per_day": -3,
                                                       "predators_per_day": 1}).status_code == 422


def test_live_reason_and_alert_mention_predators_at_risk(client):
    build_live_trap(client, [(40, 2, 0.95), (42, 2, 0.95), (44, 2, 0.95)])
    d = client.get(f"/api/traps/{TRAP}/decision").json()
    assert d["action"] == SPRAY and d["support"]["predators_at_risk"] == 80
    assert "kill an estimated 80 predators" in d["reason"]
    kn = [a["message"] for a in client.get("/api/alerts").json() if a["language"] == "kn" and a["action"] == SPRAY]
    assert kn and "80 ಪರಭಕ್ಷಕ" in kn[0]

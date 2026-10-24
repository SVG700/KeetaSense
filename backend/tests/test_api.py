"""Tests for every API endpoint (using the demo detector and a temp database)."""
import json
from datetime import datetime, timedelta

from backend.tests.conftest import tape_jpeg

TRAP = "T1-polyhouse"


def post_section(client, whitefly, predators=0, trap=TRAP, timestamp=None, seed=1):
    files = {"image": ("tape.jpg", tape_jpeg(whitefly, predators, 0, seed=seed), "image/jpeg")}
    data = {"trap_id": trap}
    if timestamp:
        data["timestamp"] = timestamp
    return client.post("/api/sections", files=files, data=data)


# --- health / traps --------------------------------------------------------
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["detector_mode"] == "demo_detector"
    assert body["telegram"] == "log_only"


def test_traps_loaded_from_config(client):
    r = client.get("/api/traps")
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert ids == ["T1-polyhouse", "T2-openfield"]
    assert r.json()[0]["status"] == "no_data"
    assert r.json()[0]["decision"]["action"] == "WAIT"


# --- sections --------------------------------------------------------------
def test_post_section_counts_and_annotated_image(client):
    r = post_section(client, whitefly=12, predators=2)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pest_total"] == 12
    assert body["predator_total"] == 2
    assert body["detector_mode"] == "demo_detector" and "DEMO DETECTOR" in body["warning"]
    img = client.get(body["annotated_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"


def test_post_section_unknown_trap(client):
    assert post_section(client, 3, trap="nope").status_code == 404


def test_post_section_rejects_non_image(client):
    r = client.post("/api/sections", files={"image": ("x.jpg", b"not an image", "image/jpeg")},
                    data={"trap_id": TRAP})
    assert r.status_code == 400


def test_post_section_bad_timestamp(client):
    assert post_section(client, 3, timestamp="yesterday-ish").status_code == 422


def test_post_section_with_edge_detections(client):
    dets = [{"class_name": "whitefly", "confidence": 0.9, "bbox": [10, 10, 20, 20]},
            {"class_name": "macrolophus", "confidence": 0.8, "bbox": [40, 40, 70, 55]}]
    r = client.post("/api/sections",
                    files={"image": ("t.jpg", tape_jpeg(0), "image/jpeg")},
                    data={"trap_id": TRAP, "detections_json": json.dumps(dets),
                          "detector_mode": "yolo_sahi"})
    assert r.status_code == 200, r.text
    assert r.json()["pest_total"] == 1 and r.json()["predator_total"] == 1
    assert r.json()["detector_mode"] == "yolo_sahi"


def test_post_section_bad_detections_json(client):
    r = client.post("/api/sections", files={"image": ("t.jpg", tape_jpeg(0), "image/jpeg")},
                    data={"trap_id": TRAP, "detections_json": "{oops"})
    assert r.status_code == 422


# --- climate ---------------------------------------------------------------
def test_post_climate_and_validation(client):
    r = client.post("/api/climate", json={"trap_id": TRAP, "temperature_c": 27.5, "humidity_pct": 70})
    assert r.status_code == 200 and r.json()["temperature_c"] == 27.5
    assert client.post("/api/climate", json={"trap_id": TRAP, "temperature_c": 99,
                                             "humidity_pct": 70}).status_code == 422
    assert client.post("/api/climate", json={"trap_id": "nope", "temperature_c": 20,
                                             "humidity_pct": 70}).status_code == 404


# --- history / decision / summary -----------------------------------------
def test_history_contains_sections_and_daily_climate(client):
    day = datetime.now() - timedelta(days=1)
    for hour, temp in ((6, 18.0), (14, 32.0)):
        client.post("/api/climate", json={"trap_id": TRAP, "temperature_c": temp, "humidity_pct": 60,
                                          "timestamp": day.replace(hour=hour).isoformat()})
    post_section(client, 5)
    r = client.get(f"/api/traps/{TRAP}/history?days=7")
    assert r.status_code == 200
    body = r.json()
    assert len(body["sections"]) == 1
    daily = body["climate_daily"][0]
    assert daily["tmin"] == 18 and daily["tmax"] == 32
    assert daily["degree_days"] == 15                 # (18+32)/2 - 10
    assert body["decisions"][0]["action"] == "WAIT"
    assert client.get("/api/traps/nope/history").status_code == 404


def test_decision_changes_to_spray_and_alerts_are_logged(client):
    for i in range(3):
        r = post_section(client, whitefly=40, predators=1, seed=10 + i)
        assert r.status_code == 200
    r = client.get(f"/api/traps/{TRAP}/decision")
    assert r.status_code == 200
    assert r.json()["action"] == "SPRAY"
    assert r.json()["reason"]
    alerts = client.get("/api/alerts").json()
    assert {a["language"] for a in alerts} == {"en", "kn"}
    assert all(a["status"] == "logged" and a["action"] == "SPRAY" for a in alerts)


def test_biocontrol_decision(client):
    for i in range(3):
        post_section(client, whitefly=30, predators=6, seed=20 + i)
    assert client.get(f"/api/traps/{TRAP}/decision").json()["action"] == "RELEASE_BIOCONTROL"


def test_summary(client):
    post_section(client, whitefly=8, predators=1)
    r = client.get("/api/summary")
    assert r.status_code == 200
    s = r.json()
    assert s["traps_total"] == 2
    assert s["pests_today"] == 8 and s["predators_today"] == 1
    assert sum(s["actions"].values()) == 2
    assert s["detector_mode"] == "demo_detector" and s["simulated_data"] is True


# --- phone check -----------------------------------------------------------
def test_phone_check(client):
    r = client.post("/api/phone-check", files={"image": ("p.jpg", tape_jpeg(30, 1), "image/jpeg")},
                    data={"days_exposed": "1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pest_total"] == 30 and body["predator_total"] == 1
    assert body["decision"]["action"] == "SPRAY"
    assert "single photo" in body["decision"]["reason"]
    assert len(body["detections"]) == 31
    assert client.get(body["annotated_url"]).status_code == 200


def test_phone_check_divides_by_days_exposed(client):
    r = client.post("/api/phone-check", files={"image": ("p.jpg", tape_jpeg(30, 1), "image/jpeg")},
                    data={"days_exposed": "3"})
    assert r.json()["decision"]["pests_per_day"] == 10
    assert r.json()["decision"]["action"] == "WAIT"


def test_phone_check_errors(client):
    assert client.post("/api/phone-check", files={"image": ("p.jpg", b"", "image/jpeg")}).status_code == 400
    assert client.post("/api/phone-check", files={"image": ("p.jpg", tape_jpeg(1), "image/jpeg")},
                       data={"target_pest": "dragon"}).status_code == 422
    assert client.post("/api/phone-check", files={"image": ("p.jpg", tape_jpeg(1), "image/jpeg")},
                       data={"days_exposed": "0"}).status_code == 422

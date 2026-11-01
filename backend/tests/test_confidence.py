"""F2 confidence-aware decisions: count range, BORDERLINE, texts."""
import json

import pytest

from backend.decision_engine import (RELEASE_BIOCONTROL, SPRAY, WAIT, Thresholds, borderline_text, classify,
                                     count_range, uncertainty)
from backend.tests.conftest import tape_jpeg

TH = Thresholds(base_temp_c=10, degree_days_per_generation=300, action_threshold_per_day=25,
                spray_ratio=10, rolling_window_days=3)
TRAP = "T1-polyhouse"


def test_count_range():
    assert count_range(45, 0.85) == pytest.approx((38.25, 52.94), abs=0.01)
    assert count_range(45, None) == (45, 45)
    assert count_range(45, 0.2, floor=0.5) == (22.5, 90.0)            # floor caps a very unsure detector
    assert count_range(0, 0.7) == (0, 0)


def test_stable_decision_is_not_borderline():
    u = uncertainty(80, 1, 0.95, 0.95, TH)                             # far above threshold, few predators
    assert not u["borderline"] and u["possible_actions"] == [SPRAY]
    u = uncertainty(5, 0, 0.6, None, TH)                                # far below threshold
    assert not u["borderline"] and u["possible_actions"] == [WAIT]


def test_threshold_flip_is_borderline():
    u = uncertainty(27, 0, 0.85, None, TH)                              # 23 .. 31.8 straddles 25
    assert u["borderline"] and u["possible_actions"] == [WAIT, SPRAY]
    assert borderline_text(u, "whitefly") == "(borderline: 23 to 32 whitefly per day)"


def test_predator_ratio_flip_is_borderline():
    # 40 pests, 4.4 predators: ratio 9.1 -> BIOCONTROL, but with fewer predators it would be SPRAY
    assert classify(40, 4.4, TH) == RELEASE_BIOCONTROL
    u = uncertainty(40, 4.4, 0.99, 0.8, TH)
    assert u["borderline"] and set(u["possible_actions"]) == {RELEASE_BIOCONTROL, SPRAY}


def test_demo_detector_scores_are_heuristic_but_vary():
    from ml.infer import demo_detect
    from ml.synthetic import render_tape
    dets = demo_detect(render_tape({"whitefly": 20, "macrolophus": 2, "nesidiocoris": 2}, 640, 640, seed=3)[0])
    scores = [d["confidence"] for d in dets]
    assert all(0.5 <= s <= 0.95 for s in scores) and len(set(scores)) > 1


# --- live engine through the API -----------------------------------------------------------
def post(client, dets, seed):
    r = client.post("/api/sections", files={"image": ("t.jpg", tape_jpeg(0, seed=seed), "image/jpeg")},
                    data={"trap_id": TRAP, "detections_json": json.dumps(dets), "detector_mode": "yolo_sahi"})
    assert r.status_code == 200
    return r.json()["section"]["id"]


def boxes(n, conf, cls="whitefly"):
    return [{"class_name": cls, "confidence": conf, "bbox": [10.0 * i, 10, 10.0 * i + 8, 18]} for i in range(n)]


def test_borderline_in_reason_alert_and_advisory(client):
    for s in (1, 2, 3):
        post(client, boxes(27, 0.85), s)                                # 27/day, unsure detector
    d = client.get(f"/api/traps/{TRAP}/decision").json()
    assert d["action"] == SPRAY and d["borderline"] is True
    assert d["uncertainty"]["pests_low"] == pytest.approx(22.9, abs=0.1)
    assert "(borderline: 23 to 32 whitefly per day)" in d["reason"]
    msgs = {a["language"]: a["message"] for a in client.get("/api/alerts").json() if a["action"] == SPRAY}
    assert "Borderline: 23 to 32 Whitefly per day" in msgs["en"]
    assert "ಗಡಿರೇಖೆಯಲ್ಲಿದೆ" in msgs["kn"]
    hi = client.get(f"/api/advisory/{TRAP}?lang=hi").json()["rendered"]["text"]
    assert "सीमा पर: प्रतिदिन 23 से 32" in hi


def test_confident_detector_is_not_borderline(client):
    for s in (4, 5, 6):
        post(client, boxes(27, 0.99), s)
    d = client.get(f"/api/traps/{TRAP}/decision").json()
    assert d["action"] == SPRAY and d["borderline"] is False and "borderline" not in d["reason"]


def test_scout_checked_boxes_count_as_certain(client):
    ids = [post(client, boxes(27, 0.85), s) for s in (7, 8, 9)]
    assert client.get(f"/api/traps/{TRAP}/decision").json()["borderline"] is True
    for sid in ids:                                                     # a scout confirms every photo
        client.post(f"/api/sections/{sid}/corrections", json={"action": "remove", "target": "m0"})
    d = client.get(f"/api/traps/{TRAP}/decision").json()
    assert d["uncertainty"]["pest_confidence"] == 0.85                  # untouched model boxes stay 0.85
    # relabel = confirmed by a person -> confidence 1.0 for that box
    client.post(f"/api/sections/{ids[0]}/corrections", json={"action": "relabel", "target": "m1",
                                                              "class_name": "macrolophus"})
    d = client.get(f"/api/traps/{TRAP}/decision").json()
    assert d["uncertainty"]["predator_confidence"] == 1.0

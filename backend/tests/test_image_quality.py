"""F1 image quality gate: generated blurred, dark, glared and duplicate photos."""
import cv2
import numpy as np
import pytest

from backend import image_quality as iq
from edge import faults
from ml.synthetic import render_tape

TRAP = "T1-polyhouse"


def tape(seed=1, n=15):
    return render_tape({"whitefly": n, "macrolophus": 1, "nesidiocoris": 1}, 1280, 800, seed=seed)[0]


def jpeg(img):
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()


def codes(reasons):
    return {r["code"]: r["level"] for r in reasons}


def test_good_photo_is_ok():
    status, reasons, m = iq.check(tape(1), tape(2))
    assert status == iq.OK and reasons == []
    assert m["similarity_to_previous"] < 0.3 and m["width"] == 1280


@pytest.mark.parametrize("fault,code", [("blur", "blurred"), ("dark", "too_dark"), ("glare", "glare")])
def test_degraded_photos_are_bad(fault, code):
    status, reasons, _ = iq.check(faults.degrade(tape(3), fault))
    assert status == iq.BAD and codes(reasons)[code] == iq.BAD


def test_duplicate_photo_means_tape_did_not_advance():
    img = tape(4)
    again = cv2.imdecode(np.frombuffer(jpeg(img), np.uint8), cv2.IMREAD_COLOR)   # re-photographed / re-encoded
    status, reasons, m = iq.check(again, img)
    assert status == iq.BAD and codes(reasons) == {"tape_not_advanced": iq.BAD}
    assert m["similarity_to_previous"] > 0.8


def test_slight_blur_is_only_a_warning():
    status, reasons, _ = iq.check(cv2.GaussianBlur(tape(5), (5, 5), 0))
    assert status == iq.WARN and codes(reasons) == {"blurred": iq.WARN}


def test_reason_texts_in_english_and_kannada():
    reasons = [{"code": "blurred", "level": "BAD"}, {"code": "glare", "level": "WARN"}]
    assert iq.reasons_text(reasons, "en") == "image blurred, glare on the tape"
    assert iq.reasons_text(reasons, "en", only_bad=True) == "image blurred"
    assert iq.reasons_text(reasons, "kn", only_bad=True) == "ಚಿತ್ರ ಮಸುಕಾಗಿದೆ"
    assert "Check the trap" in iq.check_trap_reason(reasons, "en")


# --- through the API -------------------------------------------------------------------
def post(client, img):
    return client.post("/api/sections", files={"image": ("t.jpg", jpeg(img), "image/jpeg")},
                       data={"trap_id": TRAP})


def test_bad_photo_gives_check_trap_with_alert_and_recovers(client):
    for i in range(3):
        assert post(client, tape(10 + i, n=40)).status_code == 200        # pests high -> SPRAY
    assert client.get(f"/api/traps/{TRAP}/decision").json()["action"] == "SPRAY"

    r = post(client, faults.degrade(tape(20, n=40), "blur"))
    sec = r.json()["section"]
    assert sec["quality_status"] == "BAD" and sec["quality_reasons"][0]["code"] == "blurred"
    d = client.get(f"/api/traps/{TRAP}/decision").json()
    assert d["action"] == "CHECK_TRAP" and d["underlying_action"] == "SPRAY"
    assert "image blurred" in d["reason"] and "no spray or release advice" in d["reason"]
    alerts = [a for a in client.get("/api/alerts").json() if a["action"] == "CHECK_TRAP"]
    assert {a["language"] for a in alerts} == {"en", "kn"}
    assert any("image blurred" in a["message"] for a in alerts)
    assert any("ಚಿತ್ರ ಮಸುಕಾಗಿದೆ" in a["message"] for a in alerts)
    # the BAD photo is not counted: averages still come from the 3 good sections
    assert d["window_days_used"] == 3

    post(client, tape(30, n=40))                                          # a good photo again
    assert client.get(f"/api/traps/{TRAP}/decision").json()["action"] == "SPRAY"


def test_same_photo_twice_through_api(client):
    img = tape(40)
    post(client, img)
    r = post(client, img)
    assert r.json()["section"]["quality_status"] == "BAD"
    assert client.get(f"/api/traps/{TRAP}/decision").json()["action"] == "CHECK_TRAP"
    summary = client.get("/api/summary").json()
    assert summary["actions"]["CHECK_TRAP"] == 1
    hi = client.get(f"/api/advisory/{TRAP}?lang=hi").json()
    assert "ट्रैप जाँचें" in hi["rendered"]["text"]


def test_old_database_gets_quality_columns(tmp_path, monkeypatch):
    import sqlite3
    from backend import db
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE tapesection (id INTEGER PRIMARY KEY, trap_id VARCHAR, timestamp DATETIME, "
                "image_path VARCHAR, counts JSON, pest_total INTEGER, predator_total INTEGER, "
                "detector_mode VARCHAR, simulated BOOLEAN)")
    con.execute("INSERT INTO tapesection (trap_id, image_path, pest_total) VALUES ('T1', 'x.jpg', 5)")
    con.commit()
    con.close()
    monkeypatch.setenv("KEETA_DB_PATH", str(path))
    db.reset_engine()
    db.init_db()
    con = sqlite3.connect(path)
    cols = [r[1] for r in con.execute("PRAGMA table_info(tapesection)")]
    assert {"quality_status", "quality_reasons", "quality_metrics"} <= set(cols)
    assert con.execute("SELECT pest_total FROM tapesection").fetchone() == (5,)     # data kept
    db.reset_engine()

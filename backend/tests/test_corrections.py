"""F3 scout corrections: replay, decision recompute, undo, stats, YOLO export."""
import io
import json
import zipfile

import pytest
import yaml

from backend import corrections as corr
from backend.models import Correction
from backend.tests.conftest import tape_jpeg

TRAP = "T1-polyhouse"


def det(cls, x, conf=0.8):
    return {"class_name": cls, "confidence": conf, "bbox": [x, 10.0, x + 15.0, 25.0]}


def test_apply_corrections_add_remove_relabel():
    model = [det("whitefly", 0), det("whitefly", 30), det("whitefly", 60)]
    edits = [Correction(id=1, section_id=1, action="remove", target="m0"),
             Correction(id=2, section_id=1, action="relabel", target="m1", class_name="macrolophus"),
             Correction(id=3, section_id=1, action="add", class_name="nesidiocoris", bbox=[90, 10, 120, 20])]
    boxes = corr.apply_corrections(model, edits)
    assert [b["id"] for b in boxes] == ["m1", "m2", "c3"]
    assert boxes[0]["class_name"] == "macrolophus" and boxes[0]["relabelled_from"] == "whitefly"
    assert boxes[2]["source"] == "scout"
    counts, pests, predators = corr.count(boxes)
    assert counts == {"whitefly": 1, "macrolophus": 1, "nesidiocoris": 1} and (pests, predators) == (1, 2)


def test_yolo_lines_are_normalised():
    lines = corr.yolo_lines([{"class_name": "macrolophus", "bbox": [100, 50, 140, 70]}], 200, 100)
    assert lines == ["1 0.600000 0.600000 0.200000 0.200000"]


# --- through the API ----------------------------------------------------------------
def post(client, dets, seed):
    r = client.post("/api/sections", files={"image": ("t.jpg", tape_jpeg(0, seed=seed), "image/jpeg")},
                    data={"trap_id": TRAP, "detections_json": json.dumps(dets), "detector_mode": "yolo_sahi"})
    assert r.status_code == 200, r.text
    return r.json()["section"]["id"]


def thirty_whiteflies():
    return [det("whitefly", 20 * i) for i in range(30)]


def test_correction_recomputes_the_decision_and_keeps_both_counts(client):
    ids = [post(client, thirty_whiteflies(), seed=s) for s in (1, 2, 3)]
    assert client.get(f"/api/traps/{TRAP}/decision").json()["action"] == "SPRAY"   # 30/day, no predators

    # the scout finds that 20 of the 30 "whiteflies" on each photo are dust
    for sid in ids:
        for i in range(20):
            r = client.post(f"/api/sections/{sid}/corrections", json={"action": "remove", "target": f"m{i}"})
            assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"]["action"] == "WAIT"
    assert body["decision"]["pests_per_day"] == 10
    sec = client.get(f"/api/sections/{ids[-1]}").json()
    assert sec["corrected"] and sec["pest_total"] == 30 and sec["corrected_pest_total"] == 10   # both kept
    assert len(sec["boxes"]) == 10 and len(sec["corrections"]) == 20

    # undo one edit on the last photo: 11 again
    r = client.delete(f"/api/corrections/{sec['corrections'][-1]['id']}")
    assert r.json()["section"]["corrected_pest_total"] == 11


def test_relabel_to_predator_changes_spray_to_biocontrol(client):
    ids = [post(client, thirty_whiteflies(), seed=s) for s in (4, 5, 6)]
    for sid in ids:
        for i in range(4):
            client.post(f"/api/sections/{sid}/corrections",
                        json={"action": "relabel", "target": f"m{i}", "class_name": "macrolophus"})
    d = client.get(f"/api/traps/{TRAP}/decision").json()
    assert d["action"] == "RELEASE_BIOCONTROL" and d["predators_per_day"] == 4      # 26 pests : 4 predators


def test_add_box_and_validation(client):
    sid = post(client, [det("whitefly", 0)], seed=7)
    ok = client.post(f"/api/sections/{sid}/corrections",
                     json={"action": "add", "class_name": "nesidiocoris", "bbox": [100, 100, 130, 112]})
    assert ok.status_code == 200 and ok.json()["section"]["corrected_counts"]["nesidiocoris"] == 1
    bad = [{"action": "add", "class_name": "dragon", "bbox": [1, 1, 20, 20]},
           {"action": "add", "class_name": "whitefly", "bbox": [5, 5, 6, 6]},
           {"action": "remove", "target": "m99"},
           {"action": "relabel", "target": "m0", "class_name": "whitefly"},
           {"action": "explode", "target": "m0"}]
    for b in bad:
        assert client.post(f"/api/sections/{sid}/corrections", json=b).status_code == 422, b
    assert client.post("/api/sections/99999/corrections", json={"action": "remove", "target": "m0"}).status_code == 404


def test_stats_measured_on_corrected_captures(client):
    assert client.get("/api/corrections/stats").json()["corrected_captures"] == 0
    a = post(client, thirty_whiteflies(), seed=8)
    post(client, thirty_whiteflies(), seed=9)                       # never corrected
    for i in range(6):
        client.post(f"/api/sections/{a}/corrections", json={"action": "remove", "target": f"m{i}"})
    s = client.get("/api/corrections/stats").json()
    assert s["corrected_captures"] == 1 and s["captures"] == 2 and s["correction_rate"] == 0.5
    assert s["pest_mae"] == 6 and s["label"] == "based on 1 corrected capture"


def test_export_zip_is_yolo_format(client):
    a = post(client, [det("whitefly", 0), det("whitefly", 40)], seed=10)
    client.post(f"/api/sections/{a}/corrections", json={"action": "relabel", "target": "m1", "class_name": "macrolophus"})
    client.post(f"/api/sections/{a}/corrections", json={"action": "add", "class_name": "nesidiocoris",
                                                        "bbox": [320, 160, 352, 176]})
    r = client.get("/api/corrections/export.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {f"images/{TRAP}_{a}.jpg", f"labels/{TRAP}_{a}.txt", "data.yaml", "manifest.json"} <= names
    lines = z.read(f"labels/{TRAP}_{a}.txt").decode().split()
    rows = [lines[i:i + 5] for i in range(0, len(lines), 5)]
    assert [r[0] for r in rows] == ["0", "1", "2"]                  # whitefly, macrolophus, nesidiocoris
    for r_ in rows:
        assert all(0 <= float(v) <= 1 for v in r_[1:])
    assert rows[2] == ["2", "0.525000", "0.262500", "0.050000", "0.025000"]   # 640 x 640 photo
    assert yaml.safe_load(z.read("data.yaml"))["names"] == {0: "whitefly", 1: "macrolophus", 2: "nesidiocoris"}
    assert json.loads(z.read("manifest.json"))[0]["simulated"] is True        # labelled as synthetic


def test_old_database_gets_correction_columns(tmp_path, monkeypatch):
    import sqlite3
    from backend import db
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE tapesection (id INTEGER PRIMARY KEY, trap_id VARCHAR, timestamp DATETIME, "
                "image_path VARCHAR, counts JSON, pest_total INTEGER, predator_total INTEGER, "
                "detector_mode VARCHAR, simulated BOOLEAN)")
    con.commit()
    con.close()
    monkeypatch.setenv("KEETA_DB_PATH", str(path))
    db.reset_engine()
    db.init_db()
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(tapesection)")}
    assert {"detections", "corrected_counts", "corrected_pest_total", "corrected_predator_total"} <= cols
    tables = {r[0] for r in sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "correction" in tables
    db.reset_engine()

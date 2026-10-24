"""Detector switching (demo <-> trained weights) and the Model page API."""
import json

from backend import model_reports
from ml import infer


def test_health_and_summary_show_demo_detector_label(client):
    d = client.get("/api/health").json()["detector"]
    assert d["mode"] == "demo_detector" and d["label"] == "Demo detector (synthetic only)"
    assert client.get("/api/summary").json()["detector"]["mode"] == "demo_detector"


def test_broken_weights_fall_back_to_demo_detector(tmp_path, monkeypatch):
    bad = tmp_path / "best.pt"
    bad.write_text("this is not a model")
    monkeypatch.setenv("KEETA_WEIGHTS", str(bad))
    infer.reset_detector()
    info = infer.model_info()
    assert info["mode"] == infer.MODE_DEMO
    assert info["reason"] == "weights failed to load" and info["load_error"]
    # detection still works (demo detector) instead of crashing
    r = infer.detect(__import__("numpy").full((200, 200, 3), 200, "uint8"))
    assert r.mode == infer.MODE_DEMO
    infer.reset_detector()


def test_model_card_is_read(tmp_path):
    w = tmp_path / "best.pt"
    w.write_bytes(b"x")
    w.with_suffix(".json").write_text(json.dumps({"trained_at": "2026-11-02T10:00:00"}))
    assert infer._read_model_card(w)["trained_at"] == "2026-11-02T10:00:00"
    (tmp_path / "other.json").write_text("{broken")
    assert infer._read_model_card(tmp_path / "other.pt") == {}


def _report(folder, name, synthetic, created, map50):
    (folder / f"eval_{name}.json").write_text(json.dumps({
        "created": created, "dataset": f"ml/data/{'synthetic_yolo' if synthetic else 'yolo'}/data.yaml",
        "synthetic_data": synthetic, "detector_mode": "yolo_sahi", "weights": "C:/x/best.pt",
        "test_images": 40, "map50": map50, "per_class": {}, "counting_error": {}}))


def test_model_endpoint_prefers_real_report(client, tmp_path, monkeypatch):
    _report(tmp_path, "synthetic_new", True, "2026-11-03T10:00:00", 1.0)
    _report(tmp_path, "real_test", False, "2026-11-02T10:00:00", 0.5)
    monkeypatch.setattr(model_reports, "reports_dir", lambda: tmp_path)
    body = client.get("/api/model").json()
    assert body["featured"]["name"] == "real_test"          # real beats newer synthetic
    assert body["warning"] is None
    assert [r["name"] for r in body["reports"]] == ["synthetic_new", "real_test"]


def test_model_endpoint_warns_when_only_synthetic(client, tmp_path, monkeypatch):
    _report(tmp_path, "synthetic_only", True, "2026-11-03T10:00:00", 1.0)
    monkeypatch.setattr(model_reports, "reports_dir", lambda: tmp_path)
    body = client.get("/api/model").json()
    assert body["featured"]["synthetic_data"] is True
    assert "SYNTHETIC" in body["warning"]


def test_model_endpoint_without_reports(client, tmp_path, monkeypatch):
    monkeypatch.setattr(model_reports, "reports_dir", lambda: tmp_path)
    body = client.get("/api/model").json()
    assert body["featured"] is None and "No evaluation report" in body["warning"]

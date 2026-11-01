"""Pi bring-up tools, startup self-check, robust start-up, recording and replay
(all without real hardware)."""
import json

import numpy as np
import pytest
import requests

from edge import selfcheck
from edge.calibrate_tape import set_env_value
from edge.config import EdgeConfig
from edge.main import EdgeService
from edge.replay import ReplaySource, load_manifest, make_pack
from edge.tests_hw import test_backend_link as link
from edge.tests_hw import test_camera as cam
from edge.tests_hw import test_dht22 as dht
from edge.tests_hw import test_stepper as stp
from ml.common import ROOT


def mock_cfg(tmp_path):
    cfg = EdgeConfig()
    cfg.mock_hardware = True
    cfg.data_dir = tmp_path / "edge"
    cfg.sample_dir = ROOT / "demo" / "sample_tape"
    cfg.backend_url = "http://backend.invalid"
    return cfg


class FakeCamera:
    def __init__(self, img=None, error=None):
        self.img, self.error = img, error

    def capture(self):
        if self.error:
            raise self.error
        return self.img

    def close(self):
        pass


class FakeSensor:
    def __init__(self, values):
        self.values = list(values)

    def read(self):
        return self.values.pop(0)

    def close(self):
        pass


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self.ok, self.text, self._body = status, status < 400, "", body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


# --- calibration .env writer ------------------------------------------------
def test_set_env_value_replaces_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nSTEPS_PER_SECTION=2048\n")
    set_env_value(env, "STEPS_PER_SECTION", "1800")
    assert "STEPS_PER_SECTION=2048" in (tmp_path / ".env.bak").read_text()   # old file kept
    set_env_value(env, "NEW_KEY", "x")
    assert env.read_text() == "A=1\nSTEPS_PER_SECTION=1800\nNEW_KEY=x\n"


# --- individual checks -------------------------------------------------------
def test_camera_check_pass_warn_fail(tmp_path):
    cfg = mock_cfg(tmp_path)
    assert cam.check(cfg, out=tmp_path / "c.jpg").ok and (tmp_path / "c.jpg").exists()
    dark = cam.check(cfg, camera=FakeCamera(np.zeros((100, 100, 3), np.uint8)))
    assert dark.ok and dark.warn and "too dark" in dark.summary
    broken = cam.check(cfg, camera=FakeCamera(error=RuntimeError("no camera")))
    assert not broken.ok and broken.hints


def test_dht_check_success_rate(tmp_path):
    cfg = mock_cfg(tmp_path)
    good = dht.check(cfg, reads=5, sensor=FakeSensor([(25, 60)] * 5))
    assert good.ok and not good.warn
    flaky = dht.check(cfg, reads=5, sensor=FakeSensor([(25, 60), None, (25, 60), None, (26, 61)]))
    assert flaky.ok and flaky.warn and "3/5" in flaky.summary
    dead = dht.check(cfg, reads=5, sensor=FakeSensor([None] * 4 + [(99, 50)]))   # 99 °C is implausible
    assert not dead.ok


def test_stepper_check_mock(tmp_path):
    r = stp.check(mock_cfg(tmp_path), steps=64, direction="both")
    assert r.ok and "64" in r.summary


def test_backend_link_check(tmp_path, monkeypatch):
    cfg = mock_cfg(tmp_path)
    monkeypatch.setattr(requests, "get", lambda url, **k: Resp(200, {"status": "ok"} if "health" in url
                                                                     else [{"id": cfg.trap_id}]))
    posted = {}
    monkeypatch.setattr(requests, "post", lambda url, **k: posted.update(k) or Resp(200, {"stored": False}))
    r = link.check(cfg, tries=2)
    assert r.ok and posted["params"] == {"dry_run": "true"}

    monkeypatch.setattr(requests, "get", lambda url, **k: Resp(200, {"status": "ok"} if "health" in url
                                                                     else [{"id": "other"}]))
    assert "not known" in link.check(cfg, tries=1).summary

    def down(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", down)
    assert not link.check(cfg, tries=1).ok


# --- self-check + robust start-up -----------------------------------------------
def test_selfcheck_reports_failed_parts(tmp_path, capsys):
    cfg = mock_cfg(tmp_path)
    results = selfcheck.run_quick(cfg, camera=FakeCamera(error=OSError("x")), sensor=FakeSensor([(20, 50)] * 2),
                                  init_errors={"stepper": "RuntimeError: no GPIO"}, check_backend=False)
    by_name = {r.name: r for r in results}
    assert not by_name["Camera"].ok and not by_name["Stepper motor"].ok and by_name["DHT22 sensor"].ok
    assert by_name["Detector"].ok
    selfcheck.print_summary(results, mock=True)
    out = capsys.readouterr().out
    assert "FAIL  Camera" in out and "2 problem(s)" in out


def test_service_survives_a_broken_camera(tmp_path, monkeypatch):
    import edge.main as edge_main

    def broken_camera(*a, **k):
        raise RuntimeError("camera cable loose")
    monkeypatch.setattr(edge_main, "Camera", broken_camera)
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    svc = EdgeService(mock_cfg(tmp_path))
    assert "camera" in svc.init_errors and svc.camera is None
    summary = svc.run_cycle()                # must not raise
    assert summary["captured"] is False and summary["queued"] == 1   # climate still queued
    svc.close()


# --- recording + replay ------------------------------------------------------------
def test_record_then_replay(tmp_path, monkeypatch):
    cfg = mock_cfg(tmp_path)
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    svc = EdgeService(cfg, record=True)
    svc.run_cycle()
    svc.run_cycle()
    svc.close()
    recording = cfg.data_dir / "recording" / cfg.trap_id
    entries = load_manifest(recording)
    assert len(entries) == 2 and entries[0].detections is not None and entries[0].temperature_c is not None

    pack = tmp_path / "pack"
    assert make_pack(recording, pack) == 2

    sent = []
    monkeypatch.setattr(requests, "post", lambda url, **k: sent.append((url, k.get("data") or k.get("json")))
                        or Resp(200, {"decision": {"action": "WAIT"}}))
    cfg2 = mock_cfg(tmp_path / "second")
    replay = EdgeService(cfg2, replay_dir=pack)
    assert replay.camera is None and replay.source == "replay"
    for _ in range(3):                         # loops around the 2 entries
        assert replay.run_cycle()["replay"]
    replay.close()
    sections = [d for u, d in sent if u.endswith("/api/sections")]
    assert len(sections) == 3 and all(d["source"] == "replay" for d in sections)
    assert all(json.loads(d["detections_json"]) == entries[i % 2].detections for i, d in enumerate(sections))


def test_replay_rejects_folder_without_manifest(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReplaySource(tmp_path)


def test_injected_stuck_tape_photographs_the_same_section(tmp_path, monkeypatch):
    from backend import image_quality as iq
    import cv2
    cfg = mock_cfg(tmp_path)
    cfg.inject = "stuck"
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    svc = EdgeService(cfg, record=False)
    svc.run_cycle()
    svc.run_cycle()
    images = sorted((cfg.data_dir / "images").glob("*.jpg"))
    svc.close()
    a, b = cv2.imread(str(images[-2])), cv2.imread(str(images[-1]))
    assert iq.check(b, a)[0] == iq.BAD


# --- trap health heartbeat (F6) -------------------------------------------------------
def _collect_heartbeats(monkeypatch):
    beats = []

    def post(url, **k):
        if url.endswith("/heartbeat"):
            beats.append(k["json"])
            return Resp(200, {})
        raise requests.ConnectionError()             # sections / climate stay in the offline queue
    monkeypatch.setattr(requests, "post", post)
    return beats


def test_heartbeat_reports_queue_tape_and_survives_restart(tmp_path, monkeypatch):
    beats = _collect_heartbeats(monkeypatch)
    cfg = mock_cfg(tmp_path)
    svc = EdgeService(cfg, record=False)
    svc.run_cycle()
    svc.run_cycle()
    svc.close()
    assert len(beats) == 2 and beats[-1]["simulated"] is True and beats[-1]["motor_fault"] is False
    assert beats[-1]["tape_steps_used"] == 2 * cfg.steps_per_section
    assert beats[-1]["tape_total_steps"] == cfg.tape_total_steps
    assert beats[-1]["queue_depth"] >= 2 > beats[0]["queue_depth"] - 10    # nothing uploaded: the queue grows
    again = EdgeService(cfg, record=False)                                   # tape usage is kept on disk
    assert again.tape_steps_used == 2 * cfg.steps_per_section
    again.close()


@pytest.mark.parametrize("fault", ["motor", "tape", "offline"])
def test_injected_health_faults(tmp_path, monkeypatch, fault):
    beats = _collect_heartbeats(monkeypatch)
    cfg = mock_cfg(tmp_path)
    cfg.inject = fault
    svc = EdgeService(cfg, record=False)
    for _ in range(3):
        svc.run_cycle()
    svc.close()
    if fault == "motor":
        assert all(b["motor_fault"] and b["motor_fault_detail"] for b in beats)
    elif fault == "tape":
        assert beats[0]["tape_steps_used"] >= 0.9 * cfg.tape_total_steps
    else:
        assert len(beats) == 1                       # silent after the first cycle

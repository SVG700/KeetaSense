"""Tests for the edge service in mock mode (no Raspberry Pi needed)."""
from datetime import datetime

import pytest
import requests

from edge.config import EdgeConfig
from edge.hardware.dht22 import simulated_reading
from edge.hardware.stepper import HALF_STEP_SEQUENCE, Stepper
from edge.main import EdgeService
from edge.offline_queue import OfflineQueue, backoff_seconds


def test_half_step_sequence_is_valid():
    assert len(HALF_STEP_SEQUENCE) == 8
    for a, b in zip(HALF_STEP_SEQUENCE, HALF_STEP_SEQUENCE[1:] + HALF_STEP_SEQUENCE[:1]):
        # consecutive half-steps differ by exactly one coil switching
        assert sum(x != y for x, y in zip(a, b)) == 1
        assert 1 <= sum(a) <= 2


def test_mock_stepper_counts_steps_without_gpio():
    s = Stepper([17, 18, 27, 22], steps_per_section=2048, mock=True)
    s.advance_section()
    s.step(-3)
    assert s.total_steps == 2051 and s.position == 5  # 8 - 3


def test_stepper_needs_four_pins():
    with pytest.raises(ValueError):
        Stepper([1, 2, 3], 100)


def test_simulated_climate_is_realistic():
    hot = simulated_reading(datetime(2026, 10, 25, 14, 0))
    cold = simulated_reading(datetime(2026, 10, 25, 3, 0))
    assert 15 < cold[0] < hot[0] < 35
    assert 0 <= hot[1] <= 100 and cold[1] > hot[1]


def test_backoff_grows_and_is_capped():
    assert [backoff_seconds(n) for n in (1, 2, 3)] == [10, 20, 40]
    assert backoff_seconds(50) == 600


def test_queue_retry_schedule(tmp_path):
    q = OfflineQueue(tmp_path / "q.db")
    item_id = q.add("climate", {"x": 1})
    assert [i.id for i in q.due(now=0 + 1e9)] == [item_id]
    q.mark_failed(item_id, "offline", now=1000)
    assert q.due(now=1005) == []                 # waiting for backoff
    assert len(q.due(now=1011)) == 1             # due again after 10 s
    q.mark_sent(item_id)
    assert q.size() == 0


def make_service(tmp_path, sample_dir):
    cfg = EdgeConfig()
    cfg.mock_hardware = True
    cfg.data_dir = tmp_path / "edge"
    cfg.sample_dir = sample_dir
    cfg.backend_url = "http://backend.invalid"
    return EdgeService(cfg)


class FakeResponse:
    def __init__(self, status=200):
        self.status_code, self.ok, self.text = status, status < 400, ""

    def json(self):
        return {"decision": {"action": "WAIT"}}


def test_cycle_keeps_data_when_offline_then_syncs(tmp_path, monkeypatch):
    from ml.common import ROOT
    svc = make_service(tmp_path, ROOT / "demo" / "sample_tape")

    def offline(*a, **k):
        raise requests.ConnectionError("no network")
    monkeypatch.setattr(requests, "post", offline)
    summary = svc.run_cycle()
    assert summary["captured"] and summary["queued"] == 2 and summary["sent"] == 0
    assert svc.queue.size() == 2                 # section + climate kept locally

    calls = []
    def online(url, **kwargs):
        calls.append(url)
        return FakeResponse(200)
    monkeypatch.setattr(requests, "post", online)
    # make everything due now, then sync
    svc.queue.conn.execute("UPDATE pending SET next_try = 0")
    assert svc.sync() == 2
    assert svc.queue.size() == 0
    assert any(u.endswith("/api/sections") for u in calls)
    assert any(u.endswith("/api/climate") for u in calls)
    svc.close()


def test_rejected_items_are_dropped(tmp_path, monkeypatch):
    svc = make_service(tmp_path, tmp_path / "no_samples")   # camera generates images itself
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(404))
    svc.run_cycle()
    assert svc.queue.size() == 0
    svc.close()

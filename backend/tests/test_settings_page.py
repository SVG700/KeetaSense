"""Settings page: view/edit thresholds in a temporary copy of config/pests.yaml."""
import shutil
from datetime import date

import pytest
import yaml

from backend import settings, thresholds_editor
from backend.tests.conftest import tape_jpeg

GOOD = {"base_temp_c": 10.0, "degree_days_per_generation": 300.0, "action_threshold_per_day": 25,
        "spray_ratio": 10.0, "rolling_window_days": 3}


@pytest.fixture
def pests_copy(tmp_path, monkeypatch):
    copy = tmp_path / "config" / "pests.yaml"
    copy.parent.mkdir()
    shutil.copy2(settings.ROOT / "config" / "pests.yaml", copy)
    monkeypatch.setenv("KEETA_PESTS_YAML", str(copy))
    settings.reload_config()
    yield copy
    monkeypatch.delenv("KEETA_PESTS_YAML")
    settings.reload_config()


def test_read_thresholds_shows_values_and_placeholder_status(pests_copy):
    wf = thresholds_editor.read_thresholds()["whitefly"]
    assert wf["base_temp_c"]["value"] == 10.0 and wf["base_temp_c"]["status"] == "placeholder"
    assert set(wf) == set(thresholds_editor.FIELDS)


@pytest.mark.parametrize("field,value,message", [
    ("base_temp_c", -2, "negative"),
    ("degree_days_per_generation", 0, "greater than 0"),
    ("action_threshold_per_day", "", "Required"),
    ("spray_ratio", "ten", "number"),
    ("rolling_window_days", 2.5, "whole number"),
    ("rolling_window_days", 0, "at least 1"),
    ("degree_days_per_generation", 99999, "at most"),
])
def test_validation_errors(field, value, message):
    _, errors = thresholds_editor.validate({**GOOD, field: value})
    assert message in errors[field]


def test_save_changes_value_comment_and_keeps_backup(pests_copy):
    before = pests_copy.read_text(encoding="utf-8")
    result = thresholds_editor.save("whitefly", {**GOOD, "action_threshold_per_day": 40},
                                    today=date(2026, 11, 4))
    assert result["changed"] == ["action_threshold_per_day"]
    text = pests_copy.read_text(encoding="utf-8")
    assert "action_threshold_per_day: 40  # Confirmed with IIHR mentor on 2026-11-04" in text
    # unchanged values keep their PLACEHOLDER comment; everything else is untouched
    assert "base_temp_c: 10.0  # PLACEHOLDER - confirm with IIHR mentor" in text
    assert len(text.splitlines()) == len(before.splitlines())
    assert [l for l in text.splitlines() if "action_threshold" not in l] == \
           [l for l in before.splitlines() if "action_threshold" not in l]
    assert yaml.safe_load(text)["thresholds"]["whitefly"]["action_threshold_per_day"] == 40
    backups = list((pests_copy.parent / "backups").glob("pests_*.yaml"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == before


def test_confirm_unchanged_marks_all(pests_copy):
    r = thresholds_editor.save("whitefly", GOOD, confirm_unchanged=True, today=date(2026, 11, 4))
    assert r["changed"] == [] and len(r["confirmed_unchanged"]) == 5
    statuses = {v["status"] for v in thresholds_editor.read_thresholds()["whitefly"].values()}
    assert statuses == {"confirmed"}


def test_nothing_to_save_writes_nothing(pests_copy):
    r = thresholds_editor.save("whitefly", GOOD)
    assert r["backup"] is None and not (pests_copy.parent / "backups").exists()


def test_invalid_save_does_not_touch_file(pests_copy):
    before = pests_copy.read_text(encoding="utf-8")
    with pytest.raises(ValueError) as e:
        thresholds_editor.save("whitefly", {**GOOD, "spray_ratio": -1})
    assert "spray_ratio" in e.value.args[0]["errors"]
    assert pests_copy.read_text(encoding="utf-8") == before


# --- API ----------------------------------------------------------------------
def test_api_get_and_validation_error(client, pests_copy):
    body = client.get("/api/settings/thresholds").json()
    assert body["pests"]["whitefly"]["spray_ratio"]["status"] == "placeholder"
    r = client.put("/api/settings/thresholds/whitefly", json={"values": {**GOOD, "base_temp_c": ""}})
    assert r.status_code == 422 and "base_temp_c" in r.json()["detail"]["errors"]
    r = client.put("/api/settings/thresholds/dragonfly", json={"values": GOOD})
    assert r.status_code == 422


def test_api_save_recalculates_decisions_immediately(client, pests_copy):
    for i in range(3):   # 20 whiteflies/day: below the placeholder threshold of 25 -> WAIT
        client.post("/api/sections", files={"image": ("t.jpg", tape_jpeg(20, 0, seed=i), "image/jpeg")},
                    data={"trap_id": "T1-polyhouse"})
    assert client.get("/api/traps/T1-polyhouse/decision").json()["action"] == "WAIT"
    r = client.put("/api/settings/thresholds/whitefly", json={"values": {**GOOD, "action_threshold_per_day": 15}})
    assert r.status_code == 200, r.text
    assert r.json()["decisions"]["T1-polyhouse"] == "SPRAY"
    assert client.get("/api/traps/T1-polyhouse/decision").json()["action"] == "SPRAY"
    assert client.get("/api/traps").json()[0]["thresholds"]["action_threshold_per_day"] == 15

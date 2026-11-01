"""Kannada review helper: CSV export and import round trip (on copies of the real files)."""
import csv
import shutil
from datetime import date

import pytest
import yaml

from backend import kannada_review as kr
from backend.settings import ROOT


@pytest.fixture
def files(tmp_path):
    t = tmp_path / "alert_templates.yaml"
    p = tmp_path / "pests.yaml"
    shutil.copy2(kr.TEMPLATES, t)
    shutil.copy2(ROOT / "config" / "pests.yaml", p)
    return t, p


def edit_csv(path, fixes):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["key"] in fixes:
            r["reviewer correction"] = fixes[r["key"]]
    kr.write_csv(rows, path)


def test_export_contains_every_template_and_pest_name(files, tmp_path):
    t, p = files
    rows = kr.export_rows(t, p)
    keys = [r["key"] for r in rows]
    assert {"SPRAY", "RELEASE_BIOCONTROL", "WAIT", "days_known", "days_unknown"} <= set(keys)
    assert "pest_name.whitefly" in keys
    out = tmp_path / "review.csv"
    kr.write_csv(rows, out)
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")                       # BOM for Excel
    text = raw.decode("utf-8-sig")
    assert "key,English text,Kannada text,reviewer correction" in text.splitlines()[0]
    assert "ಕೀಟಸೆನ್ಸ್" in text                                   # Kannada survives


def test_import_round_trip(files, tmp_path):
    t, p = files
    out = tmp_path / "review.csv"
    kr.write_csv(kr.export_rows(t, p), out)
    original = yaml.safe_load(t.read_text(encoding="utf-8"))
    new_wait = original["kn"]["WAIT"].replace("ಗಮನಿಸುತ್ತಿರಿ", "ಗಮನಿಸುತ್ತಾ ಇರಿ")
    edit_csv(out, {"WAIT": new_wait, "SPRAY": "OK", "pest_name.whitefly": "ಬಿಳಿ ನೊಣ (ವೈಟ್‌ಫ್ಲೈ)"})
    corrections, problems, ok = kr.read_corrections(out)
    assert problems == [] and ok == 1 and set(corrections) == {"WAIT", "pest_name.whitefly"}

    assert kr.apply_template_corrections(corrections, t, "Test Reviewer", date(2026, 11, 3)) == 1
    assert kr.apply_pest_name_corrections(corrections, p) == 1
    updated = yaml.safe_load(t.read_text(encoding="utf-8"))
    assert updated["kn"]["WAIT"].strip() == new_wait.strip()
    assert updated["kn"]["SPRAY"] == original["kn"]["SPRAY"]          # untouched
    assert updated["en"] == original["en"]
    assert "# Kannada reviewed by Test Reviewer on 2026-11-03" in t.read_text(encoding="utf-8")
    assert t.with_name(t.name + ".bak").exists()
    pests = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert pests["classes"][0]["display_kn"] == "ಬಿಳಿ ನೊಣ (ವೈಟ್‌ಫ್ಲೈ)"
    assert "# PLACEHOLDER - confirm with IIHR mentor" in p.read_text(encoding="utf-8")   # comments kept


def test_import_rejects_broken_placeholders(files, tmp_path):
    t, p = files
    out = tmp_path / "review.csv"
    kr.write_csv(kr.export_rows(t, p), out)
    edit_csv(out, {"SPRAY": "ಕ್ರಮ: ಕೀಟನಾಶಕ ಸಿಂಪಡಿಸಿ"})          # {trap_name} etc. missing
    corrections, problems, _ = kr.read_corrections(out)
    assert corrections == {} and "placeholders must stay the same" in problems[0]


def test_templates_still_render_after_rewrite(files, tmp_path, monkeypatch):
    """Rewriting the YAML (block style) must not change any rendered alert."""
    from backend import alerts
    t, p = files
    before = yaml.safe_load(t.read_text(encoding="utf-8"))
    kr.apply_template_corrections({"days_unknown": "ಇನ್ನೂ ಗೊತ್ತಿಲ್ಲ"}, t, "R", date(2026, 11, 3))
    after = yaml.safe_load(t.read_text(encoding="utf-8"))
    for lang in ("en", "kn"):
        for key in before[lang]:
            if key != "days_unknown":
                assert after[lang][key] == before[lang][key], (lang, key)
    monkeypatch.setattr(alerts, "TEMPLATES_FILE", t)
    alerts.templates.cache_clear()
    assert "ಇನ್ನೂ ಗೊತ್ತಿಲ್ಲ" == alerts.templates()["kn"]["days_unknown"]
    alerts.templates.cache_clear()


def test_export_marks_new_and_changed_kannada_as_needs_review(files, tmp_path):
    t, p = files
    first = tmp_path / "first.csv"
    kr.write_csv(kr.export_rows(t, p, previous_csv=None), first)
    rows = list(csv.DictReader(open(first, encoding="utf-8-sig")))
    assert {r["status"] for r in rows} == {"needs review"}                 # nothing seen before
    assert any(r["key"].startswith("advisory.") for r in rows) and any(r["key"].startswith("ui.") for r in rows)
    # same texts again: no longer new
    second = kr.export_rows(t, p, previous_csv=first)
    assert all(r["status"] == "needs review" for r in second)               # status carried over
    marked = [dict(r, status="machine-drafted") for r in rows]
    kr.write_csv(marked, first)
    again = {r["key"]: r["status"] for r in kr.export_rows(t, p, previous_csv=first)}
    assert set(again.values()) == {"machine-drafted"}


def test_import_dashboard_and_advisory_corrections(files, tmp_path):
    import json
    t, p = files
    ui = tmp_path / "strings.json"
    ui.write_text(json.dumps({"quality.BAD": {"en": "Photo not usable", "kn": "ಹಳೆಯದು"}}, ensure_ascii=False),
                  encoding="utf-8")
    adv = tmp_path / "advisory.yaml"
    shutil.copy2(kr.ADVISORY, adv)
    corrections = {"ui.quality.BAD": "ಹೊಸದು", "advisory.trend_stable": "ಸ್ಥಿರ.", "WAIT": None}
    del corrections["WAIT"]
    assert kr.apply_ui_corrections(corrections, ui) == 1
    assert json.loads(ui.read_text(encoding="utf-8"))["quality.BAD"]["kn"] == "ಹೊಸದು"
    assert kr.apply_advisory_corrections(corrections, adv, "R", date(2026, 11, 3)) == 1
    assert yaml.safe_load(adv.read_text(encoding="utf-8"))["kn"]["trend_stable"] == "ಸ್ಥಿರ."
    assert kr.apply_template_corrections(corrections, t, "R", date(2026, 11, 3)) == 0   # prefixed keys skipped

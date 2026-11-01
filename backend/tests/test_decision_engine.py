"""Unit tests for the pure decision engine."""
import re
from datetime import date, timedelta

import pytest

from backend import settings
from backend.decision_engine import (RELEASE_BIOCONTROL, SPRAY, WAIT, DailyCatch, DailyTemperature,
                                     Thresholds, daily_degree_days, decide, degree_day_status,
                                     pest_predator_ratio, rolling_averages)

TH = Thresholds(base_temp_c=10, degree_days_per_generation=300, action_threshold_per_day=25,
                spray_ratio=10, rolling_window_days=3)


def temps(n_days, tmin, tmax, start=date(2026, 10, 1)):
    return [DailyTemperature(start + timedelta(days=i), tmin, tmax) for i in range(n_days)]


# --- degree-days -----------------------------------------------------------
def test_daily_degree_days_formula():
    assert daily_degree_days(20, 30, 10) == 15          # (30+20)/2 - 10
    assert daily_degree_days(12, 14, 10) == 3


def test_daily_degree_days_never_negative():
    assert daily_degree_days(2, 8, 10) == 0


def test_degree_day_accumulation_and_forecast():
    dd = degree_day_status(temps(10, 20, 30), TH)    # 15 DD/day for 10 days
    assert dd.accumulated == 150
    assert dd.generations_completed == 0
    assert dd.progress_fraction == 0.5
    assert dd.dd_remaining == 150
    assert dd.avg_daily_dd == 15
    assert dd.days_to_next_generation == 10           # 150 remaining / 15 per day


def test_degree_days_roll_over_into_generations():
    dd = degree_day_status(temps(25, 20, 30), TH)    # 375 DD
    assert dd.generations_completed == 1
    assert dd.progress_dd == 75
    assert dd.days_to_next_generation == 15           # 225 / 15


def test_forecast_unknown_when_too_cold():
    dd = degree_day_status(temps(5, 0, 8), TH)
    assert dd.days_to_next_generation is None


def test_no_temperature_data():
    dd = degree_day_status([], TH)
    assert dd.accumulated == 0 and dd.days_to_next_generation is None and dd.days_of_data == 0


# --- ratio and rolling window ---------------------------------------------
def test_ratio_counts_zero_predators_as_one():
    assert pest_predator_ratio(30, 0) == 30
    assert pest_predator_ratio(30, 3) == 10


def test_rolling_window_uses_only_last_n_sections():
    catches = [DailyCatch(100, 0), DailyCatch(10, 1), DailyCatch(20, 2), DailyCatch(30, 3)]
    pests, predators, n = rolling_averages(catches, 3)
    assert (pests, predators, n) == (20, 2, 3)


# --- the three decisions ---------------------------------------------------
def test_wait_below_threshold():
    d = decide([DailyCatch(5, 1)] * 3, temps(7, 20, 30), TH, "whitefly")
    assert d.action == WAIT
    assert "below the action threshold" in d.reason


def test_spray_when_pests_high_and_few_predators():
    d = decide([DailyCatch(40, 2)] * 3, temps(7, 20, 30), TH, "whitefly")
    assert d.action == SPRAY
    assert d.ratio == 20
    assert "not keeping pace" in d.reason


def test_biocontrol_when_predators_keep_pace():
    d = decide([DailyCatch(40, 8)] * 3, temps(7, 20, 30), TH, "whitefly")
    assert d.action == RELEASE_BIOCONTROL
    assert d.ratio == 5
    assert "keeping pace" in d.reason


def test_threshold_boundaries_are_inclusive():
    # exactly at the action threshold and exactly at the spray ratio -> SPRAY
    d = decide([DailyCatch(30, 3)], [], TH)
    assert d.pests_per_day == 30 and d.ratio == 10 and d.action == SPRAY
    d = decide([DailyCatch(25, 25)], [], TH)
    assert d.action == RELEASE_BIOCONTROL
    d = decide([DailyCatch(24, 0)], [], TH)
    assert d.action == WAIT


def test_no_sections_means_wait():
    d = decide([], temps(3, 20, 30), TH)
    assert d.action == WAIT and d.window_days_used == 0


def test_reason_includes_generation_forecast():
    d = decide([DailyCatch(40, 2)] * 3, temps(10, 20, 30), TH, "whitefly")
    assert "Next whitefly generation expected in about 10 days" in d.reason


def test_reason_mentions_missing_temperature():
    d = decide([DailyCatch(1, 0)], [], TH)
    assert "No temperature data" in d.reason


def test_decision_is_json_friendly():
    d = decide([DailyCatch(40, 2)], temps(2, 20, 30), TH).to_dict()
    assert d["action"] == SPRAY and isinstance(d["degree_days"], dict)


# --- configuration ---------------------------------------------------------
def test_every_threshold_in_pests_yaml_is_placeholder_or_confirmed():
    text = (settings.ROOT / "config" / "pests.yaml").read_text(encoding="utf-8")
    block = text.split("thresholds:", 1)[1]
    value_lines = [l for l in block.splitlines()
                   if re.match(r"^\s+\w+:\s*[\d.]+", l)]
    assert value_lines, "no threshold values found"
    for line in value_lines:   # the Settings page turns PLACEHOLDER into "Confirmed ... on <date>"
        assert ("PLACEHOLDER - confirm" in line
                or "Confirmed with IIHR mentor on" in line), line


@pytest.mark.parametrize("pest", list(settings.pests_config()["thresholds"]))
def test_thresholds_load_from_config(pest):
    th = Thresholds.from_config(settings.pests_config()["thresholds"][pest])
    assert th.degree_days_per_generation > 0 and th.rolling_window_days >= 1

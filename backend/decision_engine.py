"""KeetaSense decision engine - turns insect counts + temperature into advice.

This is a PURE module: no database, no files, no network. Give it numbers,
get a decision back. That makes every rule easy to unit-test and explain.

The three possible actions:
  SPRAY               pests are above the action threshold AND predators are
                      not keeping pace (many pests per predator)
  RELEASE_BIOCONTROL  pests are above the action threshold BUT predators are
                      keeping pace - support them with more biocontrol agents
                      instead of spraying (spraying would kill them too)
  WAIT                pests are below the action threshold - keep monitoring

Key ideas:
  * Each tape section is exposed for one day, so one section = one day's catch.
    "Pests per day" is the average over the last N sections (rolling window).
  * Pest-to-predator ratio = pests / predators, counting predators as at
    least 1 so we never divide by zero.
  * Degree-days measure accumulated warmth that drives insect development:
        daily DD = max(0, (Tmax + Tmin) / 2 - Tbase)
    A new generation appears roughly every `degree_days_per_generation` DD.
    Dividing the DD still needed by the recent average DD per day gives
    "next generation expected in about N days".

All thresholds come from config/pests.yaml (marked PLACEHOLDER there).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date

SPRAY = "SPRAY"
RELEASE_BIOCONTROL = "RELEASE_BIOCONTROL"
WAIT = "WAIT"

FORECAST_AVG_DAYS = 7  # average daily DD over the last 7 days for the forecast


@dataclass
class Thresholds:
    base_temp_c: float
    degree_days_per_generation: float
    action_threshold_per_day: float
    spray_ratio: float
    rolling_window_days: int

    @classmethod
    def from_config(cls, block: dict) -> "Thresholds":
        return cls(
            base_temp_c=float(block["base_temp_c"]),
            degree_days_per_generation=float(block["degree_days_per_generation"]),
            action_threshold_per_day=float(block["action_threshold_per_day"]),
            spray_ratio=float(block["spray_ratio"]),
            rolling_window_days=int(block["rolling_window_days"]),
        )


@dataclass
class DailyCatch:
    """Counts from one tape section (one day of exposure)."""
    pests: int
    predators: int


@dataclass
class DailyTemperature:
    day: date
    tmin: float
    tmax: float


@dataclass
class DegreeDayStatus:
    accumulated: float              # total DD since the first temperature record
    generations_completed: int
    progress_dd: float              # DD into the current generation
    progress_fraction: float        # 0..1 towards the next generation
    dd_remaining: float
    avg_daily_dd: float | None      # recent average, None if no data
    days_to_next_generation: int | None  # None if it cannot be estimated
    days_of_data: int


@dataclass
class DecisionResult:
    action: str
    reason: str
    pests_per_day: float
    predators_per_day: float
    ratio: float | None
    window_days_used: int
    degree_days: DegreeDayStatus

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Building blocks (each one tested on its own)
# ---------------------------------------------------------------------------
def daily_degree_days(tmin: float, tmax: float, base_temp_c: float) -> float:
    """Simple average method: max(0, (Tmax + Tmin) / 2 - Tbase)."""
    return max(0.0, (tmax + tmin) / 2.0 - base_temp_c)


def degree_day_status(temps: list[DailyTemperature], th: Thresholds) -> DegreeDayStatus:
    """Accumulate degree-days and forecast the next generation."""
    temps = sorted(temps, key=lambda t: t.day)
    daily = [daily_degree_days(t.tmin, t.tmax, th.base_temp_c) for t in temps]
    total = sum(daily)
    per_gen = th.degree_days_per_generation
    generations = int(total // per_gen)
    progress = total - generations * per_gen
    remaining = per_gen - progress

    recent = daily[-FORECAST_AVG_DAYS:]
    avg = sum(recent) / len(recent) if recent else None
    days = math.ceil(remaining / avg) if avg and avg > 0 else None
    return DegreeDayStatus(
        accumulated=round(total, 1),
        generations_completed=generations,
        progress_dd=round(progress, 1),
        progress_fraction=round(progress / per_gen, 3),
        dd_remaining=round(remaining, 1),
        avg_daily_dd=round(avg, 2) if avg is not None else None,
        days_to_next_generation=days,
        days_of_data=len(temps),
    )


def rolling_averages(catches: list[DailyCatch], window: int) -> tuple[float, float, int]:
    """Average pests and predators per day over the last `window` sections."""
    recent = catches[-window:] if window > 0 else catches
    if not recent:
        return 0.0, 0.0, 0
    n = len(recent)
    return (sum(c.pests for c in recent) / n, sum(c.predators for c in recent) / n, n)


def pest_predator_ratio(pests: float, predators: float) -> float:
    """Pests per predator. Predators count as at least 1 to avoid dividing by zero."""
    return pests / max(predators, 1.0)


def _fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def forecast_sentence(dd: DegreeDayStatus, pest_name: str) -> str:
    if dd.days_of_data == 0:
        return "No temperature data yet, so no generation forecast."
    if dd.days_to_next_generation is None:
        return (f"It has been too cold for {pest_name} development recently, "
                f"so the next generation cannot be forecast.")
    return (f"Next {pest_name} generation expected in about {dd.days_to_next_generation} days "
            f"({_fmt(dd.progress_dd)} of {_fmt(dd.dd_remaining + dd.progress_dd)} degree-days accumulated).")


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------
def decide(catches: list[DailyCatch], temps: list[DailyTemperature], th: Thresholds,
           pest_name: str = "pest") -> DecisionResult:
    """Combine recent catches and temperatures into one recommendation.

    catches: tape sections in time order, oldest first (one per day)
    temps:   daily min/max temperatures
    """
    dd = degree_day_status(temps, th)
    forecast = forecast_sentence(dd, pest_name)
    pests, predators, n = rolling_averages(catches, th.rolling_window_days)
    threshold = th.action_threshold_per_day

    if n == 0:
        return DecisionResult(WAIT, f"No tape sections analysed yet. {forecast}",
                              0.0, 0.0, None, 0, dd)

    ratio = pest_predator_ratio(pests, predators)
    window_text = "on the last tape section" if n == 1 else f"on average over the last {n} days"
    catch_text = (f"{_fmt(pests)} {pest_name} per day {window_text} "
                  f"(action threshold {_fmt(threshold)})")

    if pests < threshold:
        action = WAIT
        reason = f"{pest_name.capitalize()} catch is below the action threshold: {catch_text}. Keep monitoring."
    elif ratio >= th.spray_ratio:
        action = SPRAY
        reason = (f"{pest_name.capitalize()} catch is high: {catch_text}. Predators are not keeping pace: "
                  f"{_fmt(ratio)} pests per predator (spray at {_fmt(th.spray_ratio)} or more).")
    else:
        action = RELEASE_BIOCONTROL
        reason = (f"{pest_name.capitalize()} catch is high: {catch_text}, but predators are keeping pace: "
                  f"{_fmt(ratio)} pests per predator (below {_fmt(th.spray_ratio)}). Release more "
                  f"biocontrol agents instead of spraying, which would also kill the predators.")

    return DecisionResult(action, f"{reason} {forecast}", round(pests, 2), round(predators, 2),
                          round(ratio, 2), n, dd)

"""Impact calculator: pesticide reduction, money saved per acre, yield loss avoided.

ESTIMATES, not measurements. Every input is an assumption from
config/impact.yaml (example values) that the user can change on the Impact page.
The one input taken from the system itself is how often it actually said SPRAY:

    sprays with KeetaSense  = SPRAY episodes in the decision history
                              (+1 re-spray for every `respray_interval_days` an episode lasts),
                              per trap, scaled from the observed days to the season length

    sprays saved            = calendar sprays - KeetaSense sprays          (not below 0)
    pesticide reduction %   = sprays saved / calendar sprays x 100
    spray cost saved / acre = sprays saved x cost of one spray
    yield saved / acre (kg) = yield x (loss without - loss with) / 100
    value of yield saved    = yield saved x price
    total benefit / acre    = spray cost saved + value of yield saved
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from functools import lru_cache

import yaml
from sqlmodel import Session, select

from backend import settings
from backend.models import Decision


@lru_cache(maxsize=1)
def assumptions() -> dict:
    with open(settings.ROOT / "config" / "impact.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def spray_history(decisions: list[tuple[str, datetime, str]], respray_days: float) -> dict:
    """decisions: (trap_id, timestamp, action) in any order.
    Counts sprays the system recommended, per trap, and the days observed."""
    by_trap: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for trap_id, ts, action in decisions:
        by_trap[trap_id].append((ts, action))
    sprays, days = [], []
    for rows in by_trap.values():
        rows.sort()
        observed = max(1.0, (rows[-1][0] - rows[0][0]).total_seconds() / 86400 + 1)
        count, start = 0, None
        for ts, action in rows + [(rows[-1][0], "END")]:
            if action == "SPRAY" and start is None:
                start = ts
            elif action != "SPRAY" and start is not None:
                episode_days = (ts - start).total_seconds() / 86400
                count += 1 + int(episode_days // respray_days)
                start = None
        sprays.append(count)
        days.append(observed)
    n = len(sprays)
    return {"traps": n, "sprays_total": sum(sprays), "days_observed_avg": round(sum(days) / n, 1) if n else 0,
            "sprays_per_trap": round(sum(sprays) / n, 2) if n else 0}


def calculate(values: dict, history: dict) -> dict:
    """Pure calculation from assumption values (+ the system's spray history)."""
    v = values
    if v.get("keetasense_sprays_per_season") in (None, ""):
        if history["traps"] and history["days_observed_avg"]:
            per_day = history["sprays_per_trap"] / history["days_observed_avg"]
            guided = math.ceil(per_day * v["season_days"])
            guided_source = (f"estimated from this system's decisions: {history['sprays_per_trap']:g} spray(s) per trap "
                             f"in {history['days_observed_avg']:g} days, scaled to {v['season_days']:g} days")
        else:
            guided, guided_source = v["calendar_sprays_per_season"], "no decision history yet - assumed no change"
    else:
        guided, guided_source = float(v["keetasense_sprays_per_season"]), "entered by you"

    calendar = float(v["calendar_sprays_per_season"])
    saved = max(0.0, calendar - guided)
    reduction_pct = saved / calendar * 100 if calendar else 0.0
    cost_saved = saved * v["cost_per_spray_inr_per_acre"]
    pesticide_saved_l = saved * v["pesticide_litres_per_spray_per_acre"]
    loss_points = max(0.0, v["yield_loss_pct_without"] - v["yield_loss_pct_with"])
    yield_saved_kg = v["yield_tonnes_per_acre"] * 1000 * loss_points / 100
    yield_value = yield_saved_kg * v["price_inr_per_kg"]
    per_acre = cost_saved + yield_value
    area = v["area_acres"]
    return {
        "sprays_calendar": calendar, "sprays_keetasense": guided, "sprays_keetasense_source": guided_source,
        "sprays_saved": round(saved, 1), "pesticide_reduction_pct": round(reduction_pct, 1),
        "pesticide_saved_litres_per_acre": round(pesticide_saved_l, 1),
        "spray_cost_saved_inr_per_acre": round(cost_saved),
        "yield_loss_avoided_kg_per_acre": round(yield_saved_kg),
        "yield_value_saved_inr_per_acre": round(yield_value),
        "total_benefit_inr_per_acre": round(per_acre),
        "total_benefit_inr_farm": round(per_acre * area),
        "area_acres": area,
    }


def validate(values: dict) -> dict[str, str]:
    errors = {}
    for key, spec in assumptions().items():
        val = values.get(key)
        if key == "keetasense_sprays_per_season" and val in (None, ""):
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            errors[key] = "Must be a number."
            continue
        if num < 0 or num != num:
            errors[key] = "Cannot be negative."
        elif key.startswith("yield_loss_pct") and num > 100:
            errors[key] = "Must be 0-100 %."
        elif key in ("season_days", "area_acres") and num == 0:
            errors[key] = "Must be greater than 0."
    return errors


def compute(session: Session, overrides: dict | None = None) -> dict:
    a = assumptions()
    values = {k: spec["value"] for k, spec in a.items()}
    values.update({k: v for k, v in (overrides or {}).items() if k in a})
    errors = validate(values)
    if errors:
        raise ValueError({"errors": errors})
    values = {k: (None if v in (None, "") else float(v)) for k, v in values.items()}
    rows = session.exec(select(Decision.trap_id, Decision.timestamp, Decision.action)).all()
    history = spray_history([tuple(r) for r in rows], values["respray_interval_days"])
    return {"assumptions": a, "values": values, "history": history, "results": calculate(values, history),
            "disclaimer": "Estimate based on the assumptions shown - not a measurement. Replace the example "
                          "values with local data before quoting it."}

"""F5 decision intelligence + the ONE pure evaluation used by both the live engine and the What-if simulator.

evaluate() = the three rules (decision_engine.decide) + the count range / BORDERLINE check (F2)
             + decision support:
    SPRAY               -> cost of harm: predators in this trap's area that a spray would also kill
                           = predators caught per day x predators_in_field_per_trapped
    RELEASE BIOCONTROL  -> dose: release_rate_per_m2 x area_per_trap_m2 predators, and a re-check date
All rates come from config/pests.yaml -> decision_support (PLACEHOLDER values).

No database, no files: services.compute_decision() collects the inputs from the database and
POST /api/decision/simulate builds them from the sliders - both call evaluate(), so the
simulator gives exactly the live answer for the same inputs (tested).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from backend.decision_engine import (RELEASE_BIOCONTROL, SPRAY, DailyCatch, DailyTemperature, Thresholds,
                                     borderline_text, decide, uncertainty)


def support(action: str, predators_per_day: float, cfg: dict, today: date, predator_name: str = "predator",
            release_name: str = "macrolophus") -> dict:
    """Cost of harm (SPRAY) or dosing + re-check date (RELEASE BIOCONTROL)."""
    out = {"predators_at_risk": None, "release_count": None, "release_class": None, "recheck_date": None,
           "area_m2": cfg["area_per_trap_m2"], "text": ""}
    if action == SPRAY:
        at_risk = round(predators_per_day * cfg["predators_in_field_per_trapped"])
        out["predators_at_risk"] = at_risk
        out["text"] = (f"Spraying would also kill an estimated {at_risk} {predator_name}s in the "
                       f"~{cfg['area_per_trap_m2']:g} m² this trap covers (rough estimate from placeholder rates)."
                       if at_risk else "Few predators are present, so a spray would harm few of them.")
    elif action == RELEASE_BIOCONTROL:
        count = math.ceil(cfg["release_rate_per_m2"] * cfg["area_per_trap_m2"])
        recheck = today + timedelta(days=int(cfg["recheck_days"]))
        out.update(release_count=count, release_class=cfg.get("release_class", release_name),
                   recheck_date=recheck.isoformat())
        out["text"] = (f"Suggested release: about {count} {cfg.get('release_class', release_name)} for the "
                       f"~{cfg['area_per_trap_m2']:g} m² this trap covers; check the trap again on "
                       f"{recheck:%d %b %Y} (placeholder rates).")
    return out


def evaluate(catches: list[DailyCatch], temps: list[DailyTemperature], th: Thresholds, *, pest_name: str,
             pest_conf: float | None, predator_conf: float | None, min_confidence: float,
             support_cfg: dict | None, today: date) -> dict:
    """The full decision as a dict (same shape for the live engine and the simulator)."""
    result = decide(catches, temps, th, pest_name).to_dict()
    u = uncertainty(result["pests_per_day"], result["predators_per_day"], pest_conf, predator_conf, th,
                    min_confidence)
    result["uncertainty"] = u
    result["borderline"] = u["borderline"] and result["window_days_used"] > 0
    if result["borderline"]:
        result["reason"] += " " + borderline_text(u, pest_name)
    result["support"] = None
    if support_cfg and result["window_days_used"] > 0:
        s = support(result["action"], result["predators_per_day"], support_cfg, today)
        result["support"] = s
        if s["text"]:
            result["reason"] += " " + s["text"]
    return result

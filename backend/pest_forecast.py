"""Pest-pressure forecast for the next 3-7 days (pure functions, no database).

The model is deliberately simple so it can be explained in one sentence:

    insects multiply with accumulated warmth, so
    ln(pests per day + 1)  =  a  +  b x (accumulated degree-days)

  1. Each recent tape section (= one day's catch) gets the degree-days of its
     day (from the trap's DHT22 readings).
  2. A straight line is fitted through ln(count + 1) against the running total
     of degree-days (least squares) -> growth per degree-day "b".
  3. Future degree-days come from the WEATHER FORECAST (Open-Meteo daily min/max);
     without a forecast, the recent daily average is used.
  4. Prediction = exp(a + b x future accumulated degree-days) - 1, with a band of
     +/- one standard deviation of the fit's errors.

A backtest refits on all but the last 3 sections and predicts those 3; its mean
absolute error is MEASURED on that trap's own data and reported as such.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

BACKTEST_POINTS = 3
RISING_PCT, FALLING_PCT = 5.0, -5.0   # daily change that counts as rising / falling


def daily_dd(tmin: float, tmax: float, base: float) -> float:
    return max(0.0, (tmin + tmax) / 2 - base)


def _fit(cum_dd: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Least-squares line y = a + b*x. Returns (a, b, residual std)."""
    if np.ptp(cum_dd) == 0:            # no warmth difference: flat line through the mean
        return float(y.mean()), 0.0, float(y.std())
    b, a = np.polyfit(cum_dd, y, 1)
    resid = y - (a + b * cum_dd)
    dof = max(1, len(y) - 2)
    return float(a), float(b), float(math.sqrt((resid ** 2).sum() / dof))


def forecast(pests: list[float], section_dd: list[float], future_dd: list[float], *,
             threshold: float, days_ahead: int = 7, min_sections: int = 5,
             start: date | None = None, pest_name: str = "pest", weather_source: str = "recent average") -> dict:
    """pests / section_dd: recent tape sections oldest first (one per day) and each day's degree-days.
    future_dd: degree-days for the coming days (from the weather forecast); padded with the recent
    average if shorter than days_ahead."""
    n = len(pests)
    if n < min_sections:
        return {"status": "not_enough_data", "sections_used": n, "days": [], "text":
                f"Not enough tape sections yet to forecast ({n} of {min_sections} needed)."}

    dd = np.array(section_dd, dtype=float)
    cum = np.cumsum(dd)
    y = np.log(np.array(pests, dtype=float) + 1)
    a, b, s = _fit(cum, y)

    recent_avg = float(dd[-7:].mean())
    future = list(future_dd[:days_ahead]) + [recent_avg] * max(0, days_ahead - len(future_dd))
    start = start or date.today()
    days, total = [], cum[-1]
    for k, ddk in enumerate(future, start=1):
        total += ddk
        mid = a + b * total
        days.append({"day": k, "date": (start + timedelta(days=k)).isoformat(), "degree_days": round(ddk, 1),
                     "pests_per_day": round(max(0.0, math.exp(mid) - 1), 1),
                     "low": round(max(0.0, math.exp(mid - s) - 1), 1),
                     "high": round(max(0.0, math.exp(mid + s) - 1), 1)})

    mean_future_dd = float(np.mean(future)) if future else recent_avg
    daily_change_pct = (math.exp(b * mean_future_dd) - 1) * 100
    trend = "rising" if daily_change_pct > RISING_PCT else "falling" if daily_change_pct < FALLING_PCT else "stable"
    current = float(np.mean(pests[-3:]))
    crosses = None
    if current < threshold:
        crosses = next((d["day"] for d in days if d["pests_per_day"] >= threshold), None)

    backtest_mae = None
    if n >= min_sections + BACKTEST_POINTS:
        k = BACKTEST_POINTS
        a2, b2, _ = _fit(cum[:-k], y[:-k])
        preds = np.exp(a2 + b2 * cum[-k:]) - 1
        backtest_mae = round(float(np.mean(np.abs(preds - np.array(pests[-k:])))), 2)

    if trend == "rising":
        text = f"{pest_name.capitalize()} pressure is rising (about {daily_change_pct:+.0f}% per day at the expected temperatures)."
    elif trend == "falling":
        text = f"{pest_name.capitalize()} pressure is falling (about {daily_change_pct:+.0f}% per day)."
    else:
        text = f"{pest_name.capitalize()} pressure is about stable."
    text += f" Forecast for day {days_ahead}: about {days[-1]['pests_per_day']:.0f} per day."
    if crosses:
        text += f" Expected to reach the action threshold ({threshold:g}/day) in about {crosses} day{'s' if crosses > 1 else ''}."

    return {"status": "ok", "sections_used": n, "days": days, "trend": trend,
            "daily_change_pct": round(daily_change_pct, 1), "growth_per_degree_day": round(b, 4),
            "crosses_threshold_in_days": crosses, "threshold": threshold, "weather_source": weather_source,
            "backtest_mae": backtest_mae, "backtest_points": BACKTEST_POINTS if backtest_mae is not None else 0,
            "text": text}

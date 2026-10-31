"""Can I spray now? A pure function over the hourly weather forecast.

A spray only works if it stays on the leaves: it needs `rain_free_hours` dry
hours afterwards, little wind (drift), and daylight working hours. This module
looks at the forecast and answers:
  - is NOW a good time? if not, why (rain soon / raining / too windy / night)?
  - when is the next good window?
All limits come from config/advisory.yaml (marked PLACEHOLDER there).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta


@dataclass
class SprayConditions:
    rain_free_hours: int
    rain_probability_pct: float
    rain_mm: float
    max_wind_kmh: float
    earliest_hour: int
    latest_hour: int

    @classmethod
    def from_config(cls, block: dict) -> "SprayConditions":
        return cls(int(block["rain_free_hours"]), float(block["rain_probability_pct"]), float(block["rain_mm"]),
                   float(block["max_wind_kmh"]), int(block["earliest_hour"]), int(block["latest_hour"]))


@dataclass
class SprayAdvice:
    ok_now: bool
    reason: str                    # "ok" | "rain_soon" | "raining" | "windy" | "outside_hours" | "no_forecast"
    rain_in_hours: float | None    # hours until the first rainy hour (None = no rain in the forecast)
    rain_prob: float | None        # chance of rain in that hour (%)
    wind_kmh: float | None         # wind now
    next_window: str | None        # ISO time of the next good hour to start spraying
    text: str                      # plain English, for the dashboard and alerts

    def to_dict(self) -> dict:
        return asdict(self)


def _is_rain(h: dict, c: SprayConditions) -> bool:
    return (h.get("rain_prob") or 0) >= c.rain_probability_pct or (h.get("rain_mm") or 0) >= c.rain_mm


def _good_start(hours: list[dict], i: int, c: SprayConditions) -> bool:
    """Is hour i a good time to START spraying?"""
    t = datetime.fromisoformat(hours[i]["time"])
    if not c.earliest_hour <= t.hour < c.latest_hour:
        return False
    if (hours[i].get("wind_kmh") or 0) > c.max_wind_kmh:
        return False
    window = hours[i:i + c.rain_free_hours]
    return len(window) == c.rain_free_hours and not any(_is_rain(h, c) for h in window)


def _when(t: datetime, now: datetime) -> str:
    if t.date() == now.date():
        return f"today {t:%H:%M}"
    if t.date() == (now + timedelta(days=1)).date():
        return f"tomorrow {t:%H:%M}"
    return f"{t:%a %d %b %H:%M}"


def advise(hourly: list[dict] | None, now: datetime, c: SprayConditions) -> SprayAdvice:
    if not hourly:
        return SprayAdvice(False, "no_forecast", None, None, None, None,
                           "No weather forecast available - check the sky and the local forecast before spraying.")
    now_hour = now.replace(minute=0, second=0, microsecond=0)
    hours = [h for h in hourly if datetime.fromisoformat(h["time"]) >= now_hour]
    if not hours:
        return SprayAdvice(False, "no_forecast", None, None, None, None,
                           "The weather forecast is out of date - check the local forecast before spraying.")

    rain_idx = next((i for i, h in enumerate(hours) if _is_rain(h, c)), None)
    rain_in = None
    rain_prob = None
    if rain_idx is not None:
        rain_in = max(0.0, (datetime.fromisoformat(hours[rain_idx]["time"]) - now).total_seconds() / 3600)
        rain_prob = hours[rain_idx].get("rain_prob")
    wind = hours[0].get("wind_kmh")
    nxt = next((i for i in range(len(hours)) if _good_start(hours, i, c)), None)
    next_window = hours[nxt]["time"] if nxt is not None else None
    next_text = (f" Next good time to spray: {_when(datetime.fromisoformat(next_window), now)}."
                 if next_window else " No good spraying window in the forecast period.")

    if _good_start(hours, 0, c):
        if rain_in is not None:
            text = (f"Good time to spray now: no rain expected for the next {c.rain_free_hours} hours "
                    f"(rain likely in about {round(rain_in)} hours).")
        else:
            text = f"Good time to spray now: no rain expected for the next {c.rain_free_hours} hours."
        return SprayAdvice(True, "ok", rain_in, rain_prob, wind, hours[0]["time"], text)

    if rain_idx == 0:
        reason, text = "raining", "Don't spray now: it is raining or rain is very likely this hour."
    elif rain_in is not None and rain_in < c.rain_free_hours:
        hrs = max(1, round(rain_in))
        prob = f" ({rain_prob:.0f}% chance)" if rain_prob is not None else ""
        reason = "rain_soon"
        text = (f"Don't spray now: rain expected in about {hrs} hour{'s' if hrs != 1 else ''}{prob} "
                f"would wash the spray off.")
    elif wind is not None and wind > c.max_wind_kmh:
        reason, text = "windy", f"Don't spray now: wind {wind:.0f} km/h (above {c.max_wind_kmh:.0f} km/h) - the spray would drift."
    else:
        reason, text = "outside_hours", (f"Not a spraying hour now (spray between {c.earliest_hour:02d}:00 "
                                         f"and {c.latest_hour:02d}:00).")
    return SprayAdvice(False, reason, rain_in, rain_prob, wind, next_window, text + next_text)

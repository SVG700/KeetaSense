"""Weather forecast for each trap, from Open-Meteo (free, no API key).

    https://open-meteo.com - "Weather data by Open-Meteo.com" (CC BY 4.0)

The demo must never wait for the internet, so:
  - get_forecast() NEVER blocks: it returns what we already have (memory or the
    cache file backend/data/weather/<trap>.json) and, if that is older than
    `refresh_minutes`, starts a refresh in a background thread.
  - With no internet the cached forecast keeps being used and is labelled with
    its age; with no cache at all there is simply no weather advice.

KEETA_WEATHER (in .env) chooses the source:
  live       (default) Open-Meteo, cached
  simulated  made-up but realistic weather, clearly labelled "Simulated weather"
             - includes a rain shower ~4 hours from now so the demo can show
             "don't spray, rain expected in 4 hours" without internet
  off        no weather at all
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import requests
import yaml

from backend import settings

log = logging.getLogger("keetasense.weather")

API_URL = "https://api.open-meteo.com/v1/forecast"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
HOURLY = "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,wind_speed_10m"
DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max"

_memory: dict[str, dict] = {}
_refreshing: set[str] = set()
_lock = threading.Lock()


@lru_cache(maxsize=1)
def advisory_config() -> dict:
    with open(settings.ROOT / "config" / "advisory.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def mode() -> str:
    m = os.environ.get("KEETA_WEATHER", "live").strip().lower()
    return m if m in ("live", "simulated", "off") else "live"


def trap_location(trap_id: str) -> tuple[float, float] | None:
    for t in settings.traps_config():
        if t["id"] == trap_id and t.get("latitude") is not None:
            return float(t["latitude"]), float(t["longitude"])
    return None


def cache_file(trap_id: str) -> Path:
    return settings.db_path().parent / "weather" / f"{trap_id}.json"


# ---------------------------------------------------------------------------
# Converting Open-Meteo's answer into our simple format
# ---------------------------------------------------------------------------
def parse_open_meteo(data: dict, fetched_at: datetime) -> dict:
    h, d = data.get("hourly", {}), data.get("daily", {})
    hourly = [{
        "time": t,
        "temp_c": h.get("temperature_2m", [None] * len(h["time"]))[i],
        "humidity": h.get("relative_humidity_2m", [None] * len(h["time"]))[i],
        "rain_prob": h.get("precipitation_probability", [None] * len(h["time"]))[i],
        "rain_mm": h.get("precipitation", [None] * len(h["time"]))[i],
        "wind_kmh": h.get("wind_speed_10m", [None] * len(h["time"]))[i],
    } for i, t in enumerate(h.get("time", []))]
    daily = [{
        "date": t,
        "tmax": d.get("temperature_2m_max", [None] * len(d["time"]))[i],
        "tmin": d.get("temperature_2m_min", [None] * len(d["time"]))[i],
        "rain_mm": d.get("precipitation_sum", [None] * len(d["time"]))[i],
        "rain_prob": d.get("precipitation_probability_max", [None] * len(d["time"]))[i],
    } for i, t in enumerate(d.get("time", []))]
    return {"source": "open-meteo", "simulated": False, "fetched_at": fetched_at.isoformat(timespec="seconds"),
            "latitude": data.get("latitude"), "longitude": data.get("longitude"),
            "timezone": data.get("timezone"), "attribution": ATTRIBUTION, "hourly": hourly, "daily": daily}


def fetch_open_meteo(lat: float, lon: float, timeout: float = 8) -> dict:
    r = requests.get(API_URL, timeout=timeout, params={
        "latitude": lat, "longitude": lon, "hourly": HOURLY, "daily": DAILY,
        "forecast_days": 7, "timezone": "auto"})
    r.raise_for_status()
    return parse_open_meteo(r.json(), datetime.now())


# ---------------------------------------------------------------------------
# Simulated weather (offline demo) - clearly labelled
# ---------------------------------------------------------------------------
def simulated_forecast(trap_id: str, now: datetime | None = None) -> dict:
    """Plausible Bengaluru weather with a rain shower starting ~4 hours from now."""
    now = (now or datetime.now()).replace(minute=0, second=0, microsecond=0)
    start = now.replace(hour=0)
    rain_from, rain_to = now + timedelta(hours=4), now + timedelta(hours=6)
    hourly, by_day = [], {}
    for i in range(7 * 24):
        t = start + timedelta(hours=i)
        daily_cycle = math.cos((t.hour - 14) / 24 * 2 * math.pi)
        raining = rain_from <= t < rain_to
        row = {"time": t.strftime("%Y-%m-%dT%H:%M"), "temp_c": round(25 + 5.5 * daily_cycle - (2 if raining else 0), 1),
               "humidity": round(65 - 15 * daily_cycle + (20 if raining else 0)),
               "rain_prob": 75 if raining else 5, "rain_mm": 2.4 if raining else 0.0,
               "wind_kmh": round(8 + 4 * max(0, daily_cycle), 1)}
        hourly.append(row)
        by_day.setdefault(t.date().isoformat(), []).append(row)
    daily = [{"date": day, "tmax": max(r["temp_c"] for r in rows), "tmin": min(r["temp_c"] for r in rows),
              "rain_mm": round(sum(r["rain_mm"] for r in rows), 1), "rain_prob": max(r["rain_prob"] for r in rows)}
             for day, rows in by_day.items()]
    loc = trap_location(trap_id) or (None, None)
    return {"source": "simulated", "simulated": True, "fetched_at": now.isoformat(timespec="seconds"),
            "latitude": loc[0], "longitude": loc[1], "timezone": "local",
            "attribution": "Simulated weather (demo) - not a real forecast", "hourly": hourly, "daily": daily}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def _age_minutes(fc: dict) -> float:
    return (datetime.now() - datetime.fromisoformat(fc["fetched_at"])).total_seconds() / 60


def _load_cache(trap_id: str) -> dict | None:
    try:
        return json.loads(cache_file(trap_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _refresh(trap_id: str, lat: float, lon: float) -> None:
    try:
        fc = fetch_open_meteo(lat, lon)
        path = cache_file(trap_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fc), encoding="utf-8")
        with _lock:
            _memory[trap_id] = fc
        log.info("Weather forecast updated for %s", trap_id)
    except Exception as e:  # offline, timeout, bad answer: keep the old forecast
        log.warning("Weather forecast for %s not updated (%s) - using the cached one if any",
                    trap_id, e.__class__.__name__)
    finally:
        with _lock:
            _refreshing.discard(trap_id)


def get_forecast(trap_id: str, wait: bool = False) -> dict | None:
    """Latest forecast for a trap, or None. Never blocks unless wait=True (used by tests/CLI)."""
    m = mode()
    if m == "off":
        return None
    if m == "simulated":
        return simulated_forecast(trap_id)
    loc = trap_location(trap_id)
    if loc is None:
        return None
    with _lock:
        fc = _memory.get(trap_id)
    if fc is None:
        fc = _load_cache(trap_id)
        if fc:
            with _lock:
                _memory[trap_id] = fc
    refresh_minutes = advisory_config()["weather"]["refresh_minutes"]
    if fc is None or _age_minutes(fc) > refresh_minutes:
        with _lock:
            start = trap_id not in _refreshing
            if start:
                _refreshing.add(trap_id)
        if start:
            t = threading.Thread(target=_refresh, args=(trap_id, *loc), daemon=True)
            t.start()
            if wait:
                t.join()
                with _lock:
                    fc = _memory.get(trap_id, fc)
    if fc is None:
        return None
    out = dict(fc)
    age = _age_minutes(fc)
    out["age_minutes"] = round(age)
    out["stale"] = age > 3 * refresh_minutes
    return out


def reset_memory() -> None:
    """Forget in-memory forecasts (tests)."""
    with _lock:
        _memory.clear()
        _refreshing.clear()

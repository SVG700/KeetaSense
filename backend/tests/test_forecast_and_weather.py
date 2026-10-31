"""Weather (Open-Meteo, cached, simulated), spray window and pest-pressure forecast."""
import json
import math
from datetime import datetime, timedelta

import pytest

from backend import pest_forecast, spray_window, weather

COND = spray_window.SprayConditions(rain_free_hours=6, rain_probability_pct=50, rain_mm=0.5, max_wind_kmh=15,
                                    earliest_hour=6, latest_hour=18)
NOW = datetime(2026, 11, 4, 9, 20)


def hours(n=48, start=datetime(2026, 11, 4, 0, 0), rain_at=(), wind=8.0, wind_at=None):
    out = []
    for i in range(n):
        t = start + timedelta(hours=i)
        rainy = t in rain_at
        out.append({"time": t.strftime("%Y-%m-%dT%H:%M"), "rain_prob": 80 if rainy else 5,
                    "rain_mm": 2.0 if rainy else 0.0, "wind_kmh": (wind_at or {}).get(t, wind)})
    return out


# --- spray window -------------------------------------------------------------
def test_rain_in_4_hours_means_dont_spray():
    rain = {datetime(2026, 11, 4, 13), datetime(2026, 11, 4, 14)}
    a = spray_window.advise(hours(rain_at=rain), NOW, COND)
    assert not a.ok_now and a.reason == "rain_soon"
    assert "rain expected in about 4 hours (80% chance)" in a.text
    assert a.next_window == "2026-11-04T15:00"           # 6 dry hours from 15:00, still a spraying hour
    assert "Next good time to spray: today 15:00." in a.text


def test_good_time_to_spray():
    a = spray_window.advise(hours(), NOW, COND)
    assert a.ok_now and a.reason == "ok" and "Good time to spray now" in a.text


def test_windy_and_night_and_no_forecast():
    windy = spray_window.advise(hours(wind=25), NOW, COND)
    assert windy.reason == "windy" and "25 km/h" in windy.text
    night = spray_window.advise(hours(), datetime(2026, 11, 4, 21, 0), COND)
    assert night.reason == "outside_hours" and night.next_window == "2026-11-05T06:00"
    assert spray_window.advise(None, NOW, COND).reason == "no_forecast"


# --- weather ---------------------------------------------------------------------
SAMPLE = {"latitude": 13.1, "longitude": 77.5, "timezone": "Asia/Kolkata",
          "hourly": {"time": ["2026-11-04T09:00", "2026-11-04T10:00"], "temperature_2m": [24.0, 25.5],
                     "relative_humidity_2m": [70, 65], "precipitation_probability": [10, 60],
                     "precipitation": [0.0, 1.2], "wind_speed_10m": [5.0, 7.0]},
          "daily": {"time": ["2026-11-04"], "temperature_2m_max": [29.0], "temperature_2m_min": [18.0],
                    "precipitation_sum": [1.2], "precipitation_probability_max": [60]}}


def test_parse_open_meteo():
    fc = weather.parse_open_meteo(SAMPLE, datetime(2026, 11, 4, 8))
    assert fc["hourly"][1] == {"time": "2026-11-04T10:00", "temp_c": 25.5, "humidity": 65, "rain_prob": 60,
                               "rain_mm": 1.2, "wind_kmh": 7.0}
    assert fc["daily"][0]["tmin"] == 18.0 and "Open-Meteo" in fc["attribution"]


@pytest.fixture
def live_weather(tmp_path, monkeypatch):
    monkeypatch.setenv("KEETA_WEATHER", "live")
    monkeypatch.setenv("KEETA_DB_PATH", str(tmp_path / "x.db"))
    weather.reset_memory()
    yield tmp_path
    weather.reset_memory()


def test_live_forecast_is_cached_and_survives_going_offline(live_weather, monkeypatch):
    calls = []
    monkeypatch.setattr(weather, "fetch_open_meteo",
                        lambda lat, lon: calls.append(1) or weather.parse_open_meteo(SAMPLE, datetime.now()))
    fc = weather.get_forecast("T1-polyhouse", wait=True)
    assert fc["source"] == "open-meteo" and len(calls) == 1
    assert json.loads(weather.cache_file("T1-polyhouse").read_text())["hourly"]
    weather.get_forecast("T1-polyhouse", wait=True)
    assert len(calls) == 1                                    # fresh cache: no second download

    # an hour later the internet is gone: the old forecast keeps being used, with its age
    weather.reset_memory()
    old = json.loads(weather.cache_file("T1-polyhouse").read_text())
    old["fetched_at"] = (datetime.now() - timedelta(hours=5)).isoformat(timespec="seconds")
    weather.cache_file("T1-polyhouse").write_text(json.dumps(old))

    def offline(lat, lon):
        raise OSError("no internet")
    monkeypatch.setattr(weather, "fetch_open_meteo", offline)
    fc = weather.get_forecast("T1-polyhouse", wait=True)
    assert fc is not None and fc["age_minutes"] >= 299 and fc["stale"] is True


def test_no_cache_and_offline_gives_none(live_weather, monkeypatch):
    monkeypatch.setattr(weather, "fetch_open_meteo", lambda lat, lon: (_ for _ in ()).throw(OSError("offline")))
    assert weather.get_forecast("T1-polyhouse", wait=True) is None


def test_simulated_weather_has_rain_in_4_hours(monkeypatch):
    monkeypatch.setenv("KEETA_WEATHER", "simulated")
    now = datetime.now()
    fc = weather.get_forecast("T1-polyhouse")
    assert fc["simulated"] and "Simulated" in fc["attribution"] and len(fc["daily"]) == 7
    a = spray_window.advise(fc["hourly"], now, COND)
    assert a.rain_in_hours is not None and 3 <= a.rain_in_hours <= 4


def test_unknown_trap_and_off_mode(monkeypatch):
    monkeypatch.setenv("KEETA_WEATHER", "off")
    assert weather.get_forecast("T1-polyhouse") is None
    monkeypatch.setenv("KEETA_WEATHER", "live")
    assert weather.get_forecast("no-such-trap") is None


# --- pest-pressure forecast ---------------------------------------------------------
def test_forecast_follows_exponential_growth():
    dd = [10.0] * 10
    pests = [math.exp(0.02 * 10 * (i + 1)) - 1 for i in range(10)]      # ln(p+1) grows 0.2 per day
    f = pest_forecast.forecast(pests, dd, [10.0] * 7, threshold=100, days_ahead=7)
    assert f["status"] == "ok" and f["trend"] == "rising"
    assert f["growth_per_degree_day"] == pytest.approx(0.02, abs=1e-6)
    expected_day1 = math.exp(0.02 * 110) - 1
    assert f["days"][0]["pests_per_day"] == pytest.approx(expected_day1, abs=0.1)
    assert f["backtest_mae"] == pytest.approx(0, abs=0.01) and f["backtest_points"] == 3


def test_forecast_threshold_crossing_and_weather_effect():
    pests = [5, 6, 7, 8, 9, 11, 12]
    dd = [8.0] * 7
    warm = pest_forecast.forecast(pests, dd, [14.0] * 7, threshold=20, days_ahead=7)
    cold = pest_forecast.forecast(pests, dd, [0.0] * 7, threshold=20, days_ahead=7)
    assert warm["crosses_threshold_in_days"] is not None
    assert cold["days"][-1]["pests_per_day"] < warm["days"][-1]["pests_per_day"]   # no warmth, no growth
    assert "action threshold" in warm["text"]


def test_forecast_needs_enough_sections():
    f = pest_forecast.forecast([1, 2], [8, 8], [], threshold=25, min_sections=5)
    assert f["status"] == "not_enough_data" and "2 of 5" in f["text"]

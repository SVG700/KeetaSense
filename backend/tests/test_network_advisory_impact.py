"""Station network (early warning, heat map), multilingual advisory, impact calculator."""
import re
from datetime import datetime, timedelta

import pytest

from backend import advisory, impact, network
from backend.tests.conftest import tape_jpeg

LANGS = ["en", "kn", "hi", "ta"]


# --- network ------------------------------------------------------------------
def test_distance_km():
    assert network.distance_km(13.0, 77.5, 14.0, 77.5) == pytest.approx(111.2, abs=0.5)
    assert network.distance_km(13.1, 77.5, 13.1, 77.5) == 0


def S(id, lat, lon, pests, threshold=25, action="WAIT"):
    return {"id": id, "name": id.upper(), "lat": lat, "lon": lon, "pests_per_day": pests, "threshold": threshold,
            "action": action}


def test_early_warnings_only_near_outbreaks_and_only_for_quiet_farms():
    stations = [S("a", 13.13, 77.49, 40, action="SPRAY"),     # outbreak
                S("b", 13.15, 77.48, 10),                      # ~2.5 km away, quiet -> warned
                S("c", 13.40, 77.90, 5),                       # ~50 km away -> not warned
                S("d", 13.135, 77.495, 30, action="SPRAY")]    # outbreak itself -> no warning
    w = network.early_warnings(stations, radius_km=10)
    assert [x["neighbour_id"] for x in w["b"]] == ["d", "a"] or [x["neighbour_id"] for x in w["b"]] == ["a", "d"]
    assert w["c"] == [] and w["a"] == [] and w["d"] == []
    assert w["b"][0]["km"] <= w["b"][1]["km"]


def test_heat_grid_matches_stations_and_stays_between_extremes():
    stations = [S("a", 13.10, 77.45, 50), S("b", 13.20, 77.55, 0)]
    g = network.heat_grid(stations, cols=10, rows=8)
    values = [v for row in g["cells"] for v in row]
    assert len(g["cells"]) == 8 and len(g["cells"][0]) == 10
    assert 0 <= min(values) and max(values) <= 2.0
    assert g["cells"][-1][0] > g["cells"][0][-1]        # south-west (near a) hotter than north-east


# --- advisory -----------------------------------------------------------------------
def fake_adv(action="SPRAY", reason="rain_soon"):
    return {"trap_id": "T1", "trap_name": "Trap One", "target_pest": "whitefly", "generated_at": "2026-11-04T09:20:00",
            "decision": {"action": action, "pests_per_day": 31.0, "predators_per_day": 1.0},
            "forecast": {"status": "ok", "trend": "rising", "daily_change_pct": 12.0, "crosses_threshold_in_days": 3},
            "spray": {"ok_now": reason == "ok", "reason": reason, "rain_in_hours": 4.0, "rain_prob": 80.0,
                      "wind_kmh": 6.0, "next_window": "2026-11-05T06:00"},
            "spray_rain_free_hours": 6,
            "early_warnings": [{"neighbour_id": "T2", "neighbour": "Trap Two", "km": 3.4}],
            "sensor": {"temperature_c": 26.5, "humidity_pct": 70.0}}


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("reason", ["ok", "rain_soon", "raining", "windy", "outside_hours", "no_forecast"])
def test_render_every_language_and_spray_reason(lang, reason):
    r = advisory.render(fake_adv(reason=reason), lang)
    assert r["lang"] == lang and len(r["lines"]) >= 4
    assert not re.search(r"\{\w+\}", r["text"]), r["text"]          # every placeholder filled


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("action", ["SPRAY", "RELEASE_BIOCONTROL", "WAIT"])
def test_spray_answer_every_language(lang, action):
    text = advisory.answer_spray_question(fake_adv(action=action), lang)
    assert not re.search(r"\{\w+\}", text) and "26.5" in text


def test_english_spray_answer_mentions_rain_and_next_window():
    text = advisory.answer_spray_question(fake_adv(), "en")
    assert "Yes, spraying is needed." in text
    assert "rain expected in about 4 hours (80% chance)" in text
    assert "Next good time to spray: tomorrow 06:00." in text


def test_templates_have_same_keys_and_placeholders_in_every_language():
    t = advisory.templates()
    for lang in LANGS:
        assert set(t[lang]) == set(t["en"]), lang
        for key, text in t["en"].items():
            assert set(re.findall(r"\{(\w+)\}", t[lang][key])) == set(re.findall(r"\{(\w+)\}", text)), (lang, key)


# --- API ----------------------------------------------------------------------------
def post(client, trap, n, seed):
    return client.post("/api/sections", files={"image": ("t.jpg", tape_jpeg(n, 0, seed=seed), "image/jpeg")},
                       data={"trap_id": trap})


def test_advisory_api_in_hindi_and_bad_language(client):
    post(client, "T1-polyhouse", 10, 1)
    r = client.get("/api/advisory/T1-polyhouse?lang=hi")
    assert r.status_code == 200
    body = r.json()
    assert body["rendered"]["lang"] == "hi" and "कार्रवाई" in body["rendered"]["text"]
    assert body["spray"]["reason"] == "no_forecast"                  # weather is off in tests
    assert body["languages"]["ta"] == "தமிழ்"
    assert client.get("/api/advisory/T1-polyhouse?lang=fr").status_code == 422


def test_outbreak_sends_early_warning_once(client):
    for i in range(3):
        post(client, "T2-openfield", 40, 10 + i)     # T2 crosses the threshold
    alerts = client.get("/api/alerts?limit=100").json()
    warned = {a["trap_id"] for a in alerts if a["action"] == "EARLY_WARNING"}
    assert {"T1-polyhouse", "T3-hesaraghatta"} <= warned       # neighbours within 10 km
    before = len(alerts)
    post(client, "T2-openfield", 40, 20)
    after = client.get("/api/alerts?limit=100").json()
    assert len([a for a in after if a["action"] == "EARLY_WARNING"]) == \
           len([a for a in alerts if a["action"] == "EARLY_WARNING"])      # not repeated
    assert len(after) >= before
    net = client.get("/api/network").json()
    t3 = next(s for s in net["stations"] if s["id"] == "T3-hesaraghatta")
    assert t3["warnings"][0]["neighbour_id"] == "T2-openfield"
    assert len(net["heat"]["cells"]) == net["heat"]["rows"]


# --- impact -------------------------------------------------------------------------
def test_spray_history_counts_episodes_and_resprays():
    d0 = datetime(2026, 10, 1)
    rows = [("t", d0 + timedelta(days=i), a) for i, a in enumerate(
        ["WAIT", "SPRAY", "SPRAY", "WAIT", "SPRAY"] + ["SPRAY"] * 8 + ["WAIT"])]
    h = impact.spray_history(rows, respray_days=7)
    # episode 1: 2 days -> 1 spray; episode 2: 9 days -> 1 + 1 re-spray
    assert h["sprays_total"] == 3 and h["days_observed_avg"] == 14


def test_calculate_formulas():
    v = {"area_acres": 2, "season_days": 120, "calendar_sprays_per_season": 12, "keetasense_sprays_per_season": 4,
         "respray_interval_days": 7, "cost_per_spray_inr_per_acre": 1500, "pesticide_litres_per_spray_per_acre": 1.0,
         "yield_tonnes_per_acre": 15, "price_inr_per_kg": 15, "yield_loss_pct_without": 15, "yield_loss_pct_with": 7}
    r = impact.calculate(v, {"traps": 0, "days_observed_avg": 0, "sprays_per_trap": 0})
    assert r["sprays_saved"] == 8 and r["pesticide_reduction_pct"] == pytest.approx(66.7, abs=0.1)
    assert r["spray_cost_saved_inr_per_acre"] == 12000
    assert r["yield_loss_avoided_kg_per_acre"] == 1200 and r["yield_value_saved_inr_per_acre"] == 18000
    assert r["total_benefit_inr_per_acre"] == 30000 and r["total_benefit_inr_farm"] == 60000
    assert r["sprays_keetasense_source"] == "entered by you"


def test_impact_api_defaults_overrides_and_validation(client):
    body = client.get("/api/impact").json()
    assert "not a measurement" in body["disclaimer"]
    assert body["assumptions"]["calendar_sprays_per_season"]["note"].startswith("ASSUMPTION")
    r = client.post("/api/impact", json={"values": {"keetasense_sprays_per_season": 3}})
    assert r.status_code == 200 and r.json()["results"]["sprays_saved"] == 9
    bad = client.post("/api/impact", json={"values": {"yield_loss_pct_with": 140, "area_acres": -1}})
    assert bad.status_code == 422 and set(bad.json()["detail"]["errors"]) == {"yield_loss_pct_with", "area_acres"}

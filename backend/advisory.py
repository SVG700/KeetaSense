"""The farmer advisory: everything one trap's farmer needs, in their language.

build()  gathers the facts (database + weather):
           decision, counts, pest-pressure forecast, can-I-spray-now check,
           early warnings from neighbouring farms, latest sensor reading
render() turns those facts into short sentences in en / kn / hi / ta
         (texts in backend/advisory_templates.yaml)
answer_spray_question() answers "Can I spray today?" (Telegram bot, dashboard)
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import yaml
from sqlmodel import Session, select

from backend import network, pest_forecast, services, settings, spray_window, weather
from backend.models import TapeSection, Trap

log = logging.getLogger("keetasense.advisory")

TEMPLATES_FILE = Path(__file__).resolve().parent / "advisory_templates.yaml"
LANGUAGES = {"en": "English", "kn": "ಕನ್ನಡ", "hi": "हिन्दी", "ta": "தமிழ்"}


@lru_cache(maxsize=1)
def templates() -> dict:
    with open(TEMPLATES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _cfg() -> dict:
    return weather.advisory_config()


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------
def station_facts(session: Session, trap: Trap) -> dict | None:
    """Pressure numbers for the network map (None if the trap has no coordinates)."""
    loc = weather.trap_location(trap.id)
    if loc is None:
        return None
    d = services.compute_decision(session, trap)
    th = services.thresholds_for(trap.target_pest)
    return {"id": trap.id, "name": trap.name, "lat": loc[0], "lon": loc[1], "simulated": trap.simulated,
            "pests_per_day": d["pests_per_day"], "predators_per_day": d["predators_per_day"],
            "threshold": th.action_threshold_per_day, "action": d["action"]}


def network_state(session: Session) -> dict:
    stations = [f for f in (station_facts(session, t) for t in session.exec(select(Trap).order_by(Trap.id)).all())
                if f is not None]
    radius = float(_cfg()["early_warning"]["radius_km"])
    warnings = network.early_warnings(stations, radius)
    for s in stations:
        s["pressure"] = round(network.pressure(s), 2)
        s["warnings"] = warnings.get(s["id"], [])
    return {"stations": stations, "radius_km": radius, "heat": network.heat_grid(stations)}


def forecast_for(session: Session, trap: Trap, fc: dict | None) -> dict:
    cfg = _cfg()["forecast"]
    th = services.thresholds_for(trap.target_pest)
    sections = session.exec(select(TapeSection).where(TapeSection.trap_id == trap.id)
                            .order_by(TapeSection.timestamp.desc()).limit(cfg["history_sections"])).all()[::-1]
    daily = {d["date"]: d["degree_days"] for d in services.daily_climate(session, trap)}
    fallback = (sum(daily.values()) / len(daily)) if daily else 8.0
    section_dd = [daily.get(s.timestamp.date().isoformat(), fallback) for s in sections]
    future, source = [], "recent average"
    if fc and fc.get("daily"):
        today = date.today().isoformat()
        future = [pest_forecast.daily_dd(d["tmin"], d["tmax"], th.base_temp_c) for d in fc["daily"]
                  if d["date"] > today and d["tmin"] is not None and d["tmax"] is not None]
        source = "simulated weather forecast" if fc.get("simulated") else "Open-Meteo weather forecast"
    return pest_forecast.forecast(
        [s.pest_total for s in sections], section_dd, future, threshold=th.action_threshold_per_day,
        days_ahead=int(cfg["days_ahead"]), min_sections=int(cfg["min_sections"]),
        pest_name=settings.pest_display_name(trap.target_pest).lower(), weather_source=source)


def build(session: Session, trap: Trap, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    decision = services.compute_decision(session, trap)
    fc = weather.get_forecast(trap.id)
    cond = spray_window.SprayConditions.from_config(_cfg()["spray_conditions"])
    spray = spray_window.advise(fc["hourly"] if fc else None, now, cond).to_dict()
    net = network_state(session)
    me = next((s for s in net["stations"] if s["id"] == trap.id), None)
    summary = services.trap_summary(session, trap)
    return {
        "trap_id": trap.id, "trap_name": trap.name, "target_pest": trap.target_pest,
        "generated_at": now.isoformat(timespec="seconds"),
        "decision": decision,
        "forecast": forecast_for(session, trap, fc),
        "spray": spray, "spray_rain_free_hours": cond.rain_free_hours,
        "weather": None if fc is None else {
            "source": fc["source"], "simulated": fc.get("simulated", False), "attribution": fc["attribution"],
            "fetched_at": fc["fetched_at"], "age_minutes": fc.get("age_minutes"), "stale": fc.get("stale", False),
            "next_hours": [h for h in fc["hourly"] if h["time"] >= now.strftime("%Y-%m-%dT%H:00")][:24],
            "daily": fc["daily"]},
        "early_warnings": me["warnings"] if me else [],
        "sensor": summary["latest_climate"],
    }


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------
def _fmt(x) -> str:
    if x is None:
        return "-"
    return f"{x:.1f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def _when(iso: str | None, now: datetime, t: dict) -> str | None:
    if not iso:
        return None
    w = datetime.fromisoformat(iso)
    time = w.strftime("%H:%M")
    if w.date() == now.date():
        return t["when_today"].format(time=time)
    if (w.date() - now.date()).days == 1:
        return t["when_tomorrow"].format(time=time)
    return t["when_date"].format(date=w.strftime("%d-%m"), time=time)


def _spray_line(adv: dict, t: dict, now: datetime) -> list[str]:
    s = adv["spray"]
    key = f"spray_{s['reason']}"
    line = t[key].format(dry_hours=adv["spray_rain_free_hours"], hours=max(1, round(s["rain_in_hours"] or 0)),
                         prob=_fmt(s["rain_prob"]), wind=_fmt(s["wind_kmh"]))
    lines = [line]
    if not s["ok_now"] and s["next_window"]:
        lines.append(t["spray_next"].format(when=_when(s["next_window"], now, t)))
    return lines


def render(adv: dict, lang: str = "en", now: datetime | None = None) -> dict:
    """Short advisory sentences in one language."""
    lang = lang if lang in templates() else "en"
    t = templates()[lang]
    now = now or datetime.fromisoformat(adv["generated_at"])
    d = adv["decision"]
    pest = settings.pest_display_name(adv["target_pest"], lang)
    lines = [t[f"action_{d['action']}"],
             t["counts"].format(pest_name=pest, pests=_fmt(d["pests_per_day"]), predators=_fmt(d["predators_per_day"]))]
    f = adv["forecast"]
    if f.get("status") == "ok":
        lines.append(t[f"trend_{f['trend']}"].format(pct=_fmt(abs(f["daily_change_pct"]))))
        if f.get("crosses_threshold_in_days"):
            lines.append(t["crosses"].format(days=f["crosses_threshold_in_days"]))
    if d["action"] == "SPRAY":
        lines += _spray_line(adv, t, now)
    for w in adv["early_warnings"][:2]:
        lines.append(t["warning"].format(neighbour=w["neighbour"], km=_fmt(w["km"])))
    title = t["title"].format(trap_name=adv["trap_name"])
    return {"lang": lang, "title": title, "lines": lines, "text": title + "\n" + "\n".join(lines)}


def answer_spray_question(adv: dict, lang: str = "en", now: datetime | None = None) -> str:
    """'Can I spray today?' - answered from the live counts, decision and weather."""
    lang = lang if lang in templates() else "en"
    t = templates()[lang]
    now = now or datetime.fromisoformat(adv["generated_at"])
    d = adv["decision"]
    pest = settings.pest_display_name(adv["target_pest"], lang)
    if d["action"] == "CHECK_TRAP":
        lines = [t["answer_check_trap"]]
    elif d["action"] == "WAIT":
        lines = [t["answer_no_need"].format(pest_name=pest, pests=_fmt(d["pests_per_day"]))]
    elif d["action"] == "RELEASE_BIOCONTROL":
        lines = [t["answer_biocontrol"]]
    else:
        lines = [t["answer_need"]] + _spray_line(adv, t, now)
    if adv.get("sensor"):
        lines.append(t["sensor"].format(temp=_fmt(adv["sensor"]["temperature_c"]), hum=_fmt(adv["sensor"]["humidity_pct"])))
    for w in adv["early_warnings"][:1]:
        lines.append(t["warning"].format(neighbour=w["neighbour"], km=_fmt(w["km"])))
    return t["title"].format(trap_name=adv["trap_name"]) + "\n" + "\n".join(lines)

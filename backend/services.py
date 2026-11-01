"""Backend logic shared by the API endpoints and demo/seed.py.

Keeping this out of main.py means the endpoints stay short and the seed
script stores data exactly the same way the live system does.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta

import cv2
import numpy as np
from sqlmodel import Session, select

from backend import actions, alerts, decision_support, hygiene, image_quality, settings
from backend.decision_engine import (DailyCatch, DailyTemperature, Thresholds, daily_degree_days, decide)
from backend.models import ClimateReading, Decision, TapeSection, Trap, TrapHealth
from ml import infer
from ml.common import category_of

log = logging.getLogger("keetasense.services")

ONLINE_WITHIN = timedelta(hours=26)
CHECK_TRAP = "CHECK_TRAP"   # decision state when the latest photo is unusable (image quality gate)  # a trap reports at least daily; allow some slack


# ---------------------------------------------------------------------------
# Traps
# ---------------------------------------------------------------------------
def sync_traps(session: Session) -> None:
    """Create or update the traps listed in config/traps.yaml."""
    for t in settings.traps_config():
        trap = session.get(Trap, t["id"]) or Trap(id=t["id"], name=t["name"])
        trap.name = t["name"]
        trap.location = t.get("location", "")
        trap.crop = t.get("crop", "")
        trap.target_pest = t.get("target_pest", "whitefly")
        trap.simulated = bool(t.get("simulated", False))
        session.add(trap)
    session.commit()


def thresholds_for(pest: str) -> Thresholds:
    block = settings.pests_config()["thresholds"].get(pest)
    if block is None:
        raise ValueError(f"No thresholds for pest '{pest}' in config/pests.yaml")
    return Thresholds.from_config(block)


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
def decode_image(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("The uploaded file is not a readable image (use JPG or PNG).")
    return img


def save_image(img: np.ndarray, folder: str, stem: str) -> str:
    """Save a BGR image under the media folder; return its relative path."""
    rel = f"{folder}/{stem}.jpg"
    path = settings.media_dir() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return rel


def media_url(rel: str | None) -> str | None:
    return f"/media/{rel}" if rel else None


def run_detection(img: np.ndarray, detections: list[dict] | None = None,
                  detector_mode: str | None = None) -> infer.DetectionResult:
    """Run the detector, or reuse detections already made on the edge device."""
    if detections is None:
        return infer.detect(img)
    clean = []
    for d in detections:  # never trust the shape of data coming over the network
        clean.append({
            "class_name": str(d["class_name"]),
            "category": category_of(str(d["class_name"])),
            "confidence": float(d.get("confidence", 0.0)),
            "bbox": [float(v) for v in d["bbox"]][:4],
        })
    mode = detector_mode or infer.MODE_DEMO
    warning = infer.DEMO_WARNING if mode == infer.MODE_DEMO else None
    return infer.build_result(img, clean, mode, warning)


# ---------------------------------------------------------------------------
# Tape sections and climate
# ---------------------------------------------------------------------------
def process_section(session: Session, trap: Trap, img: np.ndarray, timestamp: datetime,
                    simulated: bool = False, detections: list[dict] | None = None,
                    detector_mode: str | None = None, notify: bool = True, source: str = "live"
                    ) -> tuple[TapeSection, infer.DetectionResult, dict]:
    """Detect insects on one tape section, store it, and update the decision."""
    result = run_detection(img, detections, detector_mode)
    q_status, q_reasons, q_metrics = image_quality.check(img, previous_image(session, trap))
    if q_status != image_quality.OK:
        log.warning("Image quality %s for %s: %s", q_status, trap.id, image_quality.reasons_text(q_reasons))
    stem = f"{trap.id}/{timestamp:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    section = TapeSection(
        trap_id=trap.id, timestamp=timestamp,
        image_path=save_image(img, "uploads", stem),
        annotated_path=save_image(result.annotated_image, "annotated", stem),
        counts=result.counts, pest_total=result.pest_total, predator_total=result.predator_total,
        detector_mode=result.mode, simulated=simulated, source=source,
        quality_status=q_status, quality_reasons=q_reasons, quality_metrics=q_metrics,
        detections=result.detections,
    )
    session.add(section)
    session.commit()
    session.refresh(section)
    decision = update_decision(session, trap, notify=notify, now=timestamp)
    return section, result, decision


def previous_image(session: Session, trap: Trap) -> np.ndarray | None:
    """The trap's latest stored photo (to check that the tape really advanced)."""
    prev = session.exec(select(TapeSection).where(TapeSection.trap_id == trap.id)
                        .order_by(TapeSection.timestamp.desc(), TapeSection.id.desc())).first()
    if prev is None:
        return None
    return cv2.imread(str(settings.media_dir() / prev.image_path))


def add_climate(session: Session, trap: Trap, timestamp: datetime, temperature_c: float,
                humidity_pct: float, simulated: bool = False) -> ClimateReading:
    row = ClimateReading(trap_id=trap.id, timestamp=timestamp, temperature_c=temperature_c,
                         humidity_pct=humidity_pct, simulated=simulated)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def daily_climate(session: Session, trap: Trap, since: date | None = None) -> list[dict]:
    """Group climate readings by day: min/max temperature, mean humidity, degree-days."""
    q = select(ClimateReading).where(ClimateReading.trap_id == trap.id)
    if since:
        q = q.where(ClimateReading.timestamp >= datetime.combine(since, datetime.min.time()))
    by_day: dict[date, list[ClimateReading]] = defaultdict(list)
    for r in session.exec(q.order_by(ClimateReading.timestamp)):
        by_day[r.timestamp.date()].append(r)
    base = thresholds_for(trap.target_pest).base_temp_c
    out = []
    for day in sorted(by_day):
        temps = [r.temperature_c for r in by_day[day]]
        tmin, tmax = min(temps), max(temps)
        out.append({
            "date": day.isoformat(), "tmin": round(tmin, 1), "tmax": round(tmax, 1),
            "humidity_avg": round(sum(r.humidity_pct for r in by_day[day]) / len(by_day[day]), 1),
            "degree_days": round(daily_degree_days(tmin, tmax, base), 2),
            "readings": len(temps),
            "simulated": any(r.simulated for r in by_day[day]),
        })
    return out


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------
def compute_decision(session: Session, trap: Trap) -> dict:
    th = thresholds_for(trap.target_pest)
    # BAD photos (blurred, dark, glare, tape not advanced) are never counted
    good = (TapeSection.quality_status.is_(None)) | (TapeSection.quality_status != image_quality.BAD)
    recent = session.exec(select(TapeSection).where(TapeSection.trap_id == trap.id, good)
                          .order_by(TapeSection.timestamp.desc()).limit(th.rolling_window_days)).all()
    # scout-corrected counts replace the model's counts (F3)
    catches = [DailyCatch(s.effective_pest_total, s.effective_predator_total) for s in reversed(recent)]
    temps = [DailyTemperature(date.fromisoformat(d["date"]), d["tmin"], d["tmax"])
             for d in daily_climate(session, trap)]
    # F2: how sure is the detector? -> count range -> BORDERLINE if the advice could differ inside it
    pest_conf, predator_conf = window_confidence(session, recent)
    # one pure function for the live engine AND the What-if simulator (F5)
    result = decision_support.evaluate(
        catches, temps, th, pest_name=settings.pest_display_name(trap.target_pest).lower(),
        pest_conf=pest_conf, predator_conf=predator_conf, min_confidence=min_confidence(),
        support_cfg=support_config(trap.target_pest), today=date.today())
    latest = session.exec(select(TapeSection).where(TapeSection.trap_id == trap.id)
                          .order_by(TapeSection.timestamp.desc(), TapeSection.id.desc())).first()
    result["quality"] = None
    if latest is not None and latest.quality_status:
        result["quality"] = {"status": latest.quality_status, "reasons": latest.quality_reasons,
                             "section_id": latest.id}
    if latest is not None and latest.quality_status == image_quality.BAD:
        # CHECK TRAP: no spray / release advice until a usable photo arrives
        result["underlying_action"] = result["action"]
        result["action"] = CHECK_TRAP
        result["reason"] = image_quality.check_trap_reason(latest.quality_reasons, "en")
    return result


def min_confidence() -> float:
    return float(settings.pests_config()["confidence"]["min_confidence"])


def support_config(pest: str) -> dict | None:
    """F5 rates (pests.yaml -> decision_support) for this pest, or None."""
    return (settings.pests_config().get("decision_support") or {}).get(pest)


def window_confidence(session: Session, sections: list[TapeSection]) -> tuple[float | None, float | None]:
    """Mean detection confidence of pest boxes and of predator boxes over these sections.

    Scout-corrected boxes count as 1.0 (checked by a person). None when no boxes are stored
    (old data, or nothing detected) - then no range is computed."""
    from backend.corrections import apply_corrections, corrections_for   # lazy: corrections imports services
    pest, pred = [], []
    for s in sections:
        if not s.detections and s.corrected_pest_total is None:
            continue
        boxes = apply_corrections(s.detections, corrections_for(session, s.id)) if s.corrected_pest_total is not None \
            else [dict(d, category=d.get("category")) for d in s.detections]
        for b in boxes:
            conf = b.get("confidence")
            if conf is None:
                continue
            (pest if b.get("category") == "pest" else pred if b.get("category") == "predator" else []).append(float(conf))
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    return mean(pest), mean(pred)


def latest_decision(session: Session, trap_id: str) -> Decision | None:
    return session.exec(select(Decision).where(Decision.trap_id == trap_id)
                        .order_by(Decision.timestamp.desc(), Decision.id.desc())).first()


def update_decision(session: Session, trap: Trap, notify: bool = True,
                    now: datetime | None = None) -> dict:
    """Recompute the decision, store it, and alert if the action changed."""
    decision = compute_decision(session, trap)
    previous = latest_decision(session, trap.id)
    previous_action = previous.action if previous else None
    session.add(Decision(trap_id=trap.id, timestamp=now or datetime.now(), action=decision["action"],
                         reason=decision["reason"], details=decision))
    session.commit()
    changed = previous_action != decision["action"]
    first_and_actionable = previous_action is None and decision["action"] != "WAIT"
    if notify and ((previous_action is not None and changed) or first_and_actionable):
        alerts.notify_decision_change(session, trap, decision, previous_action,
                                      cooldown_until=actions.cooldown_until(session, trap.id, now))
    decision["changed"] = changed
    decision["previous_action"] = previous_action
    return decision


# ---------------------------------------------------------------------------
# Serialisers (database rows -> JSON for the frontend)
# ---------------------------------------------------------------------------
def section_to_dict(s: TapeSection) -> dict:
    return {
        "corrected": s.corrected_counts is not None,
        "corrected_counts": s.corrected_counts, "corrected_pest_total": s.corrected_pest_total,
        "corrected_predator_total": s.corrected_predator_total,
        "effective_pest_total": s.effective_pest_total, "effective_predator_total": s.effective_predator_total,
        "quality_status": s.quality_status, "quality_reasons": s.quality_reasons or [],
        "quality_metrics": s.quality_metrics or {},
        "id": s.id, "trap_id": s.trap_id, "timestamp": s.timestamp.isoformat(timespec="seconds"),
        "counts": s.counts, "pest_total": s.pest_total, "predator_total": s.predator_total,
        "image_url": media_url(s.image_path), "annotated_url": media_url(s.annotated_path),
        "detector_mode": s.detector_mode, "simulated": s.simulated, "source": s.source,
    }


def trap_summary(session: Session, trap: Trap) -> dict:
    latest = session.exec(select(TapeSection).where(TapeSection.trap_id == trap.id)
                          .order_by(TapeSection.timestamp.desc())).first()
    climate = session.exec(select(ClimateReading).where(ClimateReading.trap_id == trap.id)
                           .order_by(ClimateReading.timestamp.desc())).first()
    times = [t for t in (latest and latest.timestamp, climate and climate.timestamp) if t]
    last_seen = max(times) if times else None
    if last_seen is None:
        status = "no_data"
    elif datetime.now() - last_seen <= ONLINE_WITHIN:
        status = "online"
    else:
        status = "offline"
    return {
        "id": trap.id, "name": trap.name, "location": trap.location, "crop": trap.crop,
        "target_pest": trap.target_pest, "simulated": trap.simulated,
        "status": status, "last_seen": last_seen.isoformat(timespec="seconds") if last_seen else None,
        "latest_section": section_to_dict(latest) if latest else None,
        "latest_climate": {"timestamp": climate.timestamp.isoformat(timespec="seconds"),
                           "temperature_c": climate.temperature_c,
                           "humidity_pct": climate.humidity_pct} if climate else None,
        "decision": compute_decision(session, trap),
        "thresholds": asdict(thresholds_for(trap.target_pest)),
        "health": hygiene.health_status(session.get(TrapHealth, trap.id), datetime.now()),   # F6 heartbeat
    }

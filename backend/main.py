"""KeetaSense backend API (FastAPI).

Start it from the project root:
    python -m uvicorn backend.main:app --reload --port 8000
Interactive API docs: http://localhost:8000/docs

Endpoints
  POST /api/sections            tape image from a trap -> detect, store, decide
  POST /api/climate             temperature / humidity reading
  POST /api/phone-check         farmer's phone photo -> counts + recommendation
  GET  /api/traps               all traps with latest counts and decision
  GET  /api/traps/{id}/history  sections, daily climate and past decisions
  GET  /api/traps/{id}/decision current recommendation for one trap
  GET  /api/summary             numbers for the dashboard cards
  GET  /api/alerts              recent alerts (sent or logged)
  GET  /api/health              is everything OK? which detector is active?
  /media/...                    uploaded and annotated images
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select

from backend import advisory, alerts, impact, model_reports, services, settings, thresholds_editor, weather
from backend.db import get_engine, get_session, init_db
from backend.decision_engine import DailyCatch, decide
from backend.models import SECTION_SOURCES, AlertLog, ClimateReading, Decision, TapeSection, Trap
from ml import infer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("keetasense.api")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB is plenty for a phone photo
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup: create tables, load traps, warm up the detector."""
    settings.media_dir().mkdir(parents=True, exist_ok=True)
    init_db()
    with Session(get_engine()) as s:
        services.sync_traps(s)
    detector = infer.model_info()
    log.info("Detector: %s%s", detector["label"],
             f" ({detector['reason']})" if detector.get("reason") else "")
    log.info("Telegram alerts: %s", "configured" if alerts.telegram_configured() else "log only (no token)")
    yield


app = FastAPI(title="KeetaSense API", version=VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins(),
                   allow_methods=["*"], allow_headers=["*"])
settings.media_dir().mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(settings.media_dir())), name="media")


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    """Never crash the demo: log the error and return a friendly JSON message."""
    log.exception("Unexpected error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {exc.__class__.__name__}. "
                                                            "See the backend log."})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_trap_or_404(session: Session, trap_id: str) -> Trap:
    trap = session.get(Trap, trap_id)
    if trap is None:
        raise HTTPException(404, f"Unknown trap '{trap_id}'. Known traps are listed in config/traps.yaml.")
    return trap


def parse_timestamp(value: str | None) -> datetime:
    """ISO timestamp -> naive local datetime. Empty means 'now'."""
    if not value:
        return datetime.now()
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"Bad timestamp '{value}'. Use ISO format, e.g. 2026-10-25T08:00:00")
    if ts.tzinfo is not None:
        ts = ts.astimezone().replace(tzinfo=None)  # convert to local time
    return ts


async def read_upload(image: UploadFile) -> bytes:
    data = await image.read()
    if not data:
        raise HTTPException(400, "The uploaded image is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image too large (max 20 MB).")
    return data


def decode_or_400(data: bytes):
    try:
        return services.decode_image(data)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------
@app.post("/api/sections")
async def post_section(
    image: UploadFile = File(..., description="Photo of one tape section"),
    trap_id: str = Form(...),
    timestamp: str | None = Form(None, description="ISO time the photo was taken (default: now)"),
    simulated: bool = Form(False, description="True when sent by mock hardware"),
    detections_json: str | None = Form(None, description="Optional: detections already made on the edge device"),
    detector_mode: str | None = Form(None),
    source: str = Form("upload", description="live | mock | replay | seed | upload"),
    session: Session = Depends(get_session),
):
    trap = get_trap_or_404(session, trap_id)
    if source not in SECTION_SOURCES:
        raise HTTPException(422, f"source must be one of {sorted(SECTION_SOURCES)}")
    img = decode_or_400(await read_upload(image))
    detections = None
    if detections_json:
        try:
            detections = json.loads(detections_json)
            assert isinstance(detections, list)
        except (ValueError, AssertionError):
            raise HTTPException(422, "detections_json must be a JSON list of detections.")
    try:
        section, result, decision = services.process_section(
            session, trap, img, parse_timestamp(timestamp), simulated=simulated or trap.simulated,
            detections=detections, detector_mode=detector_mode, source=source)
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"Could not process detections: {e}")
    check_early_warnings(session)
    return {
        "section": services.section_to_dict(section),
        "counts": result.counts, "pest_total": result.pest_total, "predator_total": result.predator_total,
        "annotated_url": services.media_url(section.annotated_path),
        "detector_mode": result.mode, "warning": result.warning,
        "decision": decision,
    }


class ClimateIn(BaseModel):
    trap_id: str
    timestamp: str | None = None
    temperature_c: float = Field(ge=-20, le=60)
    humidity_pct: float = Field(ge=0, le=100)
    simulated: bool = False


@app.post("/api/climate")
def post_climate(body: ClimateIn, dry_run: bool = False, session: Session = Depends(get_session)):
    """Store a reading. dry_run=true only validates it (used by edge/tests_hw/test_backend_link.py)."""
    trap = get_trap_or_404(session, body.trap_id)
    if dry_run:
        return {"dry_run": True, "trap_id": trap.id, "temperature_c": body.temperature_c,
                "humidity_pct": body.humidity_pct, "stored": False}
    row = services.add_climate(session, trap, parse_timestamp(body.timestamp), body.temperature_c,
                               body.humidity_pct, simulated=body.simulated or trap.simulated)
    return {"id": row.id, "trap_id": row.trap_id, "timestamp": row.timestamp.isoformat(timespec="seconds"),
            "temperature_c": row.temperature_c, "humidity_pct": row.humidity_pct}


@app.post("/api/phone-check")
async def phone_check(
    image: UploadFile = File(..., description="Phone photo of a yellow sticky trap"),
    days_exposed: float = Form(1.0, gt=0, le=60, description="How many days the trap has been hanging"),
    target_pest: str = Form("whitefly"),
):
    """No hardware needed: count insects on a farmer's photo and give advice."""
    img = decode_or_400(await read_upload(image))
    try:
        th = services.thresholds_for(target_pest)
    except ValueError as e:
        raise HTTPException(422, str(e))
    result = infer.detect(img)
    stem = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    services.save_image(img, "phone", stem)
    annotated_rel = services.save_image(result.annotated_image, "phone", stem + "_annotated")
    # A trap hanging for several days collected several days of insects: convert to per-day
    catch = DailyCatch(round(result.pest_total / days_exposed), round(result.predator_total / days_exposed))
    th.rolling_window_days = 1
    decision = decide([catch], [], th, settings.pest_display_name(target_pest).lower()).to_dict()
    decision["reason"] = decision["reason"].replace(" No temperature data yet, so no generation forecast.", "")
    decision["reason"] += " (Based on a single photo, so there is no trend or temperature history.)"
    return {
        "counts": result.counts, "pest_total": result.pest_total, "predator_total": result.predator_total,
        "days_exposed": days_exposed, "detections": result.detections,
        "image_size": list(result.image_size),
        "annotated_url": services.media_url(annotated_rel),
        "detector_mode": result.mode, "detector": infer.model_info(),
        "warning": result.warning, "decision": decision,
    }


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------
@app.get("/api/traps")
def list_traps(session: Session = Depends(get_session)):
    traps = session.exec(select(Trap).order_by(Trap.id)).all()
    return [services.trap_summary(session, t) for t in traps]


@app.get("/api/traps/{trap_id}/history")
def trap_history(trap_id: str, days: int = 30, session: Session = Depends(get_session)):
    trap = get_trap_or_404(session, trap_id)
    since = datetime.now() - timedelta(days=max(1, min(days, 365)))
    sections = session.exec(select(TapeSection).where(TapeSection.trap_id == trap.id,
                                                      TapeSection.timestamp >= since)
                            .order_by(TapeSection.timestamp)).all()
    decisions = session.exec(select(Decision).where(Decision.trap_id == trap.id, Decision.timestamp >= since)
                             .order_by(Decision.timestamp.desc()).limit(50)).all()
    return {
        "trap": services.trap_summary(session, trap),
        "sections": [services.section_to_dict(s) for s in sections],
        "climate_daily": services.daily_climate(session, trap, since.date()),
        "decisions": [{"timestamp": d.timestamp.isoformat(timespec="seconds"), "action": d.action,
                       "reason": d.reason} for d in decisions],
    }


@app.get("/api/traps/{trap_id}/decision")
def trap_decision(trap_id: str, session: Session = Depends(get_session)):
    trap = get_trap_or_404(session, trap_id)
    return {"trap_id": trap.id, "trap_name": trap.name, **services.compute_decision(session, trap)}


@app.get("/api/summary")
def summary(session: Session = Depends(get_session)):
    traps = session.exec(select(Trap)).all()
    actions = {"SPRAY": 0, "RELEASE_BIOCONTROL": 0, "WAIT": 0}
    for t in traps:
        actions[services.compute_decision(session, t)["action"]] += 1
    today_start = datetime.combine(date.today(), datetime.min.time())
    today = session.exec(select(TapeSection).where(TapeSection.timestamp >= today_start)).all()
    latest = session.exec(select(TapeSection).order_by(TapeSection.timestamp.desc())).first()
    return {
        "traps_total": len(traps),
        "actions": actions,
        "pests_today": sum(s.pest_total for s in today),
        "predators_today": sum(s.predator_total for s in today),
        "sections_today": len(today),
        "sections_total": session.exec(select(func.count()).select_from(TapeSection)).one(),
        "last_update": latest.timestamp.isoformat(timespec="seconds") if latest else None,
        "simulated_data": any(t.simulated for t in traps)
                          or session.exec(select(TapeSection).where(TapeSection.simulated)).first() is not None,
        "detector_mode": infer.current_mode(),
        "detector": infer.model_info(),
        "telegram_configured": alerts.telegram_configured(),
        "alerts_total": session.exec(select(func.count()).select_from(AlertLog)).one(),
    }


@app.get("/api/alerts")
def recent_alerts(limit: int = 20, session: Session = Depends(get_session)):
    rows = session.exec(select(AlertLog).order_by(AlertLog.timestamp.desc()).limit(max(1, min(limit, 100)))).all()
    return [{"id": a.id, "trap_id": a.trap_id, "timestamp": a.timestamp.isoformat(timespec="seconds"),
             "action": a.action, "previous_action": a.previous_action, "language": a.language,
             "message": a.message, "status": a.status} for a in rows]


@app.get("/api/health")
def health(session: Session = Depends(get_session)):
    try:
        session.exec(select(func.count()).select_from(ClimateReading)).one()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": VERSION,
        "time": datetime.now().isoformat(timespec="seconds"),
        "database": db_status,
        "detector_mode": infer.current_mode(),
        "detector": infer.model_info(),
        "weights_path": str(infer.weights_path()),
        "telegram": "configured" if alerts.telegram_configured() else "log_only",
    }


# ---------------------------------------------------------------------------
# Advisory: forecast + weather + can-I-spray + early warnings, in en/kn/hi/ta
# ---------------------------------------------------------------------------
def check_early_warnings(session: Session) -> None:
    """After new data: alert farms near an outbreak (once per neighbouring outbreak). Never raises."""
    try:
        state = advisory.network_state(session)
        for s in state["stations"]:
            if not s["warnings"]:
                continue
            trap = session.get(Trap, s["id"])
            w = s["warnings"][0]
            texts = {}
            for lang in advisory.templates():
                t = advisory.templates()[lang]
                texts[lang] = ("⚠ " + t["title"].format(trap_name=trap.name) + "\n"
                               + t["warning"].format(neighbour=w["neighbour"], km=advisory._fmt(w["km"])))
            alerts.notify_early_warning(session, trap, w, texts)
    except Exception:
        log.exception("Early-warning check failed (the section itself was stored)")


def _lang(lang: str) -> str:
    if lang not in advisory.LANGUAGES:
        raise HTTPException(422, f"lang must be one of {list(advisory.LANGUAGES)}")
    return lang


@app.get("/api/advisory/{trap_id}")
def get_advisory(trap_id: str, lang: str = "en", session: Session = Depends(get_session)):
    """Everything for one farmer: decision, 3-7 day forecast, spray window, warnings, in a language."""
    trap = get_trap_or_404(session, trap_id)
    adv = advisory.build(session, trap)
    return {**adv, "rendered": advisory.render(adv, _lang(lang)),
            "spray_answer": advisory.answer_spray_question(adv, lang), "languages": advisory.LANGUAGES}


@app.get("/api/network")
def get_network(session: Session = Depends(get_session)):
    """All stations with pest pressure, early warnings and the interpolated heat map."""
    return advisory.network_state(session)


class ImpactIn(BaseModel):
    values: dict[str, float | int | str | None] = {}


@app.get("/api/impact")
def get_impact(session: Session = Depends(get_session)):
    """Impact estimate with the default (example) assumptions from config/impact.yaml."""
    return impact.compute(session)


@app.post("/api/impact")
def post_impact(body: ImpactIn, session: Session = Depends(get_session)):
    """Recalculate with the user's own numbers (nothing is saved)."""
    try:
        return impact.compute(session, body.values)
    except ValueError as e:
        raise HTTPException(422, e.args[0])


@app.get("/api/weather/{trap_id}")
def get_weather(trap_id: str, session: Session = Depends(get_session)):
    get_trap_or_404(session, trap_id)
    return {"mode": weather.mode(), "forecast": weather.get_forecast(trap_id)}


# ---------------------------------------------------------------------------
# Settings page: decision thresholds (config/pests.yaml)
# ---------------------------------------------------------------------------
class ThresholdsIn(BaseModel):
    values: dict[str, float | int | str | None]
    confirm_unchanged: bool = False   # also mark values that did not change as confirmed


@app.get("/api/settings/thresholds")
def get_thresholds():
    return {"pests": thresholds_editor.read_thresholds(), "backups": thresholds_editor.list_backups()[:10],
            "file": str(settings.pests_yaml_path())}


@app.put("/api/settings/thresholds/{pest}")
def put_thresholds(pest: str, body: ThresholdsIn, session: Session = Depends(get_session)):
    try:
        result = thresholds_editor.save(pest, body.values, body.confirm_unchanged)
    except ValueError as e:
        detail = e.args[0] if e.args and isinstance(e.args[0], dict) else {"errors": {"_": str(e)}}
        raise HTTPException(422, detail)
    settings.reload_config()                      # next reads see the new values
    decisions = {}
    for trap in session.exec(select(Trap).where(Trap.target_pest == pest)).all():
        decisions[trap.id] = services.update_decision(session, trap)["action"]   # recalculated now
    log.warning("THRESHOLDS for %s saved: changed %s, confirmed %s (backup %s)", pest, result["changed"],
                result["confirmed_unchanged"], result["backup"])
    return {**result, "decisions": decisions, "pests": thresholds_editor.read_thresholds()}


_reset_lock = threading.Lock()


@app.post("/api/reset-demo")
def reset_demo(session: Session = Depends(get_session)):
    """Wipe all data and restore the seeded demo state (hidden button in the dashboard footer).

    Disable on a real deployment with KEETA_ALLOW_RESET=0."""
    if not settings.allow_demo_reset():
        raise HTTPException(403, "Demo reset is disabled (KEETA_ALLOW_RESET=0).")
    if not _reset_lock.acquire(blocking=False):
        raise HTTPException(409, "A reset is already running.")
    try:
        from demo import seed  # demo package: only needed for this endpoint
        t0 = time.time()
        removed = seed.clear_all(session)
        created = seed.seed_history(session, log=log.info)
        log.warning("DEMO RESET: removed %s, created %d simulated sections", removed, created)
        return {"removed": removed, "sections_created": created, "seconds": round(time.time() - t0, 1)}
    finally:
        _reset_lock.release()


@app.get("/api/model")
def model_page():
    """Active detector + every evaluation report in ml/reports (newest first)."""
    reports = model_reports.list_reports()
    real = [r for r in reports if not r["synthetic_data"]]
    featured = real[0] if real else (reports[0] if reports else None)
    if not reports:
        warning = "No evaluation report yet. Run ml/evaluate.py on the real test split (Colab notebook step 5)."
    elif not real:
        warning = ("Only SYNTHETIC evaluation reports exist. They prove the pipeline runs but say nothing "
                   "about accuracy on real insects.")
    else:
        warning = None
    return {"detector": infer.model_info(), "featured": featured, "reports": reports, "warning": warning}


# ---------------------------------------------------------------------------
# The dashboard itself (built with `npm run build`), served from the same port so
# the demo needs only this one process and works with Wi-Fi off.
# Registered LAST so /api/... and /media/... always win.
# ---------------------------------------------------------------------------
@app.get("/{path:path}", include_in_schema=False)
def dashboard(path: str):
    root = settings.dashboard_dir()
    index = root / "index.html"
    if path.startswith(("api/", "media/")) or not index.exists():
        raise HTTPException(404, "Not found. (Dashboard not built? Run: npm --prefix frontend run build)")
    target = (root / path).resolve()
    if path and target.is_file() and root.resolve() in target.parents:
        return FileResponse(target)
    return FileResponse(index)  # client-side routes like /traps/T1-polyhouse

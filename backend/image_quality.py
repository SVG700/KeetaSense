"""Image quality gate: is this tape photo good enough to count insects on?

Run on every new capture (backend/services.py, process_section). Four checks:
  blur         variance of the Laplacian (edge strength) - low = blurred / out of focus
  brightness   mean grey level 0-255 - too dark (LEDs off) or too bright (washed out)
  glare        % of pixels that are saturated (>= 250) - reflections on the tape
  tape advance similarity to the PREVIOUS capture of the same trap - nearly identical
               means the motor did not move the tape (same section photographed again)

Result: quality_status OK / WARN / BAD + reasons. A BAD image is not used for the
decision; the trap shows CHECK TRAP until a good image arrives.
All limits are in config/pests.yaml -> image_quality (PLACEHOLDER values).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import yaml

from backend import settings

OK, WARN, BAD = "OK", "WARN", "BAD"
_SIZE = 320          # images are compared at this width (fast, and ignores JPEG noise)
TEMPLATES_FILE = Path(__file__).resolve().parent / "advisory_templates.yaml"


def config() -> dict:
    return settings.pests_config()["image_quality"]


def _small_gray(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape[:2]
    return cv2.resize(gray, (_SIZE, max(1, int(h * _SIZE / w))), interpolation=cv2.INTER_AREA)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """How alike two photos are, from -1 to 1 (normalised cross-correlation of their edge images).

    Edges (insects, tape texture) move when the tape advances; a plain-background
    comparison would call every yellow tape "the same"."""
    ga, gb = _small_gray(a), _small_gray(b)
    if ga.shape != gb.shape:
        gb = cv2.resize(gb, (ga.shape[1], ga.shape[0]), interpolation=cv2.INTER_AREA)
    ea = cv2.Laplacian(cv2.GaussianBlur(ga, (3, 3), 0).astype(np.float32), cv2.CV_32F)
    eb = cv2.Laplacian(cv2.GaussianBlur(gb, (3, 3), 0).astype(np.float32), cv2.CV_32F)
    ea, eb = ea - ea.mean(), eb - eb.mean()
    denom = float(np.sqrt((ea ** 2).sum() * (eb ** 2).sum()))
    return float((ea * eb).sum() / denom) if denom > 0 else 1.0


def measure(img: np.ndarray, previous: np.ndarray | None = None) -> dict:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return {
        "width": int(img.shape[1]), "height": int(img.shape[0]),
        "blur": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
        "brightness": round(float(gray.mean()), 1),
        "glare_pct": round(float((gray >= 250).mean() * 100), 2),
        "similarity_to_previous": None if previous is None else round(similarity(img, previous), 4),
    }


def assess(m: dict, cfg: dict | None = None) -> tuple[str, list[dict]]:
    """(status, reasons). Each reason: {code, level, value, limit}."""
    c = cfg or config()
    reasons = []

    def add(code, level, value, limit):
        reasons.append({"code": code, "level": level, "value": value, "limit": limit})

    if m["blur"] < c["blur_bad"]:
        add("blurred", BAD, m["blur"], c["blur_bad"])
    elif m["blur"] < c["blur_warn"]:
        add("blurred", WARN, m["blur"], c["blur_warn"])
    if m["brightness"] < c["dark_bad"]:
        add("too_dark", BAD, m["brightness"], c["dark_bad"])
    elif m["brightness"] < c["dark_warn"]:
        add("too_dark", WARN, m["brightness"], c["dark_warn"])
    if m["brightness"] > c["bright_bad"]:
        add("too_bright", BAD, m["brightness"], c["bright_bad"])
    if m["glare_pct"] > c["glare_bad_pct"]:
        add("glare", BAD, m["glare_pct"], c["glare_bad_pct"])
    elif m["glare_pct"] > c["glare_warn_pct"]:
        add("glare", WARN, m["glare_pct"], c["glare_warn_pct"])
    sim = m.get("similarity_to_previous")
    if sim is not None:
        if sim >= c["duplicate_bad"]:
            add("tape_not_advanced", BAD, sim, c["duplicate_bad"])
        elif sim >= c["duplicate_warn"]:
            add("tape_not_advanced", WARN, sim, c["duplicate_warn"])
    status = BAD if any(r["level"] == BAD for r in reasons) else WARN if reasons else OK
    return status, reasons


def check(img: np.ndarray, previous: np.ndarray | None = None) -> tuple[str, list[dict], dict]:
    metrics = measure(img, previous)
    status, reasons = assess(metrics)
    return status, reasons, metrics


@lru_cache(maxsize=1)
def _texts() -> dict:
    with open(TEMPLATES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_trap_reason(reasons: list[dict], lang: str = "en") -> str:
    t = _texts().get(lang) or _texts()["en"]
    return t["check_trap_reason"].format(reasons=reasons_text(reasons, lang, only_bad=True))


def reasons_text(reasons: list[dict], lang: str = "en", only_bad: bool = False) -> str:
    """'image blurred, tape did not advance' in the chosen language."""
    t = _texts().get(lang) or _texts()["en"]
    picked = [r for r in reasons if r["level"] == BAD] if only_bad else reasons
    return ", ".join(t.get(f"quality_{r['code']}", r["code"]) for r in picked)

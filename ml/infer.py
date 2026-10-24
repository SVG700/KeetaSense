"""KeetaSense insect detector - the ONE function everything else calls.

    from ml.infer import detect
    result = detect("tape.jpg")          # or a BGR numpy array (OpenCV image)
    result.counts          -> {"whitefly": 23, "macrolophus": 2, "nesidiocoris": 1}
    result.pest_total      -> 23
    result.predator_total  -> 3
    result.annotated_image -> BGR numpy image with boxes drawn
    result.mode            -> "yolo_sahi" or "demo_detector"

Two modes:
  1. "yolo_sahi" (the real AI): our fine-tuned YOLOv8n run with SAHI sliced
     inference. Sticky-trap photos are large and insects are tiny (a
     whitefly may be ~15 pixels), so SAHI cuts the photo into overlapping
     tiles, detects on each tile at full resolution, and merges the boxes.
  2. "demo_detector" (NOT AI): used only when no trained weights exist yet.
     It finds dark blobs on the yellow tape with classic image processing
     and guesses the class from blob shape. It is tuned for our SYNTHETIC
     demo images only. Everything it produces is labelled "DEMO DETECTOR".

Settings (from .env): KEETA_WEIGHTS, KEETA_SLICE_SIZE, KEETA_SLICE_OVERLAP,
KEETA_CONF_THRESHOLD, KEETA_DEVICE.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ml.common import ROOT, category_of, get_classes

log = logging.getLogger("keetasense.detector")

MODE_YOLO = "yolo_sahi"
MODE_DEMO = "demo_detector"

# Box colours (BGR) by category
COLORS = {"pest": (40, 40, 230), "predator": (40, 170, 40), "unknown": (200, 120, 0)}


@dataclass
class DetectionResult:
    detections: list[dict]            # [{class_name, category, confidence, bbox:[x1,y1,x2,y2]}]
    counts: dict[str, int]            # per class name
    pest_total: int
    predator_total: int
    annotated_image: np.ndarray       # BGR image with boxes
    mode: str                         # MODE_YOLO or MODE_DEMO
    warning: str | None = None
    image_size: tuple[int, int] = field(default=(0, 0))  # (width, height)

    def to_dict(self) -> dict:
        """JSON-friendly summary (without the image itself)."""
        return {
            "detections": self.detections,
            "counts": self.counts,
            "pest_total": self.pest_total,
            "predator_total": self.predator_total,
            "mode": self.mode,
            "warning": self.warning,
            "image_size": list(self.image_size),
        }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def weights_path() -> Path:
    p = Path(os.environ.get("KEETA_WEIGHTS", "ml/weights/best.pt"))
    return p if p.is_absolute() else ROOT / p


def _settings() -> dict:
    return {
        "slice_size": int(os.environ.get("KEETA_SLICE_SIZE", 640)),
        "overlap": float(os.environ.get("KEETA_SLICE_OVERLAP", 0.2)),
        "conf": float(os.environ.get("KEETA_CONF_THRESHOLD", 0.25)),
    }


def _device() -> str:
    if os.environ.get("KEETA_DEVICE"):
        return os.environ["KEETA_DEVICE"]
    try:
        import torch
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


# ---------------------------------------------------------------------------
# Model loading (once, then cached)
# ---------------------------------------------------------------------------
_model = None            # SAHI detection model, or None in demo mode
_model_loaded = False
_model_info: dict = {}   # what is loaded, for the startup log, API and dashboard
_lock = threading.Lock()  # the backend may call detect() from several threads

DEMO_WARNING = ("DEMO DETECTOR: no trained weights found, using simple blob counting "
                "tuned for synthetic images. Counts are NOT from the AI model.")


def _read_model_card(wp: Path) -> dict:
    """Training facts saved by ml/train.py next to the weights (best.pt -> best.json)."""
    card = wp.with_suffix(".json")
    try:
        return json.loads(card.read_text(encoding="utf-8")) if card.exists() else {}
    except (OSError, ValueError):
        log.warning("Could not read model card %s", card)
        return {}


def _demo_info(reason: str, error: str | None = None) -> dict:
    return {"mode": MODE_DEMO, "label": "Demo detector (synthetic only)", "reason": reason,
            "weights_name": None, "weights_path": str(weights_path()), "trained_at": None,
            "trained_at_source": None, "synthetic_data": None, "classes": None, "load_error": error}


def _load_model():
    """Load YOLO weights through SAHI, or return None to use the demo detector.

    Never raises: any problem with the weights falls back to the demo detector
    with a loud warning, so the demo keeps running.
    """
    global _model, _model_loaded, _model_info
    if _model_loaded:
        return _model
    _model_loaded = True
    wp = weights_path()
    if not wp.exists():
        log.warning("=" * 70)
        log.warning("NO TRAINED WEIGHTS at %s", wp)
        log.warning("Running in DEMO DETECTOR mode - counts are NOT from the AI model.")
        log.warning("Train on Colab (ml/train_colab.ipynb), then: python -m ml.install_model <zip>")
        log.warning("=" * 70)
        _model, _model_info = None, _demo_info("no weights file")
        return None
    try:
        from sahi import AutoDetectionModel  # lazy import: heavy library
        _model = AutoDetectionModel.from_pretrained(
            model_type="ultralytics", model_path=str(wp),
            confidence_threshold=_settings()["conf"], device=_device())
    except Exception as e:
        log.error("=" * 70)
        log.exception("COULD NOT LOAD WEIGHTS %s", wp)
        log.error("FALLING BACK TO DEMO DETECTOR - counts are NOT from the AI model.")
        log.error("=" * 70)
        _model, _model_info = None, _demo_info("weights failed to load", f"{e.__class__.__name__}: {e}")
        return None

    card = _read_model_card(wp)
    if card.get("trained_at"):
        trained_at, source = card["trained_at"], "model card"
    else:  # no card: the file date is the best we know
        trained_at, source = datetime.fromtimestamp(wp.stat().st_mtime).isoformat(timespec="seconds"), "file date"
    mapping = getattr(_model, "category_mapping", None) or {}  # SAHI: {"0": "whitefly", ...}
    model_classes = [str(v) for _, v in sorted(mapping.items(), key=lambda kv: int(kv[0]))] or card.get("classes") or []
    label = f"AI model: {wp.name}, trained {trained_at[:10]}"
    _model_info = {"mode": MODE_YOLO, "label": label, "reason": None, "weights_name": wp.name,
                   "weights_path": str(wp), "trained_at": trained_at, "trained_at_source": source,
                   "synthetic_data": card.get("synthetic_data"), "classes": model_classes, "load_error": None}
    log.info("=" * 70)
    log.info("DETECTOR: %s (SAHI sliced inference on %s)", label, _device())
    if card.get("synthetic_data"):
        log.warning("This model was trained on SYNTHETIC data - it will not work on real insects!")
    unknown = [n for n in model_classes if category_of(n) == "unknown"]
    if unknown:
        log.warning("Model classes not in config/pests.yaml (counted as neither pest nor predator): %s", unknown)
    log.info("=" * 70)
    return _model


def reset_detector() -> None:
    """Forget the cached model (used by tests or after copying new weights)."""
    global _model, _model_loaded, _model_info
    with _lock:
        _model, _model_loaded, _model_info = None, False, {}


def current_mode() -> str:
    with _lock:
        return MODE_YOLO if _load_model() is not None else MODE_DEMO


def model_info() -> dict:
    """What detector is active: mode, label for the UI, weights file, training date."""
    with _lock:
        _load_model()
        return dict(_model_info)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load_image(image) -> np.ndarray:
    """Accept a file path or a BGR numpy array; return a BGR numpy array."""
    if isinstance(image, np.ndarray):
        return image
    img = cv2.imread(str(image))
    if img is None:
        raise ValueError(f"Could not read image: {image}")
    return img


def detect(image, slice_size: int | None = None, overlap: float | None = None,
           conf: float | None = None) -> DetectionResult:
    """Detect and count insects in one tape image (path or BGR array)."""
    img = load_image(image)
    s = _settings()
    slice_size = slice_size or s["slice_size"]
    overlap = s["overlap"] if overlap is None else overlap
    conf = s["conf"] if conf is None else conf

    with _lock:
        model = _load_model()
        if model is not None:
            thresholds = class_conf_thresholds(conf)
            # ask SAHI for everything above the LOWEST class threshold, then filter per class
            raw = _detect_yolo_sahi(model, img, slice_size, overlap, min([conf, *thresholds.values()]))
            detections = apply_class_thresholds(raw, thresholds, conf)
            mode, warning = MODE_YOLO, None
        else:
            detections = demo_detect(img)
            mode, warning = MODE_DEMO, DEMO_WARNING

    return build_result(img, detections, mode, warning)


def class_conf_thresholds(default: float) -> dict[str, float]:
    """Per-class confidence thresholds from pests.yaml (falls back to the global default)."""
    return {c.name: (c.confidence_threshold if c.confidence_threshold is not None else default)
            for c in get_classes()}


def apply_class_thresholds(detections: list[dict], thresholds: dict[str, float],
                           default: float) -> list[dict]:
    """Keep a detection only if its confidence reaches its own class's threshold."""
    return [d for d in detections if d["confidence"] >= thresholds.get(d["class_name"], default)]


def build_result(img: np.ndarray, detections: list[dict], mode: str,
                 warning: str | None = None) -> DetectionResult:
    """Count detections per class/category and draw the annotated image."""
    counts = {c.name: 0 for c in get_classes()}
    for d in detections:
        counts[d["class_name"]] = counts.get(d["class_name"], 0) + 1
    pest_total = sum(1 for d in detections if d["category"] == "pest")
    predator_total = sum(1 for d in detections if d["category"] == "predator")
    annotated = draw_detections(img, detections, mode, pest_total, predator_total)
    return DetectionResult(detections, counts, pest_total, predator_total, annotated,
                           mode, warning, (img.shape[1], img.shape[0]))


def _detect_yolo_sahi(model, img_bgr, slice_size, overlap, conf) -> list[dict]:
    from sahi.predict import get_sliced_prediction
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)  # SAHI expects RGB arrays
    result = get_sliced_prediction(
        rgb, model,
        slice_height=slice_size, slice_width=slice_size,
        overlap_height_ratio=overlap, overlap_width_ratio=overlap,
        confidence_threshold=conf, verbose=0)
    detections = []
    for p in result.object_prediction_list:
        name = p.category.name
        x1, y1, x2, y2 = p.bbox.to_xyxy()
        detections.append({
            "class_name": name,
            "category": category_of(name),
            "confidence": round(float(p.score.value), 3),
            "bbox": [round(float(v), 1) for v in (x1, y1, x2, y2)],
        })
    return detections


# ---------------------------------------------------------------------------
# DEMO DETECTOR (classical image processing, NOT AI)
# ---------------------------------------------------------------------------
# Pixel sizes below match the synthetic images from ml/synthetic.py.
DEMO_MIN_AREA = 25          # smaller blobs are dust
DEMO_MAX_AREA = 6000        # bigger blobs are shadows / tape edges
DEMO_ROUND_MAX_LENGTH = 19  # blobs shorter than this are "round"
DEMO_SLIM_MIN_ASPECT = 3.8  # length/width above this is "slim", else "stout"
DEMO_DARKNESS = 60          # how much darker than the local background a pixel must be


def demo_detect(img_bgr: np.ndarray) -> list[dict]:
    """Find dark blobs on the yellow tape and label them by shape."""
    shape_to_class = {c.synthetic_shape: c.name for c in get_classes()}
    v = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)[:, :, 2]
    # Estimate the background brightness around each pixel (removes LED lighting gradient)
    background = cv2.medianBlur(v, 31)
    darker = cv2.subtract(background, v)
    mask = (darker > DEMO_DARKNESS).astype(np.uint8) * 255
    # Opening removes thin lines (grid, insect legs) and single-pixel noise
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    detections = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not DEMO_MIN_AREA <= area <= DEMO_MAX_AREA:
            continue
        (_, _), (w, h), _ = cv2.minAreaRect(cnt)
        length, width = max(w, h), max(1.0, min(w, h))
        if length < DEMO_ROUND_MAX_LENGTH:
            shape = "round"
        elif length / width >= DEMO_SLIM_MIN_ASPECT:
            shape = "slim"
        else:
            shape = "stout"
        name = shape_to_class.get(shape)
        if name is None:
            continue
        x, y, bw, bh = cv2.boundingRect(cnt)
        detections.append({
            "class_name": name,
            "category": category_of(name),
            "confidence": 0.5,  # fixed: the demo detector has no real confidence
            "bbox": [float(x - 2), float(y - 2), float(x + bw + 2), float(y + bh + 2)],
        })
    return detections


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def draw_detections(img_bgr: np.ndarray, detections: list[dict], mode: str,
                    pest_total: int, predator_total: int) -> np.ndarray:
    """Return a copy of the image with coloured boxes and a summary banner."""
    out = img_bgr.copy()
    scale = max(1.0, out.shape[1] / 1000)  # thicker lines on big photos
    thick = max(1, int(round(2 * scale)))
    for d in detections:
        x1, y1, x2, y2 = (int(round(v)) for v in d["bbox"])
        color = COLORS.get(d["category"], COLORS["unknown"])
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thick)
        if d["category"] == "predator":  # label only predators to keep it readable
            cv2.putText(out, d["class_name"][:5], (x1, max(10, y1 - 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4 * scale, color, thick)

    banner_h = int(34 * scale)
    cv2.rectangle(out, (0, 0), (out.shape[1], banner_h), (30, 30, 30), -1)
    text = f"Pests: {pest_total}   Predators: {predator_total}"
    cv2.putText(out, text, (int(8 * scale), int(24 * scale)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7 * scale, (255, 255, 255), thick)
    if mode == MODE_DEMO:
        label = "DEMO DETECTOR (not AI)"
        (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, thick)
        cv2.putText(out, label, (out.shape[1] - tw - int(8 * scale), int(24 * scale)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, (0, 165, 255), thick)
    return out


# ---------------------------------------------------------------------------
# Command line: python -m ml.infer path/to/image.jpg
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Detect and count insects in a tape image.")
    ap.add_argument("image")
    ap.add_argument("--out", help="where to save the annotated image")
    ap.add_argument("--weights", help="override KEETA_WEIGHTS")
    args = ap.parse_args()
    if args.weights:
        os.environ["KEETA_WEIGHTS"] = args.weights
    r = detect(args.image)
    summary = r.to_dict()
    summary.pop("detections")
    print(json.dumps(summary, indent=2))
    out = args.out or str(Path(args.image).with_name(Path(args.image).stem + "_annotated.jpg"))
    cv2.imwrite(out, r.annotated_image)
    print(f"annotated image -> {out}")


if __name__ == "__main__":
    main()

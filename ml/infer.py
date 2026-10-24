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

import logging
import os
import threading
from dataclasses import dataclass, field
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
_lock = threading.Lock()  # the backend may call detect() from several threads

DEMO_WARNING = ("DEMO DETECTOR: no trained weights found, using simple blob counting "
                "tuned for synthetic images. Counts are NOT from the AI model.")


def _load_model():
    """Load YOLO weights through SAHI, or return None to use the demo detector."""
    global _model, _model_loaded
    if _model_loaded:
        return _model
    _model_loaded = True
    wp = weights_path()
    if not wp.exists():
        log.warning("=" * 70)
        log.warning("NO TRAINED WEIGHTS at %s", wp)
        log.warning("Running in DEMO DETECTOR mode - counts are NOT from the AI model.")
        log.warning("Train on Colab (ml/train_colab.ipynb) and copy best.pt there.")
        log.warning("=" * 70)
        _model = None
        return None
    try:
        from sahi import AutoDetectionModel  # lazy import: heavy library
        _model = AutoDetectionModel.from_pretrained(
            model_type="ultralytics", model_path=str(wp),
            confidence_threshold=_settings()["conf"], device=_device())
        log.info("Loaded YOLO weights %s on %s (SAHI sliced inference)", wp, _device())
    except Exception:
        log.exception("Could not load weights %s - falling back to DEMO DETECTOR", wp)
        _model = None
    return _model


def reset_detector() -> None:
    """Forget the cached model (used by tests or after copying new weights)."""
    global _model, _model_loaded
    with _lock:
        _model, _model_loaded = None, False


def current_mode() -> str:
    with _lock:
        return MODE_YOLO if _load_model() is not None else MODE_DEMO


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
            detections = _detect_yolo_sahi(model, img, slice_size, overlap, conf)
            mode, warning = MODE_YOLO, None
        else:
            detections = demo_detect(img)
            mode, warning = MODE_DEMO, DEMO_WARNING

    return build_result(img, detections, mode, warning)


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

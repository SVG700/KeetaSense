"""Fine-tune YOLOv8n to detect insects on sticky traps.

Recommended: run on Google Colab with a free GPU (see ml/train_colab.ipynb).
A laptop CPU works for the tiny synthetic smoke test only.

Typical real run (Colab, GPU):
    python -m ml.convert_dataset
    python -m ml.tile_dataset                     # 640 px tiles for tiny insects
    python -m ml.train --data ml/data/yolo_tiles/data.yaml --epochs 100 --imgsz 640 --device 0

Synthetic smoke test (laptop CPU, ~1-2 minutes, proves the pipeline runs):
    python -m ml.train --data ml/data/synthetic_yolo/data.yaml --epochs 2 --imgsz 320 \
        --weights-out ml/weights/synthetic_smoke_test.pt

The best weights are copied to --weights-out (default ml/weights/best.pt),
which is where ml/infer.py looks for them.

Augmentations chosen for small insects on yellow traps:
  - brightness / saturation jitter (hsv_v, hsv_s): LED and sunlight vary
  - rotation (degrees) and up-down + left-right flips: insects land in any direction
  - blur and motion blur (albumentations): camera focus and tape movement
  - mild scale jitter only (scale=0.3): shrinking tiny insects more would erase them
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ml.common import ROOT

DEFAULT_PRETRAINED = ROOT / "ml/weights/yolov8n.pt"


def build_albumentations():
    """Blur-type augmentations; returns None if albumentations is not installed."""
    try:
        import albumentations as A
    except ImportError:
        print("[train] albumentations not installed - training without blur augmentation")
        return None
    return [
        A.Blur(blur_limit=(3, 5), p=0.10),
        A.MotionBlur(blur_limit=(3, 7), p=0.10),
        A.RandomBrightnessContrast(brightness_limit=0.15, contrast_limit=0.15, p=0.2),
        A.ImageCompression(quality_range=(60, 95), p=0.1),  # phone-photo JPEG artefacts
    ]


def load_base_model(model_arg: str):
    """Load pretrained YOLOv8n (downloads once into ml/weights/); fall back to scratch."""
    from ultralytics import YOLO
    path = Path(model_arg)
    if path.name == "yolov8n.pt" and not path.exists():
        path = DEFAULT_PRETRAINED
        path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return YOLO(str(path))
    except Exception as e:  # e.g. no internet to download pretrained weights
        print(f"[train] WARNING: could not load {path} ({e}). Training from scratch (yolov8n.yaml) "
              "- results will be much worse than fine-tuning.")
        return YOLO("yolov8n.yaml")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fine-tune YOLOv8n on sticky-trap insects.")
    ap.add_argument("--data", default=str(ROOT / "ml/data/yolo_tiles/data.yaml"))
    ap.add_argument("--model", default=str(DEFAULT_PRETRAINED), help="starting weights")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default=None, help="'cpu', '0' for first GPU, or leave empty for auto")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--patience", type=int, default=30, help="early stop after N epochs without improvement")
    ap.add_argument("--name", default="keetasense")
    ap.add_argument("--weights-out", default=str(ROOT / "ml/weights/best.pt"))
    args = ap.parse_args()

    if not Path(args.data).exists():
        print(f"[train] dataset config not found: {args.data}\n"
              "        Run python -m ml.convert_dataset (and python -m ml.tile_dataset) first.")
        sys.exit(1)

    model = load_base_model(args.model)
    train_args = dict(
        data=args.data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        workers=args.workers, patience=args.patience,
        project=str(ROOT / "ml/runs"), name=args.name, exist_ok=True,
        # --- augmentations suited to small insects ---
        hsv_h=0.01, hsv_s=0.5, hsv_v=0.4,      # colour / brightness jitter
        degrees=15.0, flipud=0.5, fliplr=0.5,  # rotation and flips
        scale=0.3, translate=0.1, mosaic=1.0,
        seed=42, deterministic=True, plots=True,
    )
    if args.device is not None:
        train_args["device"] = args.device
    augs = build_albumentations()
    if augs:
        train_args["augmentations"] = augs

    print(f"[train] training with {train_args}")
    results = model.train(**train_args)

    best = Path(results.save_dir) / "weights" / "best.pt"
    if not best.exists():
        print(f"[train] ERROR: {best} not found - training did not produce weights.")
        sys.exit(1)
    out = Path(args.weights_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, out)
    print(f"[train] best weights copied to {out}")
    print(f"[train] training curves and metrics are in {results.save_dir}")


if __name__ == "__main__":
    main()

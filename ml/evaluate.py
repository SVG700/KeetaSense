"""Evaluate the detector on the TEST split and write a JSON + Markdown report.

It runs the exact pipeline the app uses (ml.infer.detect, i.e. YOLO + SAHI,
or the demo detector) on every full-size test image and measures:

  - mAP@0.5            : mean over classes of Average Precision at IoU 0.5
  - precision / recall : per class, at the configured confidence threshold
  - counting error     : per image, |predicted count - true count|
                         MAE  = mean absolute error (insects per image)
                         MAPE = mean absolute percentage error, over images
                                whose true count is > 0

Every number in the report is MEASURED here - nothing is estimated.

Usage:
    python -m ml.evaluate --data ml/data/yolo/data.yaml --weights ml/weights/best.pt
    python -m ml.evaluate --data ml/data/synthetic_yolo/data.yaml --weights demo   # demo detector
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

from ml.common import ROOT, category_of, class_names

IOU_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def iou(a, b) -> float:
    """Intersection over union of two [x1, y1, x2, y2] boxes."""
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def average_precision(recall: np.ndarray, precision: np.ndarray) -> float:
    """Area under the precision-recall curve (all-point interpolation, as in VOC/COCO)."""
    r = np.concatenate(([0.0], recall, [1.0]))
    p = np.concatenate(([0.0], precision, [0.0]))
    for i in range(len(p) - 2, -1, -1):   # make precision monotonically decreasing
        p[i] = max(p[i], p[i + 1])
    idx = np.where(r[1:] != r[:-1])[0]
    return float(np.sum((r[idx + 1] - r[idx]) * p[idx + 1]))


def read_ground_truth(label_file: Path, width: int, height: int, names: list[str]) -> list[dict]:
    gts = []
    if label_file.exists():
        for line in label_file.read_text().splitlines():
            c, xc, yc, w, h = line.split()
            xc, yc, w, h = float(xc) * width, float(yc) * height, float(w) * width, float(h) * height
            gts.append({"class_name": names[int(c)], "bbox": [xc - w / 2, yc - h / 2, xc + w / 2, yc + h / 2]})
    return gts


def test_images_dir(data_yaml: Path) -> Path:
    data = yaml.safe_load(data_yaml.read_text())
    test = Path(data.get("test", "images/test"))
    if not test.is_absolute():
        test = Path(data.get("path", data_yaml.parent)) / test
    return test


def labels_dir_for(images_dir: Path) -> Path:
    parts = list(images_dir.parts)
    idx = len(parts) - 1 - parts[::-1].index("images")
    parts[idx] = "labels"
    return Path(*parts)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate(data_yaml: Path) -> dict:
    from ml import infer  # imported here so --weights can be set first

    names = class_names()
    img_dir = test_images_dir(data_yaml)
    lbl_dir = labels_dir_for(img_dir)
    images = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"})
    if not images:
        raise SystemExit(f"[evaluate] no test images in {img_dir}")

    preds_by_class = {n: [] for n in names}   # (image_idx, confidence, bbox)
    gts_by_class = {n: {} for n in names}     # image_idx -> list of bboxes
    count_rows = []
    mode = None

    for i, img_path in enumerate(images):
        r = infer.detect(img_path)
        mode = r.mode
        w, h = r.image_size
        gts = read_ground_truth(lbl_dir / (img_path.stem + ".txt"), w, h, names)
        for g in gts:
            gts_by_class[g["class_name"]].setdefault(i, []).append(g["bbox"])
        for d in r.detections:
            if d["class_name"] in preds_by_class:
                preds_by_class[d["class_name"]].append((i, d["confidence"], d["bbox"]))

        true_counts = {n: sum(1 for g in gts if g["class_name"] == n) for n in names}
        row = {"image": img_path.name}
        for n in names:
            row[f"true_{n}"], row[f"pred_{n}"] = true_counts[n], r.counts.get(n, 0)
        row["true_pest"] = sum(v for n, v in true_counts.items() if category_of(n) == "pest")
        row["true_predator"] = sum(v for n, v in true_counts.items() if category_of(n) == "predator")
        row["pred_pest"], row["pred_predator"] = r.pest_total, r.predator_total
        count_rows.append(row)

    # --- detection metrics per class ---
    per_class = {}
    for n in names:
        n_gt = sum(len(v) for v in gts_by_class[n].values())
        preds = sorted(preds_by_class[n], key=lambda p: -p[1])
        matched = {k: [False] * len(v) for k, v in gts_by_class[n].items()}
        tp = np.zeros(len(preds))
        for j, (img_idx, _, box) in enumerate(preds):
            best_iou, best_k = 0.0, -1
            for k, g in enumerate(gts_by_class[n].get(img_idx, [])):
                o = iou(box, g)
                if o > best_iou and not matched[img_idx][k]:
                    best_iou, best_k = o, k
            if best_iou >= IOU_THRESHOLD:
                tp[j] = 1
                matched[img_idx][best_k] = True
        cum_tp, cum_fp = np.cumsum(tp), np.cumsum(1 - tp)
        recall_curve = cum_tp / max(n_gt, 1)
        precision_curve = cum_tp / np.maximum(cum_tp + cum_fp, 1e-9)
        per_class[n] = {
            "category": category_of(n),
            "ground_truth": n_gt,
            "predictions": len(preds),
            "true_positives": int(tp.sum()),
            "precision": round(float(tp.sum() / len(preds)), 4) if preds else None,
            "recall": round(float(tp.sum() / n_gt), 4) if n_gt else None,
            "ap50": round(average_precision(recall_curve, precision_curve), 4) if n_gt else None,
        }
    aps = [v["ap50"] for v in per_class.values() if v["ap50"] is not None]

    # --- counting error ---
    def mae_mape(key: str) -> dict:
        t = np.array([r[f"true_{key}"] for r in count_rows], dtype=float)
        p = np.array([r[f"pred_{key}"] for r in count_rows], dtype=float)
        nz = t > 0
        return {
            "mae": round(float(np.mean(np.abs(p - t))), 3),
            "mape_percent": round(float(np.mean(np.abs(p[nz] - t[nz]) / t[nz]) * 100), 2) if nz.any() else None,
            "images_used_for_mape": int(nz.sum()),
            "mean_true_count": round(float(t.mean()), 2),
        }

    counting = {n: mae_mape(n) for n in names}
    counting["all_pests"] = mae_mape("pest")
    counting["all_predators"] = mae_mape("predator")

    return {
        "created": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(data_yaml),
        "synthetic_data": "synthetic" in str(data_yaml).lower(),
        "detector_mode": mode,
        "weights": str(infer.weights_path()) if mode == infer.MODE_YOLO else None,
        "iou_threshold": IOU_THRESHOLD,
        "confidence_threshold": float(os.environ.get("KEETA_CONF_THRESHOLD", 0.25)),
        "test_images": len(images),
        "map50": round(float(np.mean(aps)), 4) if aps else None,
        "per_class": per_class,
        "counting_error": counting,
        "per_image": count_rows,
    }


def to_markdown(rep: dict) -> str:
    lines = [f"# KeetaSense evaluation report", ""]
    if rep["synthetic_data"]:
        lines += ["> **SYNTHETIC DATA** - these numbers only show the pipeline runs. "
                  "They say nothing about accuracy on real insects.", ""]
    if rep["detector_mode"] == "demo_detector":
        lines += ["> **DEMO DETECTOR** - classical blob counting, not the trained AI model. "
                  "It has no real confidence score, so AP equals precision x recall at one point.", ""]
    lines += [
        f"- Created: {rep['created']}",
        f"- Dataset: `{rep['dataset']}`",
        f"- Detector: `{rep['detector_mode']}`" + (f" (weights `{rep['weights']}`)" if rep["weights"] else ""),
        f"- Test images: {rep['test_images']}",
        f"- IoU threshold: {rep['iou_threshold']}, confidence threshold: {rep['confidence_threshold']}",
        "", f"## Detection: mAP@0.5 = {rep['map50']}", "",
        "| Class | Category | GT | Pred | TP | Precision | Recall | AP@0.5 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for n, v in rep["per_class"].items():
        lines.append(f"| {n} | {v['category']} | {v['ground_truth']} | {v['predictions']} | "
                     f"{v['true_positives']} | {v['precision']} | {v['recall']} | {v['ap50']} |")
    lines += ["", "## Counting error (per image)", "",
              "| Group | Mean true count | MAE | MAPE % | Images used for MAPE |", "|---|---|---|---|---|"]
    for n, v in rep["counting_error"].items():
        lines.append(f"| {n} | {v['mean_true_count']} | {v['mae']} | {v['mape_percent']} | {v['images_used_for_mape']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Evaluate the detector on the test split.")
    ap.add_argument("--data", default=str(ROOT / "ml/data/yolo/data.yaml"))
    ap.add_argument("--weights", help="weights file, or 'demo' to evaluate the demo detector")
    ap.add_argument("--name", help="report name (default: derived from dataset and detector)")
    args = ap.parse_args()

    data_yaml = Path(args.data)
    if not data_yaml.exists():
        raise SystemExit(f"[evaluate] {data_yaml} not found. Run python -m ml.convert_dataset first.")
    if args.weights == "demo":
        os.environ["KEETA_WEIGHTS"] = str(ROOT / "ml/weights/__none__.pt")  # forces demo detector
    elif args.weights:
        os.environ["KEETA_WEIGHTS"] = str(Path(args.weights).resolve())

    rep = evaluate(data_yaml)
    name = args.name or f"{data_yaml.parent.name}_{rep['detector_mode']}"
    out_dir = ROOT / "ml/reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"eval_{name}.json").write_text(json.dumps(rep, indent=2))
    (out_dir / f"eval_{name}.md").write_text(to_markdown(rep), encoding="utf-8")
    print(to_markdown(rep))
    print(f"[evaluate] reports -> {out_dir / f'eval_{name}.json'} and .md")


if __name__ == "__main__":
    main()

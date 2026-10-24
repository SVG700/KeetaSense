"""Convert a raw insect dataset to YOLO format with a stratified 70/15/15 split.

What it does, step by step:
  1. Looks inside the raw folder (default ml/data/raw/) for images.
  2. Detects the annotation format: Pascal VOC XML or YOLO txt.
  3. Lists every label it finds and maps it to our classes using the
     aliases in config/pests.yaml (e.g. "WF" -> whitefly). Unknown labels
     are reported and skipped.
  4. Splits images 70/15/15 into train/val/test. The split is STRATIFIED by
     each image's most common class, so every split gets a similar mix,
     and uses a fixed seed so the split is the same every time.
  5. Writes ml/data/yolo/{images,labels}/{train,val,test} and data.yaml.

Usage:
    python -m ml.convert_dataset                       # real dataset
    python -m ml.convert_dataset --raw ml/data/synthetic_raw --out ml/data/synthetic_yolo
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

import cv2
import yaml

from ml.common import ROOT, class_names, resolve_alias

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

DOWNLOAD_HELP = """
================================================================
 No images found in {raw}

 Please download the "Yellow Sticky Traps" dataset (Wageningen University,
 Nieuwenhuizen et al., CC0 licence) and unzip it into that folder:

   Option A - original source (4TU.ResearchData, ~800 MB):
     https://data.4tu.nl/articles/_/12707066/1
     DOI 10.4121/uuid:8b8ba63a-1010-4de7-a7fb-6f9e3baf128e

   Option B - a Kaggle mirror, using your Kaggle API key:
     python -m ml.download_kaggle --dataset <owner>/<dataset-name>

 Then run again:  python -m ml.convert_dataset
 (Images and their .xml or .txt label files can be in any sub-folders.)
================================================================
"""


# ---------------------------------------------------------------------------
# Reading annotations
# ---------------------------------------------------------------------------
def find_images(raw: Path) -> list[Path]:
    return sorted(p for p in raw.rglob("*") if p.suffix.lower() in IMAGE_EXTS)


def detect_format(raw: Path) -> str:
    """Return "voc", "yolo" or "unknown" by looking at the label files present."""
    xmls = list(raw.rglob("*.xml"))
    if any(_is_voc(x) for x in xmls[:20]):
        return "voc"
    txts = [t for t in raw.rglob("*.txt") if t.name not in ("classes.txt", "README.txt")]
    for t in txts[:20]:
        lines = [l.split() for l in t.read_text(errors="ignore").splitlines() if l.strip()]
        if lines and all(len(l) == 5 for l in lines):
            return "yolo"
    return "unknown"


def _is_voc(xml_path: Path) -> bool:
    try:
        return ET.parse(xml_path).getroot().tag == "annotation"
    except ET.ParseError:
        return False


def read_voc(xml_path: Path, image_path: Path) -> list[tuple[str, float, float, float, float]]:
    """Return list of (raw_label, x1, y1, x2, y2) in pixels."""
    root = ET.parse(xml_path).getroot()
    boxes = []
    for obj in root.findall("object"):
        bb = obj.find("bndbox")
        boxes.append((obj.findtext("name", "").strip(),
                      float(bb.findtext("xmin")), float(bb.findtext("ymin")),
                      float(bb.findtext("xmax")), float(bb.findtext("ymax"))))
    return boxes


def image_size(image_path: Path, xml_path: Path | None = None) -> tuple[int, int]:
    """(width, height) - from the VOC <size> tag if present, else from the image."""
    if xml_path is not None:
        size = ET.parse(xml_path).getroot().find("size")
        if size is not None:
            w, h = int(float(size.findtext("width", "0"))), int(float(size.findtext("height", "0")))
            if w > 0 and h > 0:
                return w, h
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"cannot read image {image_path}")
    return img.shape[1], img.shape[0]


def read_yolo_names(raw: Path) -> list[str]:
    """Class names for a YOLO-format raw dataset (classes.txt, obj.names or data.yaml)."""
    for name in ("classes.txt", "obj.names"):
        hits = list(raw.rglob(name))
        if hits:
            return [l.strip() for l in hits[0].read_text().splitlines() if l.strip()]
    for hit in list(raw.rglob("data.yaml")) + list(raw.rglob("*.yaml")):
        names = (yaml.safe_load(hit.read_text()) or {}).get("names")
        if isinstance(names, dict):
            return [names[k] for k in sorted(names)]
        if isinstance(names, list):
            return names
    return []


def find_label_file(image: Path, raw: Path, ext: str) -> Path | None:
    """Label file next to the image, or anywhere in raw with the same stem."""
    same_dir = image.with_suffix(ext)
    if same_dir.exists():
        return same_dir
    # common layouts: images/ + labels/  or  JPEGImages/ + Annotations/
    for a, b in (("images", "labels"), ("JPEGImages", "Annotations")):
        parts = list(image.parts)
        if a in parts:
            parts[parts.index(a)] = b
            cand = Path(*parts).with_suffix(ext)
            if cand.exists():
                return cand
    return None


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------
def stratified_split(items: list[dict], ratios=(0.70, 0.15, 0.15), seed: int = 42) -> dict[str, list[dict]]:
    """Split items into train/val/test, stratified by item["strata"]."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        groups[it["strata"]].append(it)
    rng = random.Random(seed)
    out = {"train": [], "val": [], "test": []}
    for key in sorted(groups):
        g = sorted(groups[key], key=lambda it: it["name"])
        rng.shuffle(g)
        n = len(g)
        n_train = round(n * ratios[0])
        n_val = round(n * ratios[1])
        out["train"] += g[:n_train]
        out["val"] += g[n_train:n_train + n_val]
        out["test"] += g[n_train + n_val:]
    return out


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------
def convert(raw: Path, out: Path, seed: int = 42) -> dict | None:
    images = find_images(raw)
    if not images:
        print(DOWNLOAD_HELP.format(raw=raw))
        return None

    fmt = detect_format(raw)
    print(f"[convert] found {len(images)} images in {raw}")
    print(f"[convert] detected annotation format: {fmt}")
    if fmt == "unknown":
        print("[convert] ERROR: no Pascal VOC .xml or YOLO .txt labels found. "
              "Put label files next to the images and try again.")
        return None

    names = class_names()
    yolo_names = read_yolo_names(raw) if fmt == "yolo" else []
    raw_label_counts: Counter = Counter()
    items = []
    skipped_no_label = 0

    for img_path in images:
        label_path = find_label_file(img_path, raw, ".xml" if fmt == "voc" else ".txt")
        if label_path is None:
            skipped_no_label += 1
            continue
        yolo_lines = []
        if fmt == "voc":
            w, h = image_size(img_path, label_path)
            for raw_label, x1, y1, x2, y2 in read_voc(label_path, img_path):
                raw_label_counts[raw_label] += 1
                canonical = resolve_alias(raw_label)
                if canonical is None:
                    continue
                x1, x2 = max(0.0, min(x1, x2)), min(float(w), max(x1, x2))
                y1, y2 = max(0.0, min(y1, y2)), min(float(h), max(y1, y2))
                if x2 - x1 < 1 or y2 - y1 < 1:
                    continue
                yolo_lines.append((names.index(canonical),
                                   (x1 + x2) / 2 / w, (y1 + y2) / 2 / h, (x2 - x1) / w, (y2 - y1) / h))
        else:  # yolo txt
            for line in label_path.read_text().splitlines():
                parts = line.split()
                if len(parts) != 5:
                    continue
                cid = int(float(parts[0]))
                raw_label = yolo_names[cid] if cid < len(yolo_names) else f"class_{cid}"
                raw_label_counts[raw_label] += 1
                canonical = resolve_alias(raw_label)
                if canonical is None:
                    continue
                yolo_lines.append((names.index(canonical), *map(float, parts[1:])))

        per_class = Counter(names[l[0]] for l in yolo_lines)
        rel = img_path.relative_to(raw)
        safe_name = "__".join(rel.with_suffix("").parts) + img_path.suffix.lower()
        items.append({
            "image": img_path, "name": safe_name, "lines": yolo_lines,
            "counts": dict(per_class),
            # strata = most common class in the image (or "empty")
            "strata": per_class.most_common(1)[0][0] if per_class else "empty",
        })

    # --- report the labels we found ---
    print("[convert] raw labels found:")
    unmapped = []
    for label, n in raw_label_counts.most_common():
        canonical = resolve_alias(label)
        print(f"    {label!r:20} x{n:<6} -> {canonical or 'NOT MAPPED (skipped)'}")
        if canonical is None:
            unmapped.append(label)
    if unmapped:
        print(f"[convert] WARNING: {len(unmapped)} label(s) not in config/pests.yaml: {unmapped}. "
              "Add them as aliases there if they should be used.")
    if skipped_no_label:
        print(f"[convert] WARNING: {skipped_no_label} image(s) had no label file and were skipped.")
    if not items:
        print("[convert] ERROR: no labelled images to convert.")
        return None

    # --- split and write ---
    splits = stratified_split(items, seed=seed)
    if out.exists():
        shutil.rmtree(out)
    summary = {"source": str(raw), "format": fmt, "seed": seed, "classes": names, "splits": {}}
    for split, split_items in splits.items():
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)
        class_totals: Counter = Counter()
        for it in split_items:
            shutil.copy2(it["image"], out / "images" / split / it["name"])
            label_file = out / "labels" / split / (Path(it["name"]).stem + ".txt")
            label_file.write_text("".join(
                f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n" for c, x, y, w, h in it["lines"]))
            class_totals.update(it["counts"])
        summary["splits"][split] = {"images": len(split_items), "objects": dict(class_totals)}
        print(f"[convert] {split:5}: {len(split_items):5} images, objects {dict(class_totals)}")

    data_yaml = {
        "path": str(out.resolve()).replace("\\", "/"),
        "train": "images/train", "val": "images/val", "test": "images/test",
        "names": {i: n for i, n in enumerate(names)},
    }
    (out / "data.yaml").write_text(yaml.safe_dump(data_yaml, sort_keys=False))
    (out / "split_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[convert] done -> {out / 'data.yaml'}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert a raw dataset to YOLO format (70/15/15 split).")
    ap.add_argument("--raw", default=str(ROOT / "ml/data/raw"))
    ap.add_argument("--out", default=str(ROOT / "ml/data/yolo"))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    raw = Path(args.raw)
    raw.mkdir(parents=True, exist_ok=True)
    result = convert(raw, Path(args.out), args.seed)
    sys.exit(0)  # always exit cleanly; messages above explain any problem
    return result


if __name__ == "__main__":
    main()

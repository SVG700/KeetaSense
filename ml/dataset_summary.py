"""Describe a converted YOLO dataset: classes, counts, image sizes, insect sizes.

Writes a Markdown report (default ml/reports/dataset_summary.md) so the team
knows what the model will learn from BEFORE spending GPU time:
  - raw labels found and how they were mapped (from the converter)
  - images and objects per split, objects per class
  - image resolution range
  - typical insect size in pixels (median, 10th-90th percentile of the box's long side)
  - warnings for classes with too few examples

Runs automatically at the end of ml.convert_dataset. Manual use:
    python -m ml.dataset_summary --data ml/data/yolo
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from ml.common import ROOT

MIN_OBJECTS_PER_CLASS = 100      # below this a class is flagged as "too few examples"
MIN_SHARE_PER_CLASS = 0.02       # or if it is under 2 % of all objects
MIN_OBJECTS_IN_TEST = 10         # too few test examples -> per-class metrics unreliable


def summarise(data_dir: Path) -> dict:
    data = yaml.safe_load((data_dir / "data.yaml").read_text())
    names = data["names"]
    names = [names[k] for k in sorted(names)] if isinstance(names, dict) else list(names)
    split_info = {}
    split_summary_file = data_dir / "split_summary.json"
    extra = json.loads(split_summary_file.read_text()) if split_summary_file.exists() else {}

    widths, heights = [], []
    long_side = defaultdict(list)          # class -> list of box long sides (px)
    per_split_class: dict[str, Counter] = {}
    for split in ("train", "val", "test"):
        img_dir, lbl_dir = data_dir / "images" / split, data_dir / "labels" / split
        if not img_dir.exists():
            continue
        counter: Counter = Counter()
        n_images = 0
        for img_path in sorted(img_dir.iterdir()):
            try:
                with Image.open(img_path) as im:   # reads only the header, fast for big photos
                    w, h = im.size
            except OSError:
                continue
            n_images += 1
            widths.append(w)
            heights.append(h)
            lbl = lbl_dir / (img_path.stem + ".txt")
            if not lbl.exists():
                continue
            for line in lbl.read_text().splitlines():
                parts = line.split()
                if len(parts) != 5:
                    continue
                cls = names[int(parts[0])]
                counter[cls] += 1
                long_side[cls].append(max(float(parts[3]) * w, float(parts[4]) * h))
        per_split_class[split] = counter
        split_info[split] = {"images": n_images, "objects": sum(counter.values())}

    total = Counter()
    for c in per_split_class.values():
        total.update(c)
    all_objects = sum(total.values())

    classes = {}
    warnings = []
    for n in names:
        sizes = np.array(long_side.get(n, []))
        classes[n] = {
            "objects": total.get(n, 0),
            "share": round(total.get(n, 0) / all_objects, 4) if all_objects else 0,
            "per_split": {s: per_split_class[s].get(n, 0) for s in per_split_class},
            "size_px_median": round(float(np.median(sizes)), 1) if sizes.size else None,
            "size_px_p10": round(float(np.percentile(sizes, 10)), 1) if sizes.size else None,
            "size_px_p90": round(float(np.percentile(sizes, 90)), 1) if sizes.size else None,
        }
        c = classes[n]
        if c["objects"] < MIN_OBJECTS_PER_CLASS:
            warnings.append(f"'{n}' has only {c['objects']} examples (< {MIN_OBJECTS_PER_CLASS}): "
                            "the model will learn it poorly - consider more data or merging classes.")
        elif c["share"] < MIN_SHARE_PER_CLASS:
            warnings.append(f"'{n}' is only {c['share']:.1%} of all objects: strongly imbalanced.")
        if c["per_split"].get("test", 0) < MIN_OBJECTS_IN_TEST:
            warnings.append(f"'{n}' has {c['per_split'].get('test', 0)} test examples: its test metrics "
                            "will be unreliable.")

    return {
        "created": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(data_dir),
        "synthetic": "synthetic" in str(data_dir).lower(),
        "source": extra.get("source"),
        "format": extra.get("format"),
        "raw_labels": extra.get("raw_labels", {}),
        "unmapped_labels": extra.get("unmapped_labels", []),
        "splits": split_info,
        "images_total": sum(s["images"] for s in split_info.values()),
        "objects_total": all_objects,
        "resolution": {
            "width_min": min(widths, default=0), "width_max": max(widths, default=0),
            "height_min": min(heights, default=0), "height_max": max(heights, default=0),
            "most_common": "x".join(map(str, Counter(zip(widths, heights)).most_common(1)[0][0])) if widths else None,
        },
        "classes": classes,
        "warnings": warnings,
    }


def to_markdown(s: dict) -> str:
    L = ["# Dataset summary", ""]
    if s["synthetic"]:
        L += ["> **SYNTHETIC DATA** - generated test images, not real insects.", ""]
    r = s["resolution"]
    L += [f"- Created: {s['created']}",
          f"- Converted dataset: `{s['dataset']}`" + (f" (from `{s['source']}`, format {s['format']})" if s["source"] else ""),
          f"- Images: **{s['images_total']}**, labelled objects: **{s['objects_total']}**",
          f"- Image resolution: width {r['width_min']}-{r['width_max']} px, height {r['height_min']}-{r['height_max']} px "
          f"(most common {r['most_common']})", ""]
    if s["raw_labels"]:
        L += ["## Raw labels found", "", "| Raw label | Count | Mapped to |", "|---|---|---|"]
        for label, info in s["raw_labels"].items():
            L.append(f"| {label} | {info['count']} | {info['mapped_to'] or '**not mapped - skipped**'} |")
        L.append("")
    L += ["## Splits", "", "| Split | Images | Objects |", "|---|---|---|"]
    for split, v in s["splits"].items():
        L.append(f"| {split} | {v['images']} | {v['objects']} |")
    L += ["", "## Classes", "",
          "| Class | Objects | Share | Train / Val / Test | Insect size px (median, p10-p90) |",
          "|---|---|---|---|---|"]
    for n, c in s["classes"].items():
        ps = c["per_split"]
        L.append(f"| {n} | {c['objects']} | {c['share']:.1%} | {ps.get('train', 0)} / {ps.get('val', 0)} / "
                 f"{ps.get('test', 0)} | {c['size_px_median']} ({c['size_px_p10']}-{c['size_px_p90']}) |")
    L += ["", "## Warnings", ""]
    L += [f"- ⚠ {w}" for w in s["warnings"]] or ["- none"]
    L += ["", "Insect size = longer side of the labelled box, in pixels of the original photo. "
          "With SAHI 640 px tiles, an insect of N px stays N px for the model."]
    return "\n".join(L) + "\n"


def write_report(data_dir: Path, out: Path | None = None) -> Path:
    s = summarise(data_dir)
    if out is None:
        name = "dataset_summary.md" if data_dir.resolve() == (ROOT / "ml/data/yolo").resolve() \
            else f"dataset_summary_{data_dir.name}.md"
        out = ROOT / "ml/reports" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_markdown(s), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarise a converted YOLO dataset.")
    ap.add_argument("--data", default=str(ROOT / "ml/data/yolo"))
    ap.add_argument("--out")
    args = ap.parse_args()
    d = Path(args.data)
    if not (d / "data.yaml").exists():
        print(f"[summary] {d / 'data.yaml'} not found - run python -m ml.convert_dataset first.")
        return
    out = write_report(d, Path(args.out) if args.out else None)
    print(out.read_text(encoding="utf-8"))
    print(f"[summary] written to {out}")


if __name__ == "__main__":
    main()

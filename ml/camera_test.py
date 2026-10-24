"""Camera-domain test: does the detector count the same on a PHOTO of a printed
test image as on the original digital image?

On stage our camera will photograph printed images (or real tape) under LEDs.
Printing + camera add blur, colour cast, glare and perspective. This script
measures how much that changes the counts.

Step 1 - pick images to print (copies them to ml/data/camera_test/originals/):
    python -m ml.camera_test prepare --n 10
Step 2 - print them (colour, full page, matte paper if possible), put each print
    in the trap chamber (or under the LEDs) and photograph it with the Pi camera
    (python -m edge.tests_hw.test_camera --out <name>.jpg) or a phone.
    Name each photo after its original, e.g. original "img_12.jpg" -> photo
    "img_12.jpg" or "img_12_cam.jpg" or "pi_img_12.jpg" (the original's name must
    appear inside the photo's name). Put all photos in one folder.
Step 3 - compare:
    python -m ml.camera_test run --photos ml/data/camera_test/photos
Result: ml/reports/camera_test.md (+ .json).

Every number in the report is measured on your photos; nothing is estimated.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

from ml.common import ROOT, category_of, class_names

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
DEFAULT_DIR = ROOT / "ml/data/camera_test"


def _images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS) if folder.exists() else []


def match_photos(originals: list[Path], photos: list[Path]) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """Pair each photo with the original whose file name (without extension) appears in the
    photo's name. The longest matching name wins (so "img_1" does not steal "img_12")."""
    pairs, unmatched = [], []
    stems = sorted(((o.stem.lower(), o) for o in originals), key=lambda x: -len(x[0]))
    for photo in photos:
        name = photo.stem.lower()
        match = next((o for stem, o in stems if stem in name), None)
        if match is None:
            unmatched.append(photo)
        else:
            pairs.append((match, photo))
    return pairs, unmatched


def true_counts(original: Path, labels_dir: Path | None) -> dict | None:
    """Ground-truth counts from a YOLO label file, if we have one."""
    if labels_dir is None:
        return None
    lbl = labels_dir / (original.stem + ".txt")
    if not lbl.exists():
        return None
    names = class_names()
    counts = {n: 0 for n in names}
    for line in lbl.read_text().splitlines():
        if line.split():
            counts[names[int(line.split()[0])]] += 1
    return counts


def _totals(counts: dict) -> tuple[int, int]:
    pests = sum(v for k, v in counts.items() if category_of(k) == "pest")
    predators = sum(v for k, v in counts.items() if category_of(k) == "predator")
    return pests, predators


def compare(pairs: list[tuple[Path, Path]], labels_dir: Path | None = None) -> dict:
    from ml import infer
    rows = []
    mode = None
    for original, photo in pairs:
        a, b = infer.detect(original), infer.detect(photo)
        mode = a.mode
        truth = true_counts(original, labels_dir)
        row = {
            "original": original.name, "photo": photo.name,
            "original_counts": a.counts, "photo_counts": b.counts,
            "original_pests": a.pest_total, "photo_pests": b.pest_total,
            "original_predators": a.predator_total, "photo_predators": b.predator_total,
        }
        if truth is not None:
            row["true_counts"] = truth
            row["true_pests"], row["true_predators"] = _totals(truth)
        rows.append(row)

    def diff_stats(key: str) -> dict:
        o = np.array([r[f"original_{key}"] for r in rows], dtype=float)
        p = np.array([r[f"photo_{key}"] for r in rows], dtype=float)
        nz = o > 0
        return {
            "mean_abs_diff": round(float(np.mean(np.abs(p - o))), 2) if rows else None,
            "mean_signed_diff": round(float(np.mean(p - o)), 2) if rows else None,  # <0: photo finds fewer
            "mean_abs_pct_diff": round(float(np.mean(np.abs(p[nz] - o[nz]) / o[nz]) * 100), 1) if nz.any() else None,
            "images_used_for_pct": int(nz.sum()),
        }

    per_class = {}
    for n in class_names():
        o = np.array([r["original_counts"].get(n, 0) for r in rows], dtype=float)
        p = np.array([r["photo_counts"].get(n, 0) for r in rows], dtype=float)
        per_class[n] = {"mean_abs_diff": round(float(np.mean(np.abs(p - o))), 2) if rows else None,
                        "original_total": int(o.sum()), "photo_total": int(p.sum())}

    summary = {"pests": diff_stats("pests"), "predators": diff_stats("predators"), "per_class": per_class}
    with_truth = [r for r in rows if "true_pests" in r]
    if with_truth:
        summary["vs_ground_truth"] = {
            "images": len(with_truth),
            "original_pest_mae": round(float(np.mean([abs(r["original_pests"] - r["true_pests"]) for r in with_truth])), 2),
            "photo_pest_mae": round(float(np.mean([abs(r["photo_pests"] - r["true_pests"]) for r in with_truth])), 2),
        }
    return {"created": datetime.now().isoformat(timespec="seconds"), "detector_mode": mode,
            "pairs": len(rows), "summary": summary, "rows": rows}


def to_markdown(rep: dict, unmatched: list[str], source_note: str) -> str:
    s = rep["summary"]
    L = ["# Camera-domain test", "",
         f"- Created: {rep['created']}", f"- Detector: `{rep['detector_mode']}`",
         f"- Image pairs compared: {rep['pairs']}", f"- Originals: {source_note}", ""]
    if rep["detector_mode"] == "demo_detector":
        L += ["> **DEMO DETECTOR** was active - re-run after installing the trained model "
              "for meaningful numbers.", ""]
    L += ["## Summary (photo vs original)", "",
          "| Group | Mean abs. difference (insects/image) | Mean signed difference | Mean abs. % difference | Images for % |",
          "|---|---|---|---|---|"]
    for k in ("pests", "predators"):
        v = s[k]
        L.append(f"| {k} | {v['mean_abs_diff']} | {v['mean_signed_diff']} | {v['mean_abs_pct_diff']} | {v['images_used_for_pct']} |")
    L += ["", "Signed difference < 0 means the photo is counted LOWER than the original (insects lost in printing/camera).", ""]
    if "vs_ground_truth" in s:
        g = s["vs_ground_truth"]
        L += ["## Against the labelled ground truth", "",
              f"Pest count MAE on {g['images']} images: original {g['original_pest_mae']}, photo {g['photo_pest_mae']}.", ""]
    L += ["## Per class", "", "| Class | Mean abs. difference | Total in originals | Total in photos |", "|---|---|---|---|"]
    for n, v in s["per_class"].items():
        L.append(f"| {n} | {v['mean_abs_diff']} | {v['original_total']} | {v['photo_total']} |")
    L += ["", "## Per image", "", "| Original | Photo | Pests orig → photo | Predators orig → photo |", "|---|---|---|---|"]
    for r in rep["rows"]:
        L.append(f"| {r['original']} | {r['photo']} | {r['original_pests']} → {r['photo_pests']} | "
                 f"{r['original_predators']} → {r['photo_predators']} |")
    if unmatched:
        L += ["", f"**Photos with no matching original (skipped):** {', '.join(unmatched)}"]
    return "\n".join(L) + "\n"


def prepare(n: int, data_dir: Path, out_dir: Path) -> list[Path]:
    """Copy n test images (the ones with the most insects first) for printing."""
    data = yaml.safe_load((data_dir / "data.yaml").read_text())
    test_dir = Path(data.get("path", data_dir)) / data.get("test", "images/test")
    if not test_dir.is_absolute():
        test_dir = data_dir / test_dir
    labels = Path(str(test_dir).replace("images", "labels"))
    ranked = sorted(_images(test_dir), key=lambda p: -len((labels / (p.stem + ".txt")).read_text().splitlines())
                    if (labels / (p.stem + ".txt")).exists() else 0)
    originals = out_dir / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    (out_dir / "photos").mkdir(exist_ok=True)
    chosen = ranked[:n]
    for p in chosen:
        shutil.copy2(p, originals / p.name)
    (out_dir / "source.json").write_text(json.dumps({"data": str(data_dir), "labels": str(labels)}, indent=2))
    (out_dir / "PRINT_ME.txt").write_text(
        "Print every image in originals/ in COLOUR, one per page, scaled to fill the page.\n"
        "Photograph each print with the Pi camera inside the trap (or under the same LEDs),\n"
        "filling the frame with the printed area. Save the photos in photos/ with the original\n"
        "file name inside the photo name (e.g. img_12_cam.jpg). Then run:\n"
        "    python -m ml.camera_test run\n", encoding="utf-8")
    return chosen


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare detections on originals vs camera photos of prints.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("prepare", help="copy test images to print")
    p1.add_argument("--n", type=int, default=10)
    p1.add_argument("--data", default=str(ROOT / "ml/data/yolo"))
    p1.add_argument("--out", default=str(DEFAULT_DIR))
    p2 = sub.add_parser("run", help="compare photos with their originals")
    p2.add_argument("--photos", default=str(DEFAULT_DIR / "photos"))
    p2.add_argument("--originals", default=str(DEFAULT_DIR / "originals"))
    p2.add_argument("--labels", help="YOLO label folder for the originals (auto from prepare)")
    p2.add_argument("--report", default=str(ROOT / "ml/reports/camera_test.md"))
    p2.add_argument("--weights", help="override KEETA_WEIGHTS")
    args = ap.parse_args()

    if args.cmd == "prepare":
        if not (Path(args.data) / "data.yaml").exists():
            raise SystemExit(f"[camera_test] {args.data}/data.yaml not found - convert the dataset first.")
        chosen = prepare(args.n, Path(args.data), Path(args.out))
        print(f"[camera_test] copied {len(chosen)} images to {Path(args.out) / 'originals'} - see PRINT_ME.txt")
        return

    import os
    if args.weights:
        os.environ["KEETA_WEIGHTS"] = str(Path(args.weights).resolve())
    originals, photos = _images(Path(args.originals)), _images(Path(args.photos))
    if not originals or not photos:
        raise SystemExit(f"[camera_test] need images in {args.originals} and {args.photos} (see --help).")
    labels_dir = Path(args.labels) if args.labels else None
    source = Path(args.originals).parent / "source.json"
    if labels_dir is None and source.exists():
        labels_dir = Path(json.loads(source.read_text())["labels"])
    pairs, unmatched = match_photos(originals, photos)
    if not pairs:
        raise SystemExit("[camera_test] no photo matched an original by file name.")
    rep = compare(pairs, labels_dir)
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    md = to_markdown(rep, [p.name for p in unmatched], f"`{args.originals}`")
    out.write_text(md, encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(md)
    print(f"[camera_test] report -> {out}")


if __name__ == "__main__":
    main()

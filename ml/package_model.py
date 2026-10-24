"""Bundle a trained model with its evaluation report and the exact config used.

Creates ml/exports/keetasense_model_<date>.zip containing:
  weights/best.pt, weights/best.json   - the model and its "model card" (training facts)
  reports/eval_*.md/.json             - evaluation on the test split
  reports/dataset_summary.*            - what data it was trained on (if present)
  config_used/pests.yaml               - classes + thresholds at training time
  config_used/data.yaml, split_summary.json, tiling.yaml
  config_used/train_args.yaml, results.csv - Ultralytics training settings and curves

On the laptop, install it with:  python -m ml.install_model path/to/keetasense_model_<date>.zip

Usage (Colab runs this automatically at the end of the notebook):
    python -m ml.package_model --report real_test
"""
from __future__ import annotations

import argparse
import json
import zipfile
from datetime import datetime
from pathlib import Path

from ml.common import ROOT, pests_yaml_path


def package(weights: Path, report_name: str | None, data_dir: Path | None, out_dir: Path) -> Path:
    if not weights.exists():
        raise SystemExit(f"[package] {weights} not found - train first.")
    out_dir.mkdir(parents=True, exist_ok=True)
    card_path = weights.with_suffix(".json")
    card = json.loads(card_path.read_text()) if card_path.exists() else {}
    tag = "SYNTHETIC_" if card.get("synthetic_data") else ""  # never mistake a smoke test for the real model
    zip_path = out_dir / f"keetasense_model_{tag}{datetime.now():%Y%m%d_%H%M}.zip"

    files: list[tuple[Path, str]] = [(weights, "weights/best.pt")]
    if card_path.exists():
        files.append((card_path, "weights/best.json"))
    reports = ROOT / "ml/reports"
    if report_name:
        for ext in (".md", ".json"):
            p = reports / f"eval_{report_name}{ext}"
            if p.exists():
                files.append((p, f"reports/{p.name}"))
    for p in reports.glob("dataset_summary.*"):
        files.append((p, f"reports/{p.name}"))
    files.append((pests_yaml_path(), "config_used/pests.yaml"))
    if data_dir:
        for name in ("data.yaml", "split_summary.json", "tiling.yaml"):
            if (data_dir / name).exists():
                files.append((data_dir / name, f"config_used/{name}"))
    run_dir = Path(card.get("run_dir", "")) if card.get("run_dir") else None
    if run_dir and run_dir.exists():
        for name, arc in (("args.yaml", "config_used/train_args.yaml"), ("results.csv", "config_used/results.csv")):
            if (run_dir / name).exists():
                files.append((run_dir / name, arc))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in files:
            z.write(src, arc)
        z.writestr("README.txt",
                   "KeetaSense trained model package.\n"
                   "Install on the laptop: python -m ml.install_model <this zip>\n"
                   "Metrics in reports/ were MEASURED by ml/evaluate.py on the dataset named inside them.\n")
    print(f"[package] {len(files)} files -> {zip_path}")
    for _, arc in files:
        print(f"           {arc}")
    return zip_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Zip best.pt + evaluation report + config used.")
    ap.add_argument("--weights", default=str(ROOT / "ml/weights/best.pt"))
    ap.add_argument("--report", help="evaluation report name, e.g. real_test for eval_real_test.md")
    ap.add_argument("--data", help="dataset folder used (for data.yaml, split_summary.json, tiling.yaml)")
    ap.add_argument("--out", default=str(ROOT / "ml/exports"))
    args = ap.parse_args()
    package(Path(args.weights), args.report, Path(args.data) if args.data else None, Path(args.out))


if __name__ == "__main__":
    main()

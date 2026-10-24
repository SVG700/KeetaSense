"""Install a model package made by ml/package_model.py (e.g. downloaded from Colab).

    python -m ml.install_model Downloads/keetasense_model_20261102_1530.zip

What it does:
  - copies weights/best.pt and best.json into ml/weights/ (the old ones are kept
    as best_previous.pt / .json)
  - copies the evaluation reports into ml/reports/ (the dashboard's Model page shows them)
  - extracts config_used/ into ml/exports/<package name>/ for reference
  - warns if the model's classes differ from config/pests.yaml
It does NOT overwrite config/pests.yaml.
Restart the backend afterwards; its log will say which model it loaded.
"""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

from ml.common import ROOT, class_names


def install(zip_path: Path, root: Path = ROOT) -> dict:
    weights_dir, reports_dir = root / "ml/weights", root / "ml/reports"
    ref_dir = root / "ml/exports" / zip_path.stem
    weights_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    installed = {"weights": None, "reports": [], "config_used": None, "warnings": []}

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "weights/best.pt" not in names:
            raise SystemExit(f"[install] {zip_path} has no weights/best.pt - not a KeetaSense model package.")
        for old in ("best.pt", "best.json"):
            if (weights_dir / old).exists():
                shutil.copy2(weights_dir / old, weights_dir / old.replace("best", "best_previous"))
        for name in names:
            if name.endswith("/") or ".." in Path(name).parts:
                continue  # skip folders and anything trying to escape
            data = z.read(name)
            if name.startswith("weights/"):
                (weights_dir / Path(name).name).write_bytes(data)
            elif name.startswith("reports/"):
                (reports_dir / Path(name).name).write_bytes(data)
                installed["reports"].append(Path(name).name)
            elif name.startswith("config_used/"):
                ref_dir.mkdir(parents=True, exist_ok=True)
                (ref_dir / Path(name).name).write_bytes(data)
                installed["config_used"] = str(ref_dir)
    installed["weights"] = str(weights_dir / "best.pt")

    card = weights_dir / "best.json"
    if card.exists():
        info = json.loads(card.read_text())
        if info.get("synthetic_data"):
            installed["warnings"].append("this model was trained on SYNTHETIC data - it will not work on real "
                                         "insects. Install the real Colab package before the demo.")
        model_classes = info.get("classes")
        if model_classes and model_classes != class_names():
            installed["warnings"].append(
                f"model classes {model_classes} differ from config/pests.yaml {class_names()} - "
                "update pests.yaml so every model class has a pest/predator category.")
    return installed


def main() -> None:
    ap = argparse.ArgumentParser(description="Install a KeetaSense model package (.zip).")
    ap.add_argument("zip")
    args = ap.parse_args()
    result = install(Path(args.zip))
    print(f"[install] weights -> {result['weights']}")
    for r in result["reports"]:
        print(f"[install] report  -> ml/reports/{r}")
    if result["config_used"]:
        print(f"[install] config used for training -> {result['config_used']}")
    for w in result["warnings"]:
        print(f"[install] WARNING: {w}")
    print("[install] Restart the backend (and the edge service) to load the new model.")


if __name__ == "__main__":
    main()

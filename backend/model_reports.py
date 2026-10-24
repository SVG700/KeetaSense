"""Read the evaluation reports written by ml/evaluate.py (ml/reports/eval_*.json).

The dashboard's Model page shows them. Nothing here computes or estimates a
metric - it only passes on what evaluate.py measured, plus which data it was
measured on.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.settings import ROOT

log = logging.getLogger("keetasense.reports")


def reports_dir() -> Path:
    return ROOT / "ml" / "reports"


def list_reports(folder: Path | None = None) -> list[dict]:
    """All evaluation reports, newest first, reduced to what the dashboard needs."""
    out = []
    for path in (folder or reports_dir()).glob("eval_*.json"):
        try:
            rep = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Skipping unreadable report %s", path)
            continue
        counting = rep.get("counting_error", {})
        out.append({
            "name": path.stem.removeprefix("eval_"),
            "file": path.name,
            "created": rep.get("created"),
            "dataset": rep.get("dataset"),
            "synthetic_data": bool(rep.get("synthetic_data")),
            "detector_mode": rep.get("detector_mode"),
            "weights": Path(rep["weights"]).name if rep.get("weights") else None,
            "test_images": rep.get("test_images"),
            "iou_threshold": rep.get("iou_threshold"),
            "confidence_threshold": rep.get("confidence_threshold"),
            "map50": rep.get("map50"),
            "per_class": rep.get("per_class", {}),
            "counting_error": {k: v for k, v in counting.items()},
        })
    out.sort(key=lambda r: r["created"] or "", reverse=True)
    return out

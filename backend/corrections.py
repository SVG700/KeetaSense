"""F3 human-in-the-loop: a scout fixes the boxes on a tape photo.

The model's detections stay on record (tapesection.detections). Each scout edit is
a row in the `correction` table:
    add      draw a missing insect (class + box)
    remove   a box that is not an insect (dust, shadow)
    relabel  right box, wrong class (e.g. whitefly -> macrolophus)
Replaying the edits over the model's boxes gives the corrected boxes and counts,
which REPLACE the model's counts in the decision (recomputed at once). Both
numbers are kept and shown ("corrected by scout").

Box ids: "m<i>" = model detection no. i, "c<id>" = box added by correction <id>.
Corrections also become training data: export_zip() writes YOLO label files.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

import cv2
import numpy as np
import yaml
from sqlmodel import Session, select

from backend import services, settings
from backend.models import Correction, TapeSection, Trap
from ml.common import category_of, class_names

ACTIONS = ("add", "remove", "relabel")


class CorrectionError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Pure part: replay corrections over the model's boxes
# ---------------------------------------------------------------------------
def apply_corrections(model_detections: list[dict], corrections: list[Correction]) -> list[dict]:
    boxes = {}
    for i, d in enumerate(model_detections or []):
        boxes[f"m{i}"] = {"id": f"m{i}", "class_name": d["class_name"], "category": category_of(d["class_name"]),
                          "confidence": d.get("confidence"), "bbox": d["bbox"], "source": "model"}
    for c in sorted(corrections, key=lambda c: c.id or 0):
        if c.action == "add":
            boxes[f"c{c.id}"] = {"id": f"c{c.id}", "class_name": c.class_name, "category": category_of(c.class_name),
                                 "confidence": 1.0, "bbox": c.bbox, "source": "scout"}
        elif c.action == "remove":
            boxes.pop(c.target, None)
        elif c.action == "relabel" and c.target in boxes:
            b = dict(boxes[c.target])
            b.update(relabelled_from=b.get("relabelled_from", b["class_name"]), class_name=c.class_name,
                     category=category_of(c.class_name), confidence=1.0, source="scout")
            boxes[c.target] = b
    return list(boxes.values())


def count(boxes: list[dict]) -> tuple[dict, int, int]:
    counts = {n: 0 for n in class_names()}
    for b in boxes:
        counts[b["class_name"]] = counts.get(b["class_name"], 0) + 1
    pests = sum(1 for b in boxes if b["category"] == "pest")
    predators = sum(1 for b in boxes if b["category"] == "predator")
    return counts, pests, predators


# ---------------------------------------------------------------------------
# Database part
# ---------------------------------------------------------------------------
def corrections_for(session: Session, section_id: int) -> list[Correction]:
    return list(session.exec(select(Correction).where(Correction.section_id == section_id)
                             .order_by(Correction.id)).all())


def image_size(section: TapeSection) -> tuple[int, int]:
    m = section.quality_metrics or {}
    if m.get("width") and m.get("height"):
        return int(m["width"]), int(m["height"])
    img = cv2.imread(str(settings.media_dir() / section.image_path))
    return (img.shape[1], img.shape[0]) if img is not None else (0, 0)


def section_detail(session: Session, section: TapeSection) -> dict:
    corr = corrections_for(session, section.id)
    w, h = image_size(section)
    return {**services.section_to_dict(section), "image_width": w, "image_height": h,
            "boxes": apply_corrections(section.detections, corr),
            "corrections": [{"id": c.id, "action": c.action, "class_name": c.class_name, "bbox": c.bbox,
                             "target": c.target, "author": c.author,
                             "created_at": c.created_at.isoformat(timespec="seconds")} for c in corr]}


def _recompute(session: Session, section: TapeSection) -> dict:
    corr = corrections_for(session, section.id)
    if corr:
        counts, pests, predators = count(apply_corrections(section.detections, corr))
        section.corrected_counts, section.corrected_pest_total, section.corrected_predator_total = \
            counts, pests, predators
    else:   # all edits undone: back to the model's counts
        section.corrected_counts = section.corrected_pest_total = section.corrected_predator_total = None
    session.add(section)
    session.commit()
    session.refresh(section)
    trap = session.get(Trap, section.trap_id)
    return services.update_decision(session, trap)      # the decision uses the corrected counts now


def add_correction(session: Session, section: TapeSection, action: str, target: str | None = None,
                   class_name: str | None = None, bbox: list | None = None, author: str = "scout") -> dict:
    if action not in ACTIONS:
        raise CorrectionError(f"action must be one of {ACTIONS}")
    current = {b["id"]: b for b in apply_corrections(section.detections, corrections_for(session, section.id))}
    if action in ("add", "relabel") and class_name not in class_names():
        raise CorrectionError(f"class_name must be one of {class_names()}")
    if action in ("remove", "relabel") and target not in current:
        raise CorrectionError(f"no box '{target}' on this photo")
    if action == "add":
        w, h = image_size(section)
        if not bbox or len(bbox) != 4:
            raise CorrectionError("bbox must be [x1, y1, x2, y2]")
        x1, y1, x2, y2 = (float(v) for v in bbox)
        x1, x2 = sorted((max(0.0, x1), min(float(w), x2)))
        y1, y2 = sorted((max(0.0, y1), min(float(h), y2)))
        if x2 - x1 < 2 or y2 - y1 < 2:
            raise CorrectionError("the box is too small or outside the photo")
        bbox = [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)]
    else:
        bbox = current[target]["bbox"]
    if action == "relabel" and current[target]["class_name"] == class_name:
        raise CorrectionError("the box already has this class")
    session.add(Correction(section_id=section.id, action=action, target=target if action != "add" else None,
                           class_name=class_name if action != "remove" else current[target]["class_name"],
                           bbox=bbox, author=author))
    session.commit()
    decision = _recompute(session, section)
    return {"section": section_detail(session, section), "decision": decision}


def undo(session: Session, correction: Correction) -> dict:
    section = session.get(TapeSection, correction.section_id)
    session.delete(correction)
    session.commit()
    decision = _recompute(session, section)
    return {"section": section_detail(session, section), "decision": decision}


# ---------------------------------------------------------------------------
# Model page numbers - MEASURED on the captures scouts corrected
# ---------------------------------------------------------------------------
def stats(session: Session) -> dict:
    total = len(session.exec(select(TapeSection.id)).all())
    corrected = session.exec(select(TapeSection).where(TapeSection.corrected_pest_total.is_not(None))).all()
    n = len(corrected)
    if n == 0:
        return {"captures": total, "corrected_captures": 0, "correction_rate": 0.0, "pest_mae": None,
                "predator_mae": None, "per_class_mae": {},
                "label": "no corrected captures yet"}
    per_class = {c: round(float(np.mean([abs((s.counts or {}).get(c, 0) - (s.corrected_counts or {}).get(c, 0))
                                         for s in corrected])), 2) for c in class_names()}
    return {
        "captures": total, "corrected_captures": n, "correction_rate": round(n / total, 3) if total else 0.0,
        "pest_mae": round(float(np.mean([abs(s.pest_total - s.corrected_pest_total) for s in corrected])), 2),
        "predator_mae": round(float(np.mean([abs(s.predator_total - s.corrected_predator_total) for s in corrected])), 2),
        "per_class_mae": per_class,
        "simulated_captures": sum(1 for s in corrected if s.simulated),
        "label": f"based on {n} corrected capture{'s' if n != 1 else ''}",
    }


# ---------------------------------------------------------------------------
# Export for retraining: YOLO labels from the corrected boxes
# ---------------------------------------------------------------------------
def yolo_lines(boxes: list[dict], width: int, height: int) -> list[str]:
    names = class_names()
    out = []
    for b in boxes:
        if b["class_name"] not in names:
            continue
        x1, y1, x2, y2 = b["bbox"]
        out.append(f"{names.index(b['class_name'])} {(x1 + x2) / 2 / width:.6f} {(y1 + y2) / 2 / height:.6f} "
                   f"{(x2 - x1) / width:.6f} {(y2 - y1) / height:.6f}")
    return out


def export_zip(session: Session) -> tuple[bytes, int]:
    """images/ + labels/ (YOLO) + data.yaml for every corrected capture. Returns (zip bytes, captures)."""
    sections = session.exec(select(TapeSection).where(TapeSection.corrected_pest_total.is_not(None))
                            .order_by(TapeSection.id)).all()
    buf = io.BytesIO()
    manifest = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for s in sections:
            img_path = settings.media_dir() / s.image_path
            if not img_path.exists():
                continue
            w, h = image_size(s)
            boxes = apply_corrections(s.detections, corrections_for(session, s.id))
            name = f"{s.trap_id}_{s.id}"
            z.write(img_path, f"images/{name}.jpg")
            z.writestr(f"labels/{name}.txt", "\n".join(yolo_lines(boxes, w, h)) + ("\n" if boxes else ""))
            manifest.append({"file": f"{name}.jpg", "section_id": s.id, "trap_id": s.trap_id, "simulated": s.simulated,
                             "model_counts": s.counts, "corrected_counts": s.corrected_counts})
        z.writestr("data.yaml", yaml.safe_dump({"path": ".", "train": "images", "val": "images",
                                                "names": {i: n for i, n in enumerate(class_names())}},
                                               sort_keys=False))
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("README.txt",
                   "KeetaSense scout corrections - YOLO format (class x_center y_center width height, 0-1).\n"
                   f"Exported {datetime.now():%Y-%m-%d %H:%M}. Class ids follow config/pests.yaml.\n"
                   "Captures marked simulated=true in manifest.json are SYNTHETIC images - do not train on them.\n"
                   "Use: unzip into ml/data/, merge with the training split, retrain on Colab.\n")
    return buf.getvalue(), len(manifest)

"""SYNTHETIC sticky-tape image generator.

!!! These images are FAKE. They exist only to test that the software
!!! pipeline (convert -> train -> evaluate -> infer -> backend -> dashboard)
!!! runs end to end without the real dataset. Metrics measured on them say
!!! NOTHING about how well KeetaSense detects real insects.

Each image is a yellow "sticky tape" with a printed grid, uneven LED lighting,
dust specks, and dark insect-like blobs in three shapes (from pests.yaml):
  round -> small round blob        (stands in for a whitefly)
  stout -> body ~2.5x longer than wide, with legs (stands in for Macrolophus)
  slim  -> long thin body with legs                (stands in for Nesidiocoris)

Usage (writes Pascal VOC XML, exactly like a raw dataset would arrive):
    python -m ml.synthetic --n 80 --out ml/data/synthetic_raw
"""
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path
from xml.etree import ElementTree as ET

import cv2
import numpy as np

from ml.common import ROOT, get_classes

# Size ranges in pixels for each shape: body length range and width/length ratio
SHAPE_SIZES = {
    "round": {"length": (10, 15), "width_ratio": (0.75, 1.0)},
    "stout": {"length": (30, 38), "width_ratio": (0.34, 0.42)},
    "slim":  {"length": (36, 46), "width_ratio": (0.14, 0.19)},
}

YELLOW_BGR = np.array([30, 215, 235], dtype=np.float32)  # sticky-trap yellow


def _background(width: int, height: int, rng: np.random.Generator) -> np.ndarray:
    """Yellow tape with noise, a lighting gradient, a printed grid and dust."""
    img = np.ones((height, width, 3), np.float32) * YELLOW_BGR
    # uneven LED lighting: brighter in the middle, darker at the edges
    yy, xx = np.mgrid[0:height, 0:width]
    cx, cy = width * rng.uniform(0.4, 0.6), height * rng.uniform(0.4, 0.6)
    dist = np.sqrt(((xx - cx) / width) ** 2 + ((yy - cy) / height) ** 2)
    img *= (1.05 - 0.25 * dist)[..., None]
    img += rng.normal(0, 5, img.shape)  # sensor noise
    img = np.clip(img, 0, 255).astype(np.uint8)

    # printed grid (thin, medium-dark lines - like real sticky traps)
    step = int(rng.integers(90, 130))
    grid_color = (50, 165, 185)
    for x in range(int(rng.integers(0, step)), width, step):
        cv2.line(img, (x, 0), (x, height - 1), grid_color, 1)
    for y in range(int(rng.integers(0, step)), height, step):
        cv2.line(img, (0, y), (width - 1, y), grid_color, 1)

    # dust specks: tiny dark dots that a counter must NOT count as insects
    for _ in range(int(rng.integers(10, 40))):
        p = (int(rng.integers(0, width)), int(rng.integers(0, height)))
        cv2.circle(img, p, 1, (40, 90, 100), -1)
    return img


def _draw_insect(img: np.ndarray, shape: str, cx: float, cy: float,
                 length: float, width: float, angle_deg: float,
                 rng: np.random.Generator) -> None:
    """Draw one insect body (dark ellipse) plus faint legs for elongated shapes."""
    dark = int(rng.integers(15, 55))
    body_color = (dark, dark + 10, dark + 20)
    center = (int(round(cx)), int(round(cy)))
    axes = (max(1, int(length / 2)), max(1, int(width / 2)))

    if shape in ("stout", "slim"):
        # six faint legs - lighter than the body so they do not change the box
        leg_color = (60, 120, 135)
        a = math.radians(angle_deg)
        ux, uy = math.cos(a), math.sin(a)          # along the body
        px, py = -uy, ux                           # across the body
        for t in (-0.25, 0.0, 0.25):
            bx, by = cx + ux * t * length, cy + uy * t * length
            for side in (-1, 1):
                ex = bx + side * px * width * 1.3 + ux * t * length * 0.4
                ey = by + side * py * width * 1.3 + uy * t * length * 0.4
                cv2.line(img, (int(bx), int(by)), (int(ex), int(ey)), leg_color, 1)

    cv2.ellipse(img, center, axes, angle_deg, 0, 360, body_color, -1, cv2.LINE_AA)
    if shape == "round":
        # pale wing highlight in the centre (whiteflies look pale-winged)
        cv2.ellipse(img, center, (max(1, axes[0] // 3), max(1, axes[1] // 3)),
                    angle_deg, 0, 360, (dark + 40, dark + 50, dark + 55), -1)


def _rotated_box(cx, cy, length, width, angle_deg, margin=2):
    """Axis-aligned bounding box of a rotated ellipse."""
    a = math.radians(angle_deg)
    half_l, half_w = length / 2, width / 2
    hx = math.sqrt((half_l * math.cos(a)) ** 2 + (half_w * math.sin(a)) ** 2) + margin
    hy = math.sqrt((half_l * math.sin(a)) ** 2 + (half_w * math.cos(a)) ** 2) + margin
    return cx - hx, cy - hy, cx + hx, cy + hy


def render_tape(counts: dict[str, int], width: int = 640, height: int = 640,
                seed: int | None = None) -> tuple[np.ndarray, list[tuple]]:
    """Render one synthetic tape section.

    counts: how many insects of each class name to draw, e.g. {"whitefly": 20}
    Returns (BGR image, list of (class_name, x1, y1, x2, y2) boxes).
    """
    rng = np.random.default_rng(seed)
    img = _background(width, height, rng)
    shapes = {c.name: c.synthetic_shape for c in get_classes()}

    placed: list[tuple[float, float, float]] = []  # (cx, cy, radius) for overlap checks
    boxes = []
    for name, n in counts.items():
        shape = shapes[name]
        sizes = SHAPE_SIZES[shape]
        for _ in range(int(n)):
            length = rng.uniform(*sizes["length"])
            body_w = length * rng.uniform(*sizes["width_ratio"])
            angle = rng.uniform(0, 180)
            radius = length / 2 + 6
            for _attempt in range(50):  # find a free spot (no overlapping insects)
                cx = rng.uniform(radius, img.shape[1] - radius)
                cy = rng.uniform(radius, img.shape[0] - radius)
                if all(math.hypot(cx - x, cy - y) > radius + r for x, y, r in placed):
                    break
            else:
                continue  # trap too crowded - skip this insect
            placed.append((cx, cy, radius))
            _draw_insect(img, shape, cx, cy, length, body_w, angle, rng)
            x1, y1, x2, y2 = _rotated_box(cx, cy, length, body_w, angle)
            boxes.append((name, max(0, x1), max(0, y1),
                          min(img.shape[1] - 1, x2), min(img.shape[0] - 1, y2)))

    img = cv2.GaussianBlur(img, (3, 3), 0)  # slight camera softness
    return img, boxes


def write_voc_xml(path: Path, image_name: str, width: int, height: int,
                  boxes: list[tuple], label_for: dict[str, str]) -> None:
    """Save boxes as a Pascal VOC XML file (same format as many raw datasets)."""
    root = ET.Element("annotation")
    ET.SubElement(root, "filename").text = image_name
    ET.SubElement(root, "source").text = "KeetaSense SYNTHETIC generator - not real insects"
    size = ET.SubElement(root, "size")
    ET.SubElement(size, "width").text = str(width)
    ET.SubElement(size, "height").text = str(height)
    ET.SubElement(size, "depth").text = "3"
    for name, x1, y1, x2, y2 in boxes:
        obj = ET.SubElement(root, "object")
        ET.SubElement(obj, "name").text = label_for[name]
        bb = ET.SubElement(obj, "bndbox")
        for tag, v in zip(("xmin", "ymin", "xmax", "ymax"), (x1, y1, x2, y2)):
            ET.SubElement(bb, tag).text = str(int(round(v)))
    ET.ElementTree(root).write(path, encoding="utf-8")


def random_counts(rng: random.Random) -> dict[str, int]:
    """Random insect counts: many pests, a few predators (like real traps)."""
    counts = {}
    for c in get_classes():
        counts[c.name] = rng.randint(5, 40) if c.category == "pest" else rng.randint(0, 6)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate SYNTHETIC sticky-trap images (VOC XML labels).")
    ap.add_argument("--n", type=int, default=80, help="number of images")
    ap.add_argument("--out", default=str(ROOT / "ml/data/synthetic_raw"))
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=640)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "README_SYNTHETIC.txt").write_text(
        "SYNTHETIC test data generated by ml/synthetic.py.\n"
        "These are NOT real insects. Use only to test the software pipeline.\n",
        encoding="utf-8")
    # write labels using the first alias (e.g. "WF") to exercise alias mapping
    label_for = {c.name: (c.aliases[0] if c.aliases else c.name) for c in get_classes()}
    rng = random.Random(args.seed)
    for i in range(1, args.n + 1):
        img, boxes = render_tape(random_counts(rng), args.width, args.height, seed=args.seed + i)
        name = f"synthetic_{i:04d}.jpg"
        cv2.imwrite(str(out / name), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        write_voc_xml(out / f"synthetic_{i:04d}.xml", name, args.width, args.height, boxes, label_for)
    print(f"[synthetic] wrote {args.n} SYNTHETIC images + VOC XML labels to {out}")


if __name__ == "__main__":
    main()

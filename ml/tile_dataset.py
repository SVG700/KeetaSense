"""TILE-BASED training mode: cut high-resolution images + labels into overlapping tiles.

Why: real sticky-trap photos are huge (e.g. 5184 x 3456) and a whitefly is
only ~15-25 pixels. If YOLO trained on the whole photo shrunk to 640 px, a
whitefly would become 2-3 pixels and disappear. Instead we train on 640 px
tiles cut from the full-resolution photo - and at prediction time SAHI cuts
the photo into the same kind of tiles. Training and inference then "see"
insects at the same size.

How boxes are handled:
  - A box that lies fully inside a tile is copied as is.
  - A box cut by the tile edge is CLIPPED to the tile, and kept only if at
    least --min-visible (default 50 %) of its area is inside the tile.
    (With overlap, the insect appears whole in a neighbouring tile anyway.)
  - Tiles with no insects are mostly dropped: only --keep-empty (default 10 %)
    are kept, so the model still sees some plain tape and learns "no insect".

Only train and val are tiled. The test split stays full size, because
evaluate.py runs the real SAHI pipeline on whole images.

Usage:
    python -m ml.tile_dataset --data ml/data/yolo --out ml/data/yolo_tiles --tile 640 --overlap 0.2
"""
from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

import cv2
import yaml

from ml.common import ROOT


def tile_positions(length: int, tile: int, step: int) -> list[int]:
    """Start positions so tiles cover the whole length (last tile flush with the edge)."""
    if length <= tile:
        return [0]
    pos = list(range(0, length - tile, step))
    pos.append(length - tile)
    return pos


def clip_boxes_to_tile(boxes: list[tuple], tx: int, ty: int, tw: int, th: int,
                       min_visible: float = 0.5) -> list[tuple]:
    """Boxes (cls, x1, y1, x2, y2 in image pixels) -> boxes in tile pixels.

    Keeps a box if at least `min_visible` of its area lies inside the tile; clips it to the tile.
    """
    out = []
    for c, x1, y1, x2, y2 in boxes:
        ix1, iy1 = max(x1, tx), max(y1, ty)
        ix2, iy2 = min(x2, tx + tw), min(y2, ty + th)
        if ix2 <= ix1 or iy2 <= iy1:
            continue  # not in this tile
        area = (x2 - x1) * (y2 - y1)
        visible = (ix2 - ix1) * (iy2 - iy1)
        if area <= 0 or visible / area < min_visible:
            continue
        out.append((c, ix1 - tx, iy1 - ty, ix2 - tx, iy2 - ty))
    return out


def to_yolo_lines(boxes: list[tuple], tw: int, th: int) -> list[str]:
    return [f"{c} {(x1 + x2) / 2 / tw:.6f} {(y1 + y2) / 2 / th:.6f} {(x2 - x1) / tw:.6f} {(y2 - y1) / th:.6f}\n"
            for c, x1, y1, x2, y2 in boxes]


def read_yolo_boxes(label_file: Path, w: int, h: int) -> list[tuple]:
    boxes = []
    if label_file.exists():
        for line in label_file.read_text().splitlines():
            parts = line.split()
            if len(parts) != 5:
                continue
            c, xc, yc, bw, bh = int(parts[0]), *(float(v) for v in parts[1:])
            xc, yc, bw, bh = xc * w, yc * h, bw * w, bh * h
            boxes.append((c, xc - bw / 2, yc - bh / 2, xc + bw / 2, yc + bh / 2))
    return boxes


def tile_split(src: Path, dst: Path, split: str, tile: int, overlap: float,
               min_visible: float = 0.5, keep_empty: float = 0.1, seed: int = 42) -> dict:
    """Tile one split. Returns counts of tiles written / empty tiles dropped / boxes."""
    img_dir, lbl_dir = src / "images" / split, src / "labels" / split
    out_img, out_lbl = dst / "images" / split, dst / "labels" / split
    out_img.mkdir(parents=True, exist_ok=True)
    out_lbl.mkdir(parents=True, exist_ok=True)
    step = max(1, int(tile * (1 - overlap)))
    rng = random.Random(seed)
    stats = {"tiles": 0, "empty_kept": 0, "empty_dropped": 0, "boxes": 0}

    for img_path in sorted(img_dir.iterdir()):
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        h, w = img.shape[:2]
        boxes = read_yolo_boxes(lbl_dir / (img_path.stem + ".txt"), w, h)
        for ty in tile_positions(h, tile, step):
            for tx in tile_positions(w, tile, step):
                th, tw = min(tile, h), min(tile, w)
                tile_boxes = clip_boxes_to_tile(boxes, tx, ty, tw, th, min_visible)
                if not tile_boxes:
                    if rng.random() >= keep_empty:
                        stats["empty_dropped"] += 1
                        continue
                    stats["empty_kept"] += 1
                name = f"{img_path.stem}_x{tx}_y{ty}"
                cv2.imwrite(str(out_img / f"{name}.jpg"), img[ty:ty + th, tx:tx + tw], [cv2.IMWRITE_JPEG_QUALITY, 95])
                (out_lbl / f"{name}.txt").write_text("".join(to_yolo_lines(tile_boxes, tw, th)))
                stats["tiles"] += 1
                stats["boxes"] += len(tile_boxes)
    return stats


def build_tiled_dataset(src: Path, dst: Path, tile: int = 640, overlap: float = 0.2,
                        min_visible: float = 0.5, keep_empty: float = 0.1) -> Path:
    if dst.exists():
        shutil.rmtree(dst)
    for split in ("train", "val"):
        stats = tile_split(src, dst, split, tile, overlap, min_visible, keep_empty)
        print(f"[tile] {split}: {stats['tiles']} tiles ({stats['boxes']} boxes), "
              f"empty tiles kept {stats['empty_kept']}, dropped {stats['empty_dropped']}")
    data = yaml.safe_load((src / "data.yaml").read_text())
    data["path"] = str(dst.resolve()).replace("\\", "/")
    # test stays full-size: point it back at the source dataset
    data["test"] = str((src / "images" / "test").resolve()).replace("\\", "/")
    (dst / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    (dst / "tiling.yaml").write_text(yaml.safe_dump(
        {"tile": tile, "overlap": overlap, "min_visible": min_visible, "keep_empty": keep_empty,
         "source": str(src)}, sort_keys=False))
    print(f"[tile] done -> {dst / 'data.yaml'}")
    return dst / "data.yaml"


def main() -> None:
    ap = argparse.ArgumentParser(description="Tile a YOLO dataset for small-object training.")
    ap.add_argument("--data", default=str(ROOT / "ml/data/yolo"), help="folder with data.yaml")
    ap.add_argument("--out", default=str(ROOT / "ml/data/yolo_tiles"))
    ap.add_argument("--tile", type=int, default=640, help="tile size in pixels")
    ap.add_argument("--overlap", type=float, default=0.2, help="overlap between tiles (0-0.9)")
    ap.add_argument("--min-visible", type=float, default=0.5, help="keep a cut box if this fraction is inside")
    ap.add_argument("--keep-empty", type=float, default=0.1, help="fraction of empty tiles to keep")
    args = ap.parse_args()
    src = Path(args.data)
    if not (src / "data.yaml").exists():
        print(f"[tile] {src / 'data.yaml'} not found. Run python -m ml.convert_dataset first.")
        return
    if not 0 <= args.overlap < 0.9:
        raise SystemExit("--overlap must be between 0 and 0.9")
    build_tiled_dataset(src, Path(args.out), args.tile, args.overlap, args.min_visible, args.keep_empty)


if __name__ == "__main__":
    main()

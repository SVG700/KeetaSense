"""Cut a YOLO dataset into overlapping tiles for training on tiny insects.

Why: real sticky-trap photos are huge (e.g. 5184 x 3456) and a whitefly is
only ~15-25 pixels. If YOLO trained on the whole photo shrunk to 640 px, a
whitefly would become 2-3 pixels and disappear. Instead we train on 640 px
tiles cut from the full-resolution photo - and at prediction time SAHI cuts
the photo into the same kind of tiles. Training and inference then "see"
insects at the same size.

Only train and val are tiled. The test split stays full size, because
evaluate.py runs the real SAHI pipeline on whole images.

Usage:
    python -m ml.tile_dataset --data ml/data/yolo --out ml/data/yolo_tiles --tile 640 --overlap 0.2
"""
from __future__ import annotations

import argparse
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


def tile_split(src: Path, dst: Path, split: str, tile: int, overlap: float,
               keep_empty_every: int = 5) -> tuple[int, int]:
    """Tile one split. Keeps every Nth empty tile (background examples)."""
    img_dir, lbl_dir = src / "images" / split, src / "labels" / split
    out_img, out_lbl = dst / "images" / split, dst / "labels" / split
    out_img.mkdir(parents=True, exist_ok=True)
    out_lbl.mkdir(parents=True, exist_ok=True)
    step = max(1, int(tile * (1 - overlap)))
    n_tiles = n_empty_seen = 0

    for img_path in sorted(img_dir.iterdir()):
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        h, w = img.shape[:2]
        boxes = []  # pixel boxes: (cls, x1, y1, x2, y2)
        lbl = lbl_dir / (img_path.stem + ".txt")
        if lbl.exists():
            for line in lbl.read_text().splitlines():
                c, xc, yc, bw, bh = line.split()
                xc, yc, bw, bh = float(xc) * w, float(yc) * h, float(bw) * w, float(bh) * h
                boxes.append((int(c), xc - bw / 2, yc - bh / 2, xc + bw / 2, yc + bh / 2))

        for ty in tile_positions(h, tile, step):
            for tx in tile_positions(w, tile, step):
                th, tw = min(tile, h), min(tile, w)
                lines = []
                for c, x1, y1, x2, y2 in boxes:
                    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                    if not (tx <= cx < tx + tw and ty <= cy < ty + th):
                        continue  # a box belongs to the tile containing its centre
                    nx1, ny1 = max(x1, tx) - tx, max(y1, ty) - ty
                    nx2, ny2 = min(x2, tx + tw) - tx, min(y2, ty + th) - ty
                    lines.append(f"{c} {(nx1 + nx2) / 2 / tw:.6f} {(ny1 + ny2) / 2 / th:.6f} "
                                 f"{(nx2 - nx1) / tw:.6f} {(ny2 - ny1) / th:.6f}\n")
                if not lines:
                    n_empty_seen += 1
                    if n_empty_seen % keep_empty_every:
                        continue
                name = f"{img_path.stem}_x{tx}_y{ty}"
                cv2.imwrite(str(out_img / f"{name}.jpg"), img[ty:ty + th, tx:tx + tw])
                (out_lbl / f"{name}.txt").write_text("".join(lines))
                n_tiles += 1
    return n_tiles, n_empty_seen


def main() -> None:
    ap = argparse.ArgumentParser(description="Tile a YOLO dataset for small-object training.")
    ap.add_argument("--data", default=str(ROOT / "ml/data/yolo"), help="folder with data.yaml")
    ap.add_argument("--out", default=str(ROOT / "ml/data/yolo_tiles"))
    ap.add_argument("--tile", type=int, default=640)
    ap.add_argument("--overlap", type=float, default=0.2)
    args = ap.parse_args()
    src, dst = Path(args.data), Path(args.out)
    if not (src / "data.yaml").exists():
        print(f"[tile] {src / 'data.yaml'} not found. Run python -m ml.convert_dataset first.")
        return
    if dst.exists():
        shutil.rmtree(dst)
    for split in ("train", "val"):
        n, _ = tile_split(src, dst, split, args.tile, args.overlap)
        print(f"[tile] {split}: {n} tiles")
    data = yaml.safe_load((src / "data.yaml").read_text())
    data["path"] = str(dst.resolve()).replace("\\", "/")
    # test stays full-size: point it back at the source dataset
    data["test"] = str((src / "images" / "test").resolve()).replace("\\", "/")
    (dst / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    print(f"[tile] done -> {dst / 'data.yaml'}")


if __name__ == "__main__":
    main()

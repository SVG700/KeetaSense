"""Tests for real-dataset readiness: 4TU download helper, dataset summary, tiling,
augmentations, per-class confidence thresholds, model packaging."""
import json
import zipfile

import cv2
import pytest
import yaml

from ml import convert_dataset, download_4tu, infer, install_model, package_model, tile_dataset
from ml.dataset_summary import summarise, to_markdown
from ml.synthetic import render_tape, write_voc_xml

LABELS = {"whitefly": "WF", "macrolophus": "MR", "nesidiocoris": "NC"}


def make_raw(folder, n=10, size=320):
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        img, boxes = render_tape({"whitefly": 6, "macrolophus": 1, "nesidiocoris": 1}, size, size, seed=i)
        cv2.imwrite(str(folder / f"img_{i}.jpg"), img)
        write_voc_xml(folder / f"img_{i}.xml", f"img_{i}.jpg", size, size, boxes, LABELS)


# --- 4TU helper --------------------------------------------------------------
def test_4tu_extracts_zip_and_counts_files(tmp_path):
    src = tmp_path / "src"
    make_raw(src, n=3)
    raw = tmp_path / "raw"
    raw.mkdir()
    with zipfile.ZipFile(raw / "my_download.zip", "w") as z:
        for p in src.iterdir():
            z.write(p, f"data/{p.name}")
    messages = download_4tu.extract_all(raw)
    assert any("extracted 6 files" in m for m in messages)
    counts = download_4tu.count_files(raw)
    assert counts["images"] == 3 and counts["xml"] == 3
    assert download_4tu.extract_all(raw) == []          # marker file: not extracted twice


def test_4tu_rejects_incomplete_data_zip(tmp_path):
    bad = tmp_path / "data.zip"
    bad.write_bytes(b"too small")
    ok, msg = download_4tu.verify_archive(bad)
    assert not ok and "incomplete" in msg


def test_4tu_refuses_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        download_4tu._safe_target(tmp_path, "../evil.txt")


# --- dataset summary -----------------------------------------------------------
def test_dataset_summary_reports_classes_sizes_and_warnings(tmp_path):
    make_raw(tmp_path / "raw", n=20)
    convert_dataset.convert(tmp_path / "raw", tmp_path / "yolo", seed=1)
    s = summarise(tmp_path / "yolo")
    assert s["images_total"] == 20
    assert s["classes"]["whitefly"]["objects"] == 120
    assert s["resolution"]["width_max"] == 320
    assert 10 < s["classes"]["whitefly"]["size_px_median"] < 25
    assert s["raw_labels"]["WF"]["mapped_to"] == "whitefly"
    # 20 macrolophus examples is far below the minimum -> flagged
    assert any("macrolophus" in w and "only 20 examples" in w for w in s["warnings"])
    md = to_markdown(s)
    assert "| whitefly | 120 |" in md and "Warnings" in md


# --- tiling --------------------------------------------------------------------
def test_clip_box_inside_cut_and_mostly_outside():
    boxes = [(0, 10, 10, 30, 30),       # fully inside tile (0,0,100,100)
             (1, 90, 10, 110, 30),      # half inside -> kept and clipped
             (2, 95, 10, 115, 30)]      # only 25 % inside -> dropped
    out = tile_dataset.clip_boxes_to_tile(boxes, 0, 0, 100, 100, min_visible=0.5)
    assert out == [(0, 10, 10, 30, 30), (1, 90, 10, 100, 30)]
    # coordinates are relative to the tile origin
    assert tile_dataset.clip_boxes_to_tile([(0, 110, 110, 120, 120)], 100, 100, 100, 100) == [(0, 10, 10, 20, 20)]


def test_tile_positions_cover_whole_image():
    pos = tile_dataset.tile_positions(1000, 400, 320)
    assert pos[0] == 0 and pos[-1] == 600
    assert tile_dataset.tile_positions(300, 640, 512) == [0]


def test_tiled_dataset_keeps_boxes_and_drops_empty_tiles(tmp_path):
    make_raw(tmp_path / "raw", n=10, size=640)
    convert_dataset.convert(tmp_path / "raw", tmp_path / "yolo", seed=1)
    data_yaml = tile_dataset.build_tiled_dataset(tmp_path / "yolo", tmp_path / "tiles", tile=320,
                                                 overlap=0.25, keep_empty=0.0)
    labels = list((tmp_path / "tiles/labels/train").glob("*.txt"))
    assert labels and all(f.read_text().strip() for f in labels)      # no empty tiles kept
    for f in labels:
        for line in f.read_text().splitlines():
            vals = [float(v) for v in line.split()[1:]]
            assert all(0 <= v <= 1 for v in vals)
    data = yaml.safe_load(data_yaml.read_text())
    assert data["test"].endswith("yolo/images/test")                   # test stays full size
    assert (tmp_path / "tiles/tiling.yaml").exists()


# --- augmentation + per-class thresholds ------------------------------------------
def test_camera_augmentation_profile():
    from ml.train import build_albumentations
    names = [type(a).__name__ for a in build_albumentations("camera")]
    for expected in ("ColorJitter", "Blur", "ImageCompression", "Perspective", "GaussNoise"):
        assert expected in names
    assert "Perspective" not in [type(a).__name__ for a in build_albumentations("basic")]


def test_per_class_confidence_thresholds():
    dets = [{"class_name": "whitefly", "confidence": 0.3}, {"class_name": "whitefly", "confidence": 0.2},
            {"class_name": "macrolophus", "confidence": 0.5}, {"class_name": "macrolophus", "confidence": 0.7}]
    kept = infer.apply_class_thresholds(dets, {"whitefly": 0.25, "macrolophus": 0.6}, 0.25)
    assert [d["confidence"] for d in kept] == [0.3, 0.7]
    th = infer.class_conf_thresholds(0.4)
    assert set(th) == {"whitefly", "macrolophus", "nesidiocoris"}


# --- packaging round trip ---------------------------------------------------------
def test_package_and_install_round_trip(tmp_path, monkeypatch):
    weights = tmp_path / "w" / "best.pt"
    weights.parent.mkdir()
    weights.write_bytes(b"fake-weights")
    weights.with_suffix(".json").write_text(json.dumps({"weights": "best.pt", "trained_at": "2026-11-02T10:00:00",
                                                        "classes": ["whitefly", "macrolophus", "nesidiocoris"]}))
    zip_path = package_model.package(weights, None, None, tmp_path / "exports")
    with zipfile.ZipFile(zip_path) as z:
        assert {"weights/best.pt", "weights/best.json", "config_used/pests.yaml"} <= set(z.namelist())
    result = install_model.install(zip_path, root=tmp_path / "laptop")
    assert (tmp_path / "laptop/ml/weights/best.pt").read_bytes() == b"fake-weights"
    assert result["warnings"] == []

"""Tests for the ML pipeline pieces that do not need a trained model.

Run from the project root:  python -m pytest ml/tests
"""
import xml.etree.ElementTree as ET
from collections import Counter

import cv2
import yaml

from ml import convert_dataset, evaluate, infer
from ml.common import category_of, class_names, resolve_alias
from ml.synthetic import render_tape, write_voc_xml


def test_aliases_map_to_categories():
    assert resolve_alias("WF") == "whitefly"
    assert resolve_alias("mr") == "macrolophus"
    assert resolve_alias("something-else") is None
    assert category_of("whitefly") == "pest"
    assert category_of("NC") == "predator"
    assert category_of("unknown-bug") == "unknown"


def _make_voc_dataset(folder, n=10):
    label_for = {"whitefly": "WF", "macrolophus": "MR", "nesidiocoris": "NC"}
    for i in range(n):
        img, boxes = render_tape({"whitefly": 5, "macrolophus": 1, "nesidiocoris": 1}, 320, 320, seed=i)
        cv2.imwrite(str(folder / f"img_{i}.jpg"), img)
        write_voc_xml(folder / f"img_{i}.xml", f"img_{i}.jpg", 320, 320, boxes, label_for)


def test_convert_voc_creates_70_15_15_split(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "yolo"
    raw.mkdir()
    _make_voc_dataset(raw, n=20)
    summary = convert_dataset.convert(raw, out, seed=1)
    assert summary["format"] == "voc"
    sizes = {k: v["images"] for k, v in summary["splits"].items()}
    assert sizes == {"train": 14, "val": 3, "test": 3}
    data = yaml.safe_load((out / "data.yaml").read_text())
    assert list(data["names"].values()) == class_names()
    # every label line is "class x y w h" with values in 0..1
    for f in (out / "labels" / "train").glob("*.txt"):
        for line in f.read_text().splitlines():
            c, *vals = line.split()
            assert int(c) in range(len(class_names()))
            assert all(0 <= float(v) <= 1 for v in vals)


def test_split_is_reproducible(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    _make_voc_dataset(raw, n=12)
    a = convert_dataset.convert(raw, tmp_path / "a", seed=7)
    b = convert_dataset.convert(raw, tmp_path / "b", seed=7)
    assert sorted(p.name for p in (tmp_path / "a/images/test").iterdir()) == \
           sorted(p.name for p in (tmp_path / "b/images/test").iterdir())
    assert a["splits"] == b["splits"]


def test_convert_yolo_txt_format(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "classes.txt").write_text("WF\nMR\nNC\n")
    for i in range(5):
        cv2.imwrite(str(raw / f"y_{i}.jpg"), render_tape({"whitefly": 1}, 100, 100, seed=i)[0])
        (raw / f"y_{i}.txt").write_text("0 0.5 0.5 0.1 0.1\n1 0.2 0.2 0.1 0.1\n")
    summary = convert_dataset.convert(raw, tmp_path / "out", seed=1)
    assert summary["format"] == "yolo"
    total = Counter()
    for s in summary["splits"].values():
        total.update(s["objects"])
    assert total == {"whitefly": 5, "macrolophus": 5}


def test_empty_raw_folder_exits_cleanly(tmp_path, capsys):
    assert convert_dataset.convert(tmp_path, tmp_path / "out") is None
    assert "download" in capsys.readouterr().out.lower()


def test_demo_detector_counts_synthetic_image(monkeypatch, tmp_path):
    monkeypatch.setenv("KEETA_WEIGHTS", str(tmp_path / "missing.pt"))
    infer.reset_detector()
    img, boxes = render_tape({"whitefly": 12, "macrolophus": 2, "nesidiocoris": 3}, 640, 640, seed=3)
    r = infer.detect(img)
    assert r.mode == infer.MODE_DEMO and "DEMO DETECTOR" in r.warning
    truth = Counter(b[0] for b in boxes)
    assert r.counts == dict(truth)
    assert r.pest_total == truth["whitefly"]
    assert r.predator_total == truth["macrolophus"] + truth["nesidiocoris"]
    assert r.annotated_image.shape == img.shape
    infer.reset_detector()


def test_average_precision_perfect_and_iou():
    import numpy as np
    assert evaluate.average_precision(np.array([0.5, 1.0]), np.array([1.0, 1.0])) == 1.0
    assert evaluate.iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert evaluate.iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0

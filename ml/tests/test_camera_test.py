"""Camera-domain test script: matching by file name and the comparison report."""
import cv2
import numpy as np

from ml import camera_test, convert_dataset, infer
from ml.synthetic import render_tape, write_voc_xml


def test_match_photos_by_name_longest_wins(tmp_path):
    originals = [tmp_path / "img_1.jpg", tmp_path / "img_12.jpg"]
    photos = [tmp_path / "IMG_12_cam.jpg", tmp_path / "pi_img_1.jpg", tmp_path / "random.jpg"]
    pairs, unmatched = camera_test.match_photos(originals, photos)
    assert (originals[1], photos[0]) in pairs and (originals[0], photos[1]) in pairs
    assert unmatched == [photos[2]]


def test_compare_reports_differences(tmp_path, monkeypatch):
    monkeypatch.setenv("KEETA_WEIGHTS", str(tmp_path / "none.pt"))
    infer.reset_detector()
    raw = tmp_path / "raw"
    raw.mkdir()
    labels = {"whitefly": "WF", "macrolophus": "MR", "nesidiocoris": "NC"}
    for i in range(6):
        img, boxes = render_tape({"whitefly": 10, "macrolophus": 1, "nesidiocoris": 1}, 640, 640, seed=i)
        cv2.imwrite(str(raw / f"t_{i}.jpg"), img)
        write_voc_xml(raw / f"t_{i}.xml", f"t_{i}.jpg", 640, 640, boxes, labels)
    convert_dataset.convert(raw, tmp_path / "yolo", seed=1)
    chosen = camera_test.prepare(3, tmp_path / "yolo", tmp_path / "ct")
    assert chosen                                   # at least one test image copied for printing

    # "photos": the originals darkened a little (stand-in for a camera), named <stem>_cam.jpg
    originals = sorted((tmp_path / "ct/originals").iterdir())
    for o in originals:
        img = cv2.imread(str(o))
        cv2.imwrite(str(tmp_path / "ct/photos" / f"{o.stem}_cam.jpg"),
                    np.clip(img.astype(int) - 15, 0, 255).astype("uint8"))
    pairs, unmatched = camera_test.match_photos(originals, sorted((tmp_path / "ct/photos").iterdir()))
    rep = camera_test.compare(pairs, tmp_path / "yolo/labels/test")
    assert rep["pairs"] == len(originals) and not unmatched
    assert rep["summary"]["pests"]["mean_abs_diff"] is not None
    assert "vs_ground_truth" in rep["summary"]
    md = camera_test.to_markdown(rep, [], "test")
    assert "DEMO DETECTOR" in md and "Per image" in md
    infer.reset_detector()

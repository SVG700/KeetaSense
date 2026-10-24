# DECISIONS.md - assumptions and design choices

Each line: **decision** - reason.

## Environment
- **The working folder (`KeetaSense/`) is the project root** (no extra `keetasense/` sub-folder) - the folder was already named for the project.
- **Python 3.12 runs from `.tools/python`, installed with a portable `uv` in `.tools/`** - the laptop had no Python and the rules forbid global installs. `.tools/` is git-ignored; teammates can install Python 3.12 normally instead.
- **CPU build of PyTorch on laptops; GPU training on Colab** - the CPU wheel is ~10x smaller and laptop training is only a smoke test.
- **`YOLO_CONFIG_DIR` points to `ml/.ultralytics`** - Ultralytics would otherwise write settings and fonts into the user's AppData folder.
- **All Python dependencies pinned to the versions that resolved on 2026-10-25** - reproducible installs.

## ML
- **Canonical classes: whitefly (pest), macrolophus (predator), nesidiocoris (predator)** - these are the three classes annotated in the Wageningen Yellow Sticky Traps dataset (labels WF/MR/NC). More can be added in `config/pests.yaml`.
- **Class list order in `pests.yaml` defines YOLO class ids** - one source of truth for converter, model and backend.
- **Raw labels mapped through `aliases` in `pests.yaml`; unknown labels are reported and skipped** - nothing hardcoded, and the team sees exactly what was dropped.
- **Stratified split by each image's most common class, seed 42** - detection images have many labels; the dominant class is a simple, explainable stratum.
- **Kaggle download takes the dataset slug as an argument** - we could not confirm a stable Kaggle mirror name; the original source is 4TU.ResearchData (DOI 10.4121/uuid:8b8ba63a-1010-4de7-a7fb-6f9e3baf128e).
- **Train on 640 px tiles (`ml/tile_dataset.py`), infer with SAHI 640 px slices** - insects are ~15-25 px on ~5000 px photos; tiling keeps train-time and inference-time insect size the same.
- **Test split stays full size** - evaluation runs the real SAHI pipeline on whole images.
- **Augmentations: hsv_v/hsv_s jitter, +/-15 deg rotation, up-down and left-right flips, blur/motion blur/JPEG via albumentations, mild scale (0.3)** - matches LED/sun variation, random landing orientation, focus and phone-photo artefacts; strong down-scaling would erase tiny insects.
- **Synthetic data is written as Pascal VOC XML with WF/MR/NC labels, then run through the real converter** - this tests the converter and alias mapping too.
- **Synthetic smoke-test weights are saved as `ml/weights/synthetic_*.pt`, never `best.pt`** - so synthetic weights can never be mistaken for the real model.
- **Without `best.pt`, `detect()` uses a classical "DEMO DETECTOR" (background subtraction + blob shape)** - lets the whole demo run offline today; it is labelled on every image, API response and dashboard card.
- **`synthetic_shape` (round/stout/slim) per class lives in `pests.yaml`** - keeps class names out of the generator and demo detector code.
- **evaluate.py computes AP@0.5 itself from `detect()` outputs** - so the reported numbers measure the exact deployed pipeline (YOLO + SAHI), not plain YOLO validation.
- **MAPE is computed only over images whose true count is > 0** - percentage error is undefined for zero; the report states how many images were used.

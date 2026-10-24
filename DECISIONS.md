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

## Backend
- **One tape section = one day's catch; "pests per day" = average over the last `rolling_window_days` sections** - the tape advances once a day, so this works the same in real use and in the 20 s demo cycle (each cycle = one simulated day).
- **Pest-to-predator ratio = pests / max(predators, 1)** - avoids division by zero and stays easy to explain.
- **Rule order: below threshold -> WAIT; else ratio >= spray_ratio -> SPRAY; else RELEASE_BIOCONTROL; thresholds inclusive** - directly follows the problem statement; inclusive edges are tested.
- **Degree-days accumulate from the first climate record (the "biofix") with the simple average method; forecast uses the mean DD of the last 7 days** - simplest standard method; IIHR may prefer a different biofix (e.g. last spray) - noted as a limitation.
- **Daily Tmin/Tmax come from the DHT22 readings of each calendar day** - no extra weather service needed, works offline.
- **Timestamps stored as naive local time (`NaiveDatetime`)** - one farm, one time zone, offline laptop; incoming ISO times with a zone are converted to local.
- **Edge devices may send their own detections (`detections_json`); otherwise the backend runs detection** - lets the Pi do edge AI while phone/laptop uploads still work.
- **A Decision row is stored after every new section; alerts fire when the action changes (or on a first non-WAIT decision)** - gives a decision history for the dashboard and avoids repeated alerts.
- **Telegram sends run on a background thread; with no token, alerts are logged and stored with status "logged"** - the API never blocks or fails because of Telegram.
- **Kannada templates are machine-drafted and flagged for review by a native speaker** - we cannot verify the wording ourselves.
- **Phone check divides counts by `days_exposed` and uses a window of 1, with no degree-day data** - a single photo has no history; the reason text says so.
- **SQLite + local media folder, CORS for the Vite dev server only** - runs fully offline on one laptop.
- **A trap is "online" if it reported within 26 hours** - it must report at least daily; 2 hours of slack.

## Edge
- **`MOCK_HARDWARE=1` by default; Pi libraries (picamera2, RPi.GPIO, adafruit_dht) imported only inside real-mode constructors** - the same code runs on Windows/Mac/Linux.
- **Mock camera cycles through 12 SYNTHETIC images in `demo/sample_tape/` that tell a WAIT -> SPRAY -> BIOCONTROL -> WAIT story** - judges see the decision change live.
- **Half-step sequence (8 states) with coils released after each move** - smoother and more torque than full-step; releasing stops the 28BYJ-48 from heating.
- **Edge detects locally and sends its detections; if local detection fails, it sends only the image** - edge AI when possible, graceful fallback otherwise.
- **Offline queue in SQLite, exponential backoff 10 s doubling to max 10 min; HTTP 4xx items are dropped, 5xx/network errors retried** - no data loss offline, no infinite retry of invalid data.
- **Real mode: one tape cycle every `CYCLE_HOURS` (24) and a climate reading every `CLIMATE_MINUTES` (30)** - frequent readings give true daily Tmin/Tmax for degree-days.
- **Default `BACKEND_URL` uses 127.0.0.1, not localhost** - on Windows "localhost" tries IPv6 first and added ~2 s to every request.
- **Pi 5 uses `rpi-lgpio` (drop-in for RPi.GPIO)** - classic RPi.GPIO does not support the Pi 5 GPIO chip.

## Frontend
- **React 18.3.1 + Vite 8 + Tailwind 4 + Recharts 3, versions pinned exactly** - current stable releases; React 18 kept for widest library compatibility.
- **Chart colours: pests = categorical slot 1 (blue), predators = slot 2 (orange), degree-days = slot 3 (aqua); validated colour-blind safe in light and dark** - red/green would clash with the traffic light and fail for red-green colour blindness.
- **Traffic light uses reserved status colours (critical red / warning amber / good green), always with an icon and a word** - never colour alone.
- **Straight (linear) lines, legend + tooltip + table view, action threshold as a dashed reference line** - smoothed curves overshoot real counts; the table view is the accessible alternative.
- **Live mode polls every 5 s and keeps the last good data if a refresh fails** - the demo never goes blank on a network blip.
- **Theme and live-mode choice stored in localStorage (wrapped in try/catch)** - per-viewer convenience only.
- **API base defaults to http://127.0.0.1:8000 (override with VITE_API_BASE)** - same IPv6 "localhost" delay reason as the edge.
- **Decision history shows only the moments the action changed** - one row per section would be noise.
- **Phone check hides the "no temperature data" forecast sentence** - a single photo never has temperature history; the reason says so instead.

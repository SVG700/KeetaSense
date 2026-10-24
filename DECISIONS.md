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

## Demo, scripts, final check
- **Seed: Polyhouse ends on RELEASE BIOCONTROL, Open field on SPRAY; images go through the real `detect()`** - the dashboard shows two different decisions with counts consistent with the images.
- **Seed does not send alerts (`notify=False`)** - reseeding must never spam a real Telegram chat; live alerts come from the edge demo.
- **`.bat` scripts open one window per service; `.sh` scripts run services in the background and stop them on Ctrl+C** - natural for each platform.
- **`.sh` scripts start Vite with `node .../vite.js` instead of `npm run dev`** - on Git Bash, killing npm left Vite running on port 5173 (found in the final check).
- **The clean-state check clones the repo into `.tools/cleancheck` (git-ignored)** - stays inside the project folder.

---
# Round 2 (hackathon preparation, tag `pre-hackathon-baseline` = state before this round)

## Part 1 - real dataset readiness
- **`ml/download_4tu.py` does not download automatically; it prints instructions, then verifies size + MD5 of `data.zip` (published 800,596,912 bytes, MD5 141d48b274d7d3daf78ecfaa5bf39410) and unpacks** - 4TU download links are generated per session; a broken auto-download would be worse than clear manual steps. Kaggle stays as a fallback.
- **Archives are extracted with a path-traversal guard; tar links/devices are skipped; a `.extracted_<name>` marker prevents re-extracting** - downloaded archives are untrusted input.
- **The real dataset was NOT present during this round, so `config/pests.yaml` class names were not changed.** The aliases already cover the labels described for this dataset (WF, MR, NC). When `ml/reports/dataset_summary.md` is generated, check its "Raw labels found" table: any label marked "not mapped" must be added as an alias (or a new class) - **to confirm by you**.
- **`dataset_summary.md` flags a class with < 100 examples, < 2 % share, or < 10 test examples** - below these, per-class training and metrics are unreliable (rule of thumb, adjustable at the top of `ml/dataset_summary.py`).
- **Tiling keeps a cut box if >= 50 % of its area is inside the tile (clipped), keeps 10 % of empty tiles (seeded)** - with overlap the insect appears whole in a neighbour tile; a few empty tiles teach "plain tape = nothing".
- **"camera" augmentation profile is the default: colour jitter (LED cast), Gaussian noise, stronger JPEG, perspective scale 0.01-0.04, on top of blur/brightness** - mimics printed images or tape photographed by the Pi camera; all mild so tiny insects survive.
- **Per-class `confidence_threshold` in `pests.yaml` (0.25 each, same as before); SAHI runs at the lowest one and results are filtered per class; not applied to the demo detector** - lets us trade false alarms vs misses per class after real evaluation.
- **`train.py` writes a model card `best.json` (trained date, dataset, tile mode, epochs, augmentation, classes)** - the app shows "trained <date>" from it.
- **One-zip export (`ml/package_model.py`) + `ml/install_model.py`; packages from synthetic data are named `..._SYNTHETIC_...` and installing one prints a loud warning** - a smoke-test model must never be mistaken for the real one.

## Part 2 - switch from demo detector to the real model
- **`ml/weights/best.pt` is picked up automatically by every component, because backend, edge and phone check all call `ml.infer.detect()`** - one code path, one switch.
- **A weights file that fails to load never crashes anything: logged loudly (ERROR banner) and the demo detector takes over; the dashboard banner says "weights file failed to load"** - the stage demo must survive a corrupt download.
- **Detector label: "Demo detector (synthetic only)" or "AI model: <file>, trained <date>"; the date comes from the model card `best.json`, otherwise the file date (shown as "file date")** - honest about where the date comes from.
- **A banner under the header on every page shows the active detector (from /api/health)** - judges can never confuse demo counts with AI counts.
- **Model page shows only numbers read from `ml/reports/eval_*.json`; a real-data report is featured over a newer synthetic one; a warning appears when only synthetic reports exist** - no number is ever computed or estimated in the UI.
- **`YOLO_OFFLINE=1` is set by default at runtime (ml/__init__.py); `train.py` switches it back to 0** - Ultralytics otherwise does DNS look-ups and sends usage statistics; training on Colab needs the internet.

## Part 3 - camera-domain test
- **Photos are matched to originals when the original's file name (case-insensitive) appears inside the photo's name; the longest match wins** - works with "img_12_cam.jpg", "pi_img_12.jpg" etc., and "img_1" never steals "img_12".
- **`prepare` picks the test images with the most labelled insects** - more insects per print = more signal per photo.
- **Report gives absolute, signed and % difference (photo minus original) and, when labels exist, MAE against ground truth for both** - the signed value shows whether printing/camera loses insects or adds false ones.
- **All console output is UTF-8 (ml/__init__.py reconfigures stdout/stderr)** - the Windows code page crashed on "→" and would on Kannada too.

## Part 4 - Raspberry Pi bring-up tools
- **Each hardware test is a separate module with a `check()` function returning PASS/WARN/FAIL + hints, and a `main()` that exits 1 on FAIL** - runnable alone on the Pi, scriptable, and reused by the startup self-check.
- **`--real` / `--mock` flags on every test; without them MOCK_HARDWARE decides** - the scripts can be rehearsed on a laptop; real mode is explicit on the Pi.
- **The stepper test cannot sense motion, so it reports PASS when all commands were sent and asks the user to watch the shaft** - no fake "verified" claim.
- **Camera sharpness = variance of the Laplacian, WARN below `CAMERA_MIN_SHARPNESS` (default 10); brightness WARN outside 40-225** - plain yellow tape has little texture, so the sharpness number is mainly for comparing focus attempts; thresholds are deliberately loose and only warn.
- **DHT22 PASS at >= 60 % good reads with plausible values (-10..60 °C, 0..100 %)** - DHT22s miss reads normally; persistent failure is what matters.
- **Backend link test uses `POST /api/climate?dry_run=true`** - validates the full path without storing a fake reading that would distort degree-days.
- **Calibration writes `STEPS_PER_SECTION` into `.env` with a `.env.bak` copy and saves a photo after every move** - the team sees exactly where the mark is; nothing is lost.
- **Startup self-check never blocks the service; each hardware part starts independently and a failed part is reported (camera missing -> no capture, climate still sent)** - partial hardware is better than no data on stage.
- **Every cycle is recorded (`edge/data/recording/<trap>/manifest.jsonl` + images, `RECORD=1` default)** - any rehearsal automatically becomes a replay pack.
- **Removed an unmeasured claim from PI_SETUP.md ("about a minute is normal" for Pi inference)** - replaced by instructions to measure it from the log.
- **Tape sections get a `source` column (live | mock | replay | seed | upload), added to old databases by a small migration in `init_db`** - the dashboard can label replayed data; no reset needed.

## Part 5 - demo reliability
- **One launcher (`scripts/launcher.py`) behind every `.bat`/`.sh`: all services in one console with `[backend]` / `[trap]` prefixes** - one window to watch and one to close.
- **On Windows every child is placed in a Job Object with KILL_ON_JOB_CLOSE** - closing the window (or the launcher dying for any reason) kills all services; verified by force-killing the launcher.
- **Ctrl+C / Ctrl+Break are handled by the launcher, which terminates the children (8 s grace, then kill)** - verified with Ctrl+Break sent to the launcher's process group (exit 0, port freed).
- **The launcher restarts the backend or trap service if it crashes (max 5 times)** - observed working when a backend process was killed during testing.
- **The backend serves the built dashboard (`frontend/dist`) at "/" with client-side routing; the launcher rebuilds it only when the source is newer** - one process, one URL, no Node at runtime; the Vite dev server remains available with `--dev`.
- **The dashboard's default API address is "same host, port 8000"** - works on the laptop, from the backend-served page, and from a phone on the same Wi-Fi (`--lan`).
- **`--lan` binds 0.0.0.0 and prints the laptop's IP addresses; the default stays 127.0.0.1** - the Pi and phones need it, but it should be a conscious choice.
- **Offline audit: no CDN fonts/scripts/images in the dashboard (only XML namespaces and comments contain URLs); Ultralytics runs with YOLO_OFFLINE=1; Telegram uses 5-10 s timeouts on a background thread.** Verified by a test that blocks every non-local DNS lookup during the whole API flow, and a separate run of YOLO+SAHI inference with sockets blocked (0 attempts). Wi-Fi was NOT physically switched off on this laptop.
- **Synthetic images (seed history and mock-camera samples) are ALWAYS counted by the demo detector, even after `best.pt` is installed (`MOCK_USE_MODEL=1` overrides for the mock camera)** - the real model would not recognise drawn insects and the demo history would collapse to zeros.
- **`/api/reset-demo` deletes rows (not the database file) and re-seeds in-process; hidden "↺" in the footer or Alt+Shift+R; disable with `KEETA_ALLOW_RESET=0`** - deleting the file fails on Windows while the backend has it open.
- **Replay packs are folders with `manifest.jsonl` + images; `demo/replay/` is a SYNTHETIC pack recorded from the mock trap; the launcher prefers `demo/replay_real/` when present** - works out of the box today, and the real pack drops in without code changes.

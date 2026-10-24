# PROGRESS.md

## Phases

- [x] Phase 0: git repo, portable Python 3.12 (`.tools/`), pinned requirements
- [x] Phase 1: ML pipeline (converter, Kaggle helper, synthetic data, tiling, train, infer + SAHI, demo detector, evaluate, Colab notebook) - smoke-tested on synthetic data
- [x] Phase 2: Backend (FastAPI, decision engine, bilingual alerts, tests)
- [x] Phase 3: Edge service (mock hardware, offline queue, demo mode, PI_SETUP.md) - verified live against the backend
- [x] Phase 4: Frontend dashboard (overview, trap detail, phone check, live mode, dark mode, badges, error states) - built and checked in the browser
- [x] Phase 5: Seed script, sample tape images, one-command scripts, README
- [x] Final check from a clean clone (see "Final check" below)

## Round 2 (hackathon preparation)
- [x] Part 1: 4TU download/verify/extract, dataset summary report, improved tile mode (+ notebook switch), camera augmentations, per-class confidence thresholds, notebook auto-evaluate + one-zip export, install_model. Real dataset NOT present on this laptop: conversion of real data and pests.yaml name check still to do.
- [x] Part 2: automatic switch to best.pt with startup log + safe fallback, detector banner on every page, Model page with measured reports (warning when only synthetic). Checked in the browser in demo and AI-model mode (synthetic weights).
- [x] Part 3: ml/camera_test.py (prepare + run, report ml/reports/camera_test.md), README section. Not yet run on real prints (needs the trained model, printer and Pi camera).
- [x] Part 4: edge/tests_hw (camera, stepper, DHT22, backend link) with PASS/FAIL + hints, edge/calibrate_tape.py, startup self-check, robust per-part start-up, cycle recording; PI_SETUP.md bring-up order. All run in mock mode here; NOT run on a real Pi.
- [x] Part 5: single-window launcher (start/demo/replay .bat + .sh) with Job Object cleanup, Ctrl+C handling and crash restart; backend serves the built dashboard; offline audit + tests; REPLAY mode with "Replay" label; /api/reset-demo + hidden button. Tested here: demo.bat and replay.bat in one console, force-kill and Ctrl+Break cleanup, reset button in the browser.

## What works (verified)

- `python -m pytest` - **50 tests pass**: converter (VOC + YOLO formats, reproducible 70/15/15 split,
  empty-folder message), demo detector, AP/IoU maths, every decision rule incl. boundaries, degree-day
  maths and forecast, the PLACEHOLDER comment on every threshold, every API endpoint incl. error cases,
  alert logging in English + Kannada, edge stepper/queue/backoff/offline-then-sync, seed script.
- ML pipeline on synthetic data: generate → convert → train (2 and 40 epochs on CPU) → evaluate
  (YOLO+SAHI and demo detector) → `detect()`. Reports in `ml/reports/`.
- Backend serves all endpoints, stores images, annotates them, computes decisions, logs alerts.
- Edge service in mock mode: advance → capture → local detection → queue → sync; keeps data
  when the backend is down and sends it later.
- Dashboard: overview cards with traffic light, trap detail charts (counts with threshold line,
  degree-days, forecast meter, annotated image, decision history), phone check upload, live mode
  (5 s), light/dark mode, phone-width layout, "Simulated data" / "Demo detector" badges,
  "backend not reachable" and empty states.
- `scripts/demo.sh` / `demo.bat`: seed + backend + dashboard + edge mock in one command.

## Final check (2026-10-25, from a clean `git clone`)

1. `scripts\setup.bat` in a fresh clone on a laptop without Python: fell back to the portable
   `uv`, installed Python 3.12, all pinned packages, `.env`, frontend packages - exit 0.
2. `python -m pytest` in the clone: **50 passed**. `npm --prefix frontend run build`: OK.
3. `CYCLES=5 bash scripts/demo.sh`: seeded 14 days, started backend + dashboard + mock edge.
   Five edge cycles ran ~20 s apart (tape_01..05: 6, 9, 12, 38, 52 whiteflies counted on the edge),
   all synced (0 left in the queue). The dashboard with Live on updated by itself (Polyhouse pests/day
   24.3 -> 16.7), the decision went RELEASE BIOCONTROL -> WAIT -> SPRAY, and the alerts were logged in
   English and Kannada.
4. Bug found and fixed: stopping `demo.sh` left Vite running on Git Bash; re-run after the fix
   (2 cycles) - all ports freed.
5. Not run in this check: `start.bat` / `demo.bat` (they open separate console windows); their
   commands are the same as the `.sh` scripts, which were run.

## What is simulated

- Insect counts come from the **DEMO DETECTOR** (blob counting) until `ml/weights/best.pt` exists.
- All tape images (sample tape, seed history, synthetic dataset) are **synthetic drawings**.
- Seed history (14 days × 2 traps) and edge mock sensor readings are **simulated**
  (`simulated=True` in the database, badge on the dashboard).
- Stepper, camera and DHT22 run in **mock mode**; the real-hardware code paths are written but
  have **not been run on a Raspberry Pi**.

## What you must do manually

1. **Download the dataset** (https://data.4tu.nl/articles/_/12707066/1, CC0, ~800 MB) into
   `ml/data/raw/` - or use `python -m ml.download_kaggle --dataset <owner>/<name>` with your kaggle.json.
2. **Train on Colab**: run `ml/train_colab.ipynb` on a T4 GPU, then copy `best.pt` to
   `ml/weights/best.pt` and keep the evaluation report (`ml/reports/eval_real_test.md`) - those are
   the only accuracy numbers you should quote.
3. **Telegram**: create a bot with @BotFather, put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.
4. **Confirm every threshold with the IIHR mentor** in `config/pests.yaml` (base temperature,
   degree-days per generation, action threshold, spray ratio, rolling window).
5. **Have a native Kannada speaker check** `backend/alert_templates.yaml` and the Kannada names in
   `config/pests.yaml`.
6. On the Pi: wire and calibrate per `edge/PI_SETUP.md` (`STEPS_PER_SECTION`), set `MOCK_HARDWARE=0`.

## Known limitations

- No real-insect accuracy exists yet; the demo detector only works on the synthetic images
  (it would miscount real photos - every screen says "Demo detector").
- Degree-days start from the first temperature record; IIHR may prefer a biofix such as the last
  spray or transplanting date. Today's degree-day bar covers a partial day.
- One target pest per trap (whitefly); adding thrips/Tuta needs classes + thresholds in
  `pests.yaml` and a model trained on them.
- Predator counts on traps are low and noisy; the ratio uses predators ≥ 1 to avoid division by zero.
- The take-up spool diameter grows, so a fixed `STEPS_PER_SECTION` slowly advances more tape;
  recalibrate mid-roll.
- SAHI on a full 12 MP photo is slow on a Pi 4 (fine once a day; `LOCAL_DETECTION=0` offloads to the laptop).
- No user accounts / authentication: the API is meant for a trusted local farm network.
- `npm` uses its normal user-level download cache (outside the project) during `npm install`.
- Frontend has no automated UI tests (verified manually in the browser; TypeScript strict build passes).

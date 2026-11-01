# PROGRESS.md

## Round 1 - build (all done)

- [x] Phase 0: git repo, portable Python 3.12 (`.tools/`), pinned requirements
- [x] Phase 1: ML pipeline (converter, Kaggle helper, synthetic data, tiling, train, infer + SAHI, demo detector, evaluate, Colab notebook) - smoke-tested on synthetic data
- [x] Phase 2: Backend (FastAPI, decision engine, bilingual alerts, tests)
- [x] Phase 3: Edge service (mock hardware, offline queue, demo mode, PI_SETUP.md)
- [x] Phase 4: Frontend dashboard (overview, trap detail, phone check, live mode, dark mode, badges, error states)
- [x] Phase 5: Seed script, sample tape images, one-command scripts, README, clean-clone check

## Round 2 - hackathon preparation (tag `pre-hackathon-baseline` = state before this round)

Show judges exactly what was added: `git diff pre-hackathon-baseline --stat` or `git log pre-hackathon-baseline..`

- [x] **Part 1 - real dataset readiness:** `ml/download_4tu.py` (instructions, size + MD5 check, safe extraction), `ml/dataset_summary.py` (classes, counts, resolutions, insect sizes in px, warnings; written automatically by the converter), improved tile mode (box clipping by visible fraction, configurable empty-tile keep rate) with a `USE_TILES` switch in the notebook, "camera" augmentation profile (colour jitter, blur, noise, JPEG, perspective), per-class `confidence_threshold` in `pests.yaml`, notebook auto-evaluates on the real test split and downloads one zip (`ml/package_model.py`), `ml/install_model.py` for the laptop. **The real dataset was not present, so it was not converted and `pests.yaml` class names were not changed.**
- [x] **Part 2 - demo detector -> real model:** `best.pt` is used automatically by backend, edge and phone check, with a clear startup log line; weights that fail to load fall back to the demo detector with a loud warning. A banner on every screen shows "Demo detector (synthetic only)" or "AI model: <file>, trained <date>". New **Model** page shows the measured evaluation reports and warns when only synthetic reports exist.
- [x] **Part 3 - camera-domain test:** `ml/camera_test.py` (`prepare` picks test images to print, `run` compares photo vs original counts -> `ml/reports/camera_test.md`). Documented in the README. Not yet run on real prints.
- [x] **Part 4 - Pi bring-up tools:** `edge/tests_hw/test_camera|test_stepper|test_dht22|test_backend_link.py` (PASS/WARN/FAIL + hints), `edge/calibrate_tape.py` (interactive, saves `STEPS_PER_SECTION` to `.env`), startup self-check table, each hardware part starts independently, every cycle recorded for replay. `edge/PI_SETUP.md` has the step-by-step bring-up order. **All run in mock mode here; nothing was run on a real Raspberry Pi.**
- [x] **Part 5 - demo reliability:** `scripts/launcher.py` runs everything in ONE window (`start.bat`, `demo.bat`, new `replay.bat`, and `.sh` versions), Ctrl+C / closing the window stops everything (Windows Job Object), crashed services restart. The backend serves the built dashboard (one URL: http://127.0.0.1:8000). Offline audit: no CDN/remote assets; Ultralytics forced offline; Telegram with short timeouts on a background thread. REPLAY mode with a "▶ Replay" label; `/api/reset-demo` + hidden ↺ button (Alt+Shift+R). Synthetic images are always counted by the demo detector, so installing the real model cannot break the seeded demo.
- [x] **Part 6 - Settings page:** view/edit thresholds, base temperature, degree-days per generation; inline validation; timestamped backup in `config/backups/`; edited lines get "Confirmed with IIHR mentor on <date>"; decisions recalculate immediately.
- [x] **Part 7 - Kannada review helper:** `python -m backend.kannada_review export` -> `docs/kannada_review.csv` (key, English text, Kannada text, reviewer correction); `import` checks placeholders, keeps `.bak` copies and writes the corrections back.
- [x] **Final check** (below).

Tests: **103 pass** (`python -m pytest`), up from 50. Frontend: TypeScript strict build passes.

## Final check (2026-10-25, fresh `git clone` of the final commit)

1. `scripts\setup.bat` in the clone (no system Python -> portable `uv` path): exit 0.
2. `python -m pytest` in the clone: **103 passed**.
3. `scripts\demo.bat --no-browser --cycles 4` run through `cmd` (one console): the launcher built the
   dashboard itself (no `dist` in git), seeded the demo, started backend + mock trap, printed the
   self-check table (all PASS, detector WARN = demo detector), 4 cycles synced, decision went
   RELEASE BIOCONTROL -> WAIT -> WAIT -> SPRAY, no tracebacks, all processes stopped, ports freed.
4. `scripts\replay.bat` in the clone: replayed `demo/replay` cycles; the trap page showed "▶ Replay"
   and the replay note; stopping the launcher stopped every process of the clone (0 left, port freed).
5. Settings page in the browser (clone's own config): spray ratio 10 -> 8 saved, backup written,
   comment changed to "Confirmed with IIHR mentor on 2026-10-25", both decisions recalculated.
6. Earlier in this round (main folder): window-close simulated by force-killing the launcher -> Job
   Object killed all children; Ctrl+Break to the launcher's process group -> clean exit 0; reset
   button in the browser -> 28 seeded sections restored; crashed backend restarted by the launcher.

Not verified on this laptop: a physical Ctrl+C keypress and closing a visible console window
(simulated as above), Wi-Fi physically switched off (simulated by blocking all non-local network
lookups in a test and in a YOLO run), anything on a real Raspberry Pi, the real dataset and model.

## Repair (31 Oct 2026)

An interrupted move into OneDrive (29 Oct) had split `.venv`, the portable Python and
`frontend/node_modules` between this folder and `OneDrive\Desktop\Samhith\KeetaSense`, and left
OneDrive cloud tags on 314 project files. Repaired in this folder: tools reinstalled with
`scripts\setup.bat`, synthetic data regenerated, the 314 files rewritten as normal files (contents
verified identical by SHA-256), a garbled UTF-16 line removed from the end of README.md. Verified
after the repair: 103 tests pass, frontend builds, `demo.bat` (3 cycles) and `replay.bat` (2 cycles)
run in one window with no errors and stop cleanly. The OneDrive copy is incomplete (no source code)
and is not used.

## Round 3 (1 Nov) - forecasting, weather, languages, network, impact

Done (backend + bot, 172 tests pass):
- Open-Meteo weather (cached, offline-safe, `--sim-weather`) and "don't spray, rain in N hours" advice
- 3-7 day pest-pressure forecast from counts + weather (`/api/advisory/{trap}`)
- Advisories and "Can I spray today?" in English, Kannada, Hindi, Tamil (machine-drafted)
- Telegram bot (`python -m backend.telegram_bot`, auto-started by the launcher when a token is set)
- 5 simulated stations, early warnings, heat grid (`/api/network`); impact estimate (`/api/impact`)

NOT done yet (dashboard side): advisory + forecast + weather panel and voice readout on the trap page,
outbreak map page, impact calculator page, PWA install/offline cache. README not yet updated.

## Prep round (1 Nov) - 6 features, branch `feature/prep-round` (one commit each)

Done, 228 tests pass, `npm run build` passes, each feature checked in the browser / with the mock trap:
- **F1** image quality gate + CHECK TRAP state + alert (`--inject blur|dark|glare|stuck`)
- **F3** scout corrections (add/remove/relabel), corrected counts drive the decision, Model page stats, YOLO zip export
- **F4** action logging from Telegram buttons and the dashboard, chart markers, 3-day effect card, cooldown
- **F2** count range + BORDERLINE from detection confidence (Telegram + dashboard)
- **F5** cost of spraying, release dose + re-check date, What-if page (`/api/decision/simulate` == live engine)
- **F6** heartbeat + Health card, offline / tape-low / motor-fault alerts, quiet hours, one reminder,
  daily digest (`--inject offline|motor|tape`)

Still to confirm: every limit added this round is a PLACEHOLDER in `config/pests.yaml` (image quality
on the real Pi camera; release rate, predators per trapped predator and area per trap with the IIHR
mentor; cooldown, quiet hours, digest time and reminder delay with the team). New Kannada strings
are in `docs/kannada_review.csv` as "needs review". Not merged into `main`, not pushed.

## What you must still do manually

1. **Dataset:** download `data.zip` from https://data.4tu.nl/articles/_/12707066/1 into `ml/data/raw/`,
   run `python -m ml.download_4tu`, then `python -m ml.convert_dataset`. Read
   `ml/reports/dataset_summary.md`: if any raw label is "not mapped", add it as an alias in
   `config/pests.yaml` (and tell us - see DECISIONS.md, Part 1).
2. **Train on Colab** with `ml/train_colab.ipynb` (T4 GPU, Run all). Install the zip on the laptop
   (`python -m ml.install_model <zip>`) and on the Pi. Quote only numbers from `eval_real_test.md`.
3. **Camera-domain test:** print 10 test images, photograph them in the trap, run `ml.camera_test`.
4. **Raspberry Pi bring-up:** follow `edge/PI_SETUP.md` step 0-7 (camera, DHT22, stepper,
   calibration, backend link, full run, record a replay pack into `demo/replay_real/`).
5. **Telegram:** bot token + chat id in `.env`; test once with internet.
6. **Thresholds:** get real values from the IIHR mentor and enter them on the Settings page.
7. **Kannada:** send `docs/kannada_review.csv` to a native speaker; import with
   `python -m backend.kannada_review import docs/kannada_review.csv --reviewer "Name"`.
8. **Rehearse once with Wi-Fi off** (`scripts\demo.bat`, then `scripts\replay.bat`).

## Hackathon day (4-5 November) - exact steps

**Before leaving (with internet):**
1. `git pull` (or copy the folder) on the demo laptop; run `scripts\setup.bat` once.
2. Installed: `ml/weights/best.pt` (+ `best.json`) via `python -m ml.install_model`, and
   `demo/replay_real/` from a rehearsal. Check the banner shows "AI model: best.pt, trained <date>".
3. Charge the laptop and a power bank for the Pi; pack the trap, tape roll, spare tape, LED supply.

**At the venue (no internet needed):**
1. Laptop: `scripts\start.bat --lan` (real trap) - note the printed `http://<laptop-ip>:8000`.
   Without the Pi: `scripts\demo.bat` (mock trap) instead.
2. Pi: set `BACKEND_URL=http://<laptop-ip>:8000` in `.env`, run
   `python -m edge.tests_hw.test_backend_link`, then `python -m edge.main --demo` (20 s cycles) -
   check the self-check table is all PASS.
3. Open http://127.0.0.1:8000 on the laptop (and on judges' phones via the printed address),
   switch **Live on**.
4. Show: Overview traffic lights -> trap detail (chart, degree-day forecast, annotated tape) ->
   **Phone check** with a photo -> **Model** page (real measured numbers) -> **Settings** (enter the
   mentor's thresholds; decisions update instantly) -> an alert in Kannada/English.
5. **Between judge visits:** click the faint **↺** at the end of the footer (or Alt+Shift+R).
6. **If the camera or Pi fails:** Ctrl+C the laptop window, run `scripts\replay.bat` - the dashboard
   shows "▶ Replay"; say so to the judges.
7. **If anything hangs:** close the window (everything stops), start the script again.

## What is simulated (unchanged until the manual steps above are done)

- Insect counts come from the **demo detector** until `ml/weights/best.pt` is installed.
- All tape images in the repo (sample tape, seed history, `demo/replay/`) are **synthetic drawings**.
- Seed history and mock sensor readings are **simulated** (`simulated=True`, badge on the dashboard).
- Stepper, camera and DHT22 run in **mock mode** here.

## Known limitations

- No real-insect accuracy exists yet; the demo detector only works on synthetic images.
- Degree-days start from the first temperature record; IIHR may prefer another biofix date.
  Today's degree-day bar covers a partial day.
- One target pest per trap (whitefly).
- Predator counts are low and noisy; the ratio counts predators as at least 1.
- A growing take-up spool pulls slightly more tape per turn; recalibrate mid-roll.
- On-device SAHI speed on a Pi 4/5 has **not been measured**; if slow, `LOCAL_DETECTION=0`.
- No login on the dashboard, Settings page or reset endpoint (trusted local network only;
  `KEETA_ALLOW_RESET=0` disables reset).
- The camera sharpness check is a relative measure (plain tape has little texture).
- `npm` uses its normal user-level download cache during `npm install`.
- No automated browser tests for the frontend (checked manually in the browser each round).

"""KeetaSense edge service - the program that runs on the trap's Raspberry Pi.

One cycle:
  1. advance the tape (stepper motor)  -> a fresh, unused section is in view
  2. wait a moment for the tape to settle
  3. photograph the section (camera + LEDs in the dark chamber)
  4. detect and count insects locally (ml.infer.detect - the same code as the backend)
  5. read temperature / humidity (DHT22)
  6. save everything to the local SQLite queue (and record it for replay)
  7. send the queue to the backend; if offline, keep it and retry with backoff

Run (from the project root):
    python -m edge.main --demo          # one cycle every 20 s (for judges)
    python -m edge.main --once          # a single cycle, then exit
    python -m edge.main                 # real schedule: one cycle per day (CYCLE_HOURS)
    python -m edge.main --demo --replay demo/replay   # REPLAY recorded cycles (no hardware needed)

A quick self-check of camera, sensor, motor, backend and detector runs first
(skip it with --skip-selfcheck). Every cycle is also recorded to
edge/data/recording/<trap>/ so it can be replayed later (RECORD=0 to disable).

MOCK_HARDWARE=1 (default) uses sample images and simulated sensors, so this
runs on any laptop. Set MOCK_HARDWARE=0 on the Raspberry Pi.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import time
from datetime import datetime
from pathlib import Path

import cv2
import requests

from edge import selfcheck
from edge.config import EdgeConfig
from edge.hardware import DHT22, Camera, Stepper
from edge.offline_queue import OfflineQueue
from edge.replay import Recorder, ReplaySource

log = logging.getLogger("keetasense.edge")

HTTP_TIMEOUT_S = 30


class EdgeService:
    def __init__(self, cfg: EdgeConfig, replay_dir: Path | None = None, record: bool | None = None):
        self.cfg = cfg
        self.queue = OfflineQueue(cfg.data_dir / "queue.db")
        self.images_dir = cfg.data_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.running = True
        self.init_errors: dict[str, str] = {}
        self.stepper = self.camera = self.sensor = None
        self.replay = ReplaySource(replay_dir) if replay_dir else None
        if self.replay:
            log.warning("REPLAY MODE: replaying %d recorded cycles from %s (no hardware used)",
                        len(self.replay.entries), replay_dir)
        else:
            # each part starts on its own: one broken part must not stop the others
            mock = cfg.mock_hardware
            self.stepper = self._start("stepper", lambda: Stepper(cfg.stepper_pins, cfg.steps_per_section,
                                                                  cfg.step_delay_s, mock=mock))
            self.camera = self._start("camera", lambda: Camera(mock=mock, sample_dir=cfg.sample_dir,
                                                               led_pin=cfg.led_pin))
            self.sensor = self._start("sensor", lambda: DHT22(cfg.dht22_pin, mock=mock))
        if record is None:
            record = os.environ.get("RECORD", "1") == "1"
        self.recorder = Recorder(cfg.data_dir / "recording" / cfg.trap_id) if record and not self.replay else None
        # how the backend/dashboard label this data
        self.source = "replay" if self.replay else ("mock" if cfg.mock_hardware else "live")
        self._last_climate: tuple[float, float] | None = None

    def _start(self, name: str, factory):
        try:
            return factory()
        except Exception as e:
            self.init_errors[name] = f"{e.__class__.__name__}: {e}"
            log.exception("Could not start the %s - continuing without it", name)
            return None

    def run_selfcheck(self) -> list:
        if self.replay:  # no hardware in replay: only the backend link and the detector matter
            results = [r for r in selfcheck.run_quick(self.cfg, init_errors={}, skip_hardware=True)]
        else:
            results = selfcheck.run_quick(self.cfg, camera=self.camera, sensor=self.sensor, stepper=self.stepper,
                                          init_errors=self.init_errors)
        selfcheck.print_summary(results, self.cfg.mock_hardware and not self.replay)
        return results

    # --- one full cycle -----------------------------------------------------
    def run_cycle(self) -> dict:
        """Advance, capture, detect, queue, sync. Never raises - errors are logged."""
        if self.replay:
            return self.run_replay_cycle()
        summary = {"captured": False, "queued": 0, "sent": 0}
        path, payload = None, None
        try:
            if self.camera is None:
                raise RuntimeError(f"camera not available ({self.init_errors.get('camera')})")
            if self.stepper is not None:
                self.stepper.advance_section()
            else:
                log.error("Stepper not available - photographing the same tape section again")
            time.sleep(self.cfg.settle_seconds if not self.cfg.mock_hardware else 0.2)
            img = self.camera.capture()
            now = datetime.now()
            path = self.images_dir / f"{self.cfg.trap_id}_{now:%Y%m%d_%H%M%S}.jpg"
            cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            summary["captured"] = True

            payload = {"trap_id": self.cfg.trap_id, "timestamp": now.isoformat(timespec="seconds"),
                       "simulated": self.cfg.mock_hardware, "source": self.source}
            detections = self.detect_locally(img)
            if detections is not None:
                payload["detections"], payload["detector_mode"] = detections
                pests = sum(1 for d in detections[0] if d["category"] == "pest")
                log.info("Local detection: %d pests, %d predators (%s)", pests,
                         len(detections[0]) - pests, detections[1])
            self.queue.add("section", payload, str(path))
            summary["queued"] += 1
        except Exception:
            log.exception("Capture failed this cycle - will try again next cycle")

        summary["queued"] += self.read_climate()
        if self.recorder and path is not None:
            try:
                self.recorder.record(path, payload, self._last_climate)
            except Exception:
                log.exception("Could not record this cycle for replay")
        summary["sent"] = self.sync()
        log.info("Cycle done: %s, %d item(s) still waiting in the offline queue", summary, self.queue.size())
        return summary

    def run_replay_cycle(self) -> dict:
        """REPLAY: send the next recorded image + results as a new tape section."""
        entry = self.replay.next()
        now = datetime.now()
        path = self.images_dir / f"{self.cfg.trap_id}_{now:%Y%m%d_%H%M%S}_replay.jpg"
        shutil.copy2(entry.image, path)
        payload = {"trap_id": self.cfg.trap_id, "timestamp": now.isoformat(timespec="seconds"),
                   "simulated": entry.simulated, "source": "replay"}
        if entry.detections is not None:
            payload["detections"], payload["detector_mode"] = entry.detections, entry.detector_mode
        else:  # a recording without detections: detect now
            img = cv2.imread(str(entry.image))
            det = self.detect_locally(img) if img is not None else None
            if det is not None:
                payload["detections"], payload["detector_mode"] = det
        self.queue.add("section", payload, str(path))
        queued = 1
        if entry.temperature_c is not None and entry.humidity_pct is not None:
            self.queue.add("climate", {"trap_id": self.cfg.trap_id, "timestamp": payload["timestamp"],
                                       "temperature_c": entry.temperature_c, "humidity_pct": entry.humidity_pct,
                                       "simulated": entry.simulated})
            queued += 1
        n = len(self.replay.entries)
        log.info("REPLAY cycle %d/%d: %s (%s)", (self.replay.index - 1) % n + 1, n, entry.image.name,
                 payload.get("detector_mode") or "backend will detect")
        sent = self.sync()
        return {"captured": True, "queued": queued, "sent": sent, "replay": True}

    def detect_locally(self, img):
        """Run the detector on the device. Returns (detections, mode) or None."""
        if not self.cfg.local_detection:
            return None
        try:
            from ml import infer  # heavy import, done lazily
            if self.cfg.mock_hardware and not self.cfg.mock_use_model:
                # synthetic sample images: the trained model would not recognise drawn insects
                return infer.demo_detect(img), infer.MODE_DEMO
            r = infer.detect(img)
            return r.detections, r.mode
        except Exception:
            log.exception("Local detection failed - the backend will detect instead")
            return None

    def read_climate(self) -> int:
        if self.sensor is None:
            return 0
        try:
            reading = self.sensor.read()
        except Exception:
            log.exception("DHT22 read failed")
            reading = None
        self._last_climate = reading
        if reading is None:
            return 0
        temp, hum = reading
        self.queue.add("climate", {"trap_id": self.cfg.trap_id,
                                   "timestamp": datetime.now().isoformat(timespec="seconds"),
                                   "temperature_c": temp, "humidity_pct": hum,
                                   "simulated": self.cfg.mock_hardware})
        return 1

    # --- syncing ------------------------------------------------------------
    def sync(self) -> int:
        """Send due queue items to the backend. Returns how many were sent."""
        sent = 0
        for item in self.queue.due():
            try:
                resp = self._send(item)
            except requests.RequestException as e:
                delay = self.queue.mark_failed(item.id, str(e))
                log.warning("Backend unreachable (%s). Kept %d item(s) offline; retry in %.0f s.",
                            e.__class__.__name__, self.queue.size(), delay)
                break  # backend is down: no point trying the rest now
            if resp.ok:
                self.queue.mark_sent(item.id)
                sent += 1
                if item.kind == "section":
                    d = resp.json().get("decision", {})
                    log.info("Synced section -> backend decision: %s", d.get("action"))
            elif resp.status_code >= 500 or resp.status_code in (408, 429):
                delay = self.queue.mark_failed(item.id, f"HTTP {resp.status_code}")
                log.warning("Backend error HTTP %s; retry in %.0f s", resp.status_code, delay)
                break
            else:
                # 4xx = the backend rejected the data itself; retrying will not help
                log.error("Backend rejected %s item %d (HTTP %s): %s - dropping it",
                          item.kind, item.id, resp.status_code, resp.text[:200])
                self.queue.mark_sent(item.id)
        return sent

    def _send(self, item) -> requests.Response:
        url = self.cfg.backend_url
        if item.kind == "climate":
            return requests.post(f"{url}/api/climate", json=item.payload, timeout=HTTP_TIMEOUT_S)
        p = item.payload
        data = {"trap_id": p["trap_id"], "timestamp": p["timestamp"], "simulated": str(p["simulated"]).lower(),
                "source": p.get("source", "live")}
        if "detections" in p:
            data["detections_json"] = json.dumps(p["detections"])
            data["detector_mode"] = p["detector_mode"]
        with open(item.image_path, "rb") as f:
            return requests.post(f"{url}/api/sections", data=data,
                                 files={"image": (Path(item.image_path).name, f, "image/jpeg")},
                                 timeout=HTTP_TIMEOUT_S)

    # --- main loop ----------------------------------------------------------
    def run_forever(self, demo: bool, max_cycles: int | None = None) -> None:
        cycle_s = self.cfg.demo_cycle_seconds if demo else self.cfg.cycle_hours * 3600
        climate_s = cycle_s if demo else self.cfg.climate_minutes * 60
        log.info("Edge service started: trap=%s source=%s demo=%s cycle=%.0fs backend=%s",
                 self.cfg.trap_id, self.source, demo, cycle_s, self.cfg.backend_url)
        cycles = 0
        next_cycle = time.time()
        next_climate = time.time() + climate_s
        next_sync = time.time() + 15
        while self.running:
            now = time.time()
            if now >= next_cycle:
                self.run_cycle()
                cycles += 1
                next_cycle = now + cycle_s
                next_climate = now + climate_s
                if max_cycles and cycles >= max_cycles:
                    break
            elif not demo and not self.replay and now >= next_climate:  # extra readings between daily cycles
                self.read_climate()
                self.sync()
                next_climate = now + climate_s
            elif now >= next_sync and self.queue.size():  # retry the offline queue
                self.sync()
                next_sync = now + 15
            time.sleep(0.5)
        self.close()

    def close(self) -> None:
        for part in (self.stepper, self.camera, self.sensor):
            if part is None:
                continue
            try:
                part.close()
            except Exception:
                log.exception("Error while closing %s", part.__class__.__name__)
        self.queue.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="KeetaSense edge service")
    ap.add_argument("--demo", action="store_true", help="one cycle every DEMO_CYCLE_SECONDS (default 20)")
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit")
    ap.add_argument("--cycles", type=int, help="stop after this many cycles")
    ap.add_argument("--trap", help="override TRAP_ID")
    ap.add_argument("--replay", help="folder with a recording (manifest.jsonl) to replay instead of using hardware")
    ap.add_argument("--skip-selfcheck", action="store_true", help="do not run the startup self-check")
    args = ap.parse_args()

    cfg = EdgeConfig()
    if args.trap:
        cfg.trap_id = args.trap
    if cfg.mock_hardware and not args.replay:
        log.warning("MOCK_HARDWARE=1: using sample images and SIMULATED sensor values")
    try:
        service = EdgeService(cfg, replay_dir=Path(args.replay) if args.replay else None)
    except (FileNotFoundError, ValueError) as e:
        raise SystemExit(f"[edge] {e}")
    if not args.skip_selfcheck:
        service.run_selfcheck()

    def stop(*_):
        log.info("Stopping...")
        service.running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    if args.once:
        service.run_cycle()
        service.close()
    else:
        service.run_forever(demo=args.demo, max_cycles=args.cycles)


if __name__ == "__main__":
    main()

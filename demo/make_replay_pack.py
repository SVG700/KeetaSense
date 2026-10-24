"""Build demo/replay/: a SYNTHETIC replay pack recorded from the mock trap.

It runs the edge service in mock mode for one pass over demo/sample_tape/
(12 cycles, no backend needed - everything is recorded before syncing) and
turns the recording into a replay pack. It is only a fallback so replay mode
works out of the box: before the event, record a REAL pack with the Pi
(see edge/PI_SETUP.md step 7) into demo/replay_real/.

Usage:  python -m demo.make_replay_pack
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from edge.config import EdgeConfig
from edge.main import EdgeService
from edge.replay import make_pack

OUT = Path(__file__).resolve().parent / "replay"


def main() -> None:
    logging.basicConfig(level=logging.ERROR)
    work = Path(tempfile.mkdtemp(prefix="keetasense_replay_"))
    try:
        cfg = EdgeConfig()
        cfg.mock_hardware = True
        cfg.data_dir = work
        cfg.backend_url = "http://127.0.0.1:9"   # nothing listens there: items just stay queued
        service = EdgeService(cfg, record=True)
        n = len(service.camera.samples) or 12
        for _ in range(n):
            service.run_cycle()
        service.close()
        count = make_pack(work / "recording" / cfg.trap_id, OUT,
                          note="SYNTHETIC: recorded from the MOCK trap (sample tape drawings, simulated climate). "
                               "Replace with a real recording for the event: edge/PI_SETUP.md step 7.")
        print(f"[replay] SYNTHETIC replay pack with {count} cycles -> {OUT}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()

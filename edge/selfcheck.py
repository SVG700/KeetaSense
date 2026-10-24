"""Quick startup self-check for the edge service.

Before the main loop starts, check each part once (a few seconds in total)
and print a summary table, e.g.

    ┌ KeetaSense edge self-check ─────────────────────────────
    │ PASS  Camera        4056x3040, brightness 132, sharpness 410
    │ PASS  DHT22 sensor  2/2 good reads (100%), last 27.1 °C / 64 %
    │ PASS  Stepper motor pins configured (no movement at startup)
    │ FAIL  Backend link  cannot reach http://192.168.1.20:8000 (ConnectTimeout)
    │ INFO  Detector      Demo detector (synthetic only)
    └ 1 problem(s) - the service will still start; data is queued offline.

The service ALWAYS continues after the check: a missing backend only means
data waits in the offline queue. Full tests: python -m edge.tests_hw.<name>
"""
from __future__ import annotations

import logging

from edge.config import EdgeConfig
from edge.tests_hw import test_backend_link, test_camera, test_dht22
from edge.tests_hw._common import CheckResult

log = logging.getLogger("keetasense.edge.selfcheck")


def run_quick(cfg: EdgeConfig, camera=None, sensor=None, stepper=None, init_errors: dict | None = None,
              check_backend: bool = True, skip_hardware: bool = False) -> list[CheckResult]:
    init_errors = init_errors or {}
    results = []
    if not skip_hardware:
        results += _hardware_checks(cfg, camera, sensor, init_errors)

    if check_backend:
        results.append(test_backend_link.check(cfg, timeout=3, tries=1))

    try:
        from ml import infer
        info = infer.model_info()
        results.append(CheckResult("Detector", True, info["label"], warn=info["mode"] == infer.MODE_DEMO))
    except Exception as e:
        results.append(CheckResult("Detector", False, f"could not load the detector: {e}"))
    return results


def _hardware_checks(cfg: EdgeConfig, camera, sensor, init_errors: dict) -> list[CheckResult]:
    results = []
    if "camera" in init_errors:
        results.append(CheckResult("Camera", False, f"failed to start: {init_errors['camera']}",
                                   hints=test_camera.HINTS))
    else:
        results.append(test_camera.check(cfg, camera=camera))

    if "sensor" in init_errors:
        results.append(CheckResult("DHT22 sensor", False, f"failed to start: {init_errors['sensor']}",
                                   hints=test_dht22.HINTS))
    else:
        results.append(test_dht22.check(cfg, reads=2, sensor=sensor, pause_s=2.0))

    if "stepper" in init_errors:
        results.append(CheckResult("Stepper motor", False, f"failed to start: {init_errors['stepper']}"))
    else:
        results.append(CheckResult("Stepper motor", True,
                                   f"pins {cfg.stepper_pins} configured, {cfg.steps_per_section} half-steps "
                                   "per section (no movement at startup)" + (" (mock)" if cfg.mock_hardware else "")))
    return results


def print_summary(results: list[CheckResult], mock: bool) -> None:
    width = max(len(r.name) for r in results)
    print("\n┌ KeetaSense edge self-check" + (" (MOCK hardware)" if mock else "") + " " + "─" * 30)
    for r in results:
        status = "FAIL" if not r.ok else ("WARN" if r.warn else "PASS")
        print(f"│ {status}  {r.name:<{width}}  {r.summary}")
    problems = [r for r in results if not r.ok]
    if problems:
        print(f"└ {len(problems)} problem(s) - the service will still start; data is queued offline.")
        print("  Details: python -m edge.tests_hw.test_<camera|dht22|stepper|backend_link>\n")
    else:
        print("└ all checks passed\n")
    for r in results:
        log.info("self-check %s: %s - %s", r.name, "ok" if r.ok else "FAIL", r.summary)

"""Hardware test: DHT22 temperature/humidity sensor. Reads 5 times, reports success rate.

    python -m edge.tests_hw.test_dht22 --real
    python -m edge.tests_hw.test_dht22 --real --reads 10
"""
from __future__ import annotations

import argparse
import time

from edge.config import EdgeConfig
from edge.tests_hw._common import CheckResult, add_mock_flag, apply_mock_flag, finish

MIN_SUCCESS = 0.6  # DHT22s miss reads now and then; below 60 % something is wrong

HINTS = [
    "Every read fails: check DATA is on the GPIO in DHT22_PIN (BCM number, default GPIO4 = physical pin 7), "
    "VCC on 3.3 V (pin 1), GND (pin 9).",
    "Bare 4-pin sensor: it needs a 10 kΩ resistor between DATA and 3.3 V.",
    "`No module named adafruit_dht` / `board`: pip install -r edge/requirements-pi.txt.",
    "Some reads fail: normal for DHT22 - the service retries. Keep the cable under ~1 m.",
    "Temperature far too high: the sensor is inside the LED chamber or in the sun - move it out.",
]


def plausible(t: float, h: float) -> bool:
    return -10 <= t <= 60 and 0 <= h <= 100


def check(cfg: EdgeConfig, reads: int = 5, sensor=None, pause_s: float = 2.0) -> CheckResult:
    name = "DHT22 sensor"
    created = sensor is None
    try:
        if sensor is None:
            from edge.hardware import DHT22
            sensor = DHT22(cfg.dht22_pin, mock=cfg.mock_hardware, retries=1)
        ok_reads, details = [], []
        for i in range(1, reads + 1):
            r = sensor.read()
            if r is None:
                details.append(f"read {i}: failed")
            elif not plausible(*r):
                details.append(f"read {i}: {r[0]} °C, {r[1]} % - implausible")
            else:
                ok_reads.append(r)
                details.append(f"read {i}: {r[0]} °C, {r[1]} %")
            if i < reads and not cfg.mock_hardware:
                time.sleep(pause_s)  # the DHT22 needs ~2 s between reads
    except Exception as e:
        return CheckResult(name, False, f"sensor error ({e.__class__.__name__}: {e})", hints=HINTS)
    finally:
        if created and sensor is not None:
            try:
                sensor.close()
            except Exception:
                pass
    rate = len(ok_reads) / reads if reads else 0
    summary = f"{len(ok_reads)}/{reads} good reads ({rate:.0%})"
    if ok_reads:
        summary += f", last {ok_reads[-1][0]} °C / {ok_reads[-1][1]} %"
    return CheckResult(name, rate >= MIN_SUCCESS, summary, details, HINTS, warn=MIN_SUCCESS <= rate < 1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Read the DHT22 several times.")
    ap.add_argument("--reads", type=int, default=5)
    add_mock_flag(ap)
    args = ap.parse_args()
    cfg = EdgeConfig()
    apply_mock_flag(args, cfg)
    finish(check(cfg, max(1, args.reads)))


if __name__ == "__main__":
    main()

"""Link test: can this device reach the KeetaSense backend?

Checks /api/health (3 times, reports latency), that TRAP_ID exists on the
backend, and sends a test climate reading with dry_run=true (validated by the
backend but NOT stored, so it does not change any trap data).

    python -m edge.tests_hw.test_backend_link
    python -m edge.tests_hw.test_backend_link --url http://192.168.1.20:8000
"""
from __future__ import annotations

import argparse
import statistics
import time

import requests

from edge.config import EdgeConfig
from edge.tests_hw._common import CheckResult, finish

SLOW_MS = 1500

HINTS = [
    "Is the backend running on the laptop? Start it with scripts\\start.bat (or scripts/demo.sh).",
    "From a Pi, BACKEND_URL must be the laptop's Wi-Fi IP (e.g. http://192.168.1.20:8000), not 127.0.0.1. "
    "Find it with `ipconfig` (Windows) or `ip a` (Linux).",
    "The backend must listen on the network: start it with KEETA_HOST=0.0.0.0 "
    "(scripts\\start.bat --lan) - by default it only accepts the laptop itself.",
    "Windows firewall: allow Python on private networks (a pop-up appears the first time).",
    "Pi and laptop on the same Wi-Fi? Phone hotspots sometimes isolate clients - try another network.",
    "TRAP_ID unknown: it must match an id in config/traps.yaml on the laptop.",
]


def check(cfg: EdgeConfig, url: str | None = None, timeout: float = 5.0, tries: int = 3) -> CheckResult:
    name = "Backend link"
    url = (url or cfg.backend_url).rstrip("/")
    details = [f"backend URL: {url}", f"trap id: {cfg.trap_id}"]
    latencies = []
    try:
        for _ in range(tries):
            t0 = time.perf_counter()
            r = requests.get(f"{url}/api/health", timeout=timeout)
            latencies.append((time.perf_counter() - t0) * 1000)
            r.raise_for_status()
        health = r.json()
        details.append(f"health: {health.get('status')}, detector: "
                       f"{(health.get('detector') or {}).get('label', health.get('detector_mode'))}")
        details.append("latency ms: " + ", ".join(f"{x:.0f}" for x in latencies))

        traps = [t["id"] for t in requests.get(f"{url}/api/traps", timeout=timeout).json()]
        if cfg.trap_id not in traps:
            return CheckResult(name, False, f"trap '{cfg.trap_id}' not known by the backend (known: {traps})",
                               details, HINTS)
        r = requests.post(f"{url}/api/climate", params={"dry_run": "true"}, timeout=timeout,
                          json={"trap_id": cfg.trap_id, "temperature_c": 25.0, "humidity_pct": 60.0})
        r.raise_for_status()
        details.append("test reading accepted (dry run, not stored)")
    except requests.RequestException as e:
        return CheckResult(name, False, f"cannot reach {url} ({e.__class__.__name__})", details, HINTS)
    median = statistics.median(latencies)
    summary = f"reachable, median latency {median:.0f} ms"
    return CheckResult(name, True, summary, details, HINTS, warn=median > SLOW_MS)


def main() -> None:
    ap = argparse.ArgumentParser(description="Check the connection to the backend.")
    ap.add_argument("--url", help="override BACKEND_URL")
    args = ap.parse_args()
    finish(check(EdgeConfig(), args.url))


if __name__ == "__main__":
    main()

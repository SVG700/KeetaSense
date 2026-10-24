"""Shared bits for the hardware test scripts: a result type and PASS/FAIL printing."""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    name: str
    ok: bool
    summary: str                                    # one line, shown in the self-check table
    details: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)  # shown only on FAIL
    warn: bool = False                              # passed, but something looks off


def print_result(r: CheckResult) -> None:
    status = "PASS" if r.ok and not r.warn else ("WARN" if r.ok else "FAIL")
    bar = "=" * 64
    print(bar)
    print(f" {status}  {r.name}: {r.summary}")
    print(bar)
    for d in r.details:
        print(f"   {d}")
    if r.hints and (not r.ok or r.warn):
        print("\n Troubleshooting:")
        for h in r.hints:
            print(f"   - {h}")
    print()


def finish(r: CheckResult) -> None:
    """Print the result and exit with 0 (PASS/WARN) or 1 (FAIL) - handy in shell scripts."""
    print_result(r)
    sys.exit(0 if r.ok else 1)


def add_mock_flag(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--mock", action="store_true", help="force mock hardware (try the script on a laptop)")
    ap.add_argument("--real", action="store_true", help="force real hardware even if MOCK_HARDWARE=1")


def apply_mock_flag(args, cfg) -> None:
    if args.mock:
        cfg.mock_hardware = True
    elif args.real:
        cfg.mock_hardware = False
    if cfg.mock_hardware:
        print(f"[note] MOCK hardware ({'--mock' if args.mock else 'MOCK_HARDWARE=' + os.environ.get('MOCK_HARDWARE', '1')})"
              " - nothing real is being tested. Use --real on the Pi.\n")

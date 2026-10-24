"""Hardware test: 28BYJ-48 stepper via ULN2003. Turns forward and/or back.

    python -m edge.tests_hw.test_stepper --real                       # 512 half-steps forward, then back
    python -m edge.tests_hw.test_stepper --real --steps 4096 --direction forward   # one full turn
    python -m edge.tests_hw.test_stepper --real --delay 0.003         # slower = more torque

512 half-steps = 1/8 turn of the output shaft. Watch the shaft (put a bit of
tape on it as a pointer) and the 4 LEDs on the ULN2003 board.
"""
from __future__ import annotations

import argparse
import time

from edge.config import EdgeConfig
from edge.tests_hw._common import CheckResult, add_mock_flag, apply_mock_flag, finish

HINTS = [
    "Nothing moves and the ULN2003 LEDs stay dark: check IN1-IN4 wiring to the GPIO pins in STEPPER_PINS "
    "(BCM numbers!) and that the board has 5 V and GND.",
    "LEDs blink but the shaft does not turn: the motor needs more current - power the ULN2003 from a "
    "separate 5 V supply (common GND with the Pi), or slow down with --delay 0.003.",
    "Shaft vibrates / turns back and forth: the pin order is wrong - swap the middle two pins in STEPPER_PINS.",
    "Turns the wrong way: use --direction backward or reverse the pin order in STEPPER_PINS.",
    "`No module named RPi`: pip install -r edge/requirements-pi.txt (Pi 5 needs rpi-lgpio).",
    "Pi 5 'Cannot determine SOC peripheral base address': uninstall RPi.GPIO, install rpi-lgpio.",
]


def check(cfg: EdgeConfig, steps: int = 512, delay: float | None = None, direction: str = "both",
          stepper=None) -> CheckResult:
    name = "Stepper motor"
    created = stepper is None
    try:
        if stepper is None:
            from edge.hardware import Stepper
            stepper = Stepper(cfg.stepper_pins, cfg.steps_per_section, delay or cfg.step_delay_s,
                              mock=cfg.mock_hardware)
        elif delay:
            stepper.step_delay_s = delay
        moves = {"forward": [steps], "backward": [-steps], "both": [steps, -steps]}[direction]
        details = [f"pins (BCM) IN1-IN4: {cfg.stepper_pins}", f"delay per half-step: {stepper.step_delay_s} s"]
        for n in moves:
            t0 = time.time()
            if cfg.mock_hardware:
                stepper.total_steps += abs(n)  # mock: count only
            else:
                stepper.step(n)
            dt = time.time() - t0
            details.append(f"{'forward ' if n > 0 else 'backward'} {abs(n)} half-steps in {dt:.2f} s"
                           + (f" ({abs(n) / dt:.0f} steps/s)" if dt > 0 else ""))
    except Exception as e:
        return CheckResult(name, False, f"error driving the motor ({e.__class__.__name__}: {e})", hints=HINTS)
    finally:
        if created and stepper is not None:
            try:
                stepper.close()
            except Exception:
                pass
    details.append("Did the shaft turn smoothly and come back to the start? If not, see the hints below.")
    return CheckResult(name, True, f"{direction} {steps} half-steps sent" + (" (mock)" if cfg.mock_hardware else ""),
                       details, HINTS, warn=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Turn the stepper forward/back.")
    ap.add_argument("--steps", type=int, default=512, help="half-steps (4096 = one output-shaft turn)")
    ap.add_argument("--delay", type=float, help="seconds per half-step (default STEP_DELAY_S, 0.0015)")
    ap.add_argument("--direction", choices=["forward", "backward", "both"], default="both")
    add_mock_flag(ap)
    args = ap.parse_args()
    if args.delay is not None and not 0.0008 <= args.delay <= 0.05:
        raise SystemExit("--delay must be between 0.0008 and 0.05 s (too fast = the motor stalls)")
    cfg = EdgeConfig()
    apply_mock_flag(args, cfg)
    r = check(cfg, args.steps, args.delay, args.direction)
    finish(r)


if __name__ == "__main__":
    main()

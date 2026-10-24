"""Interactive tape calibration: find STEPS_PER_SECTION.

The goal: one tape advance must bring a completely fresh, unused piece of tape
under the camera - no overlap with the previous photo, and not much waste.

How it works:
  1. Mark the tape (a pen line at the top edge of the camera view) or note an insect.
  2. Advance the tape in small steps. After every step a photo is saved in
     edge/data/calibration/ so you can see where the mark has moved to.
  3. When the mark has just left the camera view, the total number of
     half-steps so far is one tape section. Save it - it goes into .env as
     STEPS_PER_SECTION (the old .env is kept as .env.bak).

Commands (type and press Enter):
  <Enter>     advance by the current step size and take a photo
  b           go back by the current step size (and take a photo)
  <number>    set the step size (half-steps), e.g. 128
  r           reset the counter to 0 (tape position = new start)
  s           save the counter as STEPS_PER_SECTION in .env
  q           quit without saving

    python -m edge.calibrate_tape --real
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import cv2

from edge.config import ROOT, EdgeConfig
from edge.tests_hw._common import add_mock_flag, apply_mock_flag


def set_env_value(env_file: Path, key: str, value: str) -> None:
    """Set KEY=value in a .env file (replace the line or append it). Keeps a .bak copy."""
    if not env_file.exists():
        example = env_file.with_name(".env.example")
        if example.exists():
            shutil.copy2(example, env_file)
        else:
            env_file.write_text("")
    shutil.copy2(env_file, env_file.with_name(env_file.name + ".bak"))
    lines = env_file.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Interactively find STEPS_PER_SECTION.")
    ap.add_argument("--step", type=int, default=256, help="initial step size in half-steps")
    ap.add_argument("--env", default=str(ROOT / ".env"), help=".env file to update")
    add_mock_flag(ap)
    args = ap.parse_args()
    cfg = EdgeConfig()
    apply_mock_flag(args, cfg)

    from edge.hardware import Camera, Stepper
    stepper = Stepper(cfg.stepper_pins, cfg.steps_per_section, cfg.step_delay_s, mock=cfg.mock_hardware)
    camera = Camera(mock=cfg.mock_hardware, sample_dir=cfg.sample_dir, led_pin=cfg.led_pin)
    out_dir = cfg.data_dir / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    step, total, shot = args.step, 0, 0

    def photo():
        nonlocal shot
        shot += 1
        path = out_dir / f"{shot:03d}_steps_{total:+06d}.jpg"
        img = camera.capture()
        h, w = img.shape[:2]
        cv2.line(img, (0, h // 2), (w, h // 2), (0, 0, 255), max(1, w // 400))  # reference line
        cv2.putText(img, f"total {total} half-steps", (10, max(30, h // 20)), cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.8, w / 1500), (0, 0, 255), max(2, w // 600))
        cv2.imwrite(str(path), img)
        print(f"   photo -> {path}")

    print(__doc__.split("Commands")[1] if "Commands" in __doc__ else "")
    print(f"Current STEPS_PER_SECTION = {cfg.steps_per_section}. Photos go to {out_dir}\n")
    photo()
    try:
        while True:
            cmd = input(f"[total {total:+d} | step {step}] > ").strip().lower()
            if cmd == "":
                stepper.step(step)
                total += step
                photo()
            elif cmd == "b":
                stepper.step(-step)
                total -= step
                photo()
            elif cmd.isdigit() and int(cmd) > 0:
                step = int(cmd)
            elif cmd == "r":
                total = 0
                print("   counter reset to 0")
            elif cmd == "s":
                if total <= 0:
                    print("   advance forward first (the counter must be > 0)")
                    continue
                set_env_value(Path(args.env), "STEPS_PER_SECTION", str(total))
                print(f"   saved STEPS_PER_SECTION={total} to {args.env} (old file: .env.bak)")
                break
            elif cmd == "q":
                print("   quit without saving")
                break
            else:
                print("   commands: Enter, b, <number>, r, s, q")
    except (KeyboardInterrupt, EOFError):
        print("\n   stopped without saving")
    finally:
        stepper.close()
        camera.close()


if __name__ == "__main__":
    main()

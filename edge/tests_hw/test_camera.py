"""Hardware test: camera. Captures one image, saves it, reports resolution,
brightness and sharpness (focus).

    python -m edge.tests_hw.test_camera                 # uses MOCK_HARDWARE from .env
    python -m edge.tests_hw.test_camera --real --out edge/data/hw_test/cam.jpg
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import cv2

from edge.config import EdgeConfig
from edge.tests_hw._common import CheckResult, add_mock_flag, apply_mock_flag, finish

MIN_BRIGHTNESS, MAX_BRIGHTNESS = 40, 225   # mean grey level 0-255
# Variance of the Laplacian (edge strength). Plain yellow tape has little texture, so even a sharp
# photo scores low; use this number to COMPARE focus settings (higher = sharper).
MIN_SHARPNESS = float(os.environ.get("CAMERA_MIN_SHARPNESS", 10))

NO_CAMERA_HINTS = [
    "Run `rpicam-hello --list-cameras` - if no camera is listed, check the ribbon cable "
    "(blue side towards the Ethernet port on Pi 4 / towards the board edge on Pi 5) and reboot.",
    "Is `python3-picamera2` installed (sudo apt install python3-picamera2) and was the venv "
    "created with --system-site-packages?",
]
PROBLEM_HINTS = {
    "too dark": "Too dark: check the LEDs (LED_PIN in .env, MOSFET/relay wiring) and that the chamber lid is closed.",
    "too bright": "Too bright / washed out: LEDs too close or reflecting - add a diffuser (tracing paper).",
    "blurry": "Blurry: Camera Module 3 focuses automatically; older modules need the lens turned by hand "
              "for the tape distance. Also make sure the tape is flat and not moving. Compare the sharpness "
              "number between attempts - higher is better.",
}
HINTS = NO_CAMERA_HINTS + list(PROBLEM_HINTS.values())


def measure(img) -> dict:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return {"width": img.shape[1], "height": img.shape[0],
            "brightness": float(gray.mean()),
            "sharpness": float(cv2.Laplacian(gray, cv2.CV_64F).var())}


def check(cfg: EdgeConfig, camera=None, out: Path | None = None) -> CheckResult:
    name = "Camera"
    created = camera is None
    try:
        if camera is None:
            from edge.hardware import Camera
            camera = Camera(mock=cfg.mock_hardware, sample_dir=cfg.sample_dir, led_pin=cfg.led_pin)
        img = camera.capture()
    except Exception as e:
        return CheckResult(name, False, f"could not capture ({e.__class__.__name__}: {e})", hints=NO_CAMERA_HINTS)
    finally:
        if created and camera is not None:
            try:
                camera.close()
            except Exception:
                pass
    if img is None or img.size == 0:
        return CheckResult(name, False, "camera returned an empty image", hints=HINTS)
    m = measure(img)
    details = [f"resolution: {m['width']} x {m['height']}",
               f"brightness: {m['brightness']:.0f} (good: {MIN_BRIGHTNESS}-{MAX_BRIGHTNESS})",
               f"sharpness:  {m['sharpness']:.0f} (good: > {MIN_SHARPNESS})"]
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        details.append(f"saved: {out}")
    problems = []
    if not MIN_BRIGHTNESS <= m["brightness"] <= MAX_BRIGHTNESS:
        problems.append("too dark" if m["brightness"] < MIN_BRIGHTNESS else "too bright")
    if m["sharpness"] < MIN_SHARPNESS:
        problems.append("blurry")
    summary = f"{m['width']}x{m['height']}, brightness {m['brightness']:.0f}, sharpness {m['sharpness']:.0f}"
    if problems:
        return CheckResult(name, True, summary + " - " + ", ".join(problems), details,
                           [PROBLEM_HINTS[p] for p in problems], warn=True)
    return CheckResult(name, True, summary, details, HINTS)


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture one test image and check it.")
    ap.add_argument("--out", default="edge/data/hw_test/camera_test.jpg")
    add_mock_flag(ap)
    args = ap.parse_args()
    cfg = EdgeConfig()
    apply_mock_flag(args, cfg)
    finish(check(cfg, out=Path(args.out)))


if __name__ == "__main__":
    main()

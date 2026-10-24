"""Camera inside the dark chamber.

Real mode: Raspberry Pi camera via picamera2, LEDs switched on for the shot.
Mock mode: cycles through the images in demo/sample_tape/ (SYNTHETIC tape
images), so the whole system can be demonstrated on any laptop.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("keetasense.edge.camera")

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


class Camera:
    def __init__(self, mock: bool = True, sample_dir: Path | None = None, led_pin: int | None = None,
                 resolution: tuple[int, int] = (4056, 3040)):
        self.mock = mock
        self.led_pin = led_pin
        self.index = 0
        self.samples: list[Path] = []
        self.picam = None
        self.gpio = None
        if mock:
            if sample_dir and sample_dir.exists():
                self.samples = sorted(p for p in sample_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
            if not self.samples:
                log.warning("[MOCK camera] no images in %s - will generate synthetic ones "
                            "(run python -m demo.generate_sample_tape)", sample_dir)
            return
        from picamera2 import Picamera2  # lazy: Pi-only library
        self.picam = Picamera2()
        self.picam.configure(self.picam.create_still_configuration(main={"size": resolution, "format": "RGB888"}))
        self.picam.start()
        time.sleep(2)  # let auto-exposure settle
        if led_pin is not None:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(led_pin, GPIO.OUT, initial=GPIO.LOW)
            self.gpio = GPIO

    def capture(self) -> np.ndarray:
        """Return one BGR image of the current tape section."""
        if self.mock:
            return self._mock_capture()
        if self.gpio:
            self.gpio.output(self.led_pin, 1)
            time.sleep(0.5)  # LEDs reach full brightness
        try:
            # "RGB888" in picamera2 is actually stored B,G,R - exactly what OpenCV wants
            return self.picam.capture_array("main")
        finally:
            if self.gpio:
                self.gpio.output(self.led_pin, 0)

    def _mock_capture(self) -> np.ndarray:
        if self.samples:
            path = self.samples[self.index % len(self.samples)]
            self.index += 1
            img = cv2.imread(str(path))
            if img is not None:
                log.info("[MOCK camera] using %s", path.name)
                return img
            log.error("[MOCK camera] could not read %s", path)
        from ml.synthetic import random_counts, render_tape  # fallback: draw one now
        import random
        self.index += 1
        img, _ = render_tape(random_counts(random.Random(self.index)), 1280, 800, seed=self.index)
        log.info("[MOCK camera] generated a synthetic tape image")
        return img

    def close(self) -> None:
        if self.picam:
            self.picam.stop()

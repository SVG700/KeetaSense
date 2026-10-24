"""28BYJ-48 stepper motor driven through a ULN2003 board - advances the tape.

The motor has 4 coils. The ULN2003 board switches them on from 4 GPIO pins
(IN1..IN4). Energising the coils in the "half-step" order below turns the
shaft one half-step at a time. The 28BYJ-48 needs about 4096 half-steps
for one full turn of the output shaft (it has a 1:64 gearbox).

STEPS_PER_SECTION (in .env) = how many half-steps move the tape by exactly
one fresh section - calibrate it on your trap (see edge/PI_SETUP.md).
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("keetasense.edge.stepper")

# Each row = which of IN1, IN2, IN3, IN4 are ON for that half-step.
HALF_STEP_SEQUENCE = [
    (1, 0, 0, 0),
    (1, 1, 0, 0),
    (0, 1, 0, 0),
    (0, 1, 1, 0),
    (0, 0, 1, 0),
    (0, 0, 1, 1),
    (0, 0, 0, 1),
    (1, 0, 0, 1),
]


class Stepper:
    def __init__(self, pins: list[int], steps_per_section: int, step_delay_s: float = 0.0015,
                 mock: bool = True):
        if len(pins) != 4:
            raise ValueError("STEPPER_PINS needs exactly 4 GPIO numbers (IN1..IN4)")
        self.pins = pins
        self.steps_per_section = steps_per_section
        self.step_delay_s = step_delay_s
        self.mock = mock
        self.position = 0          # index into HALF_STEP_SEQUENCE
        self.total_steps = 0       # for logging / tests
        self.gpio = None
        if not mock:
            import RPi.GPIO as GPIO  # lazy: only exists on a Raspberry Pi
            GPIO.setmode(GPIO.BCM)
            for p in pins:
                GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
            self.gpio = GPIO

    def step(self, n: int) -> None:
        """Move n half-steps (negative = backwards)."""
        direction = 1 if n >= 0 else -1
        for _ in range(abs(n)):
            self.position = (self.position + direction) % len(HALF_STEP_SEQUENCE)
            if self.gpio:
                for pin, value in zip(self.pins, HALF_STEP_SEQUENCE[self.position]):
                    self.gpio.output(pin, value)
                time.sleep(self.step_delay_s)
            self.total_steps += 1
        self.release()

    def release(self) -> None:
        """Switch all coils off so the motor does not heat up while idle."""
        if self.gpio:
            for p in self.pins:
                self.gpio.output(p, 0)

    def advance_section(self) -> None:
        if self.mock:
            log.info("[MOCK stepper] advancing tape by %d half-steps (pins %s)",
                     self.steps_per_section, self.pins)
            self.total_steps += self.steps_per_section
            return
        log.info("Advancing tape by %d half-steps", self.steps_per_section)
        self.step(self.steps_per_section)

    def close(self) -> None:
        if self.gpio:
            self.release()
            self.gpio.cleanup(self.pins)

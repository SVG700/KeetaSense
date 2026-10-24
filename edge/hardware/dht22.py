"""DHT22 temperature / humidity sensor.

Real mode: reads the sensor with the Adafruit CircuitPython library. The
DHT22 often fails a single read (timing-sensitive), so we retry a few times.
Mock mode: returns realistic simulated values - a daily temperature cycle
(coolest around 05:00, warmest around 14:00) plus a little noise.
"""
from __future__ import annotations

import logging
import math
import random
import time
from datetime import datetime

log = logging.getLogger("keetasense.edge.dht22")


def simulated_reading(now: datetime | None = None, rng: random.Random | None = None) -> tuple[float, float]:
    """Plausible polyhouse climate for Bengaluru: ~19-31 C, humidity 50-85 %."""
    now = now or datetime.now()
    rng = rng or random
    hour = now.hour + now.minute / 60
    # cosine with its peak at 14:00 and minimum at 02:00 (close enough to dawn)
    daily = math.cos((hour - 14) / 24 * 2 * math.pi)
    temp = 25 + 6 * daily + rng.gauss(0, 0.4)
    humidity = 67 - 15 * daily + rng.gauss(0, 1.5)
    return round(temp, 1), round(min(100, max(0, humidity)), 1)


class DHT22:
    def __init__(self, pin: int, mock: bool = True, retries: int = 5):
        self.mock = mock
        self.retries = retries
        self.sensor = None
        if not mock:
            import adafruit_dht  # lazy: Pi-only library
            import board
            self.sensor = adafruit_dht.DHT22(getattr(board, f"D{pin}"), use_pulseio=False)

    def read(self) -> tuple[float, float] | None:
        """Return (temperature_c, humidity_pct), or None if the sensor keeps failing."""
        if self.mock:
            t, h = simulated_reading()
            log.info("[MOCK DHT22] %.1f C, %.1f %%", t, h)
            return t, h
        for attempt in range(1, self.retries + 1):
            try:
                t, h = self.sensor.temperature, self.sensor.humidity
                if t is not None and h is not None:
                    return round(float(t), 1), round(float(h), 1)
            except RuntimeError as e:  # normal for DHT sensors: just try again
                log.debug("DHT22 read %d failed: %s", attempt, e)
            time.sleep(2)  # the DHT22 needs ~2 s between reads
        log.error("DHT22: no valid reading after %d attempts", self.retries)
        return None

    def close(self) -> None:
        if self.sensor:
            self.sensor.exit()

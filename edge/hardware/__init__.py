"""Hardware abstraction layer: camera, stepper motor and DHT22 sensor.

Every class takes mock=True/False. In mock mode (MOCK_HARDWARE=1, the default)
nothing Pi-specific is imported, so the code runs on Windows, Mac and Linux.
"""
from edge.hardware.camera import Camera
from edge.hardware.dht22 import DHT22
from edge.hardware.stepper import Stepper

__all__ = ["Camera", "DHT22", "Stepper"]

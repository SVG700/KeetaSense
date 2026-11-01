"""Fault injection for the MOCK trap - demo the image quality gate (and trap health) without a Pi.

    python -m edge.main --demo --inject blur     (or dark, glare, stuck, motor)
    scripts\\demo.bat --inject blur

  blur   the photo is out of focus           -> quality BAD "image blurred"
  dark   the LEDs did not switch on           -> quality BAD "image too dark"
  glare  a strong reflection on the tape      -> quality BAD "glare on the tape"
  stuck  the motor did not advance the tape   -> the same section is photographed again
         ("tape did not advance")
  motor  the motor reports a fault            -> trap health alert (also implies "stuck")
Only used in mock mode; every injected photo is still a SIMULATED image.
"""
from __future__ import annotations

import cv2
import numpy as np

FAULTS = ("blur", "dark", "glare", "stuck", "motor")


def degrade(img: np.ndarray, kind: str) -> np.ndarray:
    if kind == "blur":
        return cv2.GaussianBlur(img, (15, 15), 0)
    if kind == "dark":
        return (img.astype(np.float32) * 0.15).astype(np.uint8)
    if kind == "glare":
        out = img.copy()
        h, w = out.shape[:2]
        cv2.ellipse(out, (w // 2, h // 2), (int(w * 0.28), int(h * 0.3)), 0, 0, 360, (255, 255, 255), -1)
        return cv2.GaussianBlur(out, (3, 3), 0)
    return img

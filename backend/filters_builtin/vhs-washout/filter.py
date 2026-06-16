"""VHS washout — always-on desaturation + slight black lift.

Ported from apply_color_washout in vhs_glitch.py: lower saturation and lift the
value channel slightly for that aged-tape look. Constant effect, no beat band.
"""
import numpy as np
import cv2

PARAMS = [
    {"key": "amount", "type": "slider", "label": "Amount",
     "min": 0, "max": 0.6, "step": 0.01, "default": 0.15},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    amount = p["amount"]
    if amount <= 0:
        return frame

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] *= (1.0 - amount)                                   # lower saturation
    hsv[:, :, 2] = hsv[:, :, 2] * (1.0 - amount * 0.3) + amount * 20  # slight lift
    hsv = np.clip(hsv, 0, 255).astype(np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

"""G-funk sunset grade — warm West Coast grade + contrast S-curve (always on)."""
import numpy as np
import cv2

PARAMS = [
    {"key": "warmth", "type": "slider", "label": "Warmth",
     "min": 0, "max": 2, "step": 0.05, "default": 0.6},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    warmth = p["warmth"]
    if warmth <= 0:
        return frame

    out = frame.astype(np.float32)
    b, g, r = out[:, :, 0], out[:, :, 1], out[:, :, 2]

    # Push reds/yellows up (warm highlights), cool the blues
    r += 15 * warmth
    g += 5 * warmth
    b -= 8 * warmth

    out = np.clip(out, 0, 255).astype(np.uint8)

    # Slight contrast S-curve
    lut = np.arange(256, dtype=np.float32) / 255.0
    lut = (lut - 0.5) * (1.0 + 0.2 * warmth) + 0.5
    lut = np.clip(lut * 255, 0, 255).astype(np.uint8)
    out = cv2.LUT(out, lut)

    return out

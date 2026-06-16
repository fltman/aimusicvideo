"""Lola saturation pump — beat-synced HSV saturation boost."""
import numpy as np
import cv2

PARAMS = [
    {"key": "saturation", "type": "slider", "label": "Saturation boost",
     "min": 1.0, "max": 4.0, "step": 0.05, "default": 2.0},
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 3, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "Drive band",
     "options": ["bass", "mid", "high"], "default": "mid"},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame

    env = getattr(ctx, p["band"]) * p["intensity"]
    if env <= 0.001:
        return frame

    # Lerp saturation multiplier from 1.0 (no boost) up to `saturation` by env.
    mult = 1.0 + (p["saturation"] - 1.0) * min(1.0, env)
    if mult <= 1.001:
        return frame

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * mult, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

"""G-funk color wash — purple/gold/green cyclic overlay, phase advances over time."""
import numpy as np
import cv2

PARAMS = [
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 3, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "Drive band",
     "options": ["bass", "mid", "high"], "default": "mid"},
    {"key": "cycle_speed", "type": "slider", "label": "Cycle speed",
     "min": 0, "max": 1, "step": 0.01, "default": 0.1},
    {"key": "max_alpha", "type": "slider", "label": "Max blend",
     "min": 0, "max": 1, "step": 0.01, "default": 0.25},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    env = getattr(ctx, p["band"])
    if env <= 0.01:
        return frame

    intensity = env * p["intensity"]

    # Three signature colors (BGR)
    purple = np.array([180, 40, 160], dtype=np.float32)   # deep purple
    gold = np.array([30, 180, 240], dtype=np.float32)     # warm gold
    green = np.array([80, 180, 50], dtype=np.float32)     # chronic green

    # Advance the cycle phase from time so it keeps moving.
    phase = (ctx.t * p["cycle_speed"]) % 1.0
    if phase < 0.333:
        t = phase / 0.333
        color = purple * (1 - t) + gold * t
    elif phase < 0.666:
        t = (phase - 0.333) / 0.333
        color = gold * (1 - t) + green * t
    else:
        t = (phase - 0.666) / 0.334
        color = green * (1 - t) + purple * t

    overlay = np.full_like(frame, color, dtype=np.uint8)
    alpha = float(np.clip(p["max_alpha"] * intensity, 0.0, 1.0))
    if alpha <= 0:
        return frame
    return cv2.addWeighted(frame, 1.0 - alpha, overlay, alpha, 0)

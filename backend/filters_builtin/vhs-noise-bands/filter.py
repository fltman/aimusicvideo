"""VHS noise bands — beat-driven horizontal static-noise dropout streaks.

Ported from glitch_noise_bands in vhs_glitch.py: blend random horizontal bands
of full-range static over the frame, count/height/alpha scaled by the beat.
"""
import numpy as np
import cv2

PARAMS = [
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 3, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "Drive band",
     "options": ["bass", "mid", "high"], "default": "high"},
    {"key": "bands", "type": "knob", "label": "Max bands",
     "min": 1, "max": 12, "step": 1, "default": 5},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    env = getattr(ctx, p["band"])
    if env <= 0.01:
        return frame

    intensity = env * p["intensity"]
    h, w = frame.shape[:2]
    out = frame
    rng = ctx.rng

    max_bands = max(1, int(p["bands"]))
    num_bands = int(rng.integers(1, max_bands + 1))

    for _ in range(num_bands):
        bh = int(rng.integers(1, max(2, int(6 * intensity) + 2)))
        y0 = int(rng.integers(0, max(1, h - bh)))
        y1 = min(y0 + bh, h)
        noise = rng.integers(0, 256, size=(y1 - y0, w, 3), dtype=np.uint8)
        alpha = min(1.0, 0.3 + 0.7 * intensity)
        out[y0:y1] = cv2.addWeighted(out[y0:y1], 1 - alpha, noise, alpha, 0)

    return out

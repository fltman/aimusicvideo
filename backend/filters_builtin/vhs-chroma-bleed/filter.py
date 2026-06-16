"""VHS chroma bleed — beat-driven RGB channel separation (chromatic aberration).

Ported from glitch_color_separation in vhs_glitch.py: offset the red and blue
channels horizontally by a random amount scaled by the beat envelope.
"""
import numpy as np
import cv2

PARAMS = [
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 3, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "Drive band",
     "options": ["bass", "mid", "high"], "default": "mid"},
    {"key": "spread", "type": "slider", "label": "Max spread",
     "min": 0.005, "max": 0.15, "step": 0.005, "default": 0.04},
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
    rng = ctx.rng

    max_offset = int(w * p["spread"] * intensity)
    if max_offset < 1:
        return frame

    b, g, r = cv2.split(frame)
    r_shift = int(rng.integers(-max_offset, max_offset + 1))
    b_shift = int(rng.integers(-max_offset, max_offset + 1))
    r = np.roll(r, r_shift, axis=1)
    b = np.roll(b, b_shift, axis=1)
    return cv2.merge([b, g, r])

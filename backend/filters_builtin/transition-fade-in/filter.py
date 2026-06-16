"""Fade in from black over the start of the effect clip (uses ctx.clip_progress)."""
import numpy as np

PARAMS = [
    {"key": "fade", "type": "slider", "label": "Fade portion",
     "min": 0.05, "max": 1.0, "step": 0.05, "default": 0.4},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    k = min(1.0, ctx.clip_progress / max(0.001, p["fade"]))
    if k >= 1.0:
        return frame
    return (frame.astype(np.float32) * k).astype(np.uint8)

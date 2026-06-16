"""Dip to black: fade out then back in across the effect clip (ctx.clip_progress)."""
import numpy as np

PARAMS = [
    {"key": "depth", "type": "slider", "label": "Depth",
     "min": 0.2, "max": 1.0, "step": 0.05, "default": 1.0},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    # 1 at the edges, 0 at the centre → darkest in the middle of the clip
    edge = abs(ctx.clip_progress - 0.5) * 2.0
    k = 1.0 - p["depth"] * (1.0 - edge)
    if k >= 1.0:
        return frame
    return (frame.astype(np.float32) * max(0.0, k)).astype(np.uint8)

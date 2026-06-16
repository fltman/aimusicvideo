"""Empty filter — a starting point for new effects.

Returns the frame unchanged. Wire `ctx.bass/mid/high` (0..1 beat envelopes) into
a transform of `frame`, exposing controls via PARAMS. See FILTER_CONTRACT.md.
"""
import numpy as np  # noqa: F401  (handy for new effects)
import cv2  # noqa: F401

PARAMS = [
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 2, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "React to",
     "options": ["bass", "mid", "high"], "default": "bass"},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    # env = getattr(ctx, p["band"])      # 0..1 beat envelope this frame
    # amount = env * p["intensity"]
    # ... transform `frame` here ...
    return frame

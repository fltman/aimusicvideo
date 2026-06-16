"""VHS scanlines — always-on faint scanline overlay.

Ported from apply_scanlines in vhs_glitch.py: darken every other row by an
opacity factor. Constant effect, no beat band.
"""
import numpy as np

PARAMS = [
    {"key": "opacity", "type": "slider", "label": "Opacity",
     "min": 0, "max": 0.6, "step": 0.01, "default": 0.12},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    opacity = p["opacity"]
    if opacity <= 0:
        return frame

    out = frame.astype(np.float32)
    out[::2] *= (1.0 - opacity)
    return np.clip(out, 0, 255).astype(np.uint8)

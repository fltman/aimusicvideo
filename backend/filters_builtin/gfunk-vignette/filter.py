"""G-funk vignette — soft oval darkened edges (always on)."""
import numpy as np

PARAMS = [
    {"key": "strength", "type": "slider", "label": "Strength",
     "min": 0, "max": 1, "step": 0.02, "default": 0.4},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    strength = p["strength"]
    if strength <= 0:
        return frame

    h, w = ctx.h, ctx.w
    # Precompute the oval falloff mask once per call from ctx.w/h.
    Y, X = np.ogrid[:h, :w]
    cy, cx = h / 2, w / 2
    mask = ((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2
    mask = np.clip(mask, 0, 1)
    mask = mask ** 0.8  # soften falloff
    darken = (1.0 - mask * strength)
    darken = darken[:, :, np.newaxis].astype(np.float32)

    out = frame.astype(np.float32) * darken
    return np.clip(out, 0, 255).astype(np.uint8)

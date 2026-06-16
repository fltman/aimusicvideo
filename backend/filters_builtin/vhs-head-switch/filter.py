"""VHS head switch — bottom-of-frame head-switching bar on strong beats.

Ported from glitch_head_switch in vhs_glitch.py: on a strong hit, displace the
bottom bar horizontally and blend noise into it. The render pipeline only
triggered this above an envelope threshold, so we keep a 'threshold' gate.
"""
import numpy as np

PARAMS = [
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 3, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "Drive band",
     "options": ["bass", "mid", "high"], "default": "high"},
    {"key": "threshold", "type": "slider", "label": "Trigger threshold",
     "min": 0, "max": 1, "step": 0.05, "default": 0.3},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    env = getattr(ctx, p["band"])
    if env <= p["threshold"]:
        return frame

    intensity = env * p["intensity"]
    h, w = frame.shape[:2]
    out = frame
    rng = ctx.rng

    bar_h = int(h * (0.02 + 0.08 * intensity))
    if bar_h < 1:
        return out
    y0 = h - bar_h

    # Shift the bottom bar significantly
    shift = int(rng.integers(int(-w * 0.3), int(w * 0.3) + 1))
    out[y0:] = np.roll(out[y0:], shift, axis=1)

    # Add some noise on top
    noise = rng.integers(0, 256, size=(bar_h, w, 3), dtype=np.uint8)
    out[y0:] = (out[y0:].astype(np.float32) * 0.5 + noise.astype(np.float32) * 0.5)
    out[y0:] = np.clip(out[y0:], 0, 255).astype(np.uint8)

    return out

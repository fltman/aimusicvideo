"""Lola high flash — beat-synced white tint / color invert / vignette pulse."""
import numpy as np
import cv2

PARAMS = [
    {"key": "mode", "type": "select", "label": "Flash mode",
     "options": ["tint", "invert", "vignette"], "default": "tint"},
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 3, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "Drive band",
     "options": ["bass", "mid", "high"], "default": "high"},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]

# Cached radial vignette mask keyed by frame size (per-process, cheap to rebuild).
_VIG_CACHE = {}


def _vignette_mask(h, w):
    key = (h, w)
    m = _VIG_CACHE.get(key)
    if m is None:
        yy, xx = np.ogrid[0:h, 0:w]
        cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
        dist = np.sqrt(((xx - cx) / (cx + 1e-6)) ** 2 + ((yy - cy) / (cy + 1e-6)) ** 2)
        # 0 at center, ramps to 1 toward the corners (clamped).
        m = np.clip(dist, 0.0, 1.0).astype(np.float32)
        _VIG_CACHE[key] = m
    return m


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame

    env = getattr(ctx, p["band"]) * p["intensity"]
    if env <= 0.001:
        return frame
    amt = min(1.0, env)

    mode = p["mode"]

    if mode == "invert":
        # Blend toward inverted colors by `amt` (full invert at a strong hit).
        inv = 255 - frame
        out = frame.astype(np.float32) * (1.0 - amt) + inv.astype(np.float32) * amt
        return out.astype(np.uint8)

    if mode == "vignette":
        # Darken edges; center stays untouched. strength scales with amt.
        mask = _vignette_mask(*frame.shape[:2])
        darken = 1.0 - (mask * amt)[:, :, None]
        out = frame.astype(np.float32) * darken
        return out.astype(np.uint8)

    # default: white tint overlay (opacity capped like the source's 0..0.5 range).
    opacity = 0.5 * amt
    out = frame.astype(np.float32) * (1.0 - opacity) + 255.0 * opacity
    return out.astype(np.uint8)

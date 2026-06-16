"""VHS grain — always-on analog luma noise.

Ported from apply_vhs_grain in vhs_glitch.py: add gaussian noise to the frame.
Constant base layer (no beat band), but a 'rms_boost' control optionally adds a
touch more noise on louder moments via ctx.rms.
"""
import numpy as np

PARAMS = [
    {"key": "amount", "type": "slider", "label": "Amount",
     "min": 0, "max": 2, "step": 0.05, "default": 0.4},
    {"key": "rms_boost", "type": "slider", "label": "RMS boost",
     "min": 0, "max": 1, "step": 0.05, "default": 0.3},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame

    amount = p["amount"] + p["rms_boost"] * ctx.rms
    if amount <= 0:
        return frame

    rng = ctx.rng
    noise = rng.normal(0, 12 * amount, frame.shape).astype(np.float32)
    out = frame.astype(np.float32) + noise
    return np.clip(out, 0, 255).astype(np.uint8)

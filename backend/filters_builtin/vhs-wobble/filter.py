"""VHS wobble — gentle RMS-driven horizontal shift of a few random rows.

Ported from the RMS wobble block inside render_vhs in vhs_glitch.py: scale a
small horizontal shift by overall loudness (ctx.rms) and apply it to a handful
of random thin row bands. Driven by RMS, not a beat band.
"""
import numpy as np

PARAMS = [
    {"key": "amount", "type": "slider", "label": "Amount",
     "min": 0, "max": 3, "step": 0.05, "default": 0.5},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame

    wobble_intensity = ctx.rms * p["amount"]
    if wobble_intensity <= 0.01:
        return frame

    h, w = frame.shape[:2]
    small_shift = int(wobble_intensity * w * 0.02)
    if small_shift <= 0:
        return frame

    out = frame
    rng = ctx.rng
    for _ in range(int(rng.integers(1, 4))):
        bh = int(rng.integers(2, max(3, h // 20)))
        y0 = int(rng.integers(0, max(1, h - bh)))
        y1 = min(y0 + bh, h)
        s = int(rng.integers(-small_shift, small_shift + 1))
        out[y0:y1] = np.roll(out[y0:y1], s, axis=1)

    return out

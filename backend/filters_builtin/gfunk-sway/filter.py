"""G-funk sway — sinusoidal horizontal sway, phase from time, depth from loudness."""
import numpy as np

PARAMS = [
    {"key": "amount", "type": "slider", "label": "Amount",
     "min": 0, "max": 3, "step": 0.05, "default": 0.5},
    {"key": "speed", "type": "slider", "label": "Speed",
     "min": 0, "max": 4, "step": 0.05, "default": 0.8},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    amount = p["amount"]
    if amount <= 0:
        return frame

    h, w = frame.shape[:2]
    # Phase advances over time; depth scaled by loudness.
    phase = ctx.t * p["speed"]
    sway_amount = amount * (0.5 + 0.5 * ctx.rms)
    shift = int(w * 0.02 * sway_amount * np.sin(2 * np.pi * phase))
    if shift == 0:
        return frame

    out = np.roll(frame, shift, axis=1)
    if shift > 0:
        out[:, :shift] = out[:, shift:shift + 1]
    else:
        out[:, shift:] = out[:, shift - 1:shift]
    return out

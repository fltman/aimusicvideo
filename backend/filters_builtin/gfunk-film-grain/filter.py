"""G-funk film grain — warm 35mm grain, amount nudged by loudness (always on)."""
import numpy as np

PARAMS = [
    {"key": "amount", "type": "slider", "label": "Amount",
     "min": 0, "max": 3, "step": 0.05, "default": 0.3},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    amount = p["amount"]
    if amount <= 0:
        return frame

    # Modulate the grain amount slightly by overall loudness.
    grain_int = amount * (0.6 + 0.4 * ctx.rms)
    grain = ctx.rng.normal(0, 15 * grain_int, frame.shape).astype(np.float32)
    out = frame.astype(np.float32) + grain
    return np.clip(out, 0, 255).astype(np.uint8)

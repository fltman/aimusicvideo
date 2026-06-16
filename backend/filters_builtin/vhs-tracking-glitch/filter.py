"""VHS tracking glitch — horizontal scan-band displacement driven by the beat."""
import numpy as np

PARAMS = [
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 3, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "Drive band",
     "options": ["bass", "mid", "high"], "default": "bass"},
    {"key": "bands", "type": "knob", "label": "Bands",
     "min": 1, "max": 16, "step": 1, "default": 9},
    {"key": "roll", "type": "slider", "label": "Vertical roll",
     "min": 0, "max": 2, "step": 0.05, "default": 0.5},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame
    env = getattr(ctx, p["band"])
    if env <= 0.01:
        return frame

    intensity = env * p["intensity"]
    h, w = frame.shape[:2]
    out = frame.copy()
    rng = ctx.rng

    max_shift = int(w * 0.35 * intensity)
    if max_shift >= 1:
        bh_max = max(5, h // 8)
        for _ in range(int(p["bands"])):
            bh = int(rng.integers(4, bh_max))
            y0 = int(rng.integers(0, max(1, h - bh)))
            y1 = min(y0 + bh, h)
            shift = int(rng.integers(-max_shift, max_shift + 1))
            if shift == 0:
                continue
            out[y0:y1] = np.roll(out[y0:y1], shift, axis=1)
            if shift > 0:
                out[y0:y1, :shift] = out[y0:y1, shift:shift + 1]
            else:
                out[y0:y1, shift:] = out[y0:y1, shift - 1:shift]

    # heavy hits roll the whole frame vertically
    if env > 0.5 and p["roll"] > 0:
        roll = int(h * 0.3 * (env - 0.5) * 2 * p["roll"])
        if roll:
            out = np.roll(out, roll, axis=0)
    return out

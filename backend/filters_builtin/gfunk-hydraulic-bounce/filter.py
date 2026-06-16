"""G-funk hydraulic bounce — lowrider vertical bounce + slight zoom on the beat."""
import numpy as np
import cv2

PARAMS = [
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 3, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "Drive band",
     "options": ["bass", "mid", "high"], "default": "bass"},
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

    # Vertical displacement (bounce UP then settle) — always upward
    max_shift = int(h * 0.08 * intensity)
    if max_shift >= 2:
        shift = -abs(int(rng.integers(max_shift // 2, max(max_shift, 2))))
        if shift != 0:
            if shift < 0:  # shift up
                out[:shift] = out[-shift:]
                out[shift:] = out[shift - 1:shift]  # smear bottom edge
            else:
                out[shift:] = out[:-shift]
                out[:shift] = out[shift:shift + 1]

    # Slight zoom-in to sell the impact
    zoom = 1.0 + 0.03 * intensity
    cw = max(1, int(w / zoom))
    ch = max(1, int(h / zoom))
    x = (w - cw) // 2
    y = (h - ch) // 2
    cropped = out[y:y + ch, x:x + cw]
    out = cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)

    return out

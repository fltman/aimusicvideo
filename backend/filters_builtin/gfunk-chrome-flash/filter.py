"""G-funk chrome flash — central bloom + horizontal anamorphic streak on the beat."""
import numpy as np
import cv2

PARAMS = [
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 3, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "Drive band",
     "options": ["bass", "mid", "high"], "default": "high"},
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

    # Central bloom — jittered around frame center
    bloom = np.zeros((h, w), dtype=np.float32)
    cy = h // 2 + int(rng.integers(-max(1, h // 6), max(1, h // 6)))
    cx = w // 2 + int(rng.integers(-max(1, w // 6), max(1, w // 6)))
    cv2.circle(bloom, (cx, cy), int(min(w, h) * 0.3), 1.0, -1)
    bloom = cv2.GaussianBlur(bloom, (0, 0), sigmaX=w * 0.15, sigmaY=h * 0.15)
    bloom = (bloom * 255 * 0.6 * intensity).clip(0, 255).astype(np.uint8)
    bloom_bgr = cv2.merge([bloom, bloom, bloom])
    out = cv2.add(out, bloom_bgr)

    # Horizontal anamorphic streak through bloom center
    streak = np.zeros((h, w), dtype=np.float32)
    streak_h = max(2, int(h * 0.01))
    y0 = max(0, cy - streak_h // 2)
    y1 = min(h, y0 + streak_h)
    streak[y0:y1, :] = 1.0
    streak = cv2.GaussianBlur(streak, (0, 0), sigmaX=w * 0.4, sigmaY=streak_h * 3)
    streak = (streak * 200 * intensity).clip(0, 255).astype(np.uint8)
    streak_bgr = cv2.merge([streak, streak, streak])
    out = cv2.add(out, streak_bgr)

    return out

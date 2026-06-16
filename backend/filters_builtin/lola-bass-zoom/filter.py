"""Lola bass zoom — beat-synced center punch-zoom (crop + resize back to full frame)."""
import cv2

PARAMS = [
    {"key": "zoom_amount", "type": "slider", "label": "Zoom amount",
     "min": 0.5, "max": 0.95, "step": 0.01, "default": 0.70},
    {"key": "intensity", "type": "slider", "label": "Intensity",
     "min": 0, "max": 3, "step": 0.05, "default": 1.0},
    {"key": "band", "type": "select", "label": "Drive band",
     "options": ["bass", "mid", "high"], "default": "bass"},
    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]


def process(frame, ctx, p):
    if not p["enabled"]:
        return frame

    env = getattr(ctx, p["band"]) * p["intensity"]
    if env <= 0.001:
        return frame

    h, w = frame.shape[:2]
    # scale = 1 - (1 - zoom_amount) * env  (smaller zoom_amount => bigger punch)
    scale = 1.0 - (1.0 - p["zoom_amount"]) * env
    scale = min(1.0, max(0.05, scale))
    if scale >= 0.999:
        return frame

    cw = max(2, int(w * scale))
    ch = max(2, int(h * scale))
    cw -= cw % 2
    ch -= ch % 2
    x = (w - cw) // 2
    y = (h - ch) // 2
    cropped = frame[y:y + ch, x:x + cw]
    return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)

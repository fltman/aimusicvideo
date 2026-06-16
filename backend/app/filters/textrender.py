"""Rich text-overlay rendering for export (Pillow).

Renders a styled, animated title onto a BGR frame: font family + bold, size,
colour, outline/border, drop shadow, background box, placement, and an
animation (none / fade / typewriter / slide) driven by the clip's progress.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_SUP = "/System/Library/Fonts/Supplemental/"
_FONTS = {
    ("sans", False): _SUP + "Arial.ttf",
    ("sans", True): _SUP + "Arial Bold.ttf",
    ("serif", False): _SUP + "Times New Roman.ttf",
    ("serif", True): _SUP + "Times New Roman Bold.ttf",
    ("mono", False): _SUP + "Courier New.ttf",
    ("mono", True): _SUP + "Courier New Bold.ttf",
    ("display", False): _SUP + "Impact.ttf",
    ("display", True): _SUP + "Impact.ttf",
    ("elegant", False): _SUP + "Georgia.ttf",
    ("elegant", True): _SUP + "Georgia Bold.ttf",
}


@lru_cache(maxsize=64)
def _font(family: str, bold: bool, size: int) -> ImageFont.FreeTypeFont:
    for key in ((family, bold), (family, False), ("sans", bold), ("sans", False)):
        path = _FONTS.get(key)
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _hex_rgb(h, default=(255, 255, 255)):
    try:
        s = str(h).lstrip("#")
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        return default


def _clamp01(x):
    return max(0.0, min(1.0, x))


def render_text_clip(frame_bgr, clip: dict, progress: float, w: int, h: int):
    """Composite a styled/animated text clip onto a BGR uint8 frame."""
    text = str(clip.get("text") or "")
    anim = clip.get("textAnim") or "none"

    # animation → shown text, opacity, vertical offset
    alpha, y_off = 1.0, 0
    if anim == "typewriter":
        n = int(len(text) * _clamp01(progress / 0.6))
        text = text[:max(0, n)]
    elif anim == "fade":
        alpha = _clamp01(min(progress / 0.18, (1.0 - progress) / 0.18))
    elif anim == "slide":
        ease = _clamp01(progress / 0.25)
        alpha = ease
        y_off = int((1.0 - ease) * h * 0.05)
    if not text.strip() or alpha <= 0.01:
        return frame_bgr

    size = max(8, int(h / 12 * float(clip.get("textSize") or 1.0)))
    font = _font(clip.get("textFont") or "sans", bool(clip.get("textBold")), size)
    color = _hex_rgb(clip.get("textColor") or "#ffffff")
    stroke = int(clip.get("textStroke") or 0)
    stroke_color = _hex_rgb(clip.get("textStrokeColor") or "#000000")

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (w - tw) // 2 - bbox[0]
    pos = clip.get("textPosition") or "bottom"
    if pos == "top":
        y = int(h * 0.08) - bbox[1]
    elif pos == "center":
        y = (h - th) // 2 - bbox[1]
    else:
        y = h - int(h * 0.10) - th - bbox[1]
    y += y_off

    if clip.get("textBg"):
        bg = _hex_rgb(clip.get("textBgColor") or "#000000")
        pad = max(8, int(th * 0.3))
        draw.rounded_rectangle(
            [x + bbox[0] - pad, y + bbox[1] - pad,
             x + bbox[0] + tw + pad, y + bbox[1] + th + pad],
            radius=pad, fill=(bg[0], bg[1], bg[2], 170))

    if clip.get("textShadow"):
        off = max(2, size // 18)
        draw.text((x + off, y + off), text, font=font, fill=(0, 0, 0, 200),
                  stroke_width=stroke)

    draw.text((x, y), text, font=font, fill=color + (255,),
              stroke_width=stroke,
              stroke_fill=stroke_color + (255,) if stroke > 0 else None)

    if alpha < 1.0:
        a = overlay.getchannel("A").point(lambda v: int(v * alpha))
        overlay.putalpha(a)

    base = Image.fromarray(frame_bgr[:, :, ::-1]).convert("RGBA")
    out = Image.alpha_composite(base, overlay).convert("RGB")
    return np.ascontiguousarray(np.array(out)[:, :, ::-1])

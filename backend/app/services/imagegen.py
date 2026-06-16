"""Image generation via OpenRouter (google/gemini-3-pro-image-preview).

Mirrors the request/response shape of the user's gemini-imagegen skill: a normal
chat/completions call whose response message carries an `images` array of data
URLs. Returns raw PNG bytes; raises on any failure so the caller can report it.
"""
from __future__ import annotations

import base64
from typing import Any

import httpx

from .. import config

IMAGE_MODEL = "google/gemini-3-pro-image-preview"
_TIMEOUT = 180.0


def generate_image(
    prompt: str, reference_images: list[bytes] | None = None
) -> bytes:
    """Generate a single image; return PNG bytes.

    When `reference_images` are supplied (e.g. a character + a scene), they are
    passed as input images so the model keeps those subjects consistent.
    """
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not configured")

    if reference_images:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for img in reference_images:
            b64 = base64.b64encode(img).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })
        message_content: Any = content
    else:
        message_content = prompt

    resp = httpx.post(
        f"{config.OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "AI Music Video Studio",
        },
        json={
            "model": IMAGE_MODEL,
            "messages": [{"role": "user", "content": message_content}],
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    message = resp.json()["choices"][0]["message"]
    images = message.get("images") or []
    if not images:
        raise RuntimeError("model returned no image")

    url = images[0]["image_url"]["url"]  # data:image/png;base64,<...>
    if "," not in url:
        raise RuntimeError("malformed image data url")
    return base64.b64decode(url.split(",", 1)[1])

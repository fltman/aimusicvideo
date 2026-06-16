"""Image-to-video generation via OpenRouter (bytedance/seedance-2.0-fast).

OpenRouter video generation is an async job API: POST /videos returns a job we
poll until `completed`, then download the mp4 from `unsigned_urls`. The first
frame is passed as a base64 data URL, so local library images can be animated
without a public URL.

Job lifecycle/concurrency is owned by genqueue; this module only does the
low-level generation + asset persistence.
"""
from __future__ import annotations

import base64
import json
import time

import httpx

from .. import config, db
from . import audio


def _error_message(resp: httpx.Response) -> str:
    """Extract a readable error from an OpenRouter error response.

    Bodies look like {"error":{"message":"HTTP 400: {\\"error\\":{...}}"}} —
    unwrap the nested provider message when present.
    """
    try:
        msg = resp.json().get("error", {}).get("message") or resp.text
    except Exception:
        return resp.text[:300]
    if isinstance(msg, str) and "{" in msg:
        try:
            inner = json.loads(msg[msg.index("{"):])
            inner_msg = inner.get("error", {}).get("message")
            if inner_msg:
                return inner_msg
        except Exception:
            pass
    return str(msg)[:300]

# kling-v3.0-std animates people (unlike seedance, which blocks real-person
# images) and supports 5s / 10s durations.
VIDEO_MODEL = "kwaivgi/kling-v3.0-std"
_SUBMIT_TIMEOUT = 60.0
_POLL_INTERVAL = 6.0
_MAX_POLLS = 80  # ~8 minutes ceiling


def image_to_video(
    image_bytes: bytes,
    prompt: str,
    duration: int = 5,
    aspect_ratio: str = "16:9",
) -> bytes:
    """Generate a video from a still image; return mp4 bytes. Raises on failure."""
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not configured")

    auth = f"Bearer {config.OPENROUTER_API_KEY}"
    headers = {"Authorization": auth, "Content-Type": "application/json",
               "X-Title": "AI Music Video Studio"}
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    # kling supports 5s / 10s — pick the shortest that still covers the request so a
    # 6–10s shot is fully animated (no frozen tail)
    duration = 10 if float(duration) > 5 else 5

    submit = httpx.post(
        f"{config.OPENROUTER_BASE_URL}/videos",
        headers=headers,
        json={
            "model": VIDEO_MODEL,
            "prompt": prompt or "Subtle cinematic motion, slow camera push-in.",
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "frame_images": [
                {"type": "image_url", "image_url": {"url": data_url},
                 "frame_type": "first_frame"}
            ],
        },
        timeout=_SUBMIT_TIMEOUT,
    )
    if submit.status_code >= 400:
        raise RuntimeError(_error_message(submit))
    job = submit.json()
    poll_url = job.get("polling_url")
    job_id = job.get("id")
    status = job.get("status")

    for _ in range(_MAX_POLLS):
        if status == "completed":
            break
        if status in ("failed", "cancelled", "expired"):
            raise RuntimeError(job.get("error") or f"video job {status}")
        time.sleep(_POLL_INTERVAL)
        pr = httpx.get(poll_url, headers={"Authorization": auth}, timeout=60)
        pr.raise_for_status()
        job = pr.json()
        status = job.get("status")

    if status != "completed":
        raise RuntimeError("video generation timed out")

    urls = job.get("unsigned_urls") or []
    video_url = urls[0] if urls else (
        f"{config.OPENROUTER_BASE_URL}/videos/{job_id}/content?index=0"
    )
    dl_headers = {"Authorization": auth} if "openrouter.ai/api/" in video_url else {}
    vr = httpx.get(video_url, headers=dl_headers, timeout=180, follow_redirects=True)
    vr.raise_for_status()
    return vr.content


def save_video_asset(pid: str, mp4: bytes, source: dict, prompt: str) -> dict:
    """Persist generated mp4 as a video media asset, inheriting source identity."""
    media_dir = config.project_dir(pid) / "media"
    thumbs_dir = media_dir / "thumbs"
    media_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    import uuid
    asset_id = uuid.uuid4().hex
    path = media_dir / f"{asset_id}.mp4"
    path.write_bytes(mp4)

    info = audio.probe(str(path))
    thumb_abs = thumbs_dir / f"{asset_id}.jpg"
    thumb_rel = None
    if audio.make_thumbnail(str(path), str(thumb_abs), "video"):
        thumb_rel = config.rel_to_data(thumb_abs)

    base_name = source.get("label") or source.get("original_name") or "clip"
    return db.add_media(
        project_id=pid,
        kind="video",
        original_name=f"{base_name} (video)",
        path=config.rel_to_data(path),
        thumb_path=thumb_rel,
        duration_sec=info.get("duration"),
        width=info.get("width"),
        height=info.get("height"),
        label=source.get("label"),
        tags=source.get("tags") or None,
    )

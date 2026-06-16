"""ffmpeg/ffprobe helpers: format conversion, media probing, thumbnails.

Everything shells out to the ffmpeg/ffprobe binaries configured in config via
subprocess.run with list args (never shell=True). Conversion produces the
canonical playback/analysis WAV (44100Hz stereo pcm_s16le); probing yields the
metadata routers need to classify and size assets.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .. import config

# Extensions treated as images regardless of what ffprobe reports.
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}

# How much stderr to surface in RuntimeError messages.
_STDERR_TAIL = 2000


def _stderr_tail(text: str | None) -> str:
    if not text:
        return ""
    return text[-_STDERR_TAIL:]


def convert_to_wav(src: str | Path, dst: str | Path) -> float:
    """Transcode `src` to a 44100Hz stereo pcm_s16le WAV at `dst`.

    Returns the resulting duration in seconds (via probe). Raises RuntimeError
    on a non-zero ffmpeg exit, including the tail of stderr for diagnosis.
    """
    src = str(src)
    dst = str(dst)
    proc = subprocess.run(
        [
            config.FFMPEG, "-y",
            "-i", src,
            "-ac", "2",
            "-ar", "44100",
            "-c:a", "pcm_s16le",
            dst,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg convert_to_wav failed (exit {proc.returncode}): "
            f"{_stderr_tail(proc.stderr)}"
        )
    info = probe(dst)
    return float(info["duration"]) if info["duration"] is not None else 0.0


def probe(path: str | Path) -> dict[str, Any]:
    """Probe a media file with ffprobe.

    Returns {duration, width, height, has_video, has_audio}. Missing/unknown
    fields are None / False; never raises (a failed probe yields empties).
    """
    result: dict[str, Any] = {
        "duration": None,
        "width": None,
        "height": None,
        "has_video": False,
        "has_audio": False,
    }
    proc = subprocess.run(
        [
            config.FFPROBE,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        return result

    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError):
        return result

    fmt = data.get("format") or {}
    dur_raw = fmt.get("duration")
    if dur_raw is not None:
        try:
            result["duration"] = float(dur_raw)
        except (ValueError, TypeError):
            result["duration"] = None

    for stream in data.get("streams") or []:
        codec_type = stream.get("codec_type")
        if codec_type == "video":
            # Skip cover-art / attached-pic streams when classifying as video.
            if stream.get("disposition", {}).get("attached_pic"):
                continue
            result["has_video"] = True
            if result["width"] is None:
                w = stream.get("width")
                h = stream.get("height")
                result["width"] = int(w) if w is not None else None
                result["height"] = int(h) if h is not None else None
            # Fall back to per-stream duration if format had none.
            if result["duration"] is None and stream.get("duration") is not None:
                try:
                    result["duration"] = float(stream["duration"])
                except (ValueError, TypeError):
                    pass
        elif codec_type == "audio":
            result["has_audio"] = True
            if result["duration"] is None and stream.get("duration") is not None:
                try:
                    result["duration"] = float(stream["duration"])
                except (ValueError, TypeError):
                    pass

    return result


def media_kind(filename: str, probe_result: dict[str, Any]) -> str:
    """Classify a media file as 'image' | 'video' | 'audio'.

    Image extensions win outright; otherwise a probed video stream means
    'video', else 'audio'.
    """
    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if probe_result.get("has_video"):
        return "video"
    return "audio"


def make_thumbnail(src: str | Path, dst: str | Path, kind: str) -> bool:
    """Generate a 320px-wide thumbnail JPEG at `dst`.

    image → scaled still; video → frame grabbed at ~1s; audio → no thumb.
    Any failure (including ffmpeg non-zero exit) is swallowed → returns False.
    """
    if kind == "audio":
        return False

    src = str(src)
    dst = str(dst)
    if kind == "image":
        cmd = [
            config.FFMPEG, "-y",
            "-i", src,
            "-vf", "scale=320:-1",
            dst,
        ]
    elif kind == "video":
        cmd = [
            config.FFMPEG, "-y",
            "-ss", "1",
            "-i", src,
            "-frames:v", "1",
            "-vf", "scale=320:-1",
            dst,
        ]
    else:
        return False

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return False

    if proc.returncode != 0:
        return False
    return Path(dst).exists()


def extract_clip(
    src: str | Path, start: float, duration: float, dst: str | Path
) -> bool:
    """Extract a short mono 16kHz MP3 snippet (start..start+duration seconds).

    Used to give the chat model a small audible sample of a timeline section.
    Returns False on any failure (the clip is a best-effort context aid).
    """
    cmd = [
        config.FFMPEG, "-y",
        "-ss", str(max(0.0, start)),
        "-t", str(max(0.5, duration)),
        "-i", str(src),
        "-ac", "1",
        "-ar", "16000",
        "-b:a", "64k",
        str(dst),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return False
    return proc.returncode == 0 and Path(dst).exists()

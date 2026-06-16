"""Lyric extraction via whisper.cpp's whisper-cli (best-effort).

Lyrics are a nice-to-have layer of the analysis pipeline: a missing model, a
crashing transcription, or a malformed JSON file must NEVER take down a project
analysis. Every failure path therefore degrades gracefully to an empty list.

The whisper.cpp `-oj` JSON output looks like:
    {"transcription": [
        {"offsets": {"from": <ms>, "to": <ms>}, "text": " ..."}, ...
    ]}
We map the millisecond offsets to seconds and strip each text segment, dropping
any segment that is empty after stripping.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .. import config

# Whisper hallucinates confident text over instrumental / non-vocal audio
# (e.g. "We'll be right back." spanning a full 30s decode chunk, or non-speech
# labels like "*outro music*"). With -ml 60 a real sung line runs ~1-5s, so any
# segment this long is a non-vocal-chunk hallucination, not a lyric.
MAX_LINE_SEC = 12.0


def _is_hallucination(text: str, duration: float) -> bool:
    """Language-agnostic filter for whisper's music/silence artifacts."""
    if duration >= MAX_LINE_SEC:
        return True
    # bracketed non-speech labels: *music*, [Applause], (instrumental)
    if text and text[0] in "*[(" and text[-1] in "*])":
        return True
    return False


def transcribe(wav_path: str | Path) -> list[dict[str, Any]]:
    """Transcribe a WAV file into timed lyric segments.

    Returns a list of ``{"start": float, "end": float, "text": str}`` dicts
    (times in seconds). Returns ``[]`` if the whisper model is unavailable or
    on any error — this function never raises.
    """
    if not config.whisper_model_ready():
        return []

    wav = str(wav_path)
    if not os.path.exists(wav):
        return []

    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_prefix = os.path.join(tmp, "lyrics")
            cmd = [
                config.WHISPER_CLI,
                "-m", config.WHISPER_MODEL,
                "-f", wav,
                "-l", "auto",
                "-oj",
                "-ml", "60",
                "-sow",
                "--suppress-nst",  # suppress non-speech tokens
                "-t", str(os.cpu_count() or 1),
                "-of", out_prefix,
            ]
            subprocess.run(cmd, capture_output=True, text=True)

            json_path = out_prefix + ".json"
            if not os.path.exists(json_path):
                return []

            # whisper.cpp writes UTF-8; read it explicitly to preserve å ä ö.
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            segments = data.get("transcription") or []
            result: list[dict[str, Any]] = []
            for seg in segments:
                if not isinstance(seg, dict):
                    continue
                text = str(seg.get("text", "")).strip()
                if not text:
                    continue
                offsets = seg.get("offsets") or {}
                start_ms = offsets.get("from", 0)
                end_ms = offsets.get("to", 0)
                try:
                    start = float(start_ms) / 1000.0
                    end = float(end_ms) / 1000.0
                except (TypeError, ValueError):
                    continue
                if _is_hallucination(text, end - start):
                    continue
                result.append({"start": start, "end": end, "text": text})
            return result
    except Exception:
        return []

"""Mood / visual-direction analysis via OpenRouter (google/gemini-3.5-flash).

Given the song's lyrics and a small bundle of spectral features, ask the model
for a compact, STRICT-JSON description of the song's mood, genre, energy, color
palette and concrete visual ideas. This drives the editor's palette swatches and
visual suggestions.

The function is best-effort: any failure (no API key, network error, bad model
output, timeout) degrades to a documented fallback dict instead of raising, so
the analysis pipeline never dies on the mood stage.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .. import config

_TIMEOUT = 60.0

_SYSTEM_PROMPT = (
    "You are a music-video art director. You analyze a song from its lyrics and "
    "audio features and describe its visual mood. You always answer with a "
    "single JSON object and nothing else — no prose, no markdown, no code "
    "fences."
)

# Keys/types the model must produce; mirrored by the fallback dict below.
_REQUIRED_SCHEMA = (
    '{\n'
    '  "mood": string — one short phrase,\n'
    '  "genres": string[] — 1-4 genres,\n'
    '  "energy": number — 0..1,\n'
    '  "tempo_bpm": number,\n'
    '  "palette": string[] — exactly 5 hex colors like "#1a2b3c",\n'
    '  "keywords": string[] — 4-10 evocative words,\n'
    '  "visual_suggestions": string[] — 3 to 6 concrete shot/scene ideas\n'
    '}'
)


def _fallback(features: dict[str, Any]) -> dict[str, Any]:
    """The documented best-effort result used whenever analysis fails."""
    return {
        "mood": None,
        "genres": [],
        "energy": features.get("energy_hint"),
        "tempo_bpm": features.get("tempo"),
        "palette": [],
        "keywords": [],
        "visual_suggestions": [],
    }


def _build_user_prompt(lyrics_text: str, features: dict[str, Any]) -> str:
    lyrics = (lyrics_text or "").strip()
    if not lyrics:
        lyrics = "(no lyrics transcribed — infer mood from the audio features)"
    # Keep the prompt bounded; very long lyrics add little for mood.
    if len(lyrics) > 6000:
        lyrics = lyrics[:6000] + "\n…(truncated)"

    feature_lines = [
        f"- duration_sec: {features.get('duration')}",
        f"- tempo_bpm: {features.get('tempo')}",
        f"- bass_onsets: {features.get('bass_onsets')}",
        f"- mid_onsets: {features.get('mid_onsets')}",
        f"- high_onsets: {features.get('high_onsets')}",
        f"- energy_hint (0..1): {features.get('energy_hint')}",
    ]
    return (
        "Analyze this song and return the JSON object described below.\n\n"
        "AUDIO FEATURES:\n"
        + "\n".join(feature_lines)
        + "\n\nLYRICS:\n"
        + lyrics
        + "\n\nReturn ONLY this JSON object (no markdown, no commentary):\n"
        + _REQUIRED_SCHEMA
    )


def _strip_fences(text: str) -> str:
    """Remove ```json … ``` (or plain ``` …```) wrappers some models emit."""
    s = text.strip()
    if s.startswith("```"):
        # drop the opening fence line (``` or ```json) and the trailing fence
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", s)
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Defensively pull a JSON object out of the model's reply."""
    if not text:
        return None
    candidate = _strip_fences(text)
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    # last resort: grab the outermost {...} span and try again
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(candidate[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _coerce(obj: dict[str, Any], features: dict[str, Any]) -> dict[str, Any]:
    """Normalize the parsed object into the documented shape, filling any
    missing or wrongly-typed field from the fallback."""
    fb = _fallback(features)

    def _str_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _number(value: Any, default: Any) -> Any:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return default
        return default

    mood = obj.get("mood")
    mood = str(mood).strip() if isinstance(mood, str) and mood.strip() else fb["mood"]

    return {
        "mood": mood,
        "genres": _str_list(obj.get("genres")) or fb["genres"],
        "energy": _number(obj.get("energy"), fb["energy"]),
        "tempo_bpm": _number(obj.get("tempo_bpm"), fb["tempo_bpm"]),
        "palette": _str_list(obj.get("palette")) or fb["palette"],
        "keywords": _str_list(obj.get("keywords")) or fb["keywords"],
        "visual_suggestions": (
            _str_list(obj.get("visual_suggestions")) or fb["visual_suggestions"]
        ),
    }


def analyze_mood(lyrics_text: str, features: dict[str, Any]) -> dict[str, Any]:
    """Ask the mood model to describe the song; never raises.

    On any failure (missing key, HTTP/network error, timeout, unparseable
    output) returns the documented fallback dict built from ``features``.
    """
    if not config.OPENROUTER_API_KEY:
        return _fallback(features)

    payload = {
        "model": config.MOOD_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(lyrics_text, features)},
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "AI Music Video Studio",
    }

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(
                f"{config.OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            return _fallback(features)

        obj = _extract_json_object(content)
        if obj is None:
            return _fallback(features)

        return _coerce(obj, features)
    except Exception:
        return _fallback(features)

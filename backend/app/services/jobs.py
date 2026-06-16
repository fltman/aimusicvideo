"""Background analysis pipeline.

Runs the full song-analysis pipeline in a daemon thread so the upload request
returns immediately. Each stage writes its result to the db as soon as it is
ready (partial availability), so the frontend can render the waveform/beats
before lyrics/mood finish. Stage transitions update analysis_status /
analysis_stage / analysis_progress; any exception flips status to 'error'.

Pipeline: convert -> spectral -> lyrics -> mood.
"""
from __future__ import annotations

import threading
from typing import Any

from . import audio, whisper_lyrics, mood, spectral
from .. import db, config


def start_analysis(project_id: str, original_path: str) -> None:
    """Spawn the analysis pipeline in a daemon thread and return immediately."""
    threading.Thread(
        target=run_analysis,
        args=(project_id, original_path),
        daemon=True,
    ).start()


def run_analysis(project_id: str, original_path: str) -> None:
    """Execute the analysis stages, persisting each result as it completes.

    On any exception the project is marked status='error' with the message
    stored in analysis_error, and the function returns without re-raising.
    """
    try:
        # ── stage 1: converting ───────────────────────────────────────────
        db.update_project_fields(
            project_id,
            analysis_status="processing",
            analysis_stage="converting",
            analysis_progress=0.05,
        )

        # ── stage 2: convert to wav ───────────────────────────────────────
        wav_path = config.project_dir(project_id) / "song.wav"
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        duration = audio.convert_to_wav(original_path, str(wav_path))
        db.update_project_fields(
            project_id,
            song_wav_path=config.rel_to_data(wav_path),
            duration_sec=duration,
            analysis_progress=0.15,
        )

        # ── stage 3: spectral (beats + waveform) ──────────────────────────
        db.update_project_fields(project_id, analysis_stage="spectral")
        result = spectral.analyze(str(wav_path))
        spectral_duration = result.get("duration")
        db.update_project_fields(
            project_id,
            beats_json=result.get("beats"),
            waveform_json=result.get("waveform"),
            duration_sec=spectral_duration if spectral_duration else duration,
            analysis_progress=0.45,
        )

        # ── stage 4: lyrics (best-effort) ─────────────────────────────────
        db.update_project_fields(project_id, analysis_stage="lyrics")
        lyrics = whisper_lyrics.transcribe(str(wav_path))
        db.update_project_fields(
            project_id,
            lyrics_json=lyrics,
            analysis_progress=0.80,
        )

        # ── stage 5: mood ─────────────────────────────────────────────────
        db.update_project_fields(project_id, analysis_stage="mood")
        beats = result.get("beats") or {}
        waveform = result.get("waveform") or {}
        features: dict[str, Any] = {
            "duration": spectral_duration if spectral_duration else duration,
            "tempo": result.get("tempo"),
            "bass_onsets": len(beats.get("bass") or []),
            "mid_onsets": len(beats.get("mid") or []),
            "high_onsets": len(beats.get("high") or []),
            "energy_hint": _energy_hint(waveform.get("peaks")),
        }
        lyrics_text = "\n".join(
            seg.get("text", "") for seg in lyrics if seg.get("text")
        )
        mood_result = mood.analyze_mood(lyrics_text, features)
        db.update_project_fields(
            project_id,
            mood_json=mood_result,
            analysis_progress=0.95,
        )

        # ── done ──────────────────────────────────────────────────────────
        db.update_project_fields(
            project_id,
            analysis_status="done",
            analysis_stage="done",
            analysis_progress=1.0,
        )
    except Exception as e:  # noqa: BLE001 — pipeline must never crash the thread
        db.update_project_fields(
            project_id,
            analysis_status="error",
            analysis_error=str(e),
        )
        return


def _energy_hint(peaks: Any) -> float:
    """Mean absolute amplitude across waveform min/max peak pairs, else 0.5."""
    if not peaks:
        return 0.5
    total = 0.0
    count = 0
    for pair in peaks:
        try:
            lo, hi = pair[0], pair[1]
        except (TypeError, IndexError, ValueError):
            continue
        total += abs(float(lo)) + abs(float(hi))
        count += 2
    if count == 0:
        return 0.5
    return round(total / count, 4)

"""Spectral analysis: per-band onset (beat) detection + waveform peaks.

Ported from the band-split onset approach in vhs_glitch.py, but implemented on
numpy/scipy only (librosa/numba do not build cleanly on Python 3.14). A single
fine-hop STFT feeds all three bands; onsets are positive-spectral-flux peaks
within each band's frequency mask.

Bands (Hz):  bass 20-200  ·  mid 200-2000  ·  high 4000-8000
"""
from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal

from .. import config

# STFT params (at ANALYSIS_SR=22050: hop ~11.6ms — fine enough for the high band)
_NPERSEG = 2048
_HOP = 256

# per-band peak-pick tuning: (min seconds between onsets, height threshold 0..1)
_BAND_TUNING = {
    "bass": (config.BASS_RANGE, 0.16, 0.18),
    "mid": (config.MID_RANGE, 0.10, 0.15),
    "high": (config.HIGH_RANGE, 0.06, 0.12),
}


def _read_wav_mono(path: str) -> tuple[np.ndarray, int]:
    """Read a PCM WAV into a mono float32 array in [-1, 1]."""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())

    if sampwidth == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sampwidth} bytes")

    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)
    return data, sr


def _resample(y: np.ndarray, sr: int, target_sr: int) -> np.ndarray:
    if sr == target_sr or y.size == 0:
        return y
    g = math.gcd(sr, target_sr)
    return signal.resample_poly(y, target_sr // g, sr // g).astype(np.float32)


def _band_onsets(
    mag: np.ndarray,
    freqs: np.ndarray,
    times: np.ndarray,
    band: tuple[int, int],
    min_gap_s: float,
    height: float,
) -> list[float]:
    """Detect onset times within a frequency band via positive spectral flux."""
    lo, hi = band
    mask = (freqs >= lo) & (freqs <= hi)
    if not mask.any() or mag.shape[1] < 3:
        return []

    band_mag = mag[mask, :]
    # positive spectral flux summed over the band's bins, per frame
    flux = np.diff(band_mag, axis=1)
    flux[flux < 0] = 0.0
    env = flux.sum(axis=0)
    if env.max() <= 1e-9:
        return []
    env = env / env.max()
    # env[i] is the flux entering frame i+1
    env_times = times[1:]

    hop_s = (times[1] - times[0]) if len(times) > 1 else (_HOP / config.ANALYSIS_SR)
    distance = max(1, int(round(min_gap_s / hop_s)))
    peaks, _ = signal.find_peaks(env, height=height, distance=distance)
    return [round(float(env_times[p]), 3) for p in peaks]


def _waveform_peaks(y: np.ndarray, sr: int, pps: int) -> list[list[float]]:
    """min/max pairs per time bucket for drawing the waveform."""
    if y.size == 0:
        return []
    bucket = max(1, sr // pps)
    n = y.size // bucket
    if n == 0:
        return [[round(float(y.min()), 4), round(float(y.max()), 4)]]
    trimmed = y[: n * bucket].reshape(n, bucket)
    mins = trimmed.min(axis=1)
    maxs = trimmed.max(axis=1)
    return [[round(float(lo), 4), round(float(hi), 4)] for lo, hi in zip(mins, maxs)]


def _estimate_tempo(bass_onsets: list[float]) -> float | None:
    if len(bass_onsets) < 4:
        return None
    intervals = np.diff(np.asarray(bass_onsets))
    intervals = intervals[(intervals > 0.2) & (intervals < 2.0)]  # 30-300 bpm range
    if intervals.size == 0:
        return None
    bpm = 60.0 / float(np.median(intervals))
    # fold into a musical range
    while bpm < 70:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return round(bpm, 1)


def analyze(wav_path: str | Path) -> dict[str, Any]:
    """Run full spectral analysis on a WAV file."""
    y_orig, sr = _read_wav_mono(wav_path)
    duration = round(len(y_orig) / sr, 3) if sr else 0.0

    waveform = {"peaks": _waveform_peaks(y_orig, sr, config.WAVEFORM_PPS),
                "pps": config.WAVEFORM_PPS}

    y = _resample(y_orig, sr, config.ANALYSIS_SR)
    asr = config.ANALYSIS_SR

    beats: dict[str, list[float]] = {"bass": [], "mid": [], "high": []}
    if y.size >= _NPERSEG:
        freqs, times, zxx = signal.stft(
            y, fs=asr, nperseg=_NPERSEG, noverlap=_NPERSEG - _HOP, boundary=None
        )
        mag = np.abs(zxx)
        for name, (band, gap, height) in _BAND_TUNING.items():
            beats[name] = _band_onsets(mag, freqs, times, band, gap, height)

    return {
        "duration": duration,
        "sample_rate": sr,
        "tempo": _estimate_tempo(beats["bass"]),
        "beats": beats,
        "waveform": waveform,
    }

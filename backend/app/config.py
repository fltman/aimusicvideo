"""Central configuration: paths, env vars, external tool locations.

All filesystem layout for the app flows from DATA_DIR. Media files and the
sqlite db live under it; the API serves DATA_DIR at the /files mount so the
frontend can load any stored asset by its db-stored relative path.
"""
from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no external dependency)."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


BACKEND_DIR = Path(__file__).resolve().parent.parent
_load_dotenv(BACKEND_DIR / ".env")

# ── storage ────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR", BACKEND_DIR / "data")).resolve()
PROJECTS_DIR = DATA_DIR / "projects"
DB_PATH = DATA_DIR / "app.db"

# ── external tooling ─────────────────────────────────────────────────────────
WHISPER_CLI = os.environ.get(
    "WHISPER_CLI", "/Users/andersbj/Projekt/whisper.cpp/build/bin/whisper-cli"
)
WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL",
    "/Users/andersbj/Projekt/whisper.cpp/models/ggml-large-v3-turbo.bin",
)
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")

# ── ai ───────────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MOOD_MODEL = "google/gemini-3.5-flash"

# ── server ────────────────────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", "8100"))

# ── analysis params (ported from vhs_glitch.py band ranges) ──────────────────
ANALYSIS_SR = 22050
BASS_RANGE = (20, 200)
MID_RANGE = (200, 2000)
HIGH_RANGE = (4000, 8000)
WAVEFORM_PPS = 100  # waveform peak buckets per second


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def rel_to_data(path: Path) -> str:
    """Convert an absolute path under DATA_DIR to the relative form stored in
    the db and served at /files/<relpath>."""
    return str(Path(path).resolve().relative_to(DATA_DIR)).replace(os.sep, "/")


def whisper_model_ready() -> bool:
    """The large-v3-turbo model is ~1.55GB; treat partial downloads as not
    ready so lyric extraction degrades gracefully instead of crashing."""
    p = Path(WHISPER_MODEL)
    return p.exists() and p.stat().st_size > 1_000_000_000

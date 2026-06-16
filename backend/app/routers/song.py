"""Song upload + analysis status endpoints."""
from __future__ import annotations

import os

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import config, db
from ..models import Analysis, SongStatus
from ..services import jobs

router = APIRouter(prefix="/api/projects/{pid}", tags=["song"])


@router.post("/song")
async def upload_song(pid: str, file: UploadFile = File(...)) -> SongStatus:
    if db.get_project(pid) is None:
        raise HTTPException(404, "Project not found")

    proj_dir = config.project_dir(pid)
    proj_dir.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1]
    source_path = proj_dir / f"source{ext}"
    with open(source_path, "wb") as fh:
        fh.write(await file.read())

    db.update_project_fields(
        pid,
        song_original_name=file.filename,
        analysis_status="processing",
        analysis_progress=0.0,
        analysis_stage="queued",
        analysis_error=None,
    )
    jobs.start_analysis(pid, str(source_path))

    return SongStatus(status="processing", progress=0.0, stage="queued", error=None)


@router.get("/song/status")
def song_status(pid: str) -> SongStatus:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Project not found")
    return SongStatus(
        status=project.get("analysis_status") or "none",
        progress=project.get("analysis_progress") or 0.0,
        stage=project.get("analysis_stage"),
        error=project.get("analysis_error"),
    )


@router.get("/analysis")
def get_analysis(pid: str) -> Analysis:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Project not found")
    return Analysis(
        duration=project.get("duration_sec"),
        beats=project.get("beats_json"),
        waveform=project.get("waveform_json"),
        lyrics=project.get("lyrics_json"),
        mood=project.get("mood_json"),
    )

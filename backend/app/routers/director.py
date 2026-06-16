"""AI auto-director endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db
from ..models import AutoDirectRequest
from ..services import director

router = APIRouter(prefix="/api/projects/{pid}", tags=["director"])


@router.post("/auto-direct")
def auto_direct(pid: str, body: AutoDirectRequest) -> dict:
    project = db.get_project(pid)
    if project is None:
        raise HTTPException(404, "Project not found")
    if not project.get("song_wav_path"):
        raise HTTPException(400, "Upload a song first")
    return director.auto_direct(project, body.max_shots)

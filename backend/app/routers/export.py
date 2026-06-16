"""Full-video export endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db
from ..models import ExportRequest
from ..services import export as export_service

router = APIRouter(prefix="/api/projects/{pid}", tags=["export"])


@router.post("/export")
def start_export(pid: str, body: ExportRequest) -> dict:
    project = db.get_project(pid)
    if project is None:
        raise HTTPException(404, "Project not found")
    if not project.get("song_wav_path"):
        raise HTTPException(400, "Upload a song first")
    job, export_id = export_service.start_export(project, body.resolution, body.fps)
    return {"job_id": job["id"], "export_id": export_id}


@router.get("/export-progress/{export_id}")
def export_progress(pid: str, export_id: str) -> dict:
    return {"progress": export_service.export_progress(pid, export_id)}

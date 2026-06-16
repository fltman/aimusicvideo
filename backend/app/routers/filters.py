"""Filter library + vibe-code + preview endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from .. import db
from ..models import (
    FilterChatRequest, FilterCreate, FilterFork, FilterPreviewRequest,
    FilterRename, FilterRollback, FilterSave,
)
from ..services import filterchat, filters, genqueue

router = APIRouter(prefix="/api", tags=["filters"])


@router.get("/filters")
def list_filters() -> list[dict]:
    return filters.list_filters()


@router.post("/filters")
def create_filter(body: FilterCreate) -> dict:
    return filters.create_from_template(body.name)


@router.get("/filters/{fid}")
def get_filter(fid: str) -> dict:
    f = filters.get_filter(fid)
    if not f:
        raise HTTPException(404, "Filter not found")
    return f


@router.post("/filters/{fid}/fork")
def fork_filter(fid: str, body: FilterFork) -> dict:
    f = filters.fork(fid, body.name)
    if not f:
        raise HTTPException(404, "Filter not found")
    return f


@router.patch("/filters/{fid}")
def rename_filter(fid: str, body: FilterRename) -> dict:
    f = filters.rename_filter(fid, body.name)
    if not f:
        raise HTTPException(400, "Cannot rename a built-in filter (use Save as)")
    return f


@router.post("/filters/{fid}/save")
def save_filter(fid: str, body: FilterSave) -> dict:
    if not filters.get_filter(fid):
        raise HTTPException(404, "Filter not found")
    try:
        filterchat._smoke_test(body.code)  # validate before saving
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Invalid filter code: {e}")
    filters.save_version(fid, body.code, body.message)
    return filters.get_filter(fid)


@router.post("/filters/{fid}/rollback")
def rollback_filter(fid: str, body: FilterRollback) -> dict:
    f = filters.rollback(fid, body.version)
    if not f:
        raise HTTPException(404, "Version not found")
    return f


@router.delete("/filters/{fid}")
def delete_filter(fid: str) -> Response:
    if not filters.delete_filter(fid):
        raise HTTPException(400, "Cannot delete this filter")
    return Response(status_code=204)


@router.get("/filters/{fid}/chat")
def get_filter_chat(fid: str) -> list[dict]:
    return filters.read_chat(fid)


@router.post("/filters/{fid}/chat")
def filter_chat(fid: str, body: FilterChatRequest) -> dict:
    return filterchat.chat(fid, body.message)


@router.post("/projects/{pid}/filter-preview")
def filter_preview(pid: str, body: FilterPreviewRequest) -> dict:
    project = db.get_project(pid)
    if project is None:
        raise HTTPException(404, "Project not found")
    job = filters.render_preview(project, body.filter_id, body.params,
                                 body.cursor_time)
    return {"job_id": job["id"]}


@router.get("/job/{job_id}")
def job_status(job_id: str) -> dict:
    job = genqueue.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job

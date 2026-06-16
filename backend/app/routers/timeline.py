"""Timeline document get/save endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from .. import db
from ..models import TimelineDoc

router = APIRouter(prefix="/api/projects/{pid}", tags=["timeline"])


@router.get("/timeline")
def get_timeline(pid: str) -> dict:
    return db.get_timeline(pid)


@router.put("/timeline")
def set_timeline(pid: str, body: TimelineDoc) -> Response:
    if db.get_project(pid) is None:
        raise HTTPException(404, "Project not found")
    db.set_timeline(pid, body.model_dump())
    return Response(status_code=204)

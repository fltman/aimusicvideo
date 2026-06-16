"""Generation queue status endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from ..services import genqueue

router = APIRouter(prefix="/api/projects/{pid}", tags=["queue"])


@router.get("/queue")
def queue(pid: str) -> list[dict]:
    return genqueue.list_jobs(pid)

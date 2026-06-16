"""Global generation queue with bounded concurrency.

All AI generation (chat images, image→video) goes through one ThreadPoolExecutor
capped at MAX_CONCURRENCY, so at most N run at once and the rest queue — the user
can keep editing while generations proceed. Each job exposes status the frontend
polls; on completion the produced asset is attached to the job.

Callers pass a `runner` closure that performs the work and returns the new media
asset dict — keeping this module free of imports from chat/videogen (no cycles).
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

MAX_CONCURRENCY = 3

_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENCY, thread_name_prefix="gen")
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_seq = 0


def submit(
    project_id: str,
    kind: str,                 # 'image' | 'video' | 'filter' | 'export'
    label: str,
    runner: Callable[[], dict],
    insert_at: Optional[float] = None,
    insert_duration: Optional[float] = None,
) -> dict[str, Any]:
    """Enqueue a generation job. Returns the job record (status 'pending')."""
    global _seq
    job_id = uuid.uuid4().hex
    with _LOCK:
        _seq += 1
        _JOBS[job_id] = {
            "id": job_id,
            "project_id": project_id,
            "kind": kind,
            "label": label,
            "status": "pending",
            "asset": None,
            "error": None,
            "insert_at": insert_at,
            "insert_duration": insert_duration,
            "seq": _seq,
        }
        job = dict(_JOBS[job_id])
    _executor.submit(_work, job_id, runner)
    return job


def _work(job_id: str, runner: Callable[[], dict]) -> None:
    with _LOCK:
        if job_id not in _JOBS:
            return
        _JOBS[job_id]["status"] = "running"
    try:
        asset = runner()
        with _LOCK:
            _JOBS[job_id].update(status="done", asset=asset)
    except Exception as e:  # noqa: BLE001 — surfaced to the poller
        with _LOCK:
            _JOBS[job_id].update(status="error", error=str(e))


def list_jobs(project_id: str, limit: int = 30) -> list[dict[str, Any]]:
    with _LOCK:
        jobs = [dict(j) for j in _JOBS.values() if j["project_id"] == project_id]
    jobs.sort(key=lambda j: j["seq"], reverse=True)
    return jobs[:limit]


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        j = _JOBS.get(job_id)
        return dict(j) if j else None

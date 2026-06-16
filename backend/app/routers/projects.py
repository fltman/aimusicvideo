"""Project CRUD endpoints."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException, Response

from .. import config, db
from ..models import ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def list_projects() -> list[dict]:
    return db.list_projects()


@router.post("")
def create_project(body: ProjectCreate) -> dict:
    return db.create_project(body.name)


@router.get("/{pid}")
def get_project(pid: str) -> dict:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.patch("/{pid}")
def update_project(pid: str, body: ProjectUpdate) -> dict:
    if db.get_project(pid) is None:
        raise HTTPException(404, "Project not found")
    if body.name is not None:
        db.update_project_fields(pid, name=body.name)
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.delete("/{pid}")
def delete_project(pid: str) -> Response:
    shutil.rmtree(config.project_dir(pid), ignore_errors=True)
    db.delete_project(pid)
    return Response(status_code=204)

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
    fields = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.aspect in ("16:9", "9:16", "1:1"):
        fields["aspect"] = body.aspect
    if body.prompt_mode is not None:
        fields["prompt_mode"] = 1 if body.prompt_mode else 0
    if fields:
        db.update_project_fields(pid, **fields)
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.delete("/{pid}")
def delete_project(pid: str) -> Response:
    shutil.rmtree(config.project_dir(pid), ignore_errors=True)
    db.delete_project(pid)
    return Response(status_code=204)

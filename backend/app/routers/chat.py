"""Creative-director chat endpoint (with image-generation tool)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db
from ..models import ChatRequest
from ..services import chat as chat_service

router = APIRouter(prefix="/api/projects/{pid}", tags=["chat"])


@router.post("/chat")
def chat(pid: str, body: ChatRequest) -> dict:
    project = db.get_project(pid)
    if project is None:
        raise HTTPException(404, "Project not found")
    messages = [m.model_dump() for m in body.messages]
    return chat_service.chat(project, messages, body.cursor_time)

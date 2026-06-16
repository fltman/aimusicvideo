"""Creative-director chat endpoint (with image-generation tool).

The conversation is persisted per project (projects.chat_json) so it survives
closing the chat, reloading, and re-opening the project.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

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
    res = chat_service.chat(project, messages, body.cursor_time)
    # persist the conversation (the incoming turns + this reply)
    history = messages + [{"role": "assistant", "content": res.get("reply", "")}]
    db.update_project_fields(pid, chat_json=history[-200:])
    return res


@router.get("/chat")
def get_chat(pid: str) -> dict:
    project = db.get_project(pid)
    if project is None:
        raise HTTPException(404, "Project not found")
    return {"messages": project.get("chat_json") or []}


@router.delete("/chat")
def clear_chat(pid: str) -> Response:
    if db.get_project(pid) is None:
        raise HTTPException(404, "Project not found")
    db.update_project_fields(pid, chat_json=[])
    return Response(status_code=204)

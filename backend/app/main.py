"""FastAPI application entrypoint for the AI Music Video Studio backend."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routers import (
    chat, director, export, filters, media, projects, queue, song, timeline,
)
from .services import filters as filters_service

# Ensure storage dirs exist before mounting StaticFiles at import time.
config.ensure_dirs()

app = FastAPI(title="AI Music Video Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5200", "http://127.0.0.1:5200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()
    db.init_db()
    filters_service.seed_builtins()


app.include_router(projects.router)
app.include_router(media.router)
app.include_router(song.router)
app.include_router(timeline.router)
app.include_router(chat.router)
app.include_router(queue.router)
app.include_router(filters.router)
app.include_router(export.router)
app.include_router(director.router)

app.mount("/files", StaticFiles(directory=config.DATA_DIR), name="files")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "whisper_model_ready": config.whisper_model_ready()}

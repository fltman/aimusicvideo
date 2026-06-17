"""Media-library endpoints: upload, list, delete project assets."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from .. import config, db
from ..models import AnimateRequest, MediaUpdate, PlaceholderCreate
from ..services import (
    audio, chat as chat_service, genqueue, imagegen, placeholders, videogen,
)

router = APIRouter(prefix="/api/projects/{pid}/media", tags=["media"])


@router.get("")
def list_media(pid: str) -> list[dict]:
    return db.list_media(pid)


@router.post("")
async def upload_media(
    pid: str, files: list[UploadFile] = File(...)
) -> list[dict]:
    if db.get_project(pid) is None:
        raise HTTPException(404, "Project not found")

    media_dir = config.project_dir(pid) / "media"
    thumbs_dir = media_dir / "thumbs"
    media_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    created: list[dict] = []
    for upload in files:
        asset_id = uuid.uuid4().hex
        original_name = upload.filename or asset_id
        ext = os.path.splitext(original_name)[1]
        asset_path = media_dir / f"{asset_id}{ext}"

        with open(asset_path, "wb") as fh:
            fh.write(await upload.read())

        info = audio.probe(str(asset_path))
        kind = audio.media_kind(original_name, info)

        thumb_abs = thumbs_dir / f"{asset_id}.jpg"
        thumb_rel = None
        if audio.make_thumbnail(str(asset_path), str(thumb_abs), kind):
            thumb_rel = config.rel_to_data(thumb_abs)

        asset = db.add_media(
            project_id=pid,
            kind=kind,
            original_name=original_name,
            path=config.rel_to_data(asset_path),
            thumb_path=thumb_rel,
            duration_sec=info.get("duration"),
            width=info.get("width"),
            height=info.get("height"),
        )
        created.append(asset)

    return created


@router.post("/placeholder")
def create_placeholder(pid: str, body: PlaceholderCreate) -> dict:
    """Create a single prompt placeholder (e.g. a video placeholder from the UI)."""
    if db.get_project(pid) is None:
        raise HTTPException(404, "Project not found")
    return placeholders.create(pid, body.prompt)


@router.post("/{asset_id}/fulfill")
async def fulfill_placeholder(
    pid: str, asset_id: str, file: UploadFile = File(...)
) -> dict:
    """Drop a real image/video onto a placeholder. Every placeholder that shares
    the same prompt is turned into that asset in place."""
    if db.get_project(pid) is None:
        raise HTTPException(404, "Project not found")
    data = await file.read()
    updated = placeholders.fulfill(pid, asset_id, data, file.filename or "drop")
    if not updated:
        raise HTTPException(400, "Not a placeholder, or unsupported file")
    return {"updated": updated}


@router.post("/{asset_id}/animate")
def animate(pid: str, asset_id: str, body: AnimateRequest) -> dict:
    asset = db.get_media(asset_id)
    if asset is None or asset["project_id"] != pid:
        raise HTTPException(404, "Asset not found")
    if asset["kind"] != "image":
        raise HTTPException(400, "Only images can be animated")

    img_path = config.DATA_DIR / asset["path"]
    prompt = body.prompt or ""
    duration = body.duration
    aspect = (db.get_project(pid) or {}).get("aspect") or "16:9"

    def runner() -> dict:
        mp4 = videogen.image_to_video(img_path.read_bytes(), prompt, duration, aspect)
        return videogen.save_video_asset(pid, mp4, asset, prompt)

    label = asset.get("label") or asset.get("original_name") or "clip"
    job = genqueue.submit(pid, "video", f"{label} → video", runner)
    return {"job_id": job["id"], "status": job["status"]}


@router.post("/{asset_id}/vary")
def vary(pid: str, asset_id: str) -> dict:
    asset = db.get_media(asset_id)
    if asset is None or asset["project_id"] != pid:
        raise HTTPException(404, "Asset not found")
    if asset["kind"] != "image":
        raise HTTPException(400, "Only images can be varied")
    img_path = config.DATA_DIR / asset["path"]
    label = asset.get("label") or asset.get("original_name") or "image"

    def runner() -> dict:
        png = imagegen.generate_image(
            "A fresh variation of this image — keep the same subject, mood and "
            "style, but vary the composition and details.",
            [img_path.read_bytes()],
        )
        return chat_service._save_image_asset(pid, png, label)

    job = genqueue.submit(pid, "image", f"vary · {label}", runner)
    return {"job_id": job["id"]}


@router.patch("/{asset_id}")
def update_media(pid: str, asset_id: str, body: MediaUpdate) -> dict:
    asset = db.update_media(asset_id, label=body.label, tags=body.tags)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    return asset


@router.delete("/{asset_id}")
def delete_media(pid: str, asset_id: str) -> Response:
    asset = db.delete_media(asset_id)
    if asset:
        for rel in (asset.get("path"), asset.get("thumb_path")):
            if rel:
                abspath = config.DATA_DIR / rel
                try:
                    Path(abspath).unlink(missing_ok=True)
                except OSError:
                    pass
    return Response(status_code=204)

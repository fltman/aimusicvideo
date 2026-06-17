"""Prompt-mode placeholders.

In prompt mode the app inserts cheap placeholder media assets (kind='placeholder',
carrying only the prompt) instead of generating real images/videos. A placeholder
is "fulfilled" by dropping a real image/video onto it: the file is saved and every
placeholder that shares the EXACT same prompt is turned into that real asset in
place (so all its timeline clips update at once).
"""
from __future__ import annotations

import shutil
import uuid

from .. import config, db
from . import audio


def create(pid: str, prompt: str, label: str | None = None,
           tags: list[str] | None = None, bible_entity: str | None = None) -> dict:
    """Add a placeholder media asset (no file; the prompt is the payload)."""
    name = label or " ".join((prompt or "").split()[:6]).strip()[:60] or "placeholder"
    return db.add_media(
        project_id=pid, kind="placeholder", original_name=name,
        path="", thumb_path=None, label=label, tags=tags,
        gen_prompt=prompt, bible_entity=bible_entity,
    )


def fulfill(pid: str, asset_id: str, file_bytes: bytes, filename: str) -> list[dict]:
    """Fill a placeholder from a real image/video; update all same-prompt ones.

    Returns the list of assets that were converted (each keeps its own id).
    """
    target = db.get_media(asset_id)
    if not target or target.get("project_id") != pid or target.get("kind") != "placeholder":
        return []
    prompt = target.get("gen_prompt") or ""

    media_dir = config.project_dir(pid) / "media"
    thumbs_dir = media_dir / "thumbs"
    media_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    ext = ("." + filename.rsplit(".", 1)[-1]) if "." in filename else ""
    # save one master copy, probe it to learn kind/dims
    master_id = uuid.uuid4().hex
    master = media_dir / f"{master_id}{ext}"
    master.write_bytes(file_bytes)
    info = audio.probe(str(master))
    kind = audio.media_kind(filename, info)
    if kind not in ("image", "video"):
        master.unlink(missing_ok=True)
        return []

    # every placeholder sharing this prompt becomes the real asset (own file copy
    # so each is self-contained for later deletion)
    matches = db.placeholders_with_prompt(pid, prompt)
    if not any(m["id"] == asset_id for m in matches):
        matches.append(target)
    out: list[dict] = []
    for m in matches:
        aid = m["id"]
        dest = media_dir / f"{aid}{ext}"
        shutil.copyfile(master, dest)
        thumb_abs = thumbs_dir / f"{aid}.jpg"
        thumb_rel = None
        if audio.make_thumbnail(str(dest), str(thumb_abs), kind):
            thumb_rel = config.rel_to_data(thumb_abs)
        updated = db.update_media_content(
            aid, kind=kind, path=config.rel_to_data(dest), thumb_path=thumb_rel,
            width=info.get("width"), height=info.get("height"),
            duration_sec=info.get("duration"),
        )
        if updated:
            out.append(updated)
    master.unlink(missing_ok=True)
    return out

"""SQLite persistence layer.

All schema knowledge lives here so routers/services call helper functions
rather than writing SQL. JSON columns (analysis results + timeline doc) are
transparently encoded/decoded. WAL mode + per-call connections make this safe
for the background analysis threads.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import config

# JSON-encoded columns on the projects table.
_PROJECT_JSON_COLS = {
    "beats_json",
    "waveform_json",
    "lyrics_json",
    "mood_json",
    "timeline_json",
    "rhythm_json",
    "story_json",
    "script_json",
    "bible_links_json",
    "chat_json",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    song_original_name TEXT,
    song_wav_path     TEXT,
    duration_sec      REAL,
    analysis_status   TEXT NOT NULL DEFAULT 'none',
    analysis_progress REAL NOT NULL DEFAULT 0,
    analysis_stage    TEXT,
    analysis_error    TEXT,
    beats_json        TEXT,
    waveform_json     TEXT,
    lyrics_json       TEXT,
    mood_json         TEXT,
    timeline_json     TEXT
);

CREATE TABLE IF NOT EXISTS media_assets (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    kind          TEXT NOT NULL,
    original_name TEXT NOT NULL,
    path          TEXT NOT NULL,
    thumb_path    TEXT,
    duration_sec  REAL,
    width         INTEGER,
    height        INTEGER,
    label         TEXT,
    tags          TEXT,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_media_project ON media_assets(project_id);
"""

EMPTY_TIMELINE = {"tracks": [], "clips": []}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    config.ensure_dirs()
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the initial schema to existing dbs."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(media_assets)")}
    for col in ("label", "tags", "gen_prompt", "bible_entity"):
        if col not in cols:
            conn.execute(f"ALTER TABLE media_assets ADD COLUMN {col} TEXT")
    pcols = {r["name"] for r in conn.execute("PRAGMA table_info(projects)")}
    if "aspect" not in pcols:
        conn.execute("ALTER TABLE projects ADD COLUMN aspect TEXT DEFAULT '16:9'")
    if "prompt_mode" not in pcols:
        conn.execute("ALTER TABLE projects ADD COLUMN prompt_mode INTEGER DEFAULT 0")
    for col in ("rhythm_json", "story_json", "script_json", "bible_links_json",
                "chat_json"):
        if col not in pcols:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {col} TEXT")


def _row_to_project(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for col in _PROJECT_JSON_COLS:
        if col in d:
            d[col] = json.loads(d[col]) if d[col] else None
    return d


# ── projects ─────────────────────────────────────────────────────────────────

def create_project(name: str) -> dict[str, Any]:
    pid = _new_id()
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO projects (id, name, created_at, updated_at,
                 analysis_status, analysis_progress, timeline_json)
               VALUES (?, ?, ?, ?, 'none', 0, ?)""",
            (pid, name, now, now, json.dumps(EMPTY_TIMELINE)),
        )
    return get_project(pid)  # type: ignore[return-value]


def list_projects() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, name, created_at, updated_at, duration_sec,
                      analysis_status, analysis_progress, mood_json,
                      (song_wav_path IS NOT NULL) AS has_song
               FROM projects ORDER BY updated_at DESC"""
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            raw = d.pop("mood_json", None)
            try:
                mood = json.loads(raw) if raw else None
            except (ValueError, TypeError):
                mood = None
            d["palette"] = mood.get("palette") if isinstance(mood, dict) else None
            thumb = conn.execute(
                """SELECT thumb_path, path, kind FROM media_assets
                   WHERE project_id = ? AND kind IN ('image', 'video')
                   ORDER BY created_at DESC LIMIT 1""",
                (d["id"],),
            ).fetchone()
            d["thumb"] = (
                thumb["thumb_path"]
                or (thumb["path"] if thumb["kind"] == "image" else None)
            ) if thumb else None
            out.append(d)
    return out


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    return _row_to_project(row) if row else None


def update_project_fields(project_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields = dict(fields)
    for col in _PROJECT_JSON_COLS:
        if col in fields and not isinstance(fields[col], (str, type(None))):
            fields[col] = json.dumps(fields[col])
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE projects SET {cols} WHERE id = ?",
            (*fields.values(), project_id),
        )


def touch_project(project_id: str) -> None:
    update_project_fields(project_id)


def delete_project(project_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM media_assets WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def set_timeline(project_id: str, doc: dict[str, Any]) -> None:
    update_project_fields(project_id, timeline_json=doc)


def get_timeline(project_id: str) -> dict[str, Any]:
    p = get_project(project_id)
    if not p:
        return dict(EMPTY_TIMELINE)
    return p.get("timeline_json") or dict(EMPTY_TIMELINE)


# ── media assets ─────────────────────────────────────────────────────────────

def _row_to_media(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
    return d


def add_media(
    project_id: str,
    kind: str,
    original_name: str,
    path: str,
    thumb_path: Optional[str] = None,
    duration_sec: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    label: Optional[str] = None,
    tags: Optional[list[str]] = None,
    gen_prompt: Optional[str] = None,
    bible_entity: Optional[str] = None,
) -> dict[str, Any]:
    aid = _new_id()
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO media_assets
                 (id, project_id, kind, original_name, path, thumb_path,
                  duration_sec, width, height, label, tags, gen_prompt,
                  bible_entity, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (aid, project_id, kind, original_name, path, thumb_path,
             duration_sec, width, height, label,
             json.dumps(tags) if tags else None, gen_prompt, bible_entity, now),
        )
    return get_media(aid)  # type: ignore[return-value]


def list_media(project_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM media_assets WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
    return [_row_to_media(r) for r in rows]


def get_media(asset_id: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM media_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    return _row_to_media(row) if row else None


def update_media(
    asset_id: str,
    label: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    """Update an asset's label and/or tags (pass to set; None leaves unchanged)."""
    sets, vals = [], []
    if label is not None:
        sets.append("label = ?")
        vals.append(label)
    if tags is not None:
        sets.append("tags = ?")
        vals.append(json.dumps(tags) if tags else None)
    if sets:
        vals.append(asset_id)
        with get_conn() as conn:
            conn.execute(
                f"UPDATE media_assets SET {', '.join(sets)} WHERE id = ?", vals
            )
    return get_media(asset_id)


def update_media_content(
    asset_id: str,
    kind: str,
    path: str,
    thumb_path: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration_sec: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Turn a placeholder into a real asset in place (keeps id/label/tags/prompt)."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE media_assets SET kind = ?, path = ?, thumb_path = ?,
                 width = ?, height = ?, duration_sec = ? WHERE id = ?""",
            (kind, path, thumb_path, width, height, duration_sec, asset_id),
        )
    return get_media(asset_id)


def placeholders_with_prompt(project_id: str, prompt: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM media_assets
               WHERE project_id = ? AND kind = 'placeholder' AND gen_prompt = ?""",
            (project_id, prompt),
        ).fetchall()
    return [_row_to_media(r) for r in rows]


def delete_media(asset_id: str) -> Optional[dict[str, Any]]:
    asset = get_media(asset_id)
    if asset:
        with get_conn() as conn:
            conn.execute("DELETE FROM media_assets WHERE id = ?", (asset_id,))
    return asset

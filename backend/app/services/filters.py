"""Filter plugin library: seed, list, read, version, fork, and preview-render.

The live library lives under DATA_DIR/filters/<id>/ (seeded once from the shipped
templates in BUILTIN_FILTERS_DIR). Each filter is { manifest.json, filter.py,
versions/NNNN.py + NNNN.json, chat.json }. Previews render through the global
generation queue (max 3) as isolated subprocesses (app.filters.runner).
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .. import config, db
from . import genqueue


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "filter"


# ── seeding ──────────────────────────────────────────────────────────────────

def seed_builtins() -> None:
    """Copy shipped filter templates into the live library (once each)."""
    config.FILTERS_DIR.mkdir(parents=True, exist_ok=True)
    src_root = config.BUILTIN_FILTERS_DIR
    if not src_root.exists():
        return
    for src in src_root.iterdir():
        # only seed complete templates (guards against mid-write races)
        if not src.is_dir() or not (src / "manifest.json").exists() \
                or not (src / "filter.py").exists():
            continue
        dst = config.FILTERS_DIR / src.name
        # skip only if already fully seeded; otherwise complete a partial copy
        if dst.exists() and (dst / "filter.py").exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / "filter.py", dst / "filter.py")
        shutil.copy(src / "manifest.json", dst / "manifest.json")
        vdir = dst / "versions"
        vdir.mkdir(exist_ok=True)
        if not (vdir / "0001.py").exists():
            shutil.copy(src / "filter.py", vdir / "0001.py")
            (vdir / "0001.json").write_text(json.dumps(
                {"version": 1, "message": "Initial version", "ts": _now()}))


# ── reading ──────────────────────────────────────────────────────────────────

def _filter_dir(fid: str) -> Path:
    return config.FILTERS_DIR / fid


def _read_manifest(fid: str) -> Optional[dict]:
    p = _filter_dir(fid) / "manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


def read_params(fid: str) -> list[dict]:
    """Load the filter's PARAMS by importing filter.py (best-effort)."""
    fp = _filter_dir(fid) / "filter.py"
    if not fp.exists():
        return []
    try:
        spec = importlib.util.spec_from_file_location(f"filter_{fid}", fp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        params = getattr(mod, "PARAMS", [])
        return params if isinstance(params, list) else []
    except Exception:
        return []


def default_params(fid: str) -> dict:
    return {p["key"]: p.get("default") for p in read_params(fid) if "key" in p}


def list_filters() -> list[dict]:
    out = []
    for d in sorted(config.FILTERS_DIR.iterdir() if config.FILTERS_DIR.exists() else []):
        if not d.is_dir():
            continue
        m = _read_manifest(d.name)
        if m:
            out.append({**m, "param_count": len(read_params(d.name))})
    # templates last, then by name
    out.sort(key=lambda m: (bool(m.get("template")), m.get("name", "")))
    return out


def list_presets(fid: str) -> list[dict]:
    p = _filter_dir(fid) / "presets.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return []


def save_preset(fid: str, name: str, params: dict) -> list[dict]:
    presets = [x for x in list_presets(fid) if x.get("name") != name]
    presets.append({"name": name, "params": params})
    (_filter_dir(fid) / "presets.json").write_text(json.dumps(presets))
    return presets


def get_filter(fid: str) -> Optional[dict]:
    m = _read_manifest(fid)
    if not m:
        return None
    code = (_filter_dir(fid) / "filter.py").read_text()
    return {"manifest": m, "code": code, "params": read_params(fid),
            "versions": list_versions(fid), "presets": list_presets(fid)}


# ── versions ─────────────────────────────────────────────────────────────────

def list_versions(fid: str) -> list[dict]:
    vdir = _filter_dir(fid) / "versions"
    if not vdir.exists():
        return []
    metas = []
    for jf in sorted(vdir.glob("*.json")):
        try:
            metas.append(json.loads(jf.read_text()))
        except (ValueError, OSError):
            pass
    metas.sort(key=lambda v: v.get("version", 0), reverse=True)
    return metas


def _next_version(fid: str) -> int:
    return len(list(( _filter_dir(fid) / "versions").glob("*.py"))) + 1


def save_version(fid: str, code: str, message: str) -> dict:
    """Persist new code as the current filter.py + a new version snapshot."""
    fdir = _filter_dir(fid)
    vdir = fdir / "versions"
    vdir.mkdir(exist_ok=True)
    v = _next_version(fid)
    (vdir / f"{v:04d}.py").write_text(code)
    meta = {"version": v, "message": message, "ts": _now()}
    (vdir / f"{v:04d}.json").write_text(json.dumps(meta))
    (fdir / "filter.py").write_text(code)
    m = _read_manifest(fid) or {}
    m["version"] = v
    (fdir / "manifest.json").write_text(json.dumps(m, indent=2))
    return meta


def get_version_code(fid: str, version: int) -> Optional[str]:
    p = _filter_dir(fid) / "versions" / f"{version:04d}.py"
    return p.read_text() if p.exists() else None


def rollback(fid: str, version: int) -> Optional[dict]:
    code = get_version_code(fid, version)
    if code is None:
        return None
    save_version(fid, code, f"Rolled back to v{version}")
    return get_filter(fid)


# ── create / fork ────────────────────────────────────────────────────────────

def _new_id(name: str) -> str:
    base = _slug(name)
    fid = base
    while _filter_dir(fid).exists():
        fid = f"{base}-{uuid.uuid4().hex[:4]}"
    return fid


def fork(src_id: str, new_name: str) -> Optional[dict]:
    src = _filter_dir(src_id)
    if not src.exists():
        return None
    fid = _new_id(new_name)
    dst = _filter_dir(fid)
    shutil.copytree(src, dst)
    shutil.rmtree(dst / "versions", ignore_errors=True)
    (dst / "versions").mkdir()
    shutil.copy(dst / "filter.py", dst / "versions" / "0001.py")
    (dst / "versions" / "0001.json").write_text(json.dumps(
        {"version": 1, "message": f"Forked from {src_id}", "ts": _now()}))
    (dst / "chat.json").write_text("[]")
    m = _read_manifest(src_id) or {}
    m.update(id=fid, name=new_name, version=1, builtin=False,
             template=False, forkedFrom=src_id)
    (dst / "manifest.json").write_text(json.dumps(m, indent=2))
    return get_filter(fid)


def create_from_template(name: str) -> dict:
    return fork("_template", name)  # type: ignore[return-value]


def rename_filter(fid: str, name: str) -> Optional[dict]:
    """Rename a (non-built-in) filter in place."""
    m = _read_manifest(fid)
    if not m or m.get("builtin"):
        return None  # built-ins keep their shipped name (use Save As / fork)
    m["name"] = name
    m["template"] = False
    (_filter_dir(fid) / "manifest.json").write_text(json.dumps(m, indent=2))
    return get_filter(fid)


def delete_filter(fid: str) -> bool:
    m = _read_manifest(fid)
    if not m or m.get("builtin"):
        return False  # don't delete shipped built-ins
    shutil.rmtree(_filter_dir(fid), ignore_errors=True)
    return True


# ── chat history ─────────────────────────────────────────────────────────────

def read_chat(fid: str) -> list[dict]:
    p = _filter_dir(fid) / "chat.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return []


def write_chat(fid: str, messages: list[dict]) -> None:
    (_filter_dir(fid) / "chat.json").write_text(json.dumps(messages))


# ── preview render (via the generation queue) ────────────────────────────────

PREVIEW_W, PREVIEW_H, PREVIEW_FPS, PREVIEW_DUR = 854, 480, 24, 5.0
FAST_W, FAST_H, FAST_FPS, FAST_DUR = 426, 240, 20, 2.5


def render_preview(project: dict, fid: str, params: dict, cursor_time: float,
                   fast: bool = False) -> dict:
    """Enqueue a short timeline-under-playhead preview rendered through filter `fid`.

    `fast` renders at low res / short duration for quick vibe-coding iteration."""
    pid = project["id"]
    media = {
        m["id"]: {"path": str(config.DATA_DIR / m["path"]),
                  "kind": m["kind"], "duration": m.get("duration_sec")}
        for m in db.list_media(pid)
    }
    tl = project.get("timeline_json") or {"tracks": [], "clips": []}
    song = (str(config.DATA_DIR / project["song_wav_path"])
            if project.get("song_wav_path") else None)
    dur = project.get("duration_sec") or PREVIEW_DUR
    start = max(0.0, min(float(cursor_time), max(0.0, dur - 0.2)))

    preview_dir = config.project_dir(pid) / "filter_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    out_id = uuid.uuid4().hex
    out_path = preview_dir / f"{out_id}.mp4"

    pw, ph, pfps, pdur = (
        (FAST_W, FAST_H, FAST_FPS, FAST_DUR) if fast
        else (PREVIEW_W, PREVIEW_H, PREVIEW_FPS, PREVIEW_DUR)
    )
    spec = {
        "filter_path": str(_filter_dir(fid) / "filter.py"),
        "params": params or default_params(fid),
        "beats": project.get("beats_json") or {},
        "window": {"start": start, "duration": pdur, "fps": pfps},
        "size": {"w": pw, "h": ph},
        "tracks": tl.get("tracks", []), "clips": tl.get("clips", []),
        "media": media, "song_wav": song,
        "data_dir": str(config.DATA_DIR), "output": str(out_path),
    }
    spec_path = preview_dir / f"{out_id}.json"
    spec_path.write_text(json.dumps(spec))

    def runner() -> dict:
        proc = subprocess.run(
            [sys.executable, "-m", "app.filters.runner", str(spec_path)],
            cwd=str(config.BACKEND_DIR), capture_output=True, text=True,
        )
        spec_path.unlink(missing_ok=True)
        if proc.returncode != 0 or not out_path.exists():
            raise RuntimeError((proc.stderr or "render failed")[-300:])
        return {"preview_url": "/files/" + config.rel_to_data(out_path),
                "kind": "filter_preview"}

    label = (_read_manifest(fid) or {}).get("name", fid)
    return genqueue.submit(pid, "filter", f"preview · {label}", runner)

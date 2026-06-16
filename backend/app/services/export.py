"""Full-video export: composite the timeline + effect-clip filter chain → mp4.

Runs as a queued subprocess (app.filters.export_runner). Effect clips (clips on
effect-kind tracks carrying a filterId) are applied in track order. A progress
file is updated as windows complete so the UI can show a bar.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

from .. import config, db
from . import genqueue

RESOLUTIONS = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}


def start_export(project: dict, resolution: str = "720p", fps: int = 30) -> tuple[dict, str]:
    pid = project["id"]
    w, h = RESOLUTIONS.get(resolution, RESOLUTIONS["720p"])
    tl = project.get("timeline_json") or {"tracks": [], "clips": []}
    tracks = tl.get("tracks", [])
    clips = tl.get("clips", [])

    media = {
        m["id"]: {"path": str(config.DATA_DIR / m["path"]),
                  "kind": m["kind"], "duration": m.get("duration_sec")}
        for m in db.list_media(pid)
    }

    # effect clips, ordered by their effect-track index
    track_order = {t["id"]: i for i, t in enumerate(tracks)}
    effect_track_ids = {t["id"] for t in tracks if t.get("kind") == "effect"}
    effects = [
        {"filterId": c.get("filterId"), "params": c.get("params") or {},
         "start": c["start"], "duration": c["duration"],
         "order": track_order.get(c["trackId"], 0)}
        for c in clips
        if c.get("trackId") in effect_track_ids and c.get("filterId")
    ]

    duration = project.get("duration_sec") or 0.0
    song = (str(config.DATA_DIR / project["song_wav_path"])
            if project.get("song_wav_path") else None)

    export_dir = config.project_dir(pid) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_id = uuid.uuid4().hex
    out_path = export_dir / f"{export_id}.mp4"
    progress_path = export_dir / f"{export_id}.progress.json"

    spec = {
        "duration": duration,
        "window": {"start": 0.0, "duration": duration, "fps": fps},
        "size": {"w": w, "h": h},
        "tracks": tracks, "clips": clips, "media": media,
        "beats": project.get("beats_json") or {},
        "effects": effects,
        "song_wav": song,
        "filters_dir": str(config.FILTERS_DIR),
        "data_dir": str(config.DATA_DIR),
        "output": str(out_path),
        "progress_file": str(progress_path),
    }
    spec_path = export_dir / f"{export_id}.spec.json"
    spec_path.write_text(json.dumps(spec))

    def runner() -> dict:
        proc = subprocess.run(
            [sys.executable, "-m", "app.filters.export_runner", str(spec_path)],
            cwd=str(config.BACKEND_DIR), capture_output=True, text=True,
        )
        spec_path.unlink(missing_ok=True)
        if proc.returncode != 0 or not out_path.exists():
            raise RuntimeError((proc.stderr or "export failed")[-400:])
        return {"export_url": "/files/" + config.rel_to_data(out_path),
                "kind": "export"}

    name = project.get("name") or "video"
    job = genqueue.submit(pid, "export", f"export · {name} · {resolution}", runner)
    return job, export_id


def export_progress(pid: str, export_id: str) -> float:
    p = config.project_dir(pid) / "exports" / f"{export_id}.progress.json"
    if not p.exists():
        return 0.0
    try:
        return float(json.loads(p.read_text()).get("progress", 0.0))
    except (ValueError, OSError):
        return 0.0

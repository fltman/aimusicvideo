"""Full-timeline export runner — executed as a subprocess.

    python -m app.filters.export_runner <spec.json>

Renders the WHOLE timeline: composites the visual clips and applies the effect
chain (every effect-track clip's filter, in track order, at its time range) over
the full song, then muxes the song audio. Reuses the compositor + beat envelopes
from app.filters.runner. Rendered in windows to bound memory (each window
pre-extracts only its own video frames), all feeding one continuous encoder.

Spec JSON adds to the preview spec:
  "duration": float, "effects": [{filterId, params, start, duration, order}],
  "filters_dir": abs, "progress_file": abs
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np

from .runner import Compositor, compute_envelope, compute_rms

WINDOW_SEC = 4.0


def _load_filter(filter_path):
    spec = importlib.util.spec_from_file_location(f"f_{Path(filter_path).parent.name}",
                                                  filter_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    spec = json.loads(Path(sys.argv[1]).read_text())
    w, h = spec["size"]["w"], spec["size"]["h"]
    fps = spec["window"]["fps"]
    duration = float(spec["duration"])
    total = max(1, int(duration * fps))
    filters_dir = Path(spec["filters_dir"])
    progress_file = spec.get("progress_file")

    # resolve effect clips → loaded filters with effective params, ordered
    effects = []
    cache: dict = {}
    for e in sorted(spec.get("effects", []), key=lambda x: x.get("order", 0)):
        fid = e.get("filterId")
        if not fid:
            continue
        if fid not in cache:
            fp = filters_dir / fid / "filter.py"
            if not fp.exists():
                continue
            try:
                mod = _load_filter(fp)
                defaults = {p["key"]: p.get("default")
                            for p in getattr(mod, "PARAMS", []) if "key" in p}
                cache[fid] = (getattr(mod, "process"), defaults)
            except Exception as ex:  # skip a broken filter rather than abort export
                sys.stderr.write(f"skip filter {fid}: {ex}\n")
                continue
        process, defaults = cache[fid]
        params = {**defaults, **(e.get("params") or {})}
        effects.append({"process": process, "params": params,
                        "start": e["start"], "end": e["start"] + e["duration"]})

    # global beat envelopes + loudness over the whole song
    beats = spec.get("beats") or {}
    envs = {b: compute_envelope(total, fps, beats.get(b, []), 0.0)
            for b in ("bass", "mid", "high")}
    rms = compute_rms(spec.get("song_wav"), 0.0, duration, total, fps)
    onsets = {b: list(beats.get(b, [])) for b in ("bass", "mid", "high")}
    rng = np.random.default_rng(42)

    raw_out = str(Path(spec["output"]).with_suffix(".raw.mp4"))
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", raw_out],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    tracks, clips, media = spec.get("tracks", []), spec.get("clips", []), spec.get("media", {})
    gi = 0
    win_start = 0.0
    while win_start < duration - 1e-6:
        win_dur = min(WINDOW_SEC, duration - win_start)
        comp = Compositor(tracks, clips, media, w, h, win_start, win_dur, fps)
        nf = max(1, int(round(win_dur * fps)))
        for i in range(nf):
            if gi >= total:
                break
            t = win_start + i / fps
            frame = comp.frame_at(i, t)
            ctx = types.SimpleNamespace(
                t=t, i=gi, fps=fps, w=w, h=h,
                bass=float(envs["bass"][gi]), mid=float(envs["mid"][gi]),
                high=float(envs["high"][gi]), rms=float(rms[gi]),
                onsets=onsets, rng=rng,
            )
            for eff in effects:
                if eff["start"] <= t < eff["end"]:
                    try:
                        out = eff["process"](frame, ctx, eff["params"])
                        if out is not None:
                            frame = out
                    except Exception as ex:
                        sys.stderr.write(f"effect err @{gi}: {ex}\n")
            if frame.shape[0] != h or frame.shape[1] != w:
                import cv2
                frame = cv2.resize(frame, (w, h))
            enc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
            gi += 1
        comp.release()
        win_start += win_dur
        if progress_file:
            try:
                Path(progress_file).write_text(json.dumps({"progress": min(1.0, gi / total)}))
            except OSError:
                pass

    enc.stdin.close()
    enc.wait()

    out_path = spec["output"]
    song = spec.get("song_wav")
    if song and Path(song).exists():
        subprocess.run(
            ["ffmpeg", "-y", "-i", raw_out, "-i", song,
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
             "-shortest", out_path],
            stderr=subprocess.DEVNULL,
        )
        Path(raw_out).unlink(missing_ok=True)
    else:
        Path(raw_out).replace(out_path)
    if progress_file:
        Path(progress_file).write_text(json.dumps({"progress": 1.0}))


if __name__ == "__main__":
    main()

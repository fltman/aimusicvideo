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

import cv2
import numpy as np

from . import textrender
from .runner import Compositor, compute_envelope, compute_rms

WINDOW_SEC = 4.0


def _audio_inputs(tracks, clips, media, song_wav, r_start, r_end):
    """Audio sources active in [r_start, r_end]: (path, src_in, dur, delay)."""
    hidden = {t["id"] for t in tracks if t.get("hidden")}
    audio_ids = {t["id"] for t in tracks
                 if t.get("kind") == "audio" and t["id"] not in hidden}
    out = []
    for c in clips:
        if c.get("trackId") not in audio_ids:
            continue
        a = max(r_start, c["start"])
        b = min(r_end, c["start"] + c["duration"])
        if b <= a:
            continue
        if c.get("source") == "song":
            path = song_wav
        elif c.get("assetId") and media.get(c["assetId"]) \
                and media[c["assetId"]]["kind"] == "audio":
            path = media[c["assetId"]]["path"]
        else:
            continue
        if not path or not Path(path).exists():
            continue
        src_in = (c.get("inPoint", 0.0) or 0.0) + (a - c["start"])
        out.append((path, src_in, b - a, a - r_start))
    return out


def _mux_audio(raw_out, out_path, inputs):
    if not inputs:
        Path(raw_out).replace(out_path)
        return
    cmd = ["ffmpeg", "-y", "-i", raw_out]
    for path, *_ in inputs:
        cmd += ["-i", path]
    parts = []
    for i, (_p, src_in, dur, delay) in enumerate(inputs):
        dms = int(delay * 1000)
        parts.append(
            f"[{i + 1}:a]atrim=start={src_in}:duration={dur},"
            f"asetpts=PTS-STARTPTS,adelay={dms}|{dms}[a{i}]")
    labels = "".join(f"[a{i}]" for i in range(len(inputs)))
    parts.append(f"{labels}amix=inputs={len(inputs)}:normalize=0[aout]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-shortest", out_path]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not Path(out_path).exists():
        Path(raw_out).replace(out_path)  # fall back to silent video
    else:
        Path(raw_out).unlink(missing_ok=True)


def _active_lyric(lyrics, t):
    for ly in lyrics:
        if ly["start"] <= t < ly["end"]:
            return ly["text"]
    return None


def _hex_to_bgr(hexstr):
    try:
        s = str(hexstr).lstrip("#")
        return (int(s[4:6], 16), int(s[2:4], 16), int(s[0:2], 16))
    except Exception:
        return (255, 255, 255)


def draw_caption(frame, text, w, h, position="bottom", color=(255, 255, 255), size=1.0):
    """Translucent box + centered text at top/center/bottom (writable copy)."""
    frame = np.array(frame, dtype=np.uint8, copy=True)
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = h / 500.0 * 1.5 * size
    thickness = max(1, int(round(scale * 1.4)))
    max_w = int(w * 0.86)
    (tw, th), base = cv2.getTextSize(text, font, scale, thickness)
    if tw > max_w and tw > 0:
        scale *= max_w / tw
        thickness = max(1, int(round(scale * 1.4)))
        (tw, th), base = cv2.getTextSize(text, font, scale, thickness)
    x = max(0, (w - tw) // 2)
    if position == "top":
        y = int(h * 0.10) + th
    elif position == "center":
        y = (h + th) // 2
    else:
        y = h - int(h * 0.07)
    pad = max(6, int(th * 0.45))
    overlay = frame.copy()
    cv2.rectangle(overlay, (x - pad, y - th - pad), (x + tw + pad, y + base + pad // 2),
                  (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)
    cv2.putText(frame, text, (x, y + 2), font, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)
    return frame


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
    lyrics = spec.get("lyrics") or []
    burn_lyrics = spec.get("burn_lyrics", True) and bool(lyrics)

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
    # optional export range (defaults to the whole song)
    r_start = max(0.0, float(spec.get("range_start", 0.0)))
    r_end = min(duration, float(spec.get("range_end", duration) or duration))
    if r_end <= r_start:
        r_start, r_end = 0.0, duration
    span = max(1e-3, r_end - r_start)

    win_start = r_start
    while win_start < r_end - 1e-6:
        win_dur = min(WINDOW_SEC, r_end - win_start)
        comp = Compositor(tracks, clips, media, w, h, win_start, win_dur, fps)
        nf = max(1, int(round(win_dur * fps)))
        for i in range(nf):
            t = win_start + i / fps
            gi = min(total - 1, int(round(t * fps)))  # global frame for envelopes
            frame = comp.frame_at(i, t)
            ctx = types.SimpleNamespace(
                t=t, i=gi, fps=fps, w=w, h=h,
                bass=float(envs["bass"][gi]), mid=float(envs["mid"][gi]),
                high=float(envs["high"][gi]), rms=float(rms[gi]),
                onsets=onsets, rng=rng, clip_progress=0.0,
            )
            for eff in effects:
                if eff["start"] <= t < eff["end"]:
                    ctx.clip_progress = (t - eff["start"]) / max(
                        1e-3, eff["end"] - eff["start"])
                    try:
                        out = eff["process"](frame, ctx, eff["params"])
                        if out is not None:
                            frame = out
                    except Exception as ex:
                        sys.stderr.write(f"effect err @{gi}: {ex}\n")
            if frame.shape[0] != h or frame.shape[1] != w:
                frame = cv2.resize(frame, (w, h))
            if burn_lyrics:
                line = _active_lyric(lyrics, t)
                if line:
                    frame = draw_caption(frame, line, w, h)
            for c in clips:
                txt = c.get("text")
                if txt and c["start"] <= t < c["start"] + c["duration"]:
                    prog = (t - c["start"]) / max(1e-3, c["duration"])
                    frame = textrender.render_text_clip(frame, c, prog, w, h)
            enc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
        comp.release()
        win_start += win_dur
        if progress_file:
            try:
                Path(progress_file).write_text(
                    json.dumps({"progress": min(1.0, (win_start - r_start) / span)}))
            except OSError:
                pass

    enc.stdin.close()
    enc.wait()

    out_path = spec["output"]
    inputs = _audio_inputs(tracks, clips, media, spec.get("song_wav"),
                           r_start, r_end)
    _mux_audio(raw_out, out_path, inputs)
    if progress_file:
        Path(progress_file).write_text(json.dumps({"progress": 1.0}))


if __name__ == "__main__":
    main()

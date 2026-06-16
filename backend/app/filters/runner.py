"""Filter render runner — executed as an isolated subprocess.

    python -m app.filters.runner <spec.json>

Composites the timeline's visual clips over a time window into "program" frames,
runs each frame through a filter plugin's `process(frame, ctx, p)` (beat-synced
via precomputed per-band envelopes), and encodes the result to mp4 (muxing the
song audio for that window). Running as a subprocess isolates the user/AI-edited
filter code from the API server.

Spec JSON:
{
  "filter_path": "...filter.py", "params": {...},
  "beats": {"bass":[...],"mid":[...],"high":[...]},
  "window": {"start": 60.0, "duration": 5.0, "fps": 24},
  "size": {"w": 854, "h": 480},
  "tracks": [...], "clips": [...],
  "media": {assetId: {"path": abs, "kind": "image|video", "duration": float}},
  "song_wav": abs|null, "data_dir": abs, "output": abs
}
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
import wave
from pathlib import Path

import cv2
import numpy as np


# ── beat envelopes (smooth triangle per onset) ───────────────────────────────

def compute_envelope(n_frames, fps, onsets, t0, duration=0.16, softness=0.5):
    env = np.zeros(n_frames, dtype=np.float32)
    fade = max(duration * softness, 0.001) if softness > 0 else 0.0
    for bt in onsets:
        rel = bt - t0
        margin = duration + fade + 0.05
        sf = max(0, int((rel - margin) * fps))
        ef = min(n_frames, int((rel + duration + margin) * fps) + 1)
        for f in range(sf, ef):
            t = f / fps
            if softness > 0:
                ru = max(0.0, (t - rel) / fade)
                rd = max(0.0, (rel + duration - t) / fade)
                val = min(ru, 1.0, rd)
            else:
                val = 1.0 if rel <= t <= rel + duration else 0.0
            env[f] = min(1.0, env[f] + val)
    return env


def compute_rms(song_wav, t0, duration, n_frames, fps):
    """Per-frame loudness 0..1 from the song wav window (best-effort)."""
    rms = np.zeros(n_frames, dtype=np.float32)
    if not song_wav or not Path(song_wav).exists():
        return rms
    try:
        with wave.open(str(song_wav), "rb") as wf:
            sr = wf.getframerate()
            nch = wf.getnchannels()
            sw = wf.getsampwidth()
            wf.setpos(min(int(t0 * sr), wf.getnframes()))
            raw = wf.readframes(int(duration * sr))
        if sw != 2:
            return rms
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        if nch > 1:
            data = data.reshape(-1, nch).mean(axis=1)
        for f in range(n_frames):
            a = int((f / fps) * sr)
            b = int(((f + 1) / fps) * sr)
            seg = data[a:b]
            if seg.size:
                rms[f] = float(np.sqrt(np.mean(seg ** 2)))
        m = rms.max()
        if m > 1e-6:
            rms = rms / m
    except Exception:
        pass
    return rms


# ── compositor: timeline visual under playhead → program frame ───────────────

def ken_burns(img, motion, p, w, h):
    """Cinematic motion on a still: slow zoom / pan driven by progress p (0..1)."""
    if motion == "zoom-out":
        s = 1.0 + 0.14 * (1.0 - p)
        bw, bh = int(w * s), int(h * s)
        x, y = (bw - w) // 2, (bh - h) // 2
    elif motion in ("pan-left", "pan-right", "pan-up", "pan-down"):
        s = 1.16
        bw, bh = int(w * s), int(h * s)
        mx, my = bw - w, bh - h
        if motion == "pan-left":
            x, y = int(mx * (1 - p)), my // 2
        elif motion == "pan-right":
            x, y = int(mx * p), my // 2
        elif motion == "pan-up":
            x, y = mx // 2, int(my * (1 - p))
        else:
            x, y = mx // 2, int(my * p)
    else:  # zoom-in (default)
        s = 1.0 + 0.14 * p
        bw, bh = int(w * s), int(h * s)
        x, y = (bw - w) // 2, (bh - h) // 2
    big = cv2.resize(img, (max(bw, w + 2), max(bh, h + 2)),
                     interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(big[y:y + h, x:x + w])


def _ffmpeg_extract(path, ss, dur, fps, w, h):
    """Decode a window of a video as cover-cropped BGR frames (reliable seeking)."""
    cmd = [
        "ffmpeg", "-ss", str(max(0.0, ss)), "-i", str(path), "-t", str(dur),
        "-r", str(fps),
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    nf = buf.size // (w * h * 3)
    if nf == 0:
        return np.zeros((0, h, w, 3), dtype=np.uint8)
    return buf[: nf * w * h * 3].reshape(nf, h, w, 3)


class Compositor:
    """Renders timeline visuals (topmost visible video/image clip) per frame.

    Image clips are loaded + cover-cropped once. Each video clip's frames for
    the window are pre-extracted via ffmpeg (cv2 per-frame seeking is unreliable
    on many codecs).
    """

    def __init__(self, tracks, clips, media, w, h, t0, dur, fps):
        self.clips = clips
        self.media = media
        self.w, self.h = w, h
        self.t0, self.fps = t0, fps
        self._img_cache: dict = {}
        self._vid: dict = {}  # clip_id -> {"start_i": int, "frames": ndarray}
        self._visual_track_ids = [
            t["id"] for t in tracks
            if t.get("kind") in ("video", "image") and not t.get("hidden")
        ]
        self._preextract_videos(t0, dur, fps)

    def _cover(self, img):
        ih, iw = img.shape[:2]
        scale = max(self.w / iw, self.h / ih)
        nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        x, y = (nw - self.w) // 2, (nh - self.h) // 2
        return resized[y:y + self.h, x:x + self.w]

    def _preextract_videos(self, t0, dur, fps):
        for c in self.clips:
            if c.get("trackId") not in self._visual_track_ids:
                continue
            asset = self.media.get(c.get("assetId") or "")
            if not asset or asset["kind"] != "video":
                continue
            a = max(t0, c["start"])
            b = min(t0 + dur, c["start"] + c["duration"])
            if b <= a:
                continue
            src_start = c.get("inPoint", 0.0) + (a - c["start"])
            frames = _ffmpeg_extract(asset["path"], src_start, b - a, fps,
                                     self.w, self.h)
            self._vid[c["id"]] = {"start_i": int(round((a - t0) * fps)),
                                  "frames": frames}

    def _active_clip(self, t):
        for tid in self._visual_track_ids:
            for c in self.clips:
                if c.get("trackId") == tid and c["start"] <= t < c["start"] + c["duration"]:
                    return c
        return None

    def _image_frame(self, asset):
        key = asset["path"]
        if key not in self._img_cache:
            img = cv2.imread(str(Path(asset["path"])))
            self._img_cache[key] = self._cover(img) if img is not None else None
        return self._img_cache[key]

    def frame_at(self, i, t):
        black = np.zeros((self.h, self.w, 3), dtype=np.uint8)
        clip = self._active_clip(t)
        if clip is None:
            return black
        asset = self.media.get(clip.get("assetId") or "")
        if not asset:
            return black
        if asset["kind"] == "image":
            f = self._image_frame(asset)
            if f is None:
                return black
            motion = clip.get("motion") or "zoom-in"  # subtle Ken Burns by default
            if motion != "none" and clip.get("duration"):
                p = max(0.0, min(1.0, (t - clip["start"]) / clip["duration"]))
                f = ken_burns(f, motion, p, self.w, self.h)
            return f
        data = self._vid.get(clip["id"])
        if data and data["frames"].shape[0]:
            idx = min(max(0, i - data["start_i"]), data["frames"].shape[0] - 1)
            return data["frames"][idx]
        return black

    def release(self):
        pass


def _load_filter(filter_path):
    spec = importlib.util.spec_from_file_location("user_filter", filter_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    spec = json.loads(Path(sys.argv[1]).read_text())
    w, h = spec["size"]["w"], spec["size"]["h"]
    fps = spec["window"]["fps"]
    t0 = spec["window"]["start"]
    dur = spec["window"]["duration"]
    n = max(1, int(dur * fps))

    mod = _load_filter(spec["filter_path"])
    process = getattr(mod, "process")
    params = spec.get("params", {})

    beats = spec.get("beats") or {}
    envs = {
        band: compute_envelope(n, fps, beats.get(band, []), t0)
        for band in ("bass", "mid", "high")
    }
    rms = compute_rms(spec.get("song_wav"), t0, dur, n, fps)
    onsets = {
        band: [b - t0 for b in beats.get(band, []) if t0 <= b <= t0 + dur]
        for band in ("bass", "mid", "high")
    }
    rng = np.random.default_rng(42)

    comp = Compositor(spec.get("tracks", []), spec.get("clips", []),
                      spec.get("media", {}), w, h, t0, dur, fps)

    raw_out = str(Path(spec["output"]).with_suffix(".raw.mp4"))
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-pix_fmt", "yuv420p", raw_out],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    for i in range(n):
        t = t0 + i / fps
        frame = comp.frame_at(i, t)
        ctx = types.SimpleNamespace(
            t=t, i=i, fps=fps, w=w, h=h,
            bass=float(envs["bass"][i]), mid=float(envs["mid"][i]),
            high=float(envs["high"][i]), rms=float(rms[i]),
            onsets=onsets, rng=rng,
            clip_progress=(i / (n - 1) if n > 1 else 0.0),  # 0..1 across the clip
        )
        try:
            out = process(frame, ctx, params)
            if out is not None:
                frame = out
        except Exception as e:  # a broken filter frame shouldn't abort the render
            sys.stderr.write(f"filter error @frame {i}: {e}\n")
        if frame.shape[0] != h or frame.shape[1] != w:
            frame = cv2.resize(frame, (w, h))
        enc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())

    comp.release()
    enc.stdin.close()
    enc.wait()

    # mux the song audio for this window (best-effort)
    out_path = spec["output"]
    song = spec.get("song_wav")
    if song and Path(song).exists():
        subprocess.run(
            ["ffmpeg", "-y", "-i", raw_out, "-ss", str(t0), "-t", str(dur),
             "-i", song, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-c:a", "aac", "-shortest", out_path],
            stderr=subprocess.DEVNULL,
        )
        Path(raw_out).unlink(missing_ok=True)
    else:
        Path(raw_out).replace(out_path)


if __name__ == "__main__":
    main()

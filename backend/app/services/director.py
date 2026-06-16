"""AI auto-director: turn a song into a draft music video.

Builds a shot list from the lyrics (or even segments if instrumental), asks the
director model for one cinematic image prompt per shot (a single cheap LLM
call), then enqueues capped image generations that auto-place onto the timeline
at each shot's time + duration (via genqueue insert_at / insert_duration).
"""
from __future__ import annotations

import json
import math
from typing import Any

import httpx

from .. import config
from . import chat as chat_service
from . import genqueue, imagegen

MAX_SHOTS_CAP = 16


def _build_shots(project: dict, max_shots: int) -> list[dict]:
    duration = float(project.get("duration_sec") or 0.0)
    lyrics = project.get("lyrics_json") or []
    shots: list[dict] = []

    if lyrics:
        lines = sorted(lyrics, key=lambda x: x["start"])
        if len(lines) > max_shots:
            per = math.ceil(len(lines) / max_shots)
            groups = [lines[i:i + per] for i in range(0, len(lines), per)]
        else:
            groups = [[ln] for ln in lines]
        points = []
        if lines[0]["start"] > 3.0:
            points.append({"start": 0.0, "lyric": ""})  # instrumental intro
        for g in groups:
            points.append({"start": g[0]["start"],
                           "lyric": " ".join(x["text"] for x in g)})
        for i, p in enumerate(points):
            end = points[i + 1]["start"] if i + 1 < len(points) else duration
            shots.append({"start": round(p["start"], 2),
                          "duration": round(max(1.0, end - p["start"]), 2),
                          "lyric": p["lyric"]})
    else:
        n = max(1, min(max_shots, int(duration / 6) or 1))
        seg = duration / n if n else duration
        for i in range(n):
            shots.append({"start": round(i * seg, 2),
                          "duration": round(seg, 2), "lyric": ""})

    return shots[:max_shots]


def _mood_brief(project: dict) -> str:
    m = project.get("mood_json") or {}
    parts = []
    for k in ("mood", "genres", "energy", "tempo_bpm", "palette", "keywords"):
        v = m.get(k)
        if v:
            parts.append(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}")
    return " | ".join(parts) or "(no mood analysis)"


_MOTIONS = ["zoom-in", "zoom-out", "pan-left", "pan-right", "pan-up", "pan-down"]


def _plan_shots(project: dict, shots: list[dict]) -> tuple[str, list[dict]]:
    """One LLM call → (concept, [{prompt, motion}]) — a cohesive cinematic plan."""
    shot_lines = "\n".join(
        f"{i}. [{s['start']:.0f}s, {s['duration']:.0f}s] {s['lyric'] or '(instrumental)'}"
        for i, s in enumerate(shots)
    )
    system = (
        "You are the director of a music video. Design a COHESIVE cinematic "
        "sequence from the song's mood and the numbered shot list. Pick a single "
        "visual world (location, palette, lighting, recurring subject/motif) and "
        "keep every shot in it, while VARYING the framing (wide establishing, "
        "medium, intimate close-up, evocative detail, abstract texture) so it "
        "feels edited, not a slideshow. Return STRICT JSON: "
        '{"concept":"<1 sentence: world + palette + motif>","shots":[{"prompt":'
        '"<vivid, concrete 16:9 cinematic image prompt, in the concept, no text/'
        'captions>","motion":"<zoom-in|zoom-out|pan-left|pan-right|pan-up|'
        'pan-down>"}]} — exactly one shots entry per input shot, in order.'
    )
    user = f"SONG MOOD: {_mood_brief(project)}\n\nSHOTS:\n{shot_lines}"
    fallback = (
        (project.get("mood_json") or {}).get("mood", "moody cinematic"),
        [{"prompt": f"Cinematic 16:9 shot, {(project.get('mood_json') or {}).get('mood','moody')}"
                    + (f": {s['lyric']}" if s["lyric"] else ""),
          "motion": _MOTIONS[i % len(_MOTIONS)]}
         for i, s in enumerate(shots)],
    )
    if not config.OPENROUTER_API_KEY:
        return fallback
    try:
        resp = httpx.post(
            f"{config.OPENROUTER_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                     "Content-Type": "application/json",
                     "X-Title": "AI Music Video Studio"},
            json={"model": config.MOOD_MODEL,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  "response_format": {"type": "json_object"}},
            timeout=120,
        )
        resp.raise_for_status()
        content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
        data = json.loads(content[content.index("{"):content.rindex("}") + 1])
        designed = data.get("shots") or []
        out = []
        for i in range(len(shots)):
            d = designed[i] if i < len(designed) and isinstance(designed[i], dict) else {}
            out.append({"prompt": str(d.get("prompt") or fallback[1][i]["prompt"]),
                        "motion": d.get("motion") if d.get("motion") in _MOTIONS
                        else _MOTIONS[i % len(_MOTIONS)]})
        return str(data.get("concept") or fallback[0]), out
    except Exception:
        return fallback


def _snap_to_beat(t: float, bass: list[float]) -> float:
    if not bass:
        return t
    nearest = min(bass, key=lambda b: abs(b - t))
    return round(nearest, 2) if abs(nearest - t) < 0.4 else t


def _refs(pid: str) -> list[bytes]:
    out = []
    for a in chat_service._reference_assets(pid)[:2]:
        try:
            out.append((config.DATA_DIR / a["path"]).read_bytes())
        except OSError:
            pass
    return out


def _beat_effects(project: dict, shots: list[dict]) -> list[dict]:
    """A cohesive look + a bass-driven punch on the densest section."""
    dur = float(project.get("duration_sec") or 0.0)
    bass = (project.get("beats_json") or {}).get("bass") or []
    fx = [{"filter_id": "gfunk-vignette", "name": "Vignette", "at": 0.0,
           "duration": round(dur, 2)}]
    if bass and dur > 10 and shots:
        best = max(shots, key=lambda s: sum(
            1 for b in bass if s["start"] <= b < s["start"] + min(8.0, s["duration"])))
        fx.append({"filter_id": "lola-bass-zoom", "name": "Bass Zoom",
                   "at": best["start"], "duration": min(8.0, best["duration"])})
    return fx


def auto_direct(project: dict, max_shots: int = 10) -> dict[str, Any]:
    """Plan a cohesive draft: moving shots + title + beat-synced effects."""
    max_shots = max(1, min(MAX_SHOTS_CAP, int(max_shots)))
    pid = project["id"]
    shots = _build_shots(project, max_shots)
    bass = (project.get("beats_json") or {}).get("bass") or []
    for s in shots:
        s["start"] = _snap_to_beat(s["start"], bass)

    concept, designed = _plan_shots(project, shots)
    refs = _refs(pid) or None

    plan = []
    for i, shot in enumerate(shots):
        prompt, motion = designed[i]["prompt"], designed[i]["motion"]

        def runner(p=prompt, r=refs):
            png = imagegen.generate_image(p, r)
            return chat_service._save_image_asset(pid, png, p)

        job = genqueue.submit(pid, "image", f"shot {i + 1}/{len(shots)}", runner,
                              insert_at=shot["start"],
                              insert_duration=shot["duration"],
                              insert_meta={"motion": motion})
        plan.append({**shot, "prompt": prompt, "motion": motion, "job_id": job["id"]})

    dur = float(project.get("duration_sec") or 4.0)
    texts = [{"text": (project.get("name") or "Untitled").upper(), "at": 0.0,
              "duration": min(4.0, dur), "position": "center", "anim": "fade"}]
    return {"shots": len(plan), "concept": concept, "plan": plan,
            "texts": texts, "effects": _beat_effects(project, shots)}

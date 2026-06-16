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


def _generate_prompts(project: dict, shots: list[dict]) -> list[str]:
    """One LLM call → a cinematic image prompt per shot (aligned by index)."""
    shot_lines = "\n".join(
        f"{i}. [{s['start']:.0f}s] {s['lyric'] or '(instrumental)'}"
        for i, s in enumerate(shots)
    )
    system = (
        "You are the visual director of a music video. Given the song's mood and "
        "a numbered shot list (each with its lyric or 'instrumental'), write ONE "
        "vivid, concrete, cinematic image prompt per shot — a cohesive visual "
        "story in a consistent style/palette across all shots, 16:9, no text "
        "overlays. Return ONLY a JSON array of strings, exactly one per shot, in "
        "order."
    )
    user = f"SONG MOOD: {_mood_brief(project)}\n\nSHOTS:\n{shot_lines}"
    fallback = [
        f"Cinematic 16:9 shot reflecting '{(project.get('mood_json') or {}).get('mood', 'moody')}'"
        + (f": {s['lyric']}" if s["lyric"] else "")
        for s in shots
    ]
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
            timeout=90,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"].get("content") or ""
        content = content.strip().strip("`")
        if content.startswith("json"):
            content = content[4:]
        data = json.loads(content[content.index("["):content.rindex("]") + 1]) \
            if "[" in content else json.loads(content)
        prompts = data if isinstance(data, list) else list(data.values())[0]
        prompts = [str(p) for p in prompts]
        if len(prompts) < len(shots):
            prompts += fallback[len(prompts):]
        return prompts[:len(shots)]
    except Exception:
        return fallback


def auto_direct(project: dict, max_shots: int = 10) -> dict[str, Any]:
    """Plan shots, generate prompts, and enqueue auto-placed image generations."""
    max_shots = max(1, min(MAX_SHOTS_CAP, int(max_shots)))
    pid = project["id"]
    shots = _build_shots(project, max_shots)
    prompts = _generate_prompts(project, shots)

    plan = []
    for i, shot in enumerate(shots):
        prompt = prompts[i] if i < len(prompts) else "cinematic shot"

        def runner(p=prompt):
            png = imagegen.generate_image(p, None)
            return chat_service._save_image_asset(pid, png, p)

        job = genqueue.submit(pid, "image", f"shot {i + 1}/{len(shots)}", runner,
                              insert_at=shot["start"],
                              insert_duration=shot["duration"])
        plan.append({**shot, "prompt": prompt, "job_id": job["id"]})
    return {"shots": len(plan), "plan": plan}

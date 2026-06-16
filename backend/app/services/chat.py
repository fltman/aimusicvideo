"""Agentic creative-director chat (google/gemini-3.5-flash via OpenRouter).

Given the project's mood analysis, the lyrics around the playhead, and a short
audio clip of that exact section, the model chats with the user and can call the
`generate_image` tool to create a section-appropriate image. Generated images
are saved into the project's media library; the router returns them so the
frontend can drop a clip onto the timeline at the playhead.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import uuid
from typing import Any

import httpx

from .. import config, db
from . import audio, filters, genqueue, imagegen

CHAT_MODEL = config.MOOD_MODEL  # google/gemini-3.5-flash
_TIMEOUT = 90.0
CLIP_LEAD = 2.0       # seconds of audio before the playhead
CLIP_DURATION = 8.0   # total seconds of the section clip
LYRIC_WINDOW = 15.0   # seconds either side of the playhead
MAX_IMAGES_PER_TURN = 3

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate a still image for the current timeline section and add "
                "it to the media library + timeline. Call this when the user wants "
                "a visual / image / shot for this part of the song."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "A single, vivid, concrete, cinematic image prompt "
                            "(16:9) that reflects the section's mood, lyrics and "
                            "sound. No text overlays. When using reference images, "
                            "describe how the referenced character/scene appears."
                        ),
                    },
                    "references": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Names of existing reference images to feed in for "
                            "consistency (characters, scenes), chosen from the "
                            "AVAILABLE REFERENCE IMAGES list. E.g. [\"Kevin\", "
                            "\"bathroom\"]. Omit if none apply."
                        ),
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_text",
            "description": "Add a text/title overlay to the timeline at a time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "at": {"type": "number", "description": "start time in seconds"},
                    "duration": {"type": "number", "description": "seconds (default 3)"},
                    "position": {"type": "string",
                                 "enum": ["top", "center", "bottom"]},
                },
                "required": ["text", "at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_effect",
            "description": "Apply a filter effect over a time range. filter_id MUST "
                           "be one from the AVAILABLE FILTERS list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_id": {"type": "string"},
                    "at": {"type": "number", "description": "start time in seconds"},
                    "duration": {"type": "number", "description": "seconds"},
                },
                "required": ["filter_id", "at", "duration"],
            },
        },
    },
]


def _fmt_clock(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def _lyric_window(lyrics: list[dict] | None, cursor: float) -> str:
    if not lyrics:
        return "(instrumental — no lyrics in this section)"
    near = [
        l for l in lyrics
        if l["end"] >= cursor - LYRIC_WINDOW and l["start"] <= cursor + LYRIC_WINDOW
    ]
    if not near:
        return "(instrumental — no lyrics in this section)"
    lines = []
    for l in near:
        marker = "  <-- playhead" if l["start"] <= cursor < l["end"] else ""
        lines.append(f"[{_fmt_clock(l['start'])}] {l['text']}{marker}")
    return "\n".join(lines)


def _mood_summary(mood: dict | None) -> str:
    if not mood:
        return "(no mood analysis available)"
    parts = []
    if mood.get("mood"):
        parts.append(f"mood: {mood['mood']}")
    if mood.get("genres"):
        parts.append(f"genres: {', '.join(mood['genres'])}")
    if mood.get("energy") is not None:
        parts.append(f"energy: {mood['energy']}")
    if mood.get("tempo_bpm"):
        parts.append(f"tempo: {mood['tempo_bpm']} bpm")
    if mood.get("keywords"):
        parts.append(f"keywords: {', '.join(mood['keywords'])}")
    if mood.get("palette"):
        parts.append(f"palette: {', '.join(mood['palette'])}")
    return " | ".join(parts) if parts else "(no mood analysis available)"


def _reference_assets(pid: str) -> list[dict]:
    """Image assets that have been named/tagged — usable as references."""
    return [
        a for a in db.list_media(pid)
        if a.get("kind") == "image" and (a.get("label") or a.get("tags"))
    ]


def _asset_catalog(assets: list[dict]) -> str:
    if not assets:
        return "(none yet — the user can name & tag images in the media library)"
    lines = []
    for a in assets:
        name = a.get("label") or a.get("original_name")
        tags = a.get("tags") or []
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"- {name}{tag_str}")
    return "\n".join(lines)


def _resolve_references(pid: str, names: list[str]) -> list[bytes]:
    """Resolve reference names → image bytes (match by label, tag, then name)."""
    assets = [a for a in db.list_media(pid) if a.get("kind") == "image"]
    chosen: dict[str, dict] = {}
    for raw in names:
        q = raw.strip().lower()
        if not q:
            continue
        for a in assets:
            label = (a.get("label") or "").lower()
            tags = [t.lower() for t in (a.get("tags") or [])]
            name = (a.get("original_name") or "").lower()
            if q == label or q in tags or (q and q in name):
                chosen[a["id"]] = a
                break
    out: list[bytes] = []
    for a in chosen.values():
        p = config.DATA_DIR / a["path"]
        try:
            out.append(p.read_bytes())
        except OSError:
            pass
    return out


def _system_prompt(project: dict, cursor: float, catalog: str) -> str:
    return (
        "You are the creative director inside a music video editor, helping the "
        "user craft visuals for their song.\n\n"
        f"SONG ANALYSIS: {_mood_summary(project.get('mood_json'))}\n\n"
        f"CURRENT MOMENT: the playhead is at {_fmt_clock(cursor)} "
        f"({cursor:.1f}s) of a {project.get('duration_sec') or '?'}s song.\n\n"
        "LYRICS AROUND THIS MOMENT:\n"
        f"{_lyric_window(project.get('lyrics_json'), cursor)}\n\n"
        "AVAILABLE REFERENCE IMAGES (pass any by name in generate_image.references "
        "to keep characters/scenes consistent):\n"
        f"{catalog}\n\n"
        "A short audio clip of this exact section is attached so you can hear it.\n\n"
        "AVAILABLE FILTERS (use the exact id for apply_effect):\n"
        f"{_filter_catalog()}\n\n"
        "TOOLS: call generate_image for a section image (vivid 16:9 prompt; include "
        "reference names like \"Kevin in the bathroom\" when they exist). Call "
        "add_text to put a title/caption on the timeline. Call apply_effect to add "
        "a beat-synced filter over a time range. Use the current playhead time as "
        "the default 'at'. Otherwise talk normally and help with creative "
        "direction. Keep replies concise."
    )


def _filter_catalog() -> str:
    try:
        items = filters.list_filters()
    except Exception:
        return "(none)"
    lines = [f"- {f['id']}: {f.get('name', f['id'])}"
             for f in items if not f.get("template")]
    return "\n".join(lines[:40]) or "(none)"


def _extract_section_audio(project: dict, cursor: float) -> str | None:
    """Return a base64 mp3 of the section around the playhead, or None."""
    wav_rel = project.get("song_wav_path")
    if not wav_rel:
        return None
    wav = config.DATA_DIR / wav_rel
    if not wav.exists():
        return None
    start = max(0.0, cursor - CLIP_LEAD)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        clip_path = tf.name
    try:
        if not audio.extract_clip(str(wav), start, CLIP_DURATION, clip_path):
            return None
        with open(clip_path, "rb") as fh:
            return base64.b64encode(fh.read()).decode()
    finally:
        try:
            os.unlink(clip_path)
        except OSError:
            pass


def _post(messages: list[dict], tools: list[dict] | None) -> dict:
    payload: dict[str, Any] = {"model": CHAT_MODEL, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    resp = httpx.post(
        f"{config.OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "AI Music Video Studio",
        },
        json=payload,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


def _save_image_asset(pid: str, png: bytes, prompt: str) -> dict:
    media_dir = config.project_dir(pid) / "media"
    thumbs_dir = media_dir / "thumbs"
    media_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    asset_id = uuid.uuid4().hex
    asset_path = media_dir / f"{asset_id}.png"
    with open(asset_path, "wb") as fh:
        fh.write(png)

    info = audio.probe(str(asset_path))
    thumb_abs = thumbs_dir / f"{asset_id}.jpg"
    thumb_rel = None
    if audio.make_thumbnail(str(asset_path), str(thumb_abs), "image"):
        thumb_rel = config.rel_to_data(thumb_abs)

    name = " ".join(prompt.split()[:6]).strip()[:60] or "generated image"
    return db.add_media(
        project_id=pid,
        kind="image",
        original_name=f"{name}.png",
        path=config.rel_to_data(asset_path),
        thumb_path=thumb_rel,
        duration_sec=None,
        width=info.get("width"),
        height=info.get("height"),
    )


def chat(project: dict, messages: list[dict], cursor_time: float) -> dict:
    """Run one chat turn. Returns {reply, image_prompt, assets}."""
    pid = project["id"]
    audio_b64 = _extract_section_audio(project, cursor_time)
    catalog = _asset_catalog(_reference_assets(pid))

    # Build the API message list: system + history, with the audio clip attached
    # to the most recent user message.
    api_messages: list[dict] = [
        {"role": "system", "content": _system_prompt(project, cursor_time, catalog)}
    ]
    last_user_idx = max(
        (i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1
    )
    for i, m in enumerate(messages):
        role = m.get("role")
        text = str(m.get("content", ""))
        if role not in ("user", "assistant"):
            continue
        if i == last_user_idx and audio_b64:
            api_messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "input_audio",
                     "input_audio": {"data": audio_b64, "format": "mp3"}},
                ],
            })
        else:
            api_messages.append({"role": role, "content": text})

    first = _post(api_messages, TOOLS)
    tool_calls = first.get("tool_calls") or []
    queued: list[dict] = []
    actions: list[dict] = []      # timeline edits for the frontend to apply
    image_prompt: str | None = None

    if not tool_calls:
        return {"reply": first.get("content") or "", "image_prompt": None,
                "queued": [], "actions": []}

    # Execute tool calls: images enqueue on the generation queue; add_text /
    # apply_effect become actions the frontend applies. Then ask for a reply.
    api_messages.append({
        "role": "assistant",
        "content": first.get("content"),
        "tool_calls": tool_calls,
    })
    img_count = 0
    for tc in tool_calls:
        fn = tc.get("function", {})
        name = fn.get("name")
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}

        if name == "generate_image" and img_count < MAX_IMAGES_PER_TURN:
            img_count += 1
            prompt = str(args.get("prompt", "")).strip()
            image_prompt = prompt or image_prompt
            ref_names = args.get("references") or []
            ref_images = _resolve_references(pid, ref_names) if ref_names else None
            label = " ".join(prompt.split()[:6]).strip()[:48] or "image"

            def runner(p=prompt, refs=ref_images):
                png = imagegen.generate_image(p, refs)
                return _save_image_asset(pid, png, p)

            job = genqueue.submit(pid, "image", label, runner, insert_at=cursor_time)
            queued.append({"id": job["id"], "kind": "image", "label": label})
            used = f" using {', '.join(ref_names)}" if ref_names else ""
            result = (f"Image queued{used}; it will drop onto the timeline at "
                      f"{_fmt_clock(cursor_time)} when ready.")
        elif name == "add_text":
            text = str(args.get("text", "")).strip()
            at = float(args.get("at", cursor_time) or cursor_time)
            dur = float(args.get("duration") or 3)
            pos = args.get("position") or "bottom"
            actions.append({"type": "add_text", "text": text, "at": at,
                            "duration": dur, "position": pos})
            result = f"Added text “{text[:30]}” at {_fmt_clock(at)}."
        elif name == "apply_effect":
            fid = str(args.get("filter_id", ""))
            at = float(args.get("at", cursor_time) or cursor_time)
            dur = float(args.get("duration") or 4)
            fname = (filters._read_manifest(fid) or {}).get("name", fid)
            actions.append({"type": "apply_effect", "filter_id": fid,
                            "name": fname, "at": at, "duration": dur})
            result = f"Applied {fname} from {_fmt_clock(at)} for {dur:.0f}s."
        else:
            result = "skipped"
        api_messages.append({"role": "tool", "tool_call_id": tc.get("id"),
                             "content": result})

    try:
        closing = _post(api_messages, None)
        reply = closing.get("content") or "Done."
    except Exception:
        reply = "Done."
    return {"reply": reply, "image_prompt": image_prompt, "queued": queued,
            "actions": actions}

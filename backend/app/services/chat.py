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
import re
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
    {
        "type": "function",
        "function": {
            "name": "develop_story",
            "description": (
                "STAGE 1 of directing — write or revise the STORY of the music video "
                "(logline, theme, recurring characters & settings with frozen looks, "
                "motif, arc). Generates NO images. Call this first when the user wants "
                "to direct/storyboard the song, or whenever they ask to change the "
                "story, characters or setting. Put the user's request/changes in "
                "'notes'. Afterwards, present the story and ask what they'd change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "notes": {"type": "string", "description": "What to create or "
                              "change, in the director's words. Omit for a fresh story."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_shots",
            "description": (
                "STAGE 2 of directing — board the SHOT LIST for the current story: "
                "each shot's time, framing, what happens, and whether it reuses a "
                "library image or generates a new one. Still renders NOTHING. Call "
                "this once the user is happy with the story and wants to see the shots/"
                "images. Put any shot tweaks in 'notes'. Afterwards, summarise the "
                "shots and ask for changes before rendering. You choose the count "
                "unless the user asks for a specific number."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "notes": {"type": "string", "description": "Shot adjustments in "
                              "the director's words."},
                    "shots": {"type": "integer", "description": "Optional explicit "
                              "shot count; omit to let the director decide."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_video",
            "description": (
                "STAGE 3 of directing — RENDER the approved shots: generate/reuse the "
                "images and place them on the timeline with the title card and "
                "beat-synced effects. This SPENDS generation budget — only call it "
                "once the user has seen the shot list and explicitly approves "
                "rendering (e.g. 'render it', 'go', 'make it', 'looks good, shoot it')."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "author_effect",
            "description": (
                "Create a BRAND-NEW custom filter effect from a vibe description and "
                "place it at a time. Use when the user wants an effect that isn't well "
                "covered by the AVAILABLE FILTERS list (e.g. 'a cool glitchy effect at "
                "1:07', 'something dreamy and liquid here'). For a plain built-in that "
                "already fits, use apply_effect instead. The new filter is authored in "
                "the background and comes alive once built."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "brief": {"type": "string", "description": "What the effect should "
                              "look/feel like, in the user's words."},
                    "at": {"type": "number", "description": "start time in seconds"},
                    "duration": {"type": "number", "description": "seconds (default 4)"},
                    "band": {"type": "string", "enum": ["bass", "mid", "high"],
                             "description": "which beat band drives it (default bass)"},
                },
                "required": ["brief", "at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revise_image",
            "description": (
                "Render a NEW VERSION of an EXISTING image in the project, found by "
                "description. Use when the user references a specific image and wants a "
                "fresh take, e.g. 'the image with the lady in blue, render a new "
                "version' or 'redo the rooftop shot, make it rainier'. Identify the "
                "image in 'description'; put any requested changes in 'changes'. The new "
                "version keeps the original's identity (used as a reference) and lands "
                "where the original sits on the timeline."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Which existing "
                                    "image to revise (what's in it / its name/tag)."},
                    "changes": {"type": "string", "description": "What to change in the "
                                "new version. Omit for a straight re-roll."},
                },
                "required": ["description"],
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


def _asset_bytes_one(asset: dict) -> bytes | None:
    try:
        return (config.DATA_DIR / asset["path"]).read_bytes()
    except (OSError, KeyError, TypeError):
        return None


def _match_image(pid: str, desc: str) -> dict | None:
    """Find the existing image that best matches a free-text description."""
    from . import narrative  # token utils; narrative does not import chat
    q = narrative._tokens(desc)
    low = desc.lower()
    best, score = None, 0.0
    for a in db.list_media(pid):
        if a.get("kind") != "image":
            continue
        toks = narrative._tokens(" ".join(filter(None, [
            a.get("gen_prompt"), a.get("label"),
            " ".join(a.get("tags") or []), a.get("original_name")])))
        s = narrative._jaccard(q, toks)
        if a.get("label") and a["label"].lower() in low:
            s += 0.5
        for t in (a.get("tags") or []):
            if t and t.lower() in low:
                s += 0.3
        if s > score:
            best, score = a, s
    return best if score >= 0.12 else None


def _timeline_spot(project: dict, asset_id: str) -> tuple[float, float | None] | None:
    """Where an asset currently sits on the timeline (start, duration), if at all."""
    for c in (project.get("timeline_json") or {}).get("clips") or []:
        if c.get("assetId") == asset_id:
            return (float(c.get("start") or 0.0), float(c.get("duration") or 0.0) or None)
    return None


def _effect_name(brief: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z]+", brief) if len(w) > 2][:2]
    return (" ".join(w.capitalize() for w in words) or "Custom") + " FX"


def _author_brief(project: dict, brief: str, band: str) -> str:
    m = project.get("mood_json") or {}
    pal = ", ".join((m.get("palette") or [])[:4])
    return (
        f"Create this music-video effect: {brief}. It transforms each incoming video "
        f"frame and is beat-synced — react to ctx.{band} (0..1 envelope) and ctx.rms. "
        f"Mood: {m.get('mood','')}. Use the palette {pal}. Expose intensity (slider), "
        f"band (select bass/mid/high, default {band}) and enabled (switch) PARAMS. Pure "
        "per-frame transform, no I/O. Keep it fast (runs per frame)."
    )


def _direction_state(project: dict) -> str:
    """Tell the model where the in-progress direction stands (story / shots)."""
    story = project.get("story_json")
    script = project.get("script_json")
    if not story and not script:
        return "No story yet — start with develop_story when the user wants to direct."
    parts = []
    if story:
        cast = ", ".join(c.get("name", "") for c in story.get("characters", []))
        parts.append(f"STORY exists — logline: {story.get('logline')}; cast: {cast}")
    if script:
        parts.append(f"SHOT LIST exists — {len(script.get('shots', []))} shots proposed "
                     "(not rendered until the user approves render_video)")
    return " | ".join(parts)


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
        f"DIRECTION SO FAR: {_direction_state(project)}\n\n"
        "TOOLS:\n"
        "• generate_image — a new still for the current moment (vivid 16:9 prompt; "
        "include reference names like \"Kevin in the bathroom\" when they exist).\n"
        "• revise_image — render a NEW VERSION of an existing image the user points to "
        "by description (e.g. \"the lady in blue\"); pass any changes.\n"
        "• add_text — a title/caption at a time.\n"
        "• apply_effect — add an existing beat-synced filter over a time range.\n"
        "• author_effect — create a BRAND-NEW custom filter from a vibe (e.g. \"a cool "
        "glitchy effect at 1:07\") when no built-in fits.\n"
        "• develop_story → propose_shots → render_video — directing a full video is "
        "ITERATIVE and done IN THAT ORDER, keeping the user in control:\n"
        "   1) develop_story — write/revise the story, then present it and ask for "
        "changes. Generates nothing.\n"
        "   2) propose_shots — only once the user likes the story; board the shots, "
        "present them, ask for changes. Renders nothing.\n"
        "   3) render_video — only once the user approves the shots; this spends "
        "budget. NEVER skip ahead to rendering.\n"
        "Times: accept 'm:ss' or seconds; default 'at' to the current playhead. Keep "
        "replies concise and conversational — you are collaborating, not narrating a "
        "spec.\n\n"
        "FORMAT replies in compact GitHub markdown: **bold** for character/shot "
        "names, bullet or numbered lists for shots/options, short paragraphs. When "
        "presenting a shot list, use a numbered list with the time and a short beat "
        "per item. Don't wrap the whole reply in a code block."
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


def _save_image_asset(pid: str, png: bytes, prompt: str,
                      label: str | None = None, tags: list[str] | None = None,
                      bible_entity: str | None = None) -> dict:
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

    name = label or " ".join(prompt.split()[:6]).strip()[:60] or "generated image"
    return db.add_media(
        project_id=pid,
        kind="image",
        original_name=f"{name}.png",
        path=config.rel_to_data(asset_path),
        thumb_path=thumb_rel,
        duration_sec=None,
        width=info.get("width"),
        height=info.get("height"),
        label=label,
        tags=tags,
        gen_prompt=prompt,
        bible_entity=bible_entity,
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
    direct: dict | None = None    # full auto-direct result for the frontend to apply

    if not tool_calls:
        return {"reply": first.get("content") or "", "image_prompt": None,
                "queued": [], "actions": [], "direct": None}

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
        elif name == "author_effect":
            from . import director  # lazy: director imports chat (avoid cycle)
            brief_in = str(args.get("brief", "")).strip() or "a beat-reactive effect"
            at = float(args.get("at", cursor_time) or cursor_time)
            dur = float(args.get("duration") or 4)
            band = args.get("band") if args.get("band") in ("bass", "mid", "high") else "bass"
            try:
                detail = filters.create_blank(_effect_name(brief_in))
                fid = detail["manifest"]["id"]
                fname = detail["manifest"]["name"]
                director._enqueue_filter_authoring(
                    pid, fid, _author_brief(project, brief_in, band), fname)
                actions.append({"type": "apply_effect", "filter_id": fid, "name": fname,
                                "at": at, "duration": dur,
                                "params": {"intensity": 1.0, "band": band, "enabled": True}})
                result = (f"Authoring a custom “{fname}” effect (claude-opus) and placing "
                          f"it at {_fmt_clock(at)} for {dur:.0f}s — it comes alive once built "
                          "(watch the queue).")
            except Exception as e:  # noqa: BLE001
                result = f"Couldn't start the custom effect: {e}"
        elif name == "revise_image" and img_count < MAX_IMAGES_PER_TURN:
            img_count += 1
            desc = str(args.get("description", "")).strip()
            changes = str(args.get("changes", "")).strip()
            asset = _match_image(pid, desc)
            if not asset:
                result = (f"I couldn't find an image matching “{desc[:40]}”. "
                          "Try naming/tagging it, or describe it differently.")
            else:
                base = (asset.get("gen_prompt") or asset.get("label")
                        or asset.get("original_name") or desc)
                new_prompt = base + (f". {changes}" if changes else "")
                ref = _asset_bytes_one(asset)
                spot = _timeline_spot(project, asset["id"])
                insert_at = spot[0] if spot else cursor_time
                insert_dur = spot[1] if spot else None
                lbl = asset.get("label") or " ".join(base.split()[:5]).strip()[:40] or "image"

                def runner(p=new_prompt, r=([ref] if ref else None), a=asset):
                    png = imagegen.generate_image(p, r)
                    return _save_image_asset(pid, png, p, label=a.get("label"),
                                             tags=a.get("tags"),
                                             bible_entity=a.get("bible_entity"))

                job = genqueue.submit(pid, "image", f"revise · {lbl[:22]}", runner,
                                      insert_at=insert_at, insert_duration=insert_dur,
                                      insert_meta={"motion": "zoom-in"})
                queued.append({"id": job["id"], "kind": "image", "label": lbl[:40]})
                result = (f"Re-rendering “{lbl[:30]}”"
                          + (f" with: {changes}" if changes else "")
                          + f"; the new version will land at {_fmt_clock(insert_at)}.")
        elif name == "develop_story":
            from . import director
            out = director.develop_story(project, notes=args.get("notes"))
            story = out["story"]
            chars = "; ".join(f"{c['name']} ({c.get('role','')}) — {c['visual_anchor']}"
                              for c in story.get("characters", []))
            setts = "; ".join(f"{s['name']} — {s['visual_anchor']}"
                              for s in story.get("settings", []))
            result = (f"STORY drafted (nothing generated yet). Logline: {story.get('logline')}. "
                      f"Theme: {story.get('theme')}. Motif: {story.get('motif')}. "
                      f"Characters: {chars}. Settings: {setts}. "
                      "Present this to the user conversationally and ask what they'd change "
                      "before boarding shots.")
        elif name == "propose_shots":
            from . import director
            try:
                shots_n = int(args["shots"]) if args.get("shots") is not None else None
            except (TypeError, ValueError):
                shots_n = None
            out = director.propose_shots(project, max_shots=shots_n, notes=args.get("notes"))
            script, b = out["script"], out["broker"]
            lst = "; ".join(
                f"#{s['idx']+1} [{_fmt_clock(s['start'])}] {s.get('shot_size','')} — "
                f"{(s.get('intent') or s.get('prompt_core',''))[:48]}"
                for s in script["shots"])
            result = (f"SHOT LIST proposed (still nothing rendered): {len(script['shots'])} "
                      f"shots — {b['generate_count']} to generate, {b['reuse_count']} reused. "
                      f"{lst}. Summarise these for the user and ask for changes; render only "
                      "when they approve.")
        elif name == "render_video":
            from . import director
            direct = director.render(project)
            for c in direct.get("cast", []):
                queued.append({"id": c["job_id"], "kind": "image",
                               "label": f"cast · {c['name']}"})
            for s in direct.get("plan", []):
                queued.append({"id": s["job_id"], "kind": "image",
                               "label": f"shot {s['idx'] + 1}"})
            cast_names = ", ".join(c["name"] for c in direct.get("cast", [])
                                   if c["kind"] == "character")
            loc_names = ", ".join(c["name"] for c in direct.get("cast", [])
                                  if c["kind"] == "scene")
            bits = []
            if direct.get("cast"):
                bits.append(f"casting {len(direct['cast'])} reference image(s) first")
            bits.append(f"then rendering {direct['generate_count']} shot(s)")
            if direct.get("reuse_count"):
                bits.append(f"reusing {direct['reuse_count']}")
            if direct.get("new_filters"):
                bits.append(f"authoring {len(direct['new_filters'])} custom filter")
            result = (
                f"Rendering — {', '.join(bits)}. "
                + (f"**Cast:** {cast_names}. " if cast_names else "")
                + (f"**Locations:** {loc_names}. " if loc_names else "")
                + "The reference portraits/plates generate FIRST so every shot can "
                "reference them and the characters & scenes stay consistent. Title and "
                "effects are placed now; shots land on the timeline as they finish.")
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
            "actions": actions, "direct": direct}

"""AI auto-director: turn a song into a STORY-DRIVEN draft music video.

This orchestrates the narrative pipeline (see ``narrative.py``): read the song as
a story, board it into beat-timed shots with recurring characters/settings, reuse
existing library assets where they fit, generate only the new images the story
needs (each consistent with its character's canon reference), and lay beat-synced
effects — authoring a bespoke filter for a graphic interlude when nothing fits.

Continuity without blocking the request: generation runs in two waves on the
shared queue. Wave-0 "establishing" shots define each entity's canon image and
record it in ``bible_links_json``; wave-1 shots reference that canon. Dependent
runners wait for their entity's canon to land (with a timeout) inside the worker
thread, so ``auto_direct`` returns as soon as the plan is built.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from .. import config, db
from . import chat as chat_service
from . import genqueue, imagegen, narrative

# The director chooses the shot count from the song; this is only a hard ceiling
# so an auto-decided count can never run the generation cost away.
MAX_SHOTS_CAP = 36
_POLL = 1.5            # seconds between canon-availability polls
_ANCHOR_TIMEOUT = 150  # max seconds a dependent shot waits for its anchor
_BIBLE_LOCK = threading.Lock()


# ── bible / reference helpers ─────────────────────────────────────────────────

def _asset_bytes(asset: Optional[dict]) -> Optional[bytes]:
    if not asset:
        return None
    try:
        return (config.DATA_DIR / asset["path"]).read_bytes()
    except (OSError, KeyError, TypeError):
        return None


def _write_bible(pid: str, entity: str, asset_id: str) -> None:
    """Record an entity's canon image id (read-modify-write under a lock)."""
    with _BIBLE_LOCK:
        proj = db.get_project(pid) or {}
        links = dict(proj.get("bible_links_json") or {})
        links[entity] = asset_id
        db.update_project_fields(pid, bible_links_json=links)


def _seed_ref(pid: str, entity: str) -> Optional[bytes]:
    """A pre-existing canon for an entity (prior run / hand-tagged), or None."""
    links = (db.get_project(pid) or {}).get("bible_links_json") or {}
    aid = links.get(entity)
    if aid and aid != "__pending__":
        return _asset_bytes(db.get_media(aid))
    for a in db.list_media(pid):
        if a.get("kind") == "image" and a.get("bible_entity") == entity:
            return _asset_bytes(a)
    return None


def _wait_for_canon(pid: str, entities: list[str], timeout: float) -> list[bytes]:
    """Block until each entity has a canon image, returning up to 2 ref blobs."""
    deadline = time.time() + timeout
    out: list[bytes] = []
    for ent in entities[:2]:
        aid = None
        while time.time() < deadline:
            links = (db.get_project(pid) or {}).get("bible_links_json") or {}
            aid = links.get(ent)
            if aid and aid != "__pending__":
                break
            time.sleep(_POLL)
        b = _asset_bytes(db.get_media(aid)) if aid and aid != "__pending__" else None
        if b:
            out.append(b)
    return out


def _entity_meta(story: dict, entity: Optional[str]) -> tuple[Optional[str], Optional[list[str]]]:
    if not entity:
        return None, None
    for c in story.get("characters") or []:
        if c["id"] == entity:
            return c.get("name"), [entity, "character"]
    for s in story.get("settings") or []:
        if s["id"] == entity:
            return s.get("name"), [entity, "scene"]
    return None, [entity]


def _make_runner(pid: str, plan_shot: dict, story: dict) -> Callable[[], dict]:
    """Build the genqueue runner closure for one shot (reuse or generate)."""
    if plan_shot["decision"] == "reuse":
        aid = plan_shot["reuse_asset_id"]
        return lambda: db.get_media(aid)

    prompt = plan_shot["prompt"]
    depends = plan_shot.get("depends_on") or []     # entities to reference (cast/locations)
    entity = depends[0] if depends else None
    _, tags = _entity_meta(story, entity)           # tag the shot with its character/scene

    def runner() -> dict:
        # wait for the cast/location reference images, then generate referencing them
        refs = _wait_for_canon(pid, depends, _ANCHOR_TIMEOUT)
        png = imagegen.generate_image(prompt, refs or None)
        return chat_service._save_image_asset(
            pid, png, prompt, label=None, tags=tags, bible_entity=entity)

    return runner


# ── main entry ────────────────────────────────────────────────────────────────

def auto_direct(project: dict, max_shots: Optional[int] = None) -> dict[str, Any]:
    """Plan and enqueue a story-driven draft. Returns immediately with the plan.

    The shot count is decided by the song's structure (section count + energy-driven
    pacing). ``max_shots`` is an optional explicit override; when omitted the director
    chooses, bounded only by ``MAX_SHOTS_CAP`` so cost can't run away.

    This is the all-in-one path (story → shots → render). The chat drives the same
    stages one at a time via ``develop_story`` / ``propose_shots`` / ``render``.
    """
    develop_story(project)
    propose_shots(project, max_shots=max_shots)
    return render(db.get_project(project["id"]) or project)


# ── staged, conversational entry points (used by the director chat) ───────────

def develop_story(project: dict, notes: Optional[str] = None) -> dict:
    """Stage 1: write or revise the STORY. No images. Persists story_json."""
    project = db.get_project(project["id"]) or project
    pid = project["id"]
    rhythm = project.get("rhythm_json") or narrative.analyze_rhythm(project)
    story = narrative.analyze_story(project, rhythm, prior=project.get("story_json"),
                                    notes=notes)
    db.update_project_fields(pid, rhythm_json=rhythm, story_json=story)
    return {"rhythm": rhythm, "story": story}


def propose_shots(project: dict, max_shots: Optional[int] = None,
                  notes: Optional[str] = None) -> dict:
    """Stage 2: board the SHOT LIST (reuse/generate decided). No render. Persists script_json."""
    project = db.get_project(project["id"]) or project
    pid = project["id"]
    rhythm = project.get("rhythm_json") or narrative.analyze_rhythm(project)
    story = project.get("story_json")
    if not story:
        story = narrative.analyze_story(project, rhythm)
    script = narrative.segment_shots(project, rhythm, story, max_shots,
                                     prior=project.get("script_json"), notes=notes)
    db.update_project_fields(pid, rhythm_json=rhythm, story_json=story, script_json=script)
    inventory = narrative.build_inventory(pid)
    bplan = narrative.broker(project, story, script, inventory,
                             project.get("bible_links_json") or {})
    return {"story": story, "script": script, "broker": bplan}


def render(project: dict) -> dict[str, Any]:
    """Stage 3: generate/reuse images, lay title + effects, place on the timeline."""
    project = db.get_project(project["id"]) or project
    pid = project["id"]
    rhythm = project.get("rhythm_json") or narrative.analyze_rhythm(project)
    story = project.get("story_json") or narrative.analyze_story(project, rhythm)
    script = project.get("script_json") or narrative.segment_shots(project, rhythm, story)
    db.update_project_fields(pid, rhythm_json=rhythm, story_json=story, script_json=script)

    inventory = narrative.build_inventory(pid)
    bplan = narrative.broker(project, story, script, inventory,
                             project.get("bible_links_json") or {})
    fx = narrative.plan_effects(project, rhythm, script, story)

    # ── enqueue authoring of any bespoke interlude filter (async) ──
    for nf in fx.get("new_filters", []):
        _enqueue_filter_authoring(pid, nf["fid"], nf["brief"], nf["name"])

    # ── WAVE 0 — CAST: a clean reference image per character + location used by a
    # shot, generated FIRST so every shot can reference it for consistency. These
    # land in the media library (tagged), not on the timeline. Skip any already
    # cast on a previous run (bible_links). ──
    bible = project.get("bible_links_json") or {}
    cast: list[dict] = []
    for ent_id in bplan.get("cast_entities", []):
        if bible.get(ent_id):
            continue
        ent, kind = narrative.find_entity(story, ent_id)
        if not ent:
            continue
        prompt = narrative.reference_prompt(ent, kind, project)
        job = genqueue.submit(pid, "image", f"cast · {ent.get('name', kind)}",
                              _cast_runner(pid, ent_id, prompt, story))
        cast.append({"entity": ent_id, "name": ent.get("name"), "kind": kind,
                     "job_id": job["id"]})

    # ── WAVE 1 — SHOTS: reuse a library plate or generate referencing the cast.
    # Build the shot jobs but DON'T enqueue them yet — the cast reference images
    # must finish first so every shot has a real reference and the workers aren't
    # tied up waiting. A background orchestrator submits them once the cast is done. ──
    specs: list[dict] = []
    plan: list[dict] = []
    for ps in bplan["shots"]:
        if ps["decision"] not in ("generate", "reuse"):
            continue  # interlude_effect → handled as an effect clip, not an image
        idx = ps["idx"]
        primary = (ps.get("depends_on") or [None])[0]
        meta = {"motion": ps["motion"], "beat": ps.get("beat"),
                "bible_entity": primary, "intent": ps.get("intent")}
        label = f"shot {idx + 1}" + (" (reuse)" if ps["decision"] == "reuse" else "")
        specs.append({"label": label, "runner": _make_runner(pid, ps, story),
                      "insert_at": ps["start"], "insert_duration": ps["duration"],
                      "insert_meta": meta})
        plan.append({
            "idx": idx, "start": ps["start"], "duration": ps["duration"],
            "lyric": ps.get("lyric", ""), "prompt": ps["prompt"],
            "motion": ps["motion"],
            "decision": ps["decision"], "reuse_asset_id": ps.get("reuse_asset_id"),
            "bible_entity": primary, "beat": ps.get("beat"),
            "intent": ps.get("intent"), "shot_size": ps.get("shot_size"),
        })
    plan.sort(key=lambda p: p["start"])

    cast_ids = [c["job_id"] for c in cast]
    if cast_ids:
        # cast first → then shots (in a daemon thread so the request returns now)
        threading.Thread(target=_shots_after_cast, args=(pid, cast_ids, specs),
                         daemon=True).start()
    else:
        _enqueue_shot_specs(pid, specs)        # nothing to cast → shoot straight away

    dur = float(project.get("duration_sec") or 4.0)
    title = (story.get("logline") and _title_from(project, story)) or \
        (project.get("name") or "Untitled").upper()
    texts = [{"text": title, "at": 0.0, "duration": min(4.0, dur),
              "position": "center", "anim": "fade"}]

    return {
        "shots": len(plan), "concept": script.get("concept") or story.get("logline", ""),
        "plan": plan, "texts": texts, "cast": cast, "shots_pending": bool(cast_ids),
        "effects": fx["effects"], "interlude_clips": fx["interlude_clips"],
        "new_filters": fx["new_filters"],
        "generate_count": bplan["generate_count"], "reuse_count": bplan["reuse_count"],
        "narrative": {"logline": story.get("logline"), "theme": story.get("theme"),
                      "characters": story.get("characters", []),
                      "settings": story.get("settings", []),
                      "sections": rhythm["sections"]},
    }


def _enqueue_shot_specs(pid: str, specs: list[dict]) -> None:
    for s in specs:
        genqueue.submit(pid, "image", s["label"], s["runner"],
                        insert_at=s["insert_at"], insert_duration=s["insert_duration"],
                        insert_meta=s["insert_meta"])


def _shots_after_cast(pid: str, cast_ids: list[str], specs: list[dict],
                      timeout: float = 300.0) -> None:
    """Wait for the cast reference jobs to finish, then enqueue the shot jobs."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all((genqueue.get_job(j) or {}).get("status") in ("done", "error")
               for j in cast_ids):
            break
        time.sleep(_POLL)
    _enqueue_shot_specs(pid, specs)


def moodboard(project: dict, n: int = 4) -> dict:
    """Generate a small moodboard (overall feeling/palette/atmosphere) for review.

    Uses the analysis's visual_suggestions (already on-mood) plus the story's tone/
    motif. Images go to the media library tagged 'moodboard' — not the timeline.
    """
    project = db.get_project(project["id"]) or project
    pid = project["id"]
    n = max(2, min(6, int(n)))
    m = project.get("mood_json") or {}
    story = project.get("story_json") or {}
    style = narrative._style_suffix(project)
    tone = story.get("tone") or m.get("mood") or "evocative"
    motif = story.get("motif") or (m.get("keywords") or ["light"])[0]

    prompts = [f"{s}. {style}" for s in (m.get("visual_suggestions") or [])[:n]]
    while len(prompts) < n:
        prompts.append(f"Mood frame — {tone} atmosphere, {motif}, no people, no text. {style}")

    board = []
    for i, p in enumerate(prompts[:n]):
        job = genqueue.submit(pid, "image", f"moodboard {i + 1}", _moodboard_runner(pid, p))
        board.append({"prompt": p, "job_id": job["id"]})
    return {"board": board, "count": len(board)}


def _moodboard_runner(pid: str, prompt: str) -> Callable[[], dict]:
    def runner() -> dict:
        png = imagegen.generate_image(prompt, None)
        return chat_service._save_image_asset(pid, png, prompt, tags=["moodboard"])
    return runner


def _cast_runner(pid: str, entity_id: str, prompt: str, story: dict) -> Callable[[], dict]:
    """Generate an entity's canonical reference image and record it as canon."""
    label, tags = _entity_meta(story, entity_id)

    def runner() -> dict:
        seed = _seed_ref(pid, entity_id)         # keep identity across runs if any
        png = imagegen.generate_image(prompt, [seed] if seed else None)
        asset = chat_service._save_image_asset(
            pid, png, prompt, label=label, tags=tags, bible_entity=entity_id)
        _write_bible(pid, entity_id, asset["id"])
        return asset

    return runner


def _title_from(project: dict, story: dict) -> str:
    """A short title card: the song name (or the protagonist's name)."""
    name = (project.get("name") or "").strip()
    if name and name.lower() not in ("untitled", "new project"):
        return name.upper()
    chars = story.get("characters") or []
    if chars and chars[0].get("name"):
        return chars[0]["name"].upper()
    return (name or "Untitled").upper()


def _enqueue_filter_authoring(pid: str, fid: str, brief: str, name: str) -> None:
    """Background job: vibe-code the freshly-created blank filter via opus."""
    def runner() -> dict:
        from . import filterchat  # lazy: avoid import cost at module load
        res = filterchat.chat(fid, brief)
        return {"kind": "filter_authored", "fid": fid,
                "version": res.get("version"), "error": res.get("error")}

    genqueue.submit(pid, "filter", f"author · {name}", runner)

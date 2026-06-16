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
    anchor_for = plan_shot.get("anchor_for_entity")
    depends = plan_shot.get("depends_on") or []
    entity = anchor_for or (depends[0] if depends else None)
    label, tags = _entity_meta(story, entity)

    def runner() -> dict:
        if anchor_for:
            seed = _seed_ref(pid, anchor_for)        # keep identity across runs
            refs = [seed] if seed else []
        else:
            refs = _wait_for_canon(pid, depends, _ANCHOR_TIMEOUT)
        png = imagegen.generate_image(prompt, refs or None)
        asset = chat_service._save_image_asset(
            pid, png, prompt, label=label, tags=tags, bible_entity=entity)
        if anchor_for:
            _write_bible(pid, anchor_for, asset["id"])
        return asset

    return runner


# ── main entry ────────────────────────────────────────────────────────────────

def auto_direct(project: dict, max_shots: Optional[int] = None) -> dict[str, Any]:
    """Plan and enqueue a story-driven draft. Returns immediately with the plan.

    The shot count is decided by the song's structure (section count + energy-driven
    pacing). ``max_shots`` is an optional explicit override; when omitted the director
    chooses, bounded only by ``MAX_SHOTS_CAP`` so cost can't run away.
    """
    pid = project["id"]

    # ── plan (synchronous, ~2-4 fast LLM calls; every stage has a fallback) ──
    # max_shots=None → segment_shots decides the count from the song structure.
    rhythm = narrative.analyze_rhythm(project)
    db.update_project_fields(pid, rhythm_json=rhythm)
    story = narrative.analyze_story(project, rhythm)
    db.update_project_fields(pid, story_json=story)
    script = narrative.segment_shots(project, rhythm, story, max_shots)
    db.update_project_fields(pid, script_json=script)

    inventory = narrative.build_inventory(pid)
    bible = project.get("bible_links_json") or {}
    bplan = narrative.broker(project, story, script, inventory, bible)
    fx = narrative.plan_effects(project, rhythm, script, story)

    # ── enqueue authoring of any bespoke interlude filter (async) ──
    for nf in fx.get("new_filters", []):
        _enqueue_filter_authoring(pid, nf["fid"], nf["brief"], nf["name"])

    # ── enqueue generation in waves (wave 0 first → establishes canon) ──
    shots_by_idx = {s["idx"]: s for s in bplan["shots"]}
    plan: list[dict] = []
    for wave in bplan["generation_waves"]:
        for idx in wave["shot_idxs"]:
            ps = shots_by_idx[idx]
            meta = {"motion": ps["motion"], "beat": ps.get("beat"),
                    "bible_entity": ps.get("anchor_for_entity") or
                    (ps.get("depends_on") or [None])[0],
                    "intent": ps.get("intent")}
            label = f"shot {idx + 1}" + (" (reuse)" if ps["decision"] == "reuse" else "")
            job = genqueue.submit(
                pid, "image", label, _make_runner(pid, ps, story),
                insert_at=ps["start"], insert_duration=ps["duration"], insert_meta=meta)
            plan.append({
                "idx": idx, "start": ps["start"], "duration": ps["duration"],
                "lyric": ps.get("lyric", ""), "prompt": ps["prompt"],
                "motion": ps["motion"], "job_id": job["id"],
                "decision": ps["decision"], "reuse_asset_id": ps.get("reuse_asset_id"),
                "bible_entity": meta["bible_entity"], "beat": ps.get("beat"),
                "intent": ps.get("intent"), "shot_size": ps.get("shot_size"),
            })
    plan.sort(key=lambda p: p["start"])

    dur = float(project.get("duration_sec") or 4.0)
    title = (story.get("logline") and _title_from(project, story)) or \
        (project.get("name") or "Untitled").upper()
    texts = [{"text": title, "at": 0.0, "duration": min(4.0, dur),
              "position": "center", "anim": "fade"}]

    return {
        "shots": len(plan), "concept": script.get("concept") or story.get("logline", ""),
        "plan": plan, "texts": texts,
        "effects": fx["effects"], "interlude_clips": fx["interlude_clips"],
        "new_filters": fx["new_filters"],
        "generate_count": bplan["generate_count"], "reuse_count": bplan["reuse_count"],
        "narrative": {"logline": story.get("logline"), "theme": story.get("theme"),
                      "characters": story.get("characters", []),
                      "settings": story.get("settings", []),
                      "sections": rhythm["sections"]},
    }


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

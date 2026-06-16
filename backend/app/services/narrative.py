"""Narrative auto-director — turn a song into a STORY, then stage it.

This is the "writers' room" behind ``director.auto_direct``. Instead of one shot
per lyric line, it runs a small pipeline so the draft actually follows a story:

  0  analyze_rhythm   deterministic   -> rhythm   (sections, intensity, drops, bars)
  1  analyze_story    LLM (flash)     -> story    (logline, characters, settings, motifs, arc)
  2  segment_shots    det.+LLM        -> script   (per-shot meaning over beat-timed slots)
  3  build_inventory  deterministic   -> inventory of the existing media library
     broker           deterministic   -> plan     (reuse vs generate, refs, waves, prompts)
  4  plan_effects     det.+async opus -> effects   (per-section filters, interludes, new filters)

Design rules:
  * Rhythm/pacing/cuts are MATH (the beats are spectral-flux onsets, not downbeats —
    an LLM must not do the arithmetic). The LLM does narrative reasoning only.
  * Continuity is carried by a story "bible": every character/setting has a frozen
    ``visual_anchor`` description, and the first generated shot of an entity becomes
    its canon reference image for every later shot (see director._wave runners).
  * Every LLM stage degrades to a deterministic fallback so auto_direct never fails.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

import httpx
import numpy as np

from .. import config, db
from . import filters

# ── shared helpers ────────────────────────────────────────────────────────────

_STOP = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "with", "for",
    "as", "by", "from", "into", "over", "under", "is", "are", "be", "this",
    "that", "it", "its", "shot", "cinematic", "16", "9", "no", "text",
}


def _tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) > 2 and w not in _STOP
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _clock(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def _mood_brief(project: dict) -> str:
    m = project.get("mood_json") or {}
    parts = []
    for k in ("mood", "genres", "energy", "tempo_bpm", "palette", "keywords"):
        v = m.get(k)
        if v:
            parts.append(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}")
    return " | ".join(parts) or "(no mood analysis)"


def _style_suffix(project: dict) -> str:
    m = project.get("mood_json") or {}
    pal = ", ".join((m.get("palette") or [])[:4])
    kw = ", ".join((m.get("keywords") or [])[:4])
    bits = ["cinematic still", "16:9", "filmic lighting", "shallow depth of field"]
    if kw:
        bits.append(kw)
    if pal:
        bits.append(f"palette {pal}")
    bits.append("no text, no captions, no watermark")
    return ", ".join(bits)


def _llm_json(system: str, user: str, timeout: float = 90.0) -> Optional[dict]:
    """One JSON-mode flash call. Returns a parsed dict or None on any failure."""
    if not config.OPENROUTER_API_KEY:
        return None
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
            timeout=timeout,
        )
        resp.raise_for_status()
        content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
        return json.loads(content[content.index("{"):content.rindex("}") + 1])
    except Exception:
        return None


_MOTIONS = ["zoom-in", "zoom-out", "pan-left", "pan-right", "pan-up", "pan-down"]
_SIZES = ["wide", "medium", "close", "detail", "abstract"]


# ── Stage 0: RHYTHM (deterministic) ───────────────────────────────────────────

def analyze_rhythm(project: dict) -> dict:
    """Build the musical skeleton: intensity envelope, sections, drops, bar grid."""
    dur = float(project.get("duration_sec") or 0.0)
    beats = project.get("beats_json") or {}
    bass = sorted(beats.get("bass") or [])
    mid = sorted(beats.get("mid") or [])
    high = sorted(beats.get("high") or [])
    onsets = sorted(bass + mid + high)
    lyrics = sorted(project.get("lyrics_json") or [], key=lambda x: x["start"])
    bpm = float((project.get("mood_json") or {}).get("tempo_bpm") or 0.0)

    HZ = 4
    n = max(1, int(round(dur * HZ)))
    times = np.arange(n) / HZ

    # loudness envelope from waveform peaks ([min,max] pairs @ pps Hz)
    wf = project.get("waveform_json") or {}
    peaks = wf.get("peaks") or []
    pps = int(wf.get("pps") or 100)
    if peaks:
        amp = np.abs(np.asarray(peaks, dtype=np.float64)).max(axis=1)  # per-sample amplitude
        win = max(1, pps // HZ)
        loud = np.array([
            float(np.sqrt(np.mean(np.square(amp[i * win:(i + 1) * win]))))
            if amp[i * win:(i + 1) * win].size else 0.0
            for i in range(n)
        ])
        ref = np.percentile(loud, 95) or 1.0
        loud = np.clip(loud / ref, 0.0, 1.0)
    else:
        loud = np.full(n, 0.5)

    # onset-rate envelope (events within ±0.5s of each frame)
    if onsets:
        oarr = np.asarray(onsets)
        rate = np.array([
            float(np.count_nonzero((oarr >= t - 0.5) & (oarr < t + 0.5))) for t in times
        ])
        rref = np.percentile(rate, 95) or 1.0
        rate = np.clip(rate / rref, 0.0, 1.0)
    else:
        rate = np.zeros(n)

    inten = 0.6 * loud + 0.4 * rate
    inten = _smooth(inten, 3)
    lo, hi = float(inten.min()), float(inten.max())
    norm = (inten - lo) / (hi - lo) if hi > lo else np.full(n, 0.5)

    # words-per-second envelope
    dens = np.zeros(n)
    for ln in lyrics:
        span = max(0.5, float(ln["end"]) - float(ln["start"]))
        wps = len(str(ln.get("text", "")).split()) / span
        i0, i1 = int(ln["start"] * HZ), int(math.ceil(float(ln["end"]) * HZ))
        dens[max(0, i0):min(n, i1)] = wps

    sections = _segment(norm, dens, lyrics, dur, bass, mid, high, HZ)

    # drops: the most prominent intensity peaks, snapped to a bass kick. Keep only
    # a handful (spaced ≥6s) so beat-effects punctuate rather than spam.
    cand: list[tuple[float, float]] = []
    for i in range(1, n - 1):
        if norm[i] > 0.8 and norm[i] >= norm[i - 1] and norm[i] >= norm[i + 1]:
            cand.append((float(norm[i]), _snap(float(times[i]), bass, 0.25)))
    drops: list[float] = []
    for _, t in sorted(cand, key=lambda x: x[0], reverse=True):
        if all(abs(t - d) > 6.0 for d in drops):
            drops.append(round(t, 2))
        if len(drops) >= 6:
            break
    drops.sort()

    bar_len = (4.0 * 60.0 / bpm) if bpm > 0 else 0.0
    bar_starts = ([round(k * bar_len, 3) for k in range(int(dur / bar_len) + 1)]
                  if bar_len > 0 else [])

    return {
        "bpm": round(bpm, 1),
        "bar_len": round(bar_len, 3),
        "bar_starts": bar_starts,
        "duration": round(dur, 2),
        "intensity": [{"t": round(float(times[i]), 2), "e": round(float(norm[i]), 3)}
                      for i in range(0, n, 2)],  # 2 Hz, light enough to persist
        "sections": sections,
        "drops": drops,
    }


def _smooth(a: np.ndarray, w: int) -> np.ndarray:
    if w < 2 or a.size < w:
        return a
    k = np.ones(w) / w
    return np.convolve(a, k, mode="same")


def _snap(t: float, grid: list[float], window: float) -> float:
    if not grid:
        return t
    nearest = min(grid, key=lambda g: abs(g - t))
    return round(nearest, 3) if abs(nearest - t) <= window else round(t, 3)


def _segment(norm: np.ndarray, dens: np.ndarray, lyrics: list[dict], dur: float,
             bass: list[float], mid: list[float], high: list[float],
             hz: int) -> list[dict]:
    """Change-point split of the intensity envelope into labelled sections."""
    n = norm.size
    # quantize to 3 levels with a dead-band, then majority-smooth out flicker
    level = np.where(norm > 0.6, 2, np.where(norm < 0.33, 0, 1))
    sm = max(1, int(round(2 * hz)))
    level = np.array([
        int(np.round(np.median(level[max(0, i - sm):i + sm + 1]))) for i in range(n)
    ])
    # boundaries where the smoothed level changes
    bounds = [0] + [i for i in range(1, n) if level[i] != level[i - 1]] + [n]
    raw = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    # merge sections shorter than 6s into the previous one
    min_len = int(6 * hz)
    merged: list[list[int]] = []
    for a, b in raw:
        if merged and (b - a) < min_len:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    if len(merged) > 1 and (merged[0][1] - merged[0][0]) < min_len:
        merged[1][0] = merged[0][0]
        merged.pop(0)

    secs = []
    for idx, (a, b) in enumerate(merged):
        t0, t1 = a / hz, min(dur, b / hz)
        seg = norm[a:b]
        energy = float(seg.mean()) if seg.size else 0.0
        e_start = float(seg[:max(1, seg.size // 4)].mean()) if seg.size else energy
        e_end = float(seg[-max(1, seg.size // 4):].mean()) if seg.size else energy
        wps = float(dens[a:b].mean()) if b > a else 0.0
        lyric_t = sum(
            max(0.0, min(t1, float(l["end"])) - max(t0, float(l["start"])))
            for l in lyrics if l["end"] > t0 and l["start"] < t1
        )
        is_instr = lyric_t < 1.0
        drive = max(
            ("bass", "mid", "high"),
            key=lambda band: _count_in({"bass": bass, "mid": mid, "high": high}[band], t0, t1),
        )
        secs.append({
            "idx": idx, "start": round(t0, 2), "end": round(t1, 2),
            "energy": round(energy, 3), "wps": round(wps, 2),
            "is_instrumental": is_instr, "drive_band": drive,
            "rising": e_end - e_start > 0.15,
            "kind": _label(idx, len(merged), energy, e_start, e_end, wps, is_instr, t1 - t0),
        })
    return secs


def _count_in(grid: list[float], t0: float, t1: float) -> int:
    return sum(1 for g in grid if t0 <= g < t1)


def _label(idx: int, total: int, energy: float, e_start: float, e_end: float,
           wps: float, is_instr: bool, span: float) -> str:
    if idx == 0 and energy < 0.45:
        return "intro"
    if idx == total - 1 and energy < 0.55:
        return "outro"
    if is_instr:
        return "interlude" if energy >= 0.45 else "breakdown"
    if e_end - e_start > 0.18:
        return "build"
    if energy > 0.66 and wps < 1.5 and span <= 18.0:
        return "drop"           # drops are short bursts, not whole movements
    if energy > 0.5:
        return "chorus"
    return "verse"


# ── Stage 1: STORY (LLM, with deterministic fallback) ─────────────────────────

_STORY_SCHEMA = (
    '{"logline":"<1 sentence>","theme":"<short>","tone":"<short>","motif":"<a recurring visual>",'
    '"characters":[{"id":"char-<slug>","name":"<short>","role":"protagonist|...",'
    '"visual_anchor":"<FROZEN concrete physical description: age, build, hair, wardrobe, '
    'distinguishing features, colour notes — detailed enough to redraw identically>",'
    '"arc_note":"<how they change>"}],'
    '"settings":[{"id":"set-<slug>","name":"<short>","visual_anchor":"<concrete recurring location>"}],'
    '"motifs":[{"id":"mot-<slug>","name":"<short>","visual_form":"<concrete>"}],'
    '"arc":[{"section_idx":<int>,"act":"setup|rising|climax|resolution","emotion":"<word>"}]}'
)


def analyze_story(project: dict, rhythm: dict, prior: Optional[dict] = None,
                  notes: Optional[str] = None) -> dict:
    lyrics = sorted(project.get("lyrics_json") or [], key=lambda x: x["start"])
    transcript = "\n".join(f"[{_clock(l['start'])}] {l['text']}" for l in lyrics) \
        or "(instrumental — no lyrics)"
    sect = "\n".join(
        f"{s['idx']}. [{_clock(s['start'])}-{_clock(s['end'])}] {s['kind']} "
        f"(energy {s['energy']:.2f}{', instrumental' if s['is_instrumental'] else ''})"
        for s in rhythm["sections"]
    )
    ctx = (f"SONG: {project.get('name') or 'Untitled'} "
           f"({rhythm['duration']:.0f}s, {rhythm['bpm']:.0f} BPM)\n\n"
           f"MOOD: {_mood_brief(project)}\n\nSECTIONS:\n{sect}\n\nLYRICS:\n{transcript}")
    if prior:
        # revise: keep everything the notes don't touch
        system = (
            "You are revising an existing music-video story bible from the director's "
            "notes. Change ONLY what the notes ask for; keep everything else intact "
            "(ids, names, anchors). Return the FULL revised bible as STRICT JSON with "
            f"the same schema: {_STORY_SCHEMA}"
        )
        user = (f"CURRENT BIBLE:\n{json.dumps(prior)}\n\n"
                f"DIRECTOR NOTES: {notes or 'tighten coherence and vividness'}\n\n{ctx}")
    else:
        system = (
            "You are a music-video screenwriter. From the FULL timestamped lyrics, the "
            "mood, and the section map, infer the STORY the song tells and a small bible "
            "to stage it consistently. Decide a clear through-line — it can be literal or "
            "a single evocative visual metaphor, but it must be COHERENT and recur.\n\n"
            f"Return STRICT JSON: {_STORY_SCHEMA}"
            " — 1 to 3 characters, 1 to 4 settings. visual_anchor strings are the "
            "load-bearing part: be specific and consistent so the same subject can be "
            "regenerated."
        )
        user = ctx + (f"\n\nDIRECTOR NOTES: {notes}" if notes else "")
    data = _llm_json(system, user)
    if not data or not data.get("characters"):
        return prior or _story_fallback(project, rhythm)
    # normalise / guard
    data.setdefault("logline", (project.get("mood_json") or {}).get("mood", "A wordless mood piece"))
    for key in ("characters", "settings", "motifs", "arc"):
        if not isinstance(data.get(key), list):
            data[key] = []
    _ensure_ids(data["characters"], "char")
    _ensure_ids(data["settings"], "set")
    _ensure_ids(data["motifs"], "mot")
    return data


def _ensure_ids(items: list[dict], prefix: str) -> None:
    for i, it in enumerate(items):
        if not it.get("id"):
            it["id"] = f"{prefix}-{i}"
        if not it.get("visual_anchor"):
            it["visual_anchor"] = it.get("name", prefix)


def _story_fallback(project: dict, rhythm: dict) -> dict:
    m = project.get("mood_json") or {}
    sugg = m.get("visual_suggestions") or []
    mood = m.get("mood", "moody")
    setting_anchor = (sugg[0] if sugg else f"a {mood} environment")
    return {
        "logline": f"A {mood} journey through the song's world.",
        "theme": mood, "tone": mood, "motif": (m.get("keywords") or ["light"])[0],
        "characters": [{
            "id": "char-figure", "name": "the figure", "role": "protagonist",
            "visual_anchor": f"a solitary figure, consistent silhouette and wardrobe, "
                             f"lit in the palette {', '.join((m.get('palette') or [])[:3])}",
            "arc_note": "moves through the song's emotional arc",
        }],
        "settings": [{"id": "set-world", "name": "the world", "visual_anchor": setting_anchor}],
        "motifs": [{"id": "mot-light", "name": "light",
                    "visual_form": f"{mood} light and texture"}],
        "arc": [{"section_idx": s["idx"], "act": "rising", "emotion": s["kind"]}
                for s in rhythm["sections"]],
    }


# ── Stage 2: SCRIPT (deterministic slots + LLM meaning) ────────────────────────

SHOT_CEILING = 36  # hard safety ceiling on an auto-decided shot count


def _suggest_count(rhythm: dict) -> int:
    """How many shots the song wants: a duration × energy-scaled shots/minute."""
    dur = rhythm.get("duration") or 0.0
    secs = rhythm.get("sections") or []
    if dur <= 0 or not secs:
        return 4
    span = sum(s["end"] - s["start"] for s in secs) or dur
    mean_e = sum((s["end"] - s["start"]) * s["energy"] for s in secs) / span
    spm = 6.0 + 5.0 * mean_e            # ~6 (calm) … ~11 (energetic) shots / minute
    return int(max(4, min(SHOT_CEILING, round(dur / 60.0 * spm))))


def segment_shots(project: dict, rhythm: dict, story: dict,
                  max_shots: Optional[int] = None, prior: Optional[dict] = None,
                  notes: Optional[str] = None) -> dict:
    # keep the prior shot count on a content revision (no explicit count given)
    if max_shots is None and prior and prior.get("shots") and not _wants_recount(notes):
        target = len(prior["shots"])
    else:
        target = (_suggest_count(rhythm) if max_shots is None
                  else max(3, min(SHOT_CEILING, int(max_shots))))
    slots = _build_slots(project, rhythm, target)
    lyrics = sorted(project.get("lyrics_json") or [], key=lambda x: x["start"])
    for s in slots:
        s["lyric"] = " ".join(
            l["text"] for l in lyrics
            if l["end"] > s["start"] and l["start"] < s["start"] + s["duration"]
        ).strip()

    assigned = _assign_meaning(project, rhythm, story, slots,
                               prior=(prior or {}).get("shots"), notes=notes)
    return {"concept": assigned.get("concept", story.get("logline", "")),
            "shots": assigned["shots"]}


def _wants_recount(notes: Optional[str]) -> bool:
    if not notes:
        return False
    n = notes.lower()
    return any(w in n for w in ("more shot", "fewer shot", "shots", "faster", "slower",
                                "cut", "pace", "tighten", "longer", "shorter"))


def _build_slots(project: dict, rhythm: dict, target: int) -> list[dict]:
    """Cut the song into ``target`` beat-aligned shots, distributed across sections
    by length × energy (so a long high-energy section earns more cuts, but no single
    section runs away)."""
    bass = sorted((project.get("beats_json") or {}).get("bass") or [])
    bars = rhythm.get("bar_starts") or []
    sections = rhythm["sections"]
    dur = rhythm["duration"]

    # weight = span × (0.5 + energy); allocate the target proportionally, ≥1 each
    weights = [max(0.1, (s["end"] - s["start"]) * (0.5 + s["energy"])) for s in sections]
    wsum = sum(weights) or 1.0
    plans = [[s, max(1, int(round(target * w / wsum)))]
             for s, w in zip(sections, weights)]
    # reconcile rounding to exactly hit the target
    total = sum(p[1] for p in plans)
    while total > target:                       # trim the section with the most shots
        cut = max((p for p in plans if p[1] > 1), key=lambda p: p[1], default=None)
        if not cut:
            break
        cut[1] -= 1
        total -= 1
    while total < target:                       # grow the heaviest section
        plans[max(range(len(plans)), key=lambda i: weights[i] / plans[i][1])][1] += 1
        total += 1
    plans.sort(key=lambda p: p[0]["idx"])

    slots: list[dict] = []
    for s, n in plans:
        span = s["end"] - s["start"]
        hot = s["energy"] > 0.6
        if s["kind"] == "build" and n > 1:
            # geometrically shrinking shots accelerating into the next section
            weights = [1.0 / (1.4 ** i) for i in range(n)]
            wsum = sum(weights)
            offs, acc = [], 0.0
            for w in weights:
                offs.append(acc)
                acc += span * w / wsum
            starts = [s["start"] + o for o in offs]
        else:
            starts = [s["start"] + span * i / n for i in range(n)]
        for i, st in enumerate(starts):
            st = _snap(st, bars, 0.30)                  # land on a bar first
            st = _snap(st, bass, 0.18 if hot else 0.25)  # then nudge to a kick
            end = starts[i + 1] if i + 1 < len(starts) else s["end"]
            slots.append({
                "section_idx": s["idx"], "section_kind": s["kind"],
                "is_instrumental": s["is_instrumental"], "drive_band": s["drive_band"],
                "start": round(max(0.0, st), 2),
                "duration": round(max(0.8, min(dur, end) - st), 2),
            })
    # de-dupe identical starts, keep order
    seen, out = set(), []
    for sl in sorted(slots, key=lambda x: x["start"]):
        if sl["start"] in seen:
            continue
        seen.add(sl["start"])
        out.append(sl)
    for i, sl in enumerate(out):
        sl["idx"] = i
        nxt = out[i + 1]["start"] if i + 1 < len(out) else dur
        sl["duration"] = round(max(0.8, nxt - sl["start"]), 2)
    return out[:target]


def _assign_meaning(project: dict, rhythm: dict, story: dict, slots: list[dict],
                    prior: Optional[list[dict]] = None,
                    notes: Optional[str] = None) -> dict:
    chars = story.get("characters") or []
    setts = story.get("settings") or []
    motifs = story.get("motifs") or []
    char_ids = [c["id"] for c in chars]
    set_ids = [s["id"] for s in setts]

    slot_lines = "\n".join(
        f"{s['idx']}. [{_clock(s['start'])}] {s['section_kind']}"
        f"{' instrumental' if s['is_instrumental'] else ''} :: "
        f"{s['lyric'] or '(no lyric)'}"
        for s in slots
    )
    bible = json.dumps({
        "concept": story.get("logline"),
        "characters": [{"id": c["id"], "name": c.get("name")} for c in chars],
        "settings": [{"id": s["id"], "name": s.get("name")} for s in setts],
        "motifs": [{"id": m["id"], "name": m.get("name")} for m in motifs],
    })
    system = (
        "You are the director boarding a music video. For EACH numbered shot slot "
        "(timing is fixed — do not change it), assign its meaning so the shots tell "
        "the story with recurring characters/settings, setups and payoffs, and "
        "framing that varies (wide establishing, medium, close, detail, abstract). "
        "Reference entities by the bible ids. Return STRICT JSON: {"
        '"concept":"<1 sentence>","shots":[{"idx":<int>,'
        f'"char_ids":[<subset of {char_ids}>],"setting_id":<one of {set_ids} or null>,'
        '"motif_ids":[],"shot_size":"wide|medium|close|detail|abstract",'
        '"beat":"establish|develop|turn|payoff|interlude",'
        '"shot_kind":"image|interlude_effect",'
        '"intent":"<what this shot MEANS in 6-12 words>",'
        '"prompt_core":"<subject + action + composition, concrete, NO style words>",'
        '"motion":"zoom-in|zoom-out|pan-left|pan-right|pan-up|pan-down"}]}'
        " — exactly one entry per slot, in order. Use shot_kind \"interlude_effect\" "
        "ONLY for an instrumental slot that works as a pure graphic moment."
    )
    user = f"BIBLE: {bible}\n\nMOOD: {_mood_brief(project)}\n\nSHOT SLOTS:\n{slot_lines}"
    if prior:
        prior_brief = "\n".join(
            f"{p['idx']}. {p.get('shot_size','')} | {p.get('intent') or p.get('prompt_core','')}"
            for p in prior
        )
        user += (f"\n\nCURRENT BOARDING (revise this — keep shots the notes don't "
                 f"mention; re-map by slot index):\n{prior_brief}")
    if notes:
        user += f"\n\nDIRECTOR NOTES (apply these): {notes}"
    data = _llm_json(system, user)
    designed = (data or {}).get("shots") or []
    by_idx = {d.get("idx"): d for d in designed if isinstance(d, dict)}

    shots = []
    for s in slots:
        d = by_idx.get(s["idx"], {})
        cids = [c for c in (d.get("char_ids") or []) if c in char_ids]
        sid = d.get("setting_id") if d.get("setting_id") in set_ids else (set_ids[0] if set_ids else None)
        size = d.get("shot_size") if d.get("shot_size") in _SIZES else _SIZES[s["idx"] % len(_SIZES)]
        motion = d.get("motion") if d.get("motion") in _MOTIONS else _MOTIONS[s["idx"] % len(_MOTIONS)]
        kind = "interlude_effect" if d.get("shot_kind") == "interlude_effect" else "image"
        core = str(d.get("prompt_core") or s["lyric"] or
                   (project.get("mood_json") or {}).get("mood", "a quiet moment"))
        shots.append({**s,
                      "char_ids": cids or (char_ids[:1] if char_ids and not s["is_instrumental"] else []),
                      "setting_id": sid, "motif_ids": d.get("motif_ids") or [],
                      "shot_size": size, "beat": d.get("beat") or "develop",
                      "shot_kind": kind, "motion": motion,
                      "intent": str(d.get("intent") or "")[:120], "prompt_core": core})
    return {"concept": (data or {}).get("concept", story.get("logline", "")), "shots": shots}


# ── Stage 3: INVENTORY + BROKER (deterministic) ───────────────────────────────

def build_inventory(pid: str) -> list[dict]:
    inv = []
    for a in db.list_media(pid):
        if a.get("kind") != "image":
            continue
        desc = " ".join(filter(None, [
            a.get("gen_prompt"), a.get("label"),
            " ".join(a.get("tags") or []), a.get("original_name"),
        ]))
        inv.append({
            "id": a["id"], "label": a.get("label"), "tags": a.get("tags") or [],
            "bible_entity": a.get("bible_entity"), "w": a.get("width") or 0,
            "h": a.get("height") or 0, "tokens": _tokens(desc),
        })
    return inv


def find_entity(story: dict, entity_id: str) -> tuple[Optional[dict], str]:
    """Look up a story entity by id; returns (entity, 'character'|'scene')."""
    for c in story.get("characters") or []:
        if c["id"] == entity_id:
            return c, "character"
    for s in story.get("settings") or []:
        if s["id"] == entity_id:
            return s, "scene"
    return None, ""


def reference_prompt(entity: dict, kind: str, project: dict) -> str:
    """A clean, canonical reference image prompt for a character or location."""
    style = _style_suffix(project)
    anchor = entity.get("visual_anchor") or entity.get("name", "")
    if kind == "character":
        return (f"Character reference portrait. {anchor}. Single subject, clear and "
                f"well lit, three-quarter view from head to waist, neutral backdrop, "
                f"sharp focus on the face. {style}")
    return (f"Location establishing plate. {anchor}. Wide, empty establishing shot of "
            f"the place with no people, clear sense of the space. {style}")


def broker(project: dict, story: dict, script: dict, inventory: list[dict],
           bible_links: dict) -> dict:
    chars = {c["id"]: c for c in (story.get("characters") or [])}
    setts = {s["id"]: s for s in (story.get("settings") or [])}
    motifs = {m["id"]: m for m in (story.get("motifs") or [])}
    style = _style_suffix(project)

    placed_at: list[tuple[float, float]] = []     # reused asset time spans (avoid dup on screen)
    shots_out = []

    for shot in script["shots"]:
        primary = (shot.get("char_ids") or [None])[0] or shot.get("setting_id")

        anchors = [chars[c]["visual_anchor"] for c in shot.get("char_ids", []) if c in chars]
        if shot.get("setting_id") in setts:
            anchors.append(setts[shot["setting_id"]]["visual_anchor"])
        anchors += [motifs[m]["visual_form"] for m in shot.get("motif_ids", []) if m in motifs]
        size = shot.get("shot_size", "medium")
        prompt = ". ".join(filter(None, [
            "; ".join(anchors), f"{size} shot, {shot['prompt_core']}", style,
        ]))

        if shot.get("shot_kind") == "interlude_effect":
            shots_out.append({**shot, "decision": "effect", "prompt": prompt,
                              "reuse_asset_id": None, "anchor_for_entity": None,
                              "depends_on": [], "wave": 0})
            continue

        # score the library for a reusable plate
        ptok = _tokens(shot["prompt_core"]) | _tokens("; ".join(anchors))
        best, best_a = 0.0, None
        for a in inventory:
            score = 0.55 * _jaccard(ptok, a["tokens"])
            if primary and a.get("bible_entity") == primary:
                score += 0.30
            elif primary and a.get("label") and primary.split("-")[-1] in a["label"].lower():
                score += 0.20
            if a["w"] >= a["h"] and a["w"] >= 1024:
                score += 0.05
            if score > best:
                best, best_a = score, a

        reuse = (best >= 0.62 and best_a is not None
                 and not _asset_overlaps(best_a["id"], shot, placed_at, shots_out))

        if reuse:
            placed_at.append((shot["start"], shot["start"] + shot["duration"]))
            shots_out.append({**shot, "decision": "reuse", "prompt": prompt,
                              "reuse_asset_id": best_a["id"], "depends_on": [],
                              "score": round(best, 3)})
            continue

        # GENERATE — reference every entity in the shot. The actual reference images
        # (the cast portraits + location plates) are generated FIRST by the render
        # step; each shot here just declares which canon it needs.
        depends = list(shot.get("char_ids") or [])
        if shot.get("setting_id"):
            depends.append(shot["setting_id"])
        shots_out.append({**shot, "decision": "generate", "prompt": prompt,
                          "reuse_asset_id": None, "depends_on": depends,
                          "score": round(best, 3)})

    gen = sum(1 for s in shots_out if s["decision"] == "generate")
    reuse_n = sum(1 for s in shots_out if s["decision"] == "reuse")
    # entities that need a reference image (any referenced by a generate shot)
    cast_entities: list[str] = []
    for s in shots_out:
        if s["decision"] == "generate":
            for e in s.get("depends_on") or []:
                if e not in cast_entities:
                    cast_entities.append(e)
    return {"shots": shots_out, "generate_count": gen, "reuse_count": reuse_n,
            "cast_entities": cast_entities}


def _asset_overlaps(asset_id: str, shot: dict, placed: list, shots_out: list) -> bool:
    for prev in shots_out:
        if prev.get("reuse_asset_id") == asset_id:
            if not (shot["start"] + shot["duration"] <= prev["start"]
                    or shot["start"] >= prev["start"] + prev["duration"]):
                return True
    return False


# ── Stage 4: EFFECTS + new-filter authoring ────────────────────────────────────

# section_kind -> (filter_id, default band) for a fitting built-in
_SECTION_FX = {
    "drop": ("lola-bass-zoom", "bass"),
    "chorus": ("lola-saturation-pump", "mid"),
    "build": ("lola-high-flash", "high"),
    "breakdown": ("gfunk-film-grain", "bass"),
}
_INTERLUDE_FX = ["gfunk-sway", "vhs-wobble", "gfunk-color-wash", "vhs-chroma-bleed"]


def plan_effects(project: dict, rhythm: dict, script: dict, story: dict) -> dict:
    dur = rhythm["duration"]
    bass = sorted((project.get("beats_json") or {}).get("bass") or [])
    available = {f["id"] for f in filters.list_filters()}
    m = project.get("mood_json") or {}
    warm = _is_warm(m.get("palette") or [])

    effects = [{"filter_id": "gfunk-vignette", "name": "Vignette", "at": 0.0,
                "duration": round(dur, 2), "params": {}, "scope": "global"}]
    grade = "gfunk-sunset-grade" if warm else "gfunk-color-wash"
    if grade in available:
        effects.append({"filter_id": grade, "name": grade.replace("-", " ").title(),
                        "at": 0.0, "duration": round(dur, 2),
                        "params": {"intensity": 0.5}, "scope": "global"})

    # per-section accent filters — only the strongest few, to punctuate not spam
    accent_secs = sorted(
        [s for s in rhythm["sections"]
         if _SECTION_FX.get(s["kind"], (None,))[0] in available and s["energy"] >= 0.35],
        key=lambda s: s["energy"], reverse=True)[:3]
    for s in sorted(accent_secs, key=lambda s: s["start"]):
        fid, band = _SECTION_FX[s["kind"]]
        effects.append({
            "filter_id": fid, "name": fid.replace("-", " ").title(),
            "at": _snap(s["start"], bass, 0.25),
            "duration": round(min(s["end"], dur) - s["start"], 2),
            "params": {"band": band, "intensity": round(0.6 + 1.2 * s["energy"], 2)},
            "scope": "section",
        })

    # punch on each drop
    for t in rhythm["drops"]:
        effects.append({"filter_id": "lola-bass-zoom", "name": "Bass Punch",
                        "at": t, "duration": 1.6,
                        "params": {"band": "bass", "intensity": 1.6}, "scope": "drop"})
    if rhythm["drops"] and "vhs-tracking-glitch" in available:
        hardest = rhythm["drops"][0]
        effects.append({"filter_id": "vhs-tracking-glitch", "name": "Glitch Hit",
                        "at": hardest, "duration": 0.8, "params": {}, "scope": "drop"})

    # graphic interludes → effect-only clips (and maybe a bespoke filter)
    interlude_clips: list[dict] = []
    new_filters: list[dict] = []
    effect_shots = [sh for sh in script["shots"] if sh.get("shot_kind") == "interlude_effect"]
    for j, sh in enumerate(effect_shots):
        band = sh.get("drive_band", "bass")
        authored = None
        if j == 0:  # author ONE bespoke filter for the most prominent interlude
            authored = _begin_authored_filter(project, sh, story)
        if authored:
            new_filters.append(authored)
            fid = authored["fid"]
        else:
            fid = _INTERLUDE_FX[j % len(_INTERLUDE_FX)]
            if fid not in available:
                fid = "gfunk-sway"
        interlude_clips.append({
            "filterId": fid, "name": (authored["name"] if authored else fid.replace("-", " ").title()),
            "params": {"intensity": 1.0, "band": band, "enabled": True},
            "start": _snap(sh["start"], bass, 0.25),
            "duration": sh["duration"], "assetId": None,
        })

    return {"effects": effects, "interlude_clips": interlude_clips,
            "new_filters": new_filters}


def _is_warm(palette: list[str]) -> bool:
    score = 0
    for hexc in palette[:5]:
        try:
            h = hexc.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            score += 1 if r >= b else -1
        except (ValueError, IndexError):
            pass
    return score > 0


def _begin_authored_filter(project: dict, shot: dict, story: dict) -> Optional[dict]:
    """Create a clean blank filter now; the opus rewrite is enqueued by the director.

    Returns {fid, name, brief} or None. The director kicks off the async authoring
    job so the request stays fast; until it lands the clip renders as a no-op.
    """
    m = project.get("mood_json") or {}
    name = f"{(m.get('mood') or 'Mood').split()[0]} Interlude"
    try:
        detail = filters.create_blank(name)
    except Exception:
        return None
    fid = detail["manifest"]["id"]
    band = shot.get("drive_band", "bass")
    kws = ", ".join((m.get("keywords") or [])[:5])
    pal = ", ".join((m.get("palette") or [])[:4])
    brief = (
        f"Create a {m.get('mood','moody')} graphic interlude effect for a music video. "
        f"It should feel like: {kws or 'the song'}. React to ctx.{band} (the beat envelope) "
        f"and ctx.rms. Use the palette {pal}. Motif: {story.get('motif','light')}. "
        "Transform the incoming frame (it may be a near-black fill) into a living, "
        "beat-reactive visual — drifting light, grain, waves, or geometry — that pulses on "
        f"ctx.{band}. Expose intensity (slider), band (select bass/mid/high, default "
        f"{band}) and enabled (switch) PARAMS. Pure per-frame transform, no I/O. Keep it fast."
    )
    return {"fid": fid, "name": name, "brief": brief}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

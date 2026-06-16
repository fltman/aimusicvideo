"""Vibe-code chat: edit a filter plugin's code with claude-opus-4.8.

The model rewrites the whole filter.py; the result is validated (compile + a
one-frame smoke test) before being saved as a new version. A failed attempt is
fed back once for a fix; if it still fails nothing is saved.
"""
from __future__ import annotations

import re
import types
from typing import Any

import httpx
import numpy as np

from .. import config
from . import filters

_TIMEOUT = 180.0
_CODE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def _contract() -> str:
    p = config.BUILTIN_FILTERS_DIR / "FILTER_CONTRACT.md"
    return p.read_text() if p.exists() else ""


def _system_prompt(code: str) -> str:
    return (
        "You are an expert creative-coding engineer editing ONE video filter "
        "plugin for a music-video editor. The filter transforms a single video "
        "frame at a time and is synced to the song's beats.\n\n"
        "FILTER CONTRACT — follow it exactly:\n"
        f"{_contract()}\n\n"
        "CURRENT filter.py:\n```python\n" + code + "\n```\n\n"
        "When the user requests a change, rewrite the ENTIRE filter.py. Reply "
        "with the complete new file in ONE ```python fenced block, then a single "
        "sentence summarising the change. Keep PARAMS in sync with the code "
        "(expose new controls as slider/knob/switch/select). Keep it fast (runs "
        "per frame). Use ctx.bass/mid/high for beat-sync and ctx.rng for any "
        "randomness. Never do file/network I/O."
    )


def _extract_code(text: str) -> tuple[str | None, str]:
    m = _CODE_RE.search(text or "")
    if not m:
        return None, (text or "").strip()
    code = m.group(1).strip()
    reply = (_CODE_RE.sub("", text).strip() or "Updated the filter.")
    return code, reply


def _smoke_test(code: str) -> list[dict]:
    """Compile + run process() on a dummy frame; raises on any problem."""
    compile(code, "<filter>", "exec")
    ns: dict[str, Any] = {}
    exec(code, ns)  # noqa: S102 — user/AI filter code; render is sandboxed separately
    process = ns.get("process")
    params = ns.get("PARAMS", [])
    if not callable(process):
        raise ValueError("filter.py must define process(frame, ctx, p)")
    if not isinstance(params, list):
        raise ValueError("PARAMS must be a list")
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    ctx = types.SimpleNamespace(
        t=0.5, i=12, fps=24, w=64, h=48, bass=0.8, mid=0.4, high=0.6,
        rms=0.5, onsets={"bass": [0.5], "mid": [], "high": []},
        rng=np.random.default_rng(0),
    )
    p = {pp["key"]: pp.get("default") for pp in params if "key" in pp}
    out = process(frame, ctx, p)
    if out is not None and (out.shape != frame.shape or out.dtype != np.uint8):
        raise ValueError("process() must return an (H,W,3) uint8 frame")
    return params


def _post(messages: list[dict]) -> str:
    resp = httpx.post(
        f"{config.OPENROUTER_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                 "Content-Type": "application/json",
                 "X-Title": "AI Music Video Studio"},
        json={"model": config.FILTER_CHAT_MODEL, "messages": messages},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"].get("content") or ""


def chat(fid: str, user_message: str) -> dict:
    """One vibe-code turn. Saves a new version on success."""
    f = filters.get_filter(fid)
    if not f:
        return {"error": "filter not found"}

    history = filters.read_chat(fid)
    convo = [{"role": "system", "content": _system_prompt(f["code"])}]
    for m in history[-8:]:
        convo.append({"role": m["role"], "content": m["content"]})
    convo.append({"role": "user", "content": user_message})

    last_err = None
    for attempt in range(2):
        try:
            content = _post(convo)
        except Exception as e:  # noqa: BLE001
            return {"error": f"chat request failed: {e}"}
        code, reply = _extract_code(content)
        if not code:
            # conversational reply, no code change
            history += [{"role": "user", "content": user_message},
                        {"role": "assistant", "content": reply}]
            filters.write_chat(fid, history)
            return {"reply": reply, "version": None}
        try:
            _smoke_test(code)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            convo.append({"role": "assistant", "content": content})
            convo.append({"role": "user", "content":
                          f"That failed validation: {last_err}. "
                          "Fix it and return the complete filter.py again."})
            continue
        meta = filters.save_version(fid, code, reply[:120] or user_message[:120])
        history += [{"role": "user", "content": user_message},
                    {"role": "assistant", "content": reply}]
        filters.write_chat(fid, history)
        return {"reply": reply, "version": meta["version"], "code": code,
                "params": filters.read_params(fid)}

    return {"reply": f"I couldn't get the code working: {last_err}",
            "version": None, "error": last_err}

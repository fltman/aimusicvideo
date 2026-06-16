# Filter plugin contract

A filter is a folder with `manifest.json` + `filter.py`. `filter.py` defines a
`PARAMS` list (drives the auto-generated UI controls) and a `process()` function
called once per video frame.

```python
PARAMS = [
  # type: "slider" | "knob"  → numeric (min, max, step, default)
  # type: "switch"           → boolean (default true/false)
  # type: "select"           → enum (options: [...], default)
  {"key": "intensity", "type": "slider", "label": "Intensity",
   "min": 0, "max": 3, "step": 0.05, "default": 1.0},
  {"key": "band", "type": "select", "label": "Drive band",
   "options": ["bass", "mid", "high"], "default": "bass"},
  {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
]

def process(frame, ctx, p):
    """Return the modified frame (HxWx3 BGR uint8 numpy array)."""
    return frame
```

## `frame`
A `numpy.ndarray` of shape `(H, W, 3)`, dtype `uint8`, **BGR** channel order
(OpenCV convention). Modify and return it (or return a new array of the same
shape/dtype). `numpy as np` and `cv2` are available to import.

## `ctx` (per-frame context)
- `ctx.bass`, `ctx.mid`, `ctx.high` — float `0..1`: the beat envelope for each
  frequency band **at this frame** (smoothly ramps up on each onset, decays).
  This is how you sync to the beat: `env = getattr(ctx, p["band"])`.
- `ctx.rms` — float `0..1`: overall loudness at this frame (for constant motion).
- `ctx.onsets` — `{"bass": [t...], "mid": [...], "high": [...]}` raw onset times
  in **seconds relative to the start of this render window** (advanced use).
- `ctx.clip_progress` — float `0..1`: how far through THIS effect clip we are
  (0 at its start, 1 at its end). Use it for transitions / fades.
- `ctx.t` (seconds), `ctx.i` (frame index), `ctx.fps`, `ctx.w`, `ctx.h`.
- `ctx.rng` — a seeded `numpy.random.Generator` (use it for any randomness so
  renders are reproducible; do not call `np.random` directly).

## `p` (parameter values)
A dict mapping each `PARAMS` key → its current value, e.g. `p["intensity"]`.
Always read params from `p`; never hardcode.

## Rules
- Keep `process` self-contained and fast (it runs per frame). Imports go at the
  top of the file.
- Always honour an `enabled` switch if present (return `frame` unchanged when off).
- Never read/write files, network, or do anything outside transforming `frame`.
- The returned array must be `(H, W, 3)` uint8; resize if you change dimensions.

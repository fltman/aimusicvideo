# AI Music Video Studio — Build Contract (Step 1)

This document is the **authoritative interface contract**. Foundation files are
already written and MUST NOT be changed. Build the leaf modules below to match
these signatures exactly. Do not invent new endpoints, fields, or store actions.

## Stack
- Backend: FastAPI (Python 3.14), uvicorn, sqlite3, numpy/scipy, shelling out to
  `ffmpeg`/`ffprobe` and `whisper-cli`. Port **8100**.
- Frontend: React 18 + Vite + TypeScript + Tailwind 3, Zustand. Port **5200**.
  Dev proxy sends `/api` and `/files` to 8100.

## Already-written foundation (DO NOT MODIFY — import and use)
- `backend/app/config.py` — paths, tool locations, analysis params, helpers:
  `ensure_dirs()`, `project_dir(id)`, `rel_to_data(path)`, `whisper_model_ready()`,
  `DATA_DIR`, `PROJECTS_DIR`, `FFMPEG`, `FFPROBE`, `WHISPER_CLI`, `WHISPER_MODEL`,
  `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `MOOD_MODEL`,
  `BASS_RANGE/MID_RANGE/HIGH_RANGE`, `ANALYSIS_SR`, `WAVEFORM_PPS`, `PORT`.
- `backend/app/db.py` — all persistence helpers (see below).
- `backend/app/models.py` — Pydantic schemas: `ProjectCreate`, `ProjectUpdate`,
  `Track`, `Clip`, `TimelineDoc`, `SongStatus`, `Analysis`.
- `backend/app/services/spectral.py` — `analyze(wav_path) -> dict` returning
  `{duration, sample_rate, tempo, beats:{bass,mid,high}, waveform:{peaks,pps}}`.
- `frontend/src/types.ts`, `frontend/src/api/client.ts`,
  `frontend/src/store/editorStore.ts` — see store API below.

### db.py helper functions (use these, never raw SQL)
- `init_db()`
- `create_project(name) -> dict`, `list_projects() -> list[dict]`,
  `get_project(id) -> dict|None`, `update_project_fields(id, **fields)`,
  `delete_project(id)`, `set_timeline(id, doc)`, `get_timeline(id) -> dict`
- `add_media(project_id, kind, original_name, path, thumb_path=None,
  duration_sec=None, width=None, height=None) -> dict`,
  `list_media(project_id) -> list[dict]`, `get_media(asset_id) -> dict|None`,
  `delete_media(asset_id) -> dict|None`
- Project JSON columns auto-encode/decode: `beats_json`, `waveform_json`,
  `lyrics_json`, `mood_json`, `timeline_json`. Pass python objects to
  `update_project_fields`; they are JSON-serialized for you.
- Project row analysis fields: `analysis_status` (`none|processing|done|error`),
  `analysis_progress` (0..1 float), `analysis_stage` (str), `analysis_error`.

## Filesystem layout (under `DATA_DIR` = backend/data)
```
data/
  app.db
  projects/<pid>/
    source.<ext>          # original uploaded song
    song.wav              # converted 44100Hz stereo pcm_s16le (playback + analysis)
    media/<assetId>.<ext> # library asset
    media/thumbs/<assetId>.jpg
```
Store **relative** paths in the db (`config.rel_to_data(abspath)`), e.g.
`projects/<pid>/song.wav`. The frontend loads them via `/files/<relpath>`.

---

## BUILD TASK 1 — backend/app/services/audio.py
ffmpeg/ffprobe helpers. Functions:
- `convert_to_wav(src, dst) -> float`: run
  `ffmpeg -y -i src -ac 2 -ar 44100 -c:a pcm_s16le dst`; return duration (sec)
  via `probe(dst)`. Raise `RuntimeError` on non-zero exit (include stderr tail).
- `probe(path) -> dict`: run ffprobe (`-v quiet -print_format json -show_format
  -show_streams`); return `{duration: float|None, width: int|None,
  height: int|None, has_video: bool, has_audio: bool}`.
- `media_kind(filename, probe_result) -> 'image'|'video'|'audio'`: images by
  extension (jpg/jpeg/png/gif/webp/bmp/heic) → 'image'; else 'video' if
  has_video else 'audio'.
- `make_thumbnail(src, dst, kind) -> bool`: image → `ffmpeg -y -i src -vf
  scale=320:-1 dst`; video → `ffmpeg -y -ss 1 -i src -frames:v 1 -vf scale=320:-1
  dst`; audio → return False (no thumb). Swallow errors → return False.
Use `subprocess.run([...], capture_output=True, text=True)`. No shell=True.

## BUILD TASK 2 — backend/app/services/whisper_lyrics.py
- `transcribe(wav_path) -> list[dict]` returning `[{start:float, end:float,
  text:str}]` (seconds). If `not config.whisper_model_ready()` → return `[]`.
  Run in a temp dir:
  `whisper-cli -m <WHISPER_MODEL> -f <wav> -l auto -oj -ml 60 -sow -t <ncpu>
   -of <out_prefix>` then read `<out_prefix>.json`. whisper.cpp JSON shape:
  `{"transcription":[{"offsets":{"from":<ms>,"to":<ms>}, "text":"..."}]}`.
  Map `from/to` ms → seconds, strip text. Drop empty-text segments. Any
  exception → return `[]` (never raise — lyrics are best-effort).

## BUILD TASK 3 — backend/app/services/mood.py
- `analyze_mood(lyrics_text: str, features: dict) -> dict` calling OpenRouter
  `MOOD_MODEL` (`google/gemini-3.5-flash`) via httpx POST
  `{OPENROUTER_BASE_URL}/chat/completions` with `Authorization: Bearer
  {OPENROUTER_API_KEY}`. `features` contains `duration`, `tempo`,
  `bass_onsets`, `mid_onsets`, `high_onsets`, `energy_hint`. Prompt the model to
  return STRICT JSON only with keys: `mood` (string), `genres` (string[]),
  `energy` (0..1 number), `tempo_bpm` (number), `palette` (array of 5 hex
  colors), `keywords` (string[]), `visual_suggestions` (string[] of 3-6 ideas).
  Parse defensively (strip ```json fences). On any failure return
  `{"mood": None, "genres": [], "energy": features.get("energy_hint"),
   "tempo_bpm": features.get("tempo"), "palette": [], "keywords": [],
   "visual_suggestions": []}`. Timeout 60s. Never raise.

## BUILD TASK 4 — backend/app/services/jobs.py
Background analysis pipeline (runs in a daemon thread).
- `start_analysis(project_id: str, original_path: str) -> None`: spawn
  `threading.Thread(target=run_analysis, args=..., daemon=True).start()`.
- `run_analysis(project_id, original_path)`: stages, writing each result to the
  db as soon as it is ready (partial availability) via
  `db.update_project_fields`:
  1. status=`processing`, stage=`converting`, progress=0.05
  2. `audio.convert_to_wav(original_path, project_dir/song.wav)` →
     set `song_wav_path` (rel), `duration_sec`; progress 0.15
  3. stage=`spectral`: `spectral.analyze(wav)` → set `beats_json` (result
     `beats`), `waveform_json` (result `waveform`), refine `duration_sec`;
     progress 0.45
  4. stage=`lyrics`: `whisper_lyrics.transcribe(wav)` → set `lyrics_json`;
     progress 0.80
  5. stage=`mood`: build `features` (duration, tempo from spectral result,
     per-band onset counts, energy_hint = mean abs of waveform or 0.5),
     `lyrics_text` = "\n".join(lyric texts); `mood.analyze_mood(...)` → set
     `mood_json`; progress 0.95
  6. status=`done`, stage=`done`, progress=1.0
  On any exception: `update_project_fields(status='error',
  analysis_error=str(e))` and return.

## BUILD TASK 5 — backend/app/routers/{projects,media,song,timeline}.py + main.py
Each router is an `APIRouter`. Use `db`, `models`, services. Return JSON dicts
(db helpers already return dicts). 404 via `HTTPException(404)`.

### routers/projects.py — `router = APIRouter(prefix="/api/projects", tags=["projects"])`
- `GET ""` → `db.list_projects()`
- `POST ""` body `ProjectCreate` → `db.create_project(body.name)`
- `GET "/{pid}"` → `db.get_project(pid)` or 404
- `PATCH "/{pid}"` body `ProjectUpdate` → if name: `update_project_fields(pid,
  name=...)`; return `get_project(pid)` (404 if missing)
- `DELETE "/{pid}"` → `shutil.rmtree(config.project_dir(pid), ignore_errors=True)`
  then `db.delete_project(pid)`; return `Response(status_code=204)`

### routers/media.py — `prefix="/api/projects/{pid}/media", tags=["media"]`
- `GET ""` → `db.list_media(pid)`
- `POST ""` params `files: list[UploadFile] = File(...)` → for each file:
  generate assetId, ext from filename; save to `project_dir/media/<assetId><ext>`;
  `audio.probe`; `audio.media_kind`; thumbnail to
  `project_dir/media/thumbs/<assetId>.jpg` (rel stored only if created);
  `db.add_media(...)`; collect and return list[dict]. `mkdir(parents=True)`.
- `DELETE "/{asset_id}"` → `db.delete_media`; unlink file + thumb if exist;
  204. (Note: pid is in the path but delete by asset_id.)

### routers/song.py — `prefix="/api/projects/{pid}", tags=["song"]`
- `POST "/song"` param `file: UploadFile = File(...)` → 404 if project missing;
  save original to `project_dir/source<ext>`; `update_project_fields(pid,
  song_original_name=file.filename, analysis_status='processing',
  analysis_progress=0.0, analysis_stage='queued', analysis_error=None)`;
  `jobs.start_analysis(pid, str(source_path))`; return
  `SongStatus(status='processing', progress=0.0, stage='queued', error=None)`.
- `GET "/song/status"` → from `get_project`: `SongStatus(status=analysis_status,
  progress=analysis_progress, stage=analysis_stage, error=analysis_error)`.
- `GET "/analysis"` → from `get_project`: `Analysis(duration=duration_sec,
  beats=beats_json, waveform=waveform_json, lyrics=lyrics_json, mood=mood_json)`.

### routers/timeline.py — `prefix="/api/projects/{pid}", tags=["timeline"]`
- `GET "/timeline"` → `db.get_timeline(pid)`
- `PUT "/timeline"` body `TimelineDoc` → `db.set_timeline(pid,
  body.model_dump())`; 204

### main.py
- `app = FastAPI(title="AI Music Video Studio")`
- CORS: allow_origins `["http://localhost:5200","http://127.0.0.1:5200"]`,
  all methods/headers.
- `@app.on_event("startup")` → `config.ensure_dirs(); db.init_db()`
- include the four routers.
- `app.mount("/files", StaticFiles(directory=config.DATA_DIR), name="files")`
  (ensure_dirs first so the directory exists at import time — call
  `config.ensure_dirs()` at module top before mount).
- `GET "/api/health"` → `{"ok": True, "whisper_model_ready":
  config.whisper_model_ready()}`.

---

## FRONTEND — store API (already written, import `useEditor` from
`store/editorStore`)
State: `projectId, project, media, analysis, tracks, clips, selectedClipId,
playing, currentTime, duration, pixelsPerSecond, loading, analysisStatus,
analysisStage`.
Actions: `loadProject(id)`, `refreshAnalysis()`, `reset()`, `refreshMedia()`,
`play()`, `pause()`, `togglePlay()`, `seek(t)`, `setZoom(pps)`,
`select(clipId|null)`, `addTrack(kind,name?)`, `ensureTrack(kind)`,
`removeTrack(id)`, `addClipFromAsset(asset, start?, trackId?)`,
`moveClip(id,newStart,newTrackId?)`, `updateClip(id,patch)`,
`trimClip(id,'start'|'end', newTimelineTime)`, `splitClipAt(id,t)`,
`splitAtPlayhead()`, `removeClip(id)`.
Pure helpers exported from the store module: `activeVisualClip(tracks,clips,t)`,
`activeLyricIndex(lyrics,t)`, `timelineDuration(clips,songDuration)`.
Helper `filesUrl(path)` from `api/client`.

**All panel components are SELF-CONTAINED**: they read everything from
`useEditor(...)` and take no required props (optional `className` only). This
keeps them decoupled. Time→pixel mapping inside the timeline: `x =
time * pixelsPerSecond`. Use a shared left gutter width of **120px** for track
headers (constant `TRACK_HEADER_W = 120`) and **track height 64px**
(`TRACK_H = 64`), ruler height **28px** (`RULER_H = 28`). Define these in
`frontend/src/lib/constants.ts` (BUILD TASK 7 creates it; BUILD TASK 6 imports it).

## BUILD TASK 6 — Timeline cluster (one coherent module)
Files: `components/timeline/Timeline.tsx`, `Ruler.tsx`, `TrackRow.tsx`,
`ClipView.tsx`, `Playhead.tsx`.
- `Timeline.tsx`: horizontal scroll container. Left 120px gutter = track headers
  (name + kind icon + an "x" to remove non-song tracks). Right = scrollable lane
  area width = `duration * pixelsPerSecond`. Renders `<Ruler/>` on top, one
  `<TrackRow/>` per track, `<Playhead/>` overlay. A toolbar row with "+ Track"
  (audio/video/image/effect), zoom in/out (calls `setZoom`), and current
  duration. Clicking empty ruler/lane area seeks (`seek(x / pps)`). Auto-scroll
  horizontally to keep the playhead visible while playing.
- `Ruler.tsx`: tick marks + `m:ss` labels every nice interval based on pps; draw
  beat markers from `analysis.beats` as thin vertical ticks colored by band
  (tailwind `bg-bass/bg-mid/bg-high`), bass tallest. Click → seek.
- `TrackRow.tsx`: a lane (height 64) rendering its clips (`ClipView`) and acting
  as a drop target for media dragged from the library (read
  `e.dataTransfer.getData('application/x-asset-id')`, look up asset in
  `media`, call `addClipFromAsset(asset, dropTimeSec, track.id)`). Only accept
  drops whose asset.kind matches the track.kind (audio→audio, image→image,
  video→video).
- `ClipView.tsx`: absolutely positioned (`left = start*pps`, `width =
  duration*pps`). Draggable to move (updates via `moveClip`, allow moving to
  another track of same kind by computing pointer Y). Left/right trim handles
  (8px) call `trimClip(id,'start'|'end', timelineTime)`. Selected outline when
  `selectedClipId===id`; click selects. For audio clips with a song waveform
  (clip.source==='song' or audio asset), draw a mini waveform from
  `analysis.waveform.peaks` offset by `inPoint`. Double-click or a scissor while
  selected splits at playhead if inside. Show name label.
- `Playhead.tsx`: vertical line at `currentTime*pps` over the lanes; draggable to
  scrub (`seek`).
Keep all pointer math consistent (account for the 120px gutter + scrollLeft).
Use pointer events (`onPointerDown/Move/Up`) with `setPointerCapture`.

## BUILD TASK 7 — App shell + panels
Files: `lib/constants.ts` (TRACK_HEADER_W=120, TRACK_H=64, RULER_H=28,
MIN_CLIP=0.05), `lib/format.ts` (`fmtTime(sec) -> "m:ss.cs"`, `fmtClock(sec)->
"m:ss"`), `App.tsx`, `pages/ProjectsView.tsx`, `pages/EditorView.tsx`,
`components/PreviewStage.tsx`, `components/MediaLibrary.tsx`,
`components/LyricsColumn.tsx`, `components/Transport.tsx`.
- `App.tsx`: hash routing. `#/` → `<ProjectsView/>`; `#/project/<id>` →
  `<EditorView projectId=.../>`. Listen to `hashchange`.
- `ProjectsView.tsx`: list projects (`api.listProjects`), create (name prompt /
  inline form), open (set hash to `#/project/<id>`), delete (confirm). Card grid,
  dark theme, show analysis_status badge + duration. Title "AI Music Video
  Studio".
- `EditorView.tsx`: on mount `useEditor.loadProject(projectId)`. Layout (dark
  NLE): top bar (project name, back to projects, `<Transport/>`); main area =
  left `<MediaLibrary/>` (~220px) + center `<PreviewStage/>` + right
  `<LyricsColumn/>` (~260px); bottom = `<Timeline/>` (resizable-ish, ~40% height).
  If no song yet → a centered upload dropzone (calls `api.uploadSong`, then poll
  `api.songStatus` every 1s; while processing show stage + progress bar; on done
  `refreshAnalysis()`). Keep polling logic here.
- `PreviewStage.tsx`: black 16:9 stage. Compute `activeVisualClip(tracks,clips,
  currentTime)`. Image → `<img>` cover. Video → a single reused `<video>` muted,
  src = `filesUrl(asset.path)`; target source time = `clip.inPoint +
  (currentTime - clip.start)`; when `playing` ensure `video.play()` and correct
  drift if `|video.currentTime - target| > 0.3`; when paused set
  `video.currentTime = target`. No active visual → show subtle mood palette
  swatches / "no visual under playhead". Overlay the active lyric line near the
  bottom (karaoke style) using `activeLyricIndex`.
- `MediaLibrary.tsx`: upload button (multi-file → `api.uploadMedia` →
  `refreshMedia`), grid of assets (thumb via `filesUrl(thumb_path)`, fallback
  icon for audio), each `draggable` setting
  `e.dataTransfer.setData('application/x-asset-id', asset.id)`. Delete on hover.
  Double-click adds to timeline at playhead (`addClipFromAsset`).
- `LyricsColumn.tsx`: vertical synced lyric list from `analysis.lyrics`.
  Highlight active line (`activeLyricIndex`), auto-scroll it into view as
  `currentTime` advances, click a line → `seek(line.start)`. Header "Lyrics".
  If none → show "No lyrics yet" / processing hint.
- `Transport.tsx`: play/pause (`togglePlay`), stop (`seek(0)`+pause), current
  time / duration (`fmtTime`), a scissor button (`splitAtPlayhead`), delete
  selected (`removeClip(selectedClipId)`), zoom buttons.

## Conventions
- TypeScript strict. Functional components + hooks. No new npm deps beyond
  package.json (react, react-dom, zustand). Tailwind classes for styling; the
  config defines `panel/panel2/panel3/edge/accent/bass/mid/high` colors.
- Keep components performant: subscribe to narrow store slices
  (`useEditor(s => s.currentTime)`), avoid selecting the whole store.
- Return only the files for your task. Do not modify foundation files.

// Editor store — the single source of truth for the timeline editor.
// Holds project/media/analysis + the timeline doc (tracks/clips), drives the
// master audio clock, exposes timeline-editing ops, and debounce-persists.
import { create } from 'zustand';
import { api, filesUrl } from '../api/client';
import type {
  Analysis,
  Clip,
  MediaAsset,
  ProjectFull,
  TimelineDoc,
  Track,
  TrackKind,
} from '../types';

const DEFAULT_IMAGE_DURATION = 4; // seconds for a freshly-dropped image clip
const SONG_TRACK_NAME = 'Music';
const SAVE_DEBOUNCE_MS = 600;

let audioEl: HTMLAudioElement | null = null;
let rafId = 0;
let saveTimer: ReturnType<typeof setTimeout> | null = null;

// undo/redo history of the timeline doc (coalesced per gesture)
let past: TimelineDoc[] = [];
let future: TimelineDoc[] = [];
let histBurst = false;
let histTimer: ReturnType<typeof setTimeout> | null = null;
const HIST_MAX = 120;
const SNAP_PX = 8; // snap distance in pixels

const snapshot = (tracks: Track[], clips: Clip[]): TimelineDoc => ({
  tracks: tracks.map((t) => ({ ...t })),
  clips: clips.map((c) => ({ ...c })),
});

const uid = () => Math.random().toString(36).slice(2, 10);

// ── pure selectors (used by preview / lyrics / ruler) ───────────────────────

/** Topmost video/image clip active at time t (later track in order wins). */
export function activeVisualClip(
  tracks: Track[],
  clips: Clip[],
  t: number,
): { clip: Clip; track: Track } | null {
  // Topmost track wins: tracks render top→bottom in array order, so the FIRST
  // (smallest-index) visual track with an active clip is the one shown.
  for (let order = 0; order < tracks.length; order++) {
    const track = tracks[order];
    if (track.kind !== 'video' && track.kind !== 'image') continue;
    if (track.hidden) continue;
    for (const clip of clips) {
      if (clip.trackId !== track.id) continue;
      if (t >= clip.start && t < clip.start + clip.duration) {
        return { clip, track };
      }
    }
  }
  return null;
}

export function activeLyricIndex(
  lyrics: { start: number; end: number }[] | null,
  t: number,
): number {
  if (!lyrics) return -1;
  for (let i = 0; i < lyrics.length; i++) {
    if (t >= lyrics[i].start && t < lyrics[i].end) return i;
  }
  return -1;
}

export function timelineDuration(clips: Clip[], songDuration: number): number {
  let max = songDuration;
  for (const c of clips) max = Math.max(max, c.start + c.duration);
  return Math.max(max, 1);
}

/** Source media length for trim clamping (null = unbounded, e.g. images). */
function sourceDuration(
  clip: Clip,
  media: MediaAsset[],
  songDuration: number,
): number | null {
  if (clip.source === 'song') return songDuration || null;
  if (clip.assetId) {
    const a = media.find((m) => m.id === clip.assetId);
    if (a && (a.kind === 'video' || a.kind === 'audio')) {
      return a.duration_sec ?? null;
    }
  }
  return null; // image / effect — freely stretchable
}

export interface EditorState {
  projectId: string | null;
  project: ProjectFull | null;
  media: MediaAsset[];
  analysis: Analysis | null;
  tracks: Track[];
  clips: Clip[];

  previewAsset: MediaAsset | null; // source-preview: show a library asset directly
  selectedClipId: string | null;
  selectedClipIds: string[];            // multi-select
  filterWorkspaceClipId: string | null; // effect clip open in the filter workspace
  textEditorClipId: string | null;      // text clip open in the text editor
  rangeIn: number | null;               // loop/export range in
  rangeOut: number | null;              // loop/export range out
  loop: boolean;
  playing: boolean;
  currentTime: number;
  duration: number;
  pixelsPerSecond: number;

  loading: boolean;
  analysisStatus: string; // none|processing|done|error
  analysisStage: string | null;

  // lifecycle
  loadProject: (id: string) => Promise<void>;
  refreshAnalysis: () => Promise<void>;
  reset: () => void;

  // media
  refreshMedia: () => Promise<void>;
  setPreviewAsset: (asset: MediaAsset | null) => void;
  setAspect: (aspect: string) => void;

  snapEnabled: boolean;

  // transport (audio is master clock)
  play: () => void;
  pause: () => void;
  togglePlay: () => void;
  seek: (t: number) => void;
  setZoom: (pps: number) => void;
  toggleSnap: () => void;
  undo: () => void;
  redo: () => void;

  // range / loop
  setRangeIn: () => void;
  setRangeOut: () => void;
  clearRange: () => void;
  toggleLoop: () => void;

  // timeline editing
  select: (clipId: string | null) => void;
  toggleSelect: (clipId: string) => void;
  removeSelected: () => void;
  addTextClip: (text: string, start?: number, duration?: number, position?: 'top' | 'center' | 'bottom') => void;
  updateClipText: (clipId: string, patch: Partial<Clip>) => void;
  openTextEditor: (clipId: string | null) => void;
  addTrack: (kind: TrackKind, name?: string) => Track;
  ensureTrack: (kind: TrackKind) => Track;
  removeTrack: (trackId: string) => void;
  moveTrack: (trackId: string, dir: -1 | 1) => void;
  toggleTrackHidden: (trackId: string) => void;
  addClipFromAsset: (asset: MediaAsset, start?: number, trackId?: string, duration?: number, extra?: Partial<Clip>) => void;
  moveClip: (clipId: string, newStart: number, newTrackId?: string) => void;
  updateClip: (clipId: string, patch: Partial<Clip>) => void;
  trimClip: (clipId: string, edge: 'start' | 'end', newTimelineTime: number) => void;
  splitClipAt: (clipId: string, t: number) => void;
  splitAtPlayhead: () => void;
  removeClip: (clipId: string) => void;

  // effect clips + filter workspace
  addEffectClip: (filterId: string, name: string, start?: number, duration?: number) => void;
  updateClipParams: (clipId: string, params: Record<string, unknown>) => void;
  setClipFilter: (clipId: string, filterId: string, name: string) => void;
  openFilterWorkspace: (clipId: string) => void;
  closeFilterWorkspace: () => void;

  // internal
  _ensureSongClip: () => void;
}

function stopRaf() {
  if (rafId) cancelAnimationFrame(rafId);
  rafId = 0;
}

export const useEditor = create<EditorState>((set, get) => {
  const recomputeDuration = () => {
    const { clips, project } = get();
    const songDur = project?.duration_sec ?? 0;
    set({ duration: timelineDuration(clips, songDur) });
  };

  const scheduleSave = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const { projectId, tracks, clips } = get();
      if (projectId) api.saveTimeline(projectId, { tracks, clips }).catch(() => {});
    }, SAVE_DEBOUNCE_MS);
  };

  /** Snapshot the pre-change timeline once per gesture burst (for undo). */
  const captureHistory = () => {
    if (!histBurst) {
      const { tracks, clips } = get();
      past.push(snapshot(tracks, clips));
      if (past.length > HIST_MAX) past.shift();
      future = [];
      histBurst = true;
    }
    if (histTimer) clearTimeout(histTimer);
    histTimer = setTimeout(() => {
      histBurst = false;
    }, 350);
  };

  /** Apply a timeline mutation: capture history, set state, recompute, persist. */
  const mutate = (next: Partial<EditorState>) => {
    if ('tracks' in next || 'clips' in next) captureHistory();
    set(next);
    recomputeDuration();
    scheduleSave();
  };

  /** Nearest snap target (beats / playhead / clip edges / 0) within threshold. */
  const snapTime = (t: number, excludeClipId?: string): number => {
    if (!get().snapEnabled) return t;
    const { pixelsPerSecond, analysis, clips, currentTime } = get();
    const thresh = SNAP_PX / pixelsPerSecond;
    const targets: number[] = [0, currentTime];
    const b = analysis?.beats;
    if (b) {
      for (const band of [b.bass, b.mid, b.high]) {
        if (band) for (const x of band) targets.push(x);
      }
    }
    for (const c of clips) {
      if (c.id === excludeClipId) continue;
      targets.push(c.start, c.start + c.duration);
    }
    let best = t;
    let bestD = thresh;
    for (const x of targets) {
      const d = Math.abs(x - t);
      if (d < bestD) {
        bestD = d;
        best = x;
      }
    }
    return best;
  };

  const tick = () => {
    if (!audioEl) return;
    const { loop, rangeIn, rangeOut } = get();
    if (loop && rangeIn != null && rangeOut != null &&
        audioEl.currentTime >= rangeOut) {
      audioEl.currentTime = rangeIn;
    }
    set({ currentTime: audioEl.currentTime });
    if (!audioEl.paused) rafId = requestAnimationFrame(tick);
  };

  return {
    projectId: null,
    project: null,
    media: [],
    analysis: null,
    tracks: [],
    clips: [],
    previewAsset: null,
    selectedClipId: null,
    selectedClipIds: [],
    filterWorkspaceClipId: null,
    textEditorClipId: null,
    rangeIn: null,
    rangeOut: null,
    loop: false,
    playing: false,
    currentTime: 0,
    duration: 1,
    pixelsPerSecond: 100,
    snapEnabled: true,
    loading: false,
    analysisStatus: 'none',
    analysisStage: null,

    async loadProject(id) {
      stopRaf();
      audioEl?.pause();
      audioEl = null;
      past = [];
      future = [];
      histBurst = false;
      set({
        loading: true,
        projectId: id,
        currentTime: 0,
        playing: false,
        selectedClipId: null,
        selectedClipIds: [],
        filterWorkspaceClipId: null,
        textEditorClipId: null,
        rangeIn: null,
        rangeOut: null,
        previewAsset: null,
      });
      const project = await api.getProject(id);
      const media = await api.listMedia(id);
      const doc = project.timeline_json ?? { tracks: [], clips: [] };
      const analysis: Analysis = {
        duration: project.duration_sec,
        beats: project.beats_json,
        waveform: project.waveform_json,
        lyrics: project.lyrics_json,
        mood: project.mood_json,
      };

      set({
        project,
        media,
        analysis,
        tracks: doc.tracks ?? [],
        clips: doc.clips ?? [],
        analysisStatus: project.analysis_status,
        analysisStage: project.analysis_stage,
        loading: false,
      });

      if (project.song_wav_path) {
        audioEl = new Audio(filesUrl(project.song_wav_path));
        audioEl.preload = 'auto';
        audioEl.addEventListener('ended', () => {
          stopRaf();
          set({ playing: false });
        });
        get()._ensureSongClip();
      }
      recomputeDuration();
    },

    async refreshAnalysis() {
      const { projectId } = get();
      if (!projectId) return;
      const project = await api.getProject(projectId);
      const analysis: Analysis = {
        duration: project.duration_sec,
        beats: project.beats_json,
        waveform: project.waveform_json,
        lyrics: project.lyrics_json,
        mood: project.mood_json,
      };
      set({
        project,
        analysis,
        analysisStatus: project.analysis_status,
        analysisStage: project.analysis_stage,
      });
      if (project.song_wav_path && !audioEl) {
        audioEl = new Audio(filesUrl(project.song_wav_path));
        audioEl.preload = 'auto';
        audioEl.addEventListener('ended', () => {
          stopRaf();
          set({ playing: false });
        });
      }
      get()._ensureSongClip();
      recomputeDuration();
    },

    reset() {
      stopRaf();
      audioEl?.pause();
      audioEl = null;
      set({
        projectId: null, project: null, media: [], analysis: null,
        tracks: [], clips: [], previewAsset: null, selectedClipId: null,
        filterWorkspaceClipId: null,
        playing: false, currentTime: 0, duration: 1,
        analysisStatus: 'none', analysisStage: null,
      });
    },

    async refreshMedia() {
      const { projectId } = get();
      if (!projectId) return;
      set({ media: await api.listMedia(projectId) });
    },

    setPreviewAsset(asset) {
      if (asset) get().pause(); // entering source-preview pauses timeline playback
      set({ previewAsset: asset });
    },

    setAspect(aspect) {
      const { projectId, project } = get();
      if (!projectId || !project) return;
      set({ project: { ...project, aspect: aspect as ProjectFull['aspect'] } });
      api.setProjectAspect(projectId, aspect).catch(() => {});
    },

    // ── transport ──────────────────────────────────────────────────────
    play() {
      if (!audioEl) return;
      audioEl.play().catch(() => {});
      set({ playing: true, previewAsset: null });
      stopRaf();
      rafId = requestAnimationFrame(tick);
    },
    pause() {
      audioEl?.pause();
      stopRaf();
      set({ playing: false });
    },
    togglePlay() {
      get().playing ? get().pause() : get().play();
    },
    seek(t) {
      const dur = get().duration;
      const clamped = Math.max(0, Math.min(t, dur));
      if (audioEl) audioEl.currentTime = Math.min(clamped, audioEl.duration || clamped);
      set({ currentTime: clamped, previewAsset: null });
    },
    setZoom(pps) {
      set({ pixelsPerSecond: Math.max(10, Math.min(600, pps)) });
    },

    toggleSnap() {
      set({ snapEnabled: !get().snapEnabled });
    },

    undo() {
      if (!past.length) return;
      const { tracks, clips } = get();
      future.push(snapshot(tracks, clips));
      const prev = past.pop()!;
      set({ tracks: prev.tracks, clips: prev.clips, selectedClipId: null });
      recomputeDuration();
      scheduleSave();
    },

    redo() {
      if (!future.length) return;
      const { tracks, clips } = get();
      past.push(snapshot(tracks, clips));
      const next = future.pop()!;
      set({ tracks: next.tracks, clips: next.clips, selectedClipId: null });
      recomputeDuration();
      scheduleSave();
    },

    // ── editing ────────────────────────────────────────────────────────
    select(clipId) {
      set({ selectedClipId: clipId, selectedClipIds: clipId ? [clipId] : [] });
    },

    toggleSelect(clipId) {
      const cur = get().selectedClipIds;
      const next = cur.includes(clipId)
        ? cur.filter((id) => id !== clipId)
        : [...cur, clipId];
      set({ selectedClipIds: next, selectedClipId: next[next.length - 1] ?? null });
    },

    removeSelected() {
      const ids = new Set(get().selectedClipIds);
      if (get().selectedClipId) ids.add(get().selectedClipId!);
      if (!ids.size) return;
      mutate({
        clips: get().clips.filter((c) => !ids.has(c.id)),
        selectedClipId: null,
        selectedClipIds: [],
      });
    },

    addTextClip(text, start, duration, position) {
      const track = get().ensureTrack('text');
      const clip: Clip = {
        id: uid(),
        trackId: track.id,
        assetId: null,
        name: text,
        text,
        textPosition: position ?? 'bottom',
        textColor: '#ffffff',
        textSize: 1,
        textFont: 'sans',
        textBold: true,
        textAnim: 'fade',
        textStroke: 0,
        textStrokeColor: '#000000',
        textShadow: true,
        textBg: false,
        textBgColor: '#000000',
        start: Math.max(0, start ?? get().currentTime),
        duration: duration ?? 3,
        inPoint: 0,
        color: '#3aa0a0',
      };
      mutate({ clips: [...get().clips, clip], selectedClipId: clip.id,
               selectedClipIds: [clip.id] });
      set({ textEditorClipId: clip.id });
    },

    updateClipText(clipId, patch) {
      mutate({
        clips: get().clips.map((c) =>
          c.id === clipId
            ? { ...c, ...patch, name: (patch.text ?? c.text ?? c.name) as string }
            : c,
        ),
      });
    },

    openTextEditor(clipId) {
      set({ textEditorClipId: clipId, selectedClipId: clipId ?? null });
    },

    setRangeIn() {
      const t = get().currentTime;
      const out = get().rangeOut;
      set({ rangeIn: t, rangeOut: out != null && out <= t ? null : out });
    },
    setRangeOut() {
      const t = get().currentTime;
      const inn = get().rangeIn;
      set({ rangeOut: t, rangeIn: inn != null && inn >= t ? null : inn });
    },
    clearRange() {
      set({ rangeIn: null, rangeOut: null });
    },
    toggleLoop() {
      set({ loop: !get().loop });
    },

    addTrack(kind, name) {
      const track: Track = {
        id: uid(),
        kind,
        name: name ?? `${kind[0].toUpperCase()}${kind.slice(1)} ${get().tracks.filter((t) => t.kind === kind).length + 1}`,
      };
      mutate({ tracks: [...get().tracks, track] });
      return track;
    },

    ensureTrack(kind) {
      const existing = get().tracks.find((t) => t.kind === kind);
      if (existing) return existing;
      return get().addTrack(kind);
    },

    removeTrack(trackId) {
      mutate({
        tracks: get().tracks.filter((t) => t.id !== trackId),
        clips: get().clips.filter((c) => c.trackId !== trackId),
      });
    },

    moveTrack(trackId, dir) {
      const tracks = [...get().tracks];
      const i = tracks.findIndex((t) => t.id === trackId);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= tracks.length) return;
      [tracks[i], tracks[j]] = [tracks[j], tracks[i]];
      mutate({ tracks });
    },

    toggleTrackHidden(trackId) {
      mutate({
        tracks: get().tracks.map((t) =>
          t.id === trackId ? { ...t, hidden: !t.hidden } : t,
        ),
      });
    },

    addClipFromAsset(asset, start, trackId, duration, extra) {
      const kind: TrackKind = asset.kind === 'audio' ? 'audio' : asset.kind;
      const track = trackId
        ? get().tracks.find((t) => t.id === trackId)!
        : get().ensureTrack(kind);
      const dur =
        duration ??
        (asset.kind === 'image'
          ? DEFAULT_IMAGE_DURATION
          : asset.duration_sec ?? DEFAULT_IMAGE_DURATION);
      const at = start ?? get().currentTime;
      const clip: Clip = {
        id: uid(),
        trackId: track.id,
        assetId: asset.id,
        name: asset.original_name,
        start: Math.max(0, at),
        duration: dur,
        inPoint: 0,
        ...extra,
      };
      mutate({ clips: [...get().clips, clip], selectedClipId: clip.id });
    },

    moveClip(clipId, newStart, newTrackId) {
      const clip = get().clips.find((c) => c.id === clipId);
      let start = Math.max(0, newStart);
      if (clip) {
        // snap either the start or the end edge, whichever hits a target
        const snapStart = snapTime(start, clipId);
        const snapEnd = snapTime(start + clip.duration, clipId) - clip.duration;
        const startSnapped = snapStart !== start;
        const endSnapped = snapEnd !== start;
        if (startSnapped && endSnapped) {
          start = Math.abs(snapStart - start) <= Math.abs(snapEnd - start)
            ? snapStart : snapEnd;
        } else if (startSnapped) {
          start = snapStart;
        } else if (endSnapped) {
          start = snapEnd;
        }
        start = Math.max(0, start);
      }
      mutate({
        clips: get().clips.map((c) =>
          c.id === clipId
            ? { ...c, start, trackId: newTrackId ?? c.trackId }
            : c,
        ),
      });
    },

    updateClip(clipId, patch) {
      mutate({
        clips: get().clips.map((c) => (c.id === clipId ? { ...c, ...patch } : c)),
      });
    },

    trimClip(clipId, edge, newTimelineTime) {
      const { clips, media, project } = get();
      const songDur = project?.duration_sec ?? 0;
      const clip = clips.find((c) => c.id === clipId);
      if (!clip) return;
      newTimelineTime = snapTime(newTimelineTime, clipId); // snap the dragged edge
      const srcDur = sourceDuration(clip, media, songDur);
      const MIN = 0.05;

      let { start, duration, inPoint } = clip;
      if (edge === 'start') {
        // dragging the left edge: keep the right edge fixed in timeline time
        const rightEdge = clip.start + clip.duration;
        let t = Math.min(Math.max(0, newTimelineTime), rightEdge - MIN);
        const deltaIn = t - clip.start; // +ve trims into the source
        let newIn = clip.inPoint + deltaIn;
        if (newIn < 0) {
          t -= newIn; // can't go before source start
          newIn = 0;
        }
        start = t;
        inPoint = newIn;
        duration = rightEdge - t;
      } else {
        // dragging the right edge
        let newDur = Math.max(MIN, newTimelineTime - clip.start);
        if (srcDur != null) newDur = Math.min(newDur, srcDur - clip.inPoint);
        duration = newDur;
      }
      mutate({
        clips: clips.map((c) =>
          c.id === clipId ? { ...c, start, duration, inPoint } : c,
        ),
      });
    },

    splitClipAt(clipId, t) {
      const { clips } = get();
      const clip = clips.find((c) => c.id === clipId);
      if (!clip) return;
      if (t <= clip.start + 0.02 || t >= clip.start + clip.duration - 0.02) return;
      const leftDur = t - clip.start;
      const left: Clip = { ...clip, duration: leftDur };
      const right: Clip = {
        ...clip,
        id: uid(),
        start: t,
        duration: clip.duration - leftDur,
        inPoint: clip.inPoint + leftDur,
      };
      mutate({
        clips: clips.flatMap((c) => (c.id === clipId ? [left, right] : [c])),
        selectedClipId: right.id,
      });
    },

    splitAtPlayhead() {
      // split only the selected clip (if the playhead is inside it)
      const { clips, currentTime, selectedClipId } = get();
      if (!selectedClipId) return;
      const c = clips.find((cl) => cl.id === selectedClipId);
      if (c && currentTime > c.start && currentTime < c.start + c.duration) {
        get().splitClipAt(c.id, currentTime);
      }
    },

    removeClip(clipId) {
      mutate({
        clips: get().clips.filter((c) => c.id !== clipId),
        selectedClipId: get().selectedClipId === clipId ? null : get().selectedClipId,
      });
    },

    // ── effect clips + filter workspace ─────────────────────────────────
    addEffectClip(filterId, name, start, duration) {
      const track = get().ensureTrack('effect');
      const clip: Clip = {
        id: uid(),
        trackId: track.id,
        assetId: null,
        filterId,
        params: {},
        name,
        start: Math.max(0, start ?? get().currentTime),
        duration: duration ?? 4,
        inPoint: 0,
        color: '#9b6df0',
      };
      mutate({ clips: [...get().clips, clip], selectedClipId: clip.id });
      set({ filterWorkspaceClipId: clip.id });
    },

    updateClipParams(clipId, params) {
      mutate({
        clips: get().clips.map((c) =>
          c.id === clipId ? { ...c, params: { ...(c.params ?? {}), ...params } } : c,
        ),
      });
    },

    setClipFilter(clipId, filterId, name) {
      mutate({
        clips: get().clips.map((c) =>
          c.id === clipId ? { ...c, filterId, name, params: {} } : c,
        ),
      });
    },

    openFilterWorkspace(clipId) {
      set({ filterWorkspaceClipId: clipId, selectedClipId: clipId });
    },

    closeFilterWorkspace() {
      set({ filterWorkspaceClipId: null });
    },

    // ── internal ───────────────────────────────────────────────────────
    _ensureSongClip() {
      const { clips, tracks, project } = get();
      if (!project?.song_wav_path || !project.duration_sec) return;
      if (clips.some((c) => c.source === 'song')) return;
      let track = tracks.find((t) => t.kind === 'audio' && t.name === SONG_TRACK_NAME);
      let nextTracks = tracks;
      if (!track) {
        track = { id: uid(), kind: 'audio', name: SONG_TRACK_NAME };
        nextTracks = [track, ...tracks];
      }
      const songClip: Clip = {
        id: uid(),
        trackId: track.id,
        assetId: null,
        source: 'song',
        name: project.song_original_name ?? 'Song',
        start: 0,
        duration: project.duration_sec,
        inPoint: 0,
        color: '#6d6df0',
      };
      mutate({ tracks: nextTracks, clips: [songClip, ...clips] });
    },
  };
});

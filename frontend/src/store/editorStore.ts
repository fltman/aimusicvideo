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
  Track,
  TrackKind,
} from '../types';

const DEFAULT_IMAGE_DURATION = 4; // seconds for a freshly-dropped image clip
const SONG_TRACK_NAME = 'Music';
const SAVE_DEBOUNCE_MS = 600;

let audioEl: HTMLAudioElement | null = null;
let rafId = 0;
let saveTimer: ReturnType<typeof setTimeout> | null = null;

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
  filterWorkspaceClipId: string | null; // effect clip open in the filter workspace
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

  // transport (audio is master clock)
  play: () => void;
  pause: () => void;
  togglePlay: () => void;
  seek: (t: number) => void;
  setZoom: (pps: number) => void;

  // timeline editing
  select: (clipId: string | null) => void;
  addTrack: (kind: TrackKind, name?: string) => Track;
  ensureTrack: (kind: TrackKind) => Track;
  removeTrack: (trackId: string) => void;
  moveTrack: (trackId: string, dir: -1 | 1) => void;
  toggleTrackHidden: (trackId: string) => void;
  addClipFromAsset: (asset: MediaAsset, start?: number, trackId?: string) => void;
  moveClip: (clipId: string, newStart: number, newTrackId?: string) => void;
  updateClip: (clipId: string, patch: Partial<Clip>) => void;
  trimClip: (clipId: string, edge: 'start' | 'end', newTimelineTime: number) => void;
  splitClipAt: (clipId: string, t: number) => void;
  splitAtPlayhead: () => void;
  removeClip: (clipId: string) => void;

  // effect clips + filter workspace
  addEffectClip: (filterId: string, name: string) => void;
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

  /** Apply a timeline mutation: set state, recompute duration, persist. */
  const mutate = (next: Partial<EditorState>) => {
    set(next);
    recomputeDuration();
    scheduleSave();
  };

  const tick = () => {
    if (!audioEl) return;
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
    filterWorkspaceClipId: null,
    playing: false,
    currentTime: 0,
    duration: 1,
    pixelsPerSecond: 100,
    loading: false,
    analysisStatus: 'none',
    analysisStage: null,

    async loadProject(id) {
      stopRaf();
      audioEl?.pause();
      audioEl = null;
      set({
        loading: true,
        projectId: id,
        currentTime: 0,
        playing: false,
        selectedClipId: null,
        filterWorkspaceClipId: null,
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

    // ── editing ────────────────────────────────────────────────────────
    select(clipId) {
      set({ selectedClipId: clipId });
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

    addClipFromAsset(asset, start, trackId) {
      const kind: TrackKind = asset.kind === 'audio' ? 'audio' : asset.kind;
      const track = trackId
        ? get().tracks.find((t) => t.id === trackId)!
        : get().ensureTrack(kind);
      const dur =
        asset.kind === 'image'
          ? DEFAULT_IMAGE_DURATION
          : asset.duration_sec ?? DEFAULT_IMAGE_DURATION;
      const at = start ?? get().currentTime;
      const clip: Clip = {
        id: uid(),
        trackId: track.id,
        assetId: asset.id,
        name: asset.original_name,
        start: Math.max(0, at),
        duration: dur,
        inPoint: 0,
      };
      mutate({ clips: [...get().clips, clip], selectedClipId: clip.id });
    },

    moveClip(clipId, newStart, newTrackId) {
      mutate({
        clips: get().clips.map((c) =>
          c.id === clipId
            ? { ...c, start: Math.max(0, newStart), trackId: newTrackId ?? c.trackId }
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
    addEffectClip(filterId, name) {
      const track = get().ensureTrack('effect');
      const clip: Clip = {
        id: uid(),
        trackId: track.id,
        assetId: null,
        filterId,
        params: {},
        name,
        start: Math.max(0, get().currentTime),
        duration: 4,
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

// Typed API client. Dev server proxies /api and /files to the backend (8100),
// so URLs are relative.
import type {
  Analysis,
  AnimateStart,
  ChatMessage,
  ChatResponse,
  FilterChatMsg,
  FilterChatResult,
  FilterDetail,
  FilterManifest,
  GenJob,
  MediaAsset,
  ProjectFull,
  ProjectSummary,
  SongStatus,
  TimelineDoc,
} from '../types';

const API = '/api';

/** Build a loadable URL for a stored asset given its db `path`. */
export function filesUrl(path: string): string {
  return `/files/${path}`;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

export const api = {
  // ── projects ──────────────────────────────────────────────────────────
  listProjects: () => req<ProjectSummary[]>(`${API}/projects`),
  createProject: (name: string) =>
    req<ProjectFull>(`${API}/projects`, json('POST', { name })),
  getProject: (id: string) => req<ProjectFull>(`${API}/projects/${id}`),
  updateProject: (id: string, name: string) =>
    req<ProjectFull>(`${API}/projects/${id}`, json('PATCH', { name })),
  setProjectAspect: (id: string, aspect: string) =>
    req<ProjectFull>(`${API}/projects/${id}`, json('PATCH', { aspect })),
  deleteProject: (id: string) =>
    req<void>(`${API}/projects/${id}`, { method: 'DELETE' }),

  // ── song upload + analysis ────────────────────────────────────────────
  uploadSong: (id: string, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return req<SongStatus>(`${API}/projects/${id}/song`, {
      method: 'POST',
      body: fd,
    });
  },
  songStatus: (id: string) =>
    req<SongStatus>(`${API}/projects/${id}/song/status`),
  getAnalysis: (id: string) => req<Analysis>(`${API}/projects/${id}/analysis`),

  // ── media library ─────────────────────────────────────────────────────
  listMedia: (id: string) => req<MediaAsset[]>(`${API}/projects/${id}/media`),
  uploadMedia: (id: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append('files', f));
    return req<MediaAsset[]>(`${API}/projects/${id}/media`, {
      method: 'POST',
      body: fd,
    });
  },
  updateMedia: (
    id: string,
    assetId: string,
    patch: { label?: string | null; tags?: string[] },
  ) =>
    req<MediaAsset>(
      `${API}/projects/${id}/media/${assetId}`,
      json('PATCH', patch),
    ),
  deleteMedia: (id: string, assetId: string) =>
    req<void>(`${API}/projects/${id}/media/${assetId}`, { method: 'DELETE' }),

  // ── image → video (seedance) ──────────────────────────────────────────
  animateImage: (
    id: string,
    assetId: string,
    body: { prompt?: string; duration?: number },
  ) =>
    req<AnimateStart>(
      `${API}/projects/${id}/media/${assetId}/animate`,
      json('POST', body),
    ),

  // ── AI auto-director ──────────────────────────────────────────────────
  autoDirect: (id: string, maxShots: number) =>
    req<{
      shots: number;
      concept?: string;
      plan: unknown[];
      texts?: { text: string; at: number; duration: number; position: 'top' | 'center' | 'bottom' }[];
      effects?: {
        filter_id: string;
        name: string;
        at: number;
        duration: number;
        params?: Record<string, unknown>;
      }[];
      interlude_clips?: {
        filterId: string;
        name: string;
        params?: Record<string, unknown>;
        start: number;
        duration: number;
      }[];
      new_filters?: { fid: string; name: string }[];
      generate_count?: number;
      reuse_count?: number;
      narrative?: {
        logline?: string;
        theme?: string;
        characters?: { id: string; name: string }[];
        settings?: { id: string; name: string }[];
      };
    }>(`${API}/projects/${id}/auto-direct`, json('POST', { max_shots: maxShots })),

  varyImage: (id: string, assetId: string) =>
    req<{ job_id: string }>(
      `${API}/projects/${id}/media/${assetId}/vary`,
      { method: 'POST' },
    ),

  // ── generation queue ──────────────────────────────────────────────────
  listQueue: (id: string) => req<GenJob[]>(`${API}/projects/${id}/queue`),
  jobStatus: (jobId: string) => req<GenJob>(`${API}/job/${jobId}`),

  // ── filter plugins ────────────────────────────────────────────────────
  listFilters: () => req<FilterManifest[]>(`${API}/filters`),
  createFilter: (name: string) =>
    req<FilterDetail>(`${API}/filters`, json('POST', { name })),
  getFilter: (id: string) => req<FilterDetail>(`${API}/filters/${id}`),
  forkFilter: (id: string, name: string) =>
    req<FilterDetail>(`${API}/filters/${id}/fork`, json('POST', { name })),
  renameFilter: (id: string, name: string) =>
    req<FilterDetail>(`${API}/filters/${id}`, json('PATCH', { name })),
  saveFilter: (id: string, code: string, message: string) =>
    req<FilterDetail>(`${API}/filters/${id}/save`, json('POST', { code, message })),
  rollbackFilter: (id: string, version: number) =>
    req<FilterDetail>(`${API}/filters/${id}/rollback`, json('POST', { version })),
  deleteFilter: (id: string) =>
    req<void>(`${API}/filters/${id}`, { method: 'DELETE' }),
  saveFilterPreset: (id: string, name: string, params: Record<string, unknown>) =>
    req<FilterDetail>(`${API}/filters/${id}/presets`, json('POST', { name, params })),
  getFilterChat: (id: string) => req<FilterChatMsg[]>(`${API}/filters/${id}/chat`),
  filterChat: (id: string, message: string, previewUrl?: string | null) =>
    req<FilterChatResult>(
      `${API}/filters/${id}/chat`,
      json('POST', { message, preview_url: previewUrl ?? null }),
    ),
  renderFilterPreview: (
    pid: string,
    filterId: string,
    params: Record<string, unknown>,
    cursorTime: number,
    fast?: boolean,
  ) =>
    req<{ job_id: string }>(
      `${API}/projects/${pid}/filter-preview`,
      json('POST', {
        filter_id: filterId,
        params,
        cursor_time: cursorTime,
        fast: !!fast,
      }),
    ),

  // ── export ────────────────────────────────────────────────────────────
  exportVideo: (
    pid: string,
    resolution: string,
    burnLyrics: boolean,
    rangeStart?: number | null,
    rangeEnd?: number | null,
  ) =>
    req<{ job_id: string; export_id: string }>(
      `${API}/projects/${pid}/export`,
      json('POST', {
        resolution,
        burn_lyrics: burnLyrics,
        range_start: rangeStart ?? null,
        range_end: rangeEnd ?? null,
      }),
    ),
  exportProgress: (pid: string, exportId: string) =>
    req<{ progress: number }>(`${API}/projects/${pid}/export-progress/${exportId}`),

  // ── creative-director chat ────────────────────────────────────────────
  chat: (id: string, messages: ChatMessage[], cursorTime: number) =>
    req<ChatResponse>(
      `${API}/projects/${id}/chat`,
      json('POST', { messages, cursor_time: cursorTime }),
    ),

  // ── timeline ──────────────────────────────────────────────────────────
  getTimeline: (id: string) => req<TimelineDoc>(`${API}/projects/${id}/timeline`),
  saveTimeline: (id: string, doc: TimelineDoc) =>
    req<void>(`${API}/projects/${id}/timeline`, json('PUT', doc)),
};

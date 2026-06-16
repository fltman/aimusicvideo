// Typed API client. Dev server proxies /api and /files to the backend (8100),
// so URLs are relative.
import type {
  Analysis,
  AnimateStart,
  ChatMessage,
  ChatResponse,
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

  // ── generation queue ──────────────────────────────────────────────────
  listQueue: (id: string) => req<GenJob[]>(`${API}/projects/${id}/queue`),

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

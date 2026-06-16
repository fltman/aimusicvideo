// Shared types — mirror backend/app/models.py and db.py schema.

export type TrackKind = 'audio' | 'video' | 'image' | 'effect' | 'text';
export type MediaKind = 'image' | 'video' | 'audio';
export type AnalysisStatus = 'none' | 'processing' | 'done' | 'error';

export interface ProjectSummary {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  duration_sec: number | null;
  analysis_status: AnalysisStatus;
  analysis_progress: number;
  has_song: number; // sqlite boolean (0/1)
  thumb?: string | null;     // preview: latest image/video thumb (rel path)
  palette?: string[] | null; // mood palette fallback
}

export interface MediaAsset {
  id: string;
  project_id: string;
  kind: MediaKind;
  original_name: string;
  path: string;          // relative under data/, load via filesUrl(path)
  thumb_path: string | null;
  duration_sec: number | null;
  width: number | null;
  height: number | null;
  label: string | null;   // user-given name, e.g. "Kevin"
  tags: string[];         // e.g. ["character"], ["scene"]
  created_at: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface QueuedRef {
  id: string;
  kind: string;
  label: string;
}

export interface ChatAction {
  type: 'add_text' | 'apply_effect';
  text?: string;
  at?: number;
  duration?: number;
  position?: 'top' | 'center' | 'bottom';
  filter_id?: string;
  name?: string;
}

export interface ChatResponse {
  reply: string;
  image_prompt: string | null;
  queued: QueuedRef[];
  actions: ChatAction[];
}

export interface AnimateStart {
  job_id: string;
  status: string;
}

export type GenStatus = 'pending' | 'running' | 'done' | 'error';

export interface GenJob {
  id: string;
  project_id: string;
  kind: 'image' | 'video';
  label: string;
  status: GenStatus;
  asset: MediaAsset | null;
  error: string | null;
  insert_at: number | null;
  insert_duration: number | null;
  insert_meta?: Record<string, unknown> | null;
  seq: number;
}

export interface Beats {
  bass: number[];
  mid: number[];
  high: number[];
}

export interface Waveform {
  peaks: [number, number][]; // [min, max] per bucket
  pps: number;               // buckets per second
}

export interface LyricLine {
  start: number;
  end: number;
  text: string;
}

export interface Mood {
  mood?: string;
  genres?: string[];
  energy?: number;          // 0..1
  tempo_bpm?: number;
  palette?: string[];       // hex colors
  keywords?: string[];
  visual_suggestions?: string[];
  [k: string]: unknown;
}

export interface Analysis {
  duration: number | null;
  beats: Beats | null;
  waveform: Waveform | null;
  lyrics: LyricLine[] | null;
  mood: Mood | null;
}

export interface SongStatus {
  status: AnalysisStatus;
  progress: number;
  stage: string | null;
  error: string | null;
}

// ── timeline doc ──────────────────────────────────────────────────────────
export interface Track {
  id: string;
  kind: TrackKind;
  name: string;
  hidden?: boolean; // excluded from the preview; lane dimmed
}

export interface Clip {
  id: string;
  trackId: string;
  assetId: string | null;
  name: string;
  start: number;      // timeline position (seconds)
  duration: number;   // length on the timeline (seconds)
  inPoint: number;    // offset into source media (seconds)
  color?: string;
  motion?: 'zoom-in' | 'zoom-out' | 'pan-left' | 'pan-right' | 'pan-up' | 'pan-down' | 'none';
  filterId?: string;                       // effect clips: the filter plugin
  params?: Record<string, unknown>;        // effect clips: param values
  text?: string;                           // text clips: the overlay text
  textPosition?: 'top' | 'center' | 'bottom';
  textColor?: string;
  textSize?: number;                       // relative font size (1 = default)
  textFont?: 'sans' | 'serif' | 'mono' | 'display' | 'elegant';
  textBold?: boolean;
  textAnim?: 'none' | 'fade' | 'typewriter' | 'slide';
  textStroke?: number;                     // border/outline width (0 = none)
  textStrokeColor?: string;
  textShadow?: boolean;
  textBg?: boolean;
  textBgColor?: string;
  [k: string]: unknown;
}

// ── filter plugins ──────────────────────────────────────────────────────────
export type FilterParamType = 'slider' | 'knob' | 'switch' | 'select';

export interface FilterParam {
  key: string;
  type: FilterParamType;
  label: string;
  min?: number;
  max?: number;
  step?: number;
  default: unknown;
  options?: string[];
}

export interface FilterManifest {
  id: string;
  name: string;
  description: string;
  version: number;
  builtin?: boolean;
  template?: boolean;
  forkedFrom?: string;
  tags?: string[];
  param_count?: number;
}

export interface FilterVersion {
  version: number;
  message: string;
  ts: string;
}

export interface FilterPreset {
  name: string;
  params: Record<string, unknown>;
}

export interface FilterDetail {
  manifest: FilterManifest;
  code: string;
  params: FilterParam[];
  versions: FilterVersion[];
  presets?: FilterPreset[];
}

export interface FilterChatMsg {
  role: 'user' | 'assistant';
  content: string;
}

export interface FilterChatResult {
  reply: string;
  version: number | null;
  code?: string;
  params?: FilterParam[];
  error?: string;
}

export interface TimelineDoc {
  tracks: Track[];
  clips: Clip[];
}

export type Aspect = '16:9' | '9:16' | '1:1';

export interface ProjectFull extends ProjectSummary {
  aspect?: Aspect;
  song_original_name: string | null;
  song_wav_path: string | null;
  analysis_stage: string | null;
  analysis_error: string | null;
  beats_json: Beats | null;
  waveform_json: Waveform | null;
  lyrics_json: LyricLine[] | null;
  mood_json: Mood | null;
  timeline_json: TimelineDoc | null;
}

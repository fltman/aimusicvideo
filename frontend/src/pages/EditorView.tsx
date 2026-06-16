import { useCallback, useEffect, useRef, useState } from 'react';
import { useEditor } from '../store/editorStore';
import { api } from '../api/client';
import type { GenJob, SongStatus } from '../types';
import Transport from '../components/Transport';
import MediaLibrary from '../components/MediaLibrary';
import PreviewStage from '../components/PreviewStage';
import RightPanel from '../components/RightPanel';
import ChatDock from '../components/ChatDock';
import GenerationQueue from '../components/GenerationQueue';
import AutoDirectButton from '../components/AutoDirectButton';
import ExportButton from '../components/ExportButton';
import ResizeHandle from '../components/ResizeHandle';
import FilterWorkspace from '../components/FilterWorkspace';
import Timeline from '../components/timeline/Timeline';

const clamp = (v: number, min: number, max: number) =>
  Math.max(min, Math.min(max, v));

/** Number state persisted to localStorage (panel sizes survive reload). */
function usePersistentNum(key: string, def: number) {
  const [v, setV] = useState(() => {
    const s = localStorage.getItem(key);
    const n = s ? Number(s) : NaN;
    return Number.isFinite(n) ? n : def;
  });
  useEffect(() => {
    localStorage.setItem(key, String(v));
  }, [key, v]);
  return [v, setV] as const;
}

export default function EditorView({ projectId }: { projectId: string }) {
  const loadProject = useEditor((s) => s.loadProject);
  const refreshAnalysis = useEditor((s) => s.refreshAnalysis);
  const refreshMedia = useEditor((s) => s.refreshMedia);
  const addClipFromAsset = useEditor((s) => s.addClipFromAsset);
  const togglePlay = useEditor((s) => s.togglePlay);

  const project = useEditor((s) => s.project);
  const loading = useEditor((s) => s.loading);
  const analysisStatus = useEditor((s) => s.analysisStatus);

  const [songStatus, setSongStatus] = useState<SongStatus | null>(null);
  const [genJobs, setGenJobs] = useState<GenJob[]>([]);
  const handledJobs = useRef<Set<string>>(new Set());
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  // resizable panel sizes (persisted)
  const [libW, setLibW] = usePersistentNum('amv.libW', 220);
  const [rightW, setRightW] = usePersistentNum('amv.rightW', 300);
  const [timelineH, setTimelineH] = usePersistentNum('amv.timelineH', 320);

  // Load the project once on mount.
  useEffect(() => {
    loadProject(projectId);
  }, [projectId, loadProject]);

  const hasSong = !!project?.song_wav_path || analysisStatus === 'done';
  const isProcessing =
    analysisStatus === 'processing' || songStatus?.status === 'processing';

  // Poll song status while processing; refresh analysis when done.
  useEffect(() => {
    if (!isProcessing) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const st = await api.songStatus(projectId);
        if (cancelled) return;
        setSongStatus(st);
        if (st.status === 'done') {
          await refreshAnalysis();
        } else if (st.status === 'error') {
          await refreshAnalysis();
        }
      } catch {
        /* keep polling */
      }
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [isProcessing, projectId, refreshAnalysis]);

  // Poll the generation queue; when a job finishes, refresh media and drop the
  // produced asset onto the timeline at the position it was requested for.
  useEffect(() => {
    if (!hasSong) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const jobs = await api.listQueue(projectId);
        if (cancelled) return;
        setGenJobs(jobs);
        for (const job of jobs) {
          if (handledJobs.current.has(job.id)) continue;
          if (job.status === 'done') {
            handledJobs.current.add(job.id);
            await refreshMedia();
            if (job.asset && job.insert_at != null) {
              addClipFromAsset(
                job.asset,
                job.insert_at,
                undefined,
                job.insert_duration ?? undefined,
              );
            }
          } else if (job.status === 'error') {
            handledJobs.current.add(job.id);
          }
        }
      } catch {
        /* keep polling */
      }
    };
    tick();
    const timer = setInterval(tick, 2500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [hasSong, projectId, refreshMedia, addClipFromAsset]);

  // Keyboard: space = play/pause, Delete/Backspace = remove selected clip
  // (ignored while typing in a field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      if ((e.metaKey || e.ctrlKey) && (e.key === 'z' || e.key === 'Z')) {
        e.preventDefault();
        if (e.shiftKey) useEditor.getState().redo();
        else useEditor.getState().undo();
        return;
      }
      if (e.code === 'Space') {
        e.preventDefault();
        togglePlay();
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (useEditor.getState().selectedClipIds.length) {
          e.preventDefault();
          useEditor.getState().removeSelected();
        }
      } else if (e.key === 'i' || e.key === 'I') {
        useEditor.getState().setRangeIn();
      } else if (e.key === 'o' || e.key === 'O') {
        useEditor.getState().setRangeOut();
      } else if (e.key === 'l' || e.key === 'L') {
        useEditor.getState().toggleLoop();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [togglePlay]);

  const uploadSong = useCallback(
    async (file: File) => {
      setUploading(true);
      try {
        const st = await api.uploadSong(projectId, file);
        setSongStatus(st);
      } finally {
        setUploading(false);
      }
    },
    [projectId],
  );

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadSong(file);
  };

  const back = () => {
    window.location.hash = '#/';
  };

  return (
    <div className="flex h-full flex-col bg-[#0f1014]">
      {/* Top bar */}
      <header className="flex items-center gap-4 border-b border-edge bg-panel px-4 py-2">
        <button
          onClick={back}
          className="rounded-md px-2 py-1 text-sm text-white/60 hover:bg-panel3 hover:text-white"
          title="Back to projects"
        >
          ← Projects
        </button>
        <div className="h-5 w-px bg-edge" />
        <h1 className="truncate text-sm font-medium">
          {project?.name ?? (loading ? 'Loading…' : 'Project')}
        </h1>
        <div className="ml-auto flex items-center gap-3">
          <GenerationQueue jobs={genJobs} />
          <AutoDirectButton />
          <ExportButton />
          <Transport />
        </div>
      </header>

      {/* Main area */}
      {!hasSong ? (
        <div className="flex flex-1 items-center justify-center p-8">
          {isProcessing ? (
            <div className="w-full max-w-md rounded-xl border border-edge bg-panel2 p-8 text-center">
              <div className="mb-4 text-3xl">🎶</div>
              <p className="mb-1 font-medium">Analyzing your song…</p>
              <p className="mb-4 text-sm text-white/50">
                {songStatus?.stage ?? 'queued'}
              </p>
              <div className="h-2 overflow-hidden rounded-full bg-panel3">
                <div
                  className="h-full rounded-full bg-accent transition-all"
                  style={{
                    width: `${Math.round((songStatus?.progress ?? 0) * 100)}%`,
                  }}
                />
              </div>
              <p className="mt-2 text-xs text-white/40">
                {Math.round((songStatus?.progress ?? 0) * 100)}%
              </p>
            </div>
          ) : (
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileInput.current?.click()}
              className={[
                'flex w-full max-w-xl cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-16 text-center transition-colors',
                dragOver
                  ? 'border-accent bg-accent/10'
                  : 'border-edge bg-panel2 hover:border-accent/60 hover:bg-panel3',
              ].join(' ')}
            >
              <div className="mb-4 text-4xl">🎵</div>
              <p className="mb-1 text-lg font-medium">
                {uploading ? 'Uploading…' : 'Drop a song to begin'}
              </p>
              <p className="text-sm text-white/40">
                or click to choose an audio file. We’ll analyze beats, waveform and
                lyrics.
              </p>
              <input
                ref={fileInput}
                type="file"
                accept="audio/*,video/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadSong(f);
                  e.target.value = '';
                }}
              />
            </div>
          )}
        </div>
      ) : (
        <>
          {/* Upper: library | preview | right panel (all resizable) */}
          <div className="flex min-h-0 flex-1">
            <div style={{ width: libW }} className="shrink-0 overflow-hidden">
              <MediaLibrary className="h-full" />
            </div>
            <ResizeHandle
              orientation="vertical"
              onResize={(dx) => setLibW((w) => clamp(w + dx, 160, 520))}
            />
            <PreviewStage className="min-w-0 flex-1" />
            <ResizeHandle
              orientation="vertical"
              onResize={(dx) => setRightW((w) => clamp(w - dx, 200, 560))}
            />
            <div style={{ width: rightW }} className="shrink-0 overflow-hidden">
              <RightPanel className="h-full" />
            </div>
          </div>

          {/* resizable divider + timeline */}
          <ResizeHandle
            orientation="horizontal"
            onResize={(dy) =>
              setTimelineH((h) => clamp(h - dy, 160, window.innerHeight - 220))
            }
          />
          <div
            style={{ height: timelineH }}
            className="shrink-0 overflow-hidden bg-panel"
          >
            <Timeline />
          </div>

          {/* Floating director chat */}
          <ChatDock />

          {/* Full-screen filter workspace (self-gates on filterWorkspaceClipId) */}
          <FilterWorkspace />
        </>
      )}
    </div>
  );
}

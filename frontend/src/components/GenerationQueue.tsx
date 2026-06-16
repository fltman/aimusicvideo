import { useState } from 'react';
import type { GenJob, GenStatus } from '../types';

const STATUS: Record<GenStatus, { dot: string; label: string }> = {
  pending: { dot: 'bg-white/40', label: 'queued' },
  running: { dot: 'bg-accent animate-pulse', label: 'generating' },
  done: { dot: 'bg-high', label: 'done' },
  error: { dot: 'bg-bass', label: 'failed' },
};

/** Top-bar generation-queue indicator with an expandable job list. */
export default function GenerationQueue({ jobs }: { jobs: GenJob[] }) {
  const [open, setOpen] = useState(false);
  if (jobs.length === 0) return null;

  const active = jobs.filter(
    (j) => j.status === 'pending' || j.status === 'running',
  );

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-md bg-panel3 px-2.5 py-1.5 text-xs text-white/80 hover:bg-edge"
        title="Generation queue (max 3 at a time)"
      >
        {active.length > 0 ? (
          <>
            <span className="h-2 w-2 rounded-full bg-accent animate-pulse" />
            {active.length} generating
          </>
        ) : (
          <>
            <span className="h-2 w-2 rounded-full bg-high" />
            generations
          </>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 max-h-80 w-72 overflow-y-auto rounded-lg border border-edge bg-panel2 p-1.5 shadow-xl shadow-black/50">
          <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-white/35">
            Generations · max 3 parallel
          </div>
          {jobs.slice(0, 12).map((j) => (
            <div
              key={j.id}
              className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-panel3"
              title={j.error ?? j.label}
            >
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${STATUS[j.status].dot}`}
              />
              <span className="text-sm">{j.kind === 'video' ? '🎬' : '🖼'}</span>
              <span className="min-w-0 flex-1 truncate text-white/80">
                {j.label}
              </span>
              <span
                className={`shrink-0 ${j.status === 'error' ? 'text-bass' : 'text-white/40'}`}
              >
                {STATUS[j.status].label}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

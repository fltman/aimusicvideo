import { useState } from 'react';
import { useEditor } from '../store/editorStore';
import { api } from '../api/client';

/** One-click draft: generate shot images from the song and auto-place them. */
export default function AutoDirectButton() {
  const projectId = useEditor((s) => s.projectId);
  const analysisStatus = useEditor((s) => s.analysisStatus);
  const addTextClip = useEditor((s) => s.addTextClip);
  const addEffectClip = useEditor((s) => s.addEffectClip);

  const [open, setOpen] = useState(false);
  const [maxShots, setMaxShots] = useState(10);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ready = analysisStatus === 'done';

  const run = async () => {
    if (!projectId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.autoDirect(projectId, maxShots);
      // apply the title card + beat-synced effects now; shot images auto-place
      // as the generation queue completes.
      for (const t of res.texts ?? []) {
        addTextClip(t.text, t.at, t.duration, t.position);
      }
      for (const e of res.effects ?? []) {
        addEffectClip(e.filter_id, e.name, e.at, e.duration);
      }
      // adding clips auto-opens their editors — close them after auto-direct
      useEditor.getState().closeFilterWorkspace();
      useEditor.getState().openTextEditor(null);
      setDone(res.shots);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={!ready}
        className="flex items-center gap-1.5 rounded-md bg-gradient-to-r from-accent to-high px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
        title={ready ? 'Auto-generate a draft music video' : 'Analyze a song first'}
      >
        ✨ Auto-direct
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-72 rounded-lg border border-edge bg-panel2 p-3 shadow-xl shadow-black/50">
          <div className="mb-1 text-[10px] uppercase tracking-wider text-white/40">
            Auto-direct a draft
          </div>
          <p className="mb-3 text-[11px] leading-relaxed text-white/50">
            Generates one shot image per section (from the mood + lyrics) and
            drops them onto the timeline, beat-aligned. Refine afterwards.
          </p>
          <div className="mb-1 flex items-center justify-between text-xs text-white/60">
            <span>Shots</span>
            <span className="tabular-nums text-white">{maxShots}</span>
          </div>
          <input
            type="range"
            min={3}
            max={16}
            value={maxShots}
            onChange={(e) => setMaxShots(Number(e.target.value))}
            disabled={busy}
            className="mb-2 w-full accent-accent"
          />
          <p className="mb-3 text-[10px] text-white/35">
            Queues {maxShots} image generations (≈ ${(maxShots * 0.04).toFixed(2)}).
            Watch the generation queue.
          </p>
          {done != null ? (
            <p className="rounded bg-high/15 py-2 text-center text-sm text-high">
              ✓ Queued {done} shots — they'll land on the timeline.
            </p>
          ) : (
            <button
              onClick={run}
              disabled={busy}
              className="w-full rounded bg-accent py-2 text-sm font-medium text-white hover:bg-accent/80 disabled:opacity-50"
            >
              {busy ? 'Planning…' : 'Generate draft'}
            </button>
          )}
          {error && <p className="mt-2 text-[11px] text-bass">{error}</p>}
        </div>
      )}
    </div>
  );
}

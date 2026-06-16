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
  const [result, setResult] = useState<{
    concept?: string;
    generate: number;
    reuse: number;
    filters: number;
    characters: string[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ready = analysisStatus === 'done';

  const run = async () => {
    if (!projectId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.autoDirect(projectId, maxShots);
      // Apply the title card, beat-synced effects and graphic interludes now;
      // the shot images (and any reused library assets) auto-place onto the
      // timeline as the generation queue completes. focus=false so the many
      // effect adds don't flash the filter workspace open.
      for (const t of res.texts ?? []) {
        addTextClip(t.text, t.at, t.duration, t.position);
      }
      for (const e of res.effects ?? []) {
        addEffectClip(e.filter_id, e.name, e.at, e.duration, e.params, false);
      }
      for (const c of res.interlude_clips ?? []) {
        addEffectClip(c.filterId, c.name, c.start, c.duration, c.params, false);
      }
      // adding clips can open their editors — close them after auto-direct
      useEditor.getState().closeFilterWorkspace();
      useEditor.getState().openTextEditor(null);
      setResult({
        concept: res.concept,
        generate: res.generate_count ?? res.shots,
        reuse: res.reuse_count ?? 0,
        filters: res.new_filters?.length ?? 0,
        characters: (res.narrative?.characters ?? []).map((c) => c.name),
      });
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
            Reads the song as a <span className="text-white/70">story</span>, boards
            it into beat-timed shots with recurring characters, reuses matching
            library images, generates the rest (kept consistent), and lays
            beat-synced effects. A fully editable draft.
          </p>
          <div className="mb-1 flex items-center justify-between text-xs text-white/60">
            <span>Max shots</span>
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
            Up to {maxShots} shots; only new ones are generated. Planning takes a
            few seconds, then images land via the queue.
          </p>
          {result ? (
            <div className="rounded bg-high/10 p-2 text-[11px] text-high/90">
              {result.concept && (
                <p className="mb-1.5 italic leading-snug text-high/80">
                  “{result.concept}”
                </p>
              )}
              <p>
                ✓ {result.generate} shot{result.generate === 1 ? '' : 's'} generating
                {result.reuse > 0 && `, ${result.reuse} reused`}
                {result.filters > 0 && `, ${result.filters} custom filter authored`}.
              </p>
              {result.characters.length > 0 && (
                <p className="mt-1 text-high/60">
                  Cast: {result.characters.join(', ')}
                </p>
              )}
              <button
                onClick={() => setResult(null)}
                className="mt-2 w-full rounded bg-accent/80 py-1 text-xs font-medium text-white hover:bg-accent"
              >
                Direct again
              </button>
            </div>
          ) : (
            <button
              onClick={run}
              disabled={busy}
              className="w-full rounded bg-accent py-2 text-sm font-medium text-white hover:bg-accent/80 disabled:opacity-50"
            >
              {busy ? 'Writing the story…' : 'Generate draft'}
            </button>
          )}
          {error && <p className="mt-2 text-[11px] text-bass">{error}</p>}
        </div>
      )}
    </div>
  );
}

import { useEditor } from '../store/editorStore';

/** Small section heading. */
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-white/40">
      {children}
    </h3>
  );
}

function Chips({ items, tone = 'default' }: { items: string[]; tone?: 'default' | 'accent' }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it, i) => (
        <span
          key={i}
          className={[
            'rounded-full px-2.5 py-1 text-xs',
            tone === 'accent'
              ? 'bg-accent/15 text-accent ring-1 ring-accent/30'
              : 'bg-panel3 text-white/70',
          ].join(' ')}
        >
          {it}
        </span>
      ))}
    </div>
  );
}

/** Gemini music analysis: mood, music style, visual mood. */
export default function AnalysisPanel({ className = '' }: { className?: string }) {
  const mood = useEditor((s) => s.analysis?.mood ?? null);
  const analysisStatus = useEditor((s) => s.analysisStatus);

  if (!mood || (!mood.mood && !mood.genres?.length && !mood.palette?.length)) {
    return (
      <div className={`flex h-full items-start justify-center bg-panel ${className}`}>
        <p className="px-4 pt-8 text-center text-xs text-white/30">
          {analysisStatus === 'processing'
            ? 'Analyzing mood & style…'
            : 'No analysis yet.'}
        </p>
      </div>
    );
  }

  const energy = typeof mood.energy === 'number' ? Math.max(0, Math.min(1, mood.energy)) : null;
  const palette = mood.palette ?? [];
  const keywords = mood.keywords ?? [];
  const genres = mood.genres ?? [];
  const suggestions = mood.visual_suggestions ?? [];

  return (
    <div className={`h-full overflow-y-auto bg-panel px-3 py-4 ${className}`}>
      {/* ── MOOD ─────────────────────────────────────────── */}
      <section className="mb-6">
        <SectionLabel>Mood</SectionLabel>
        {mood.mood && (
          <p className="mb-3 text-lg font-semibold capitalize leading-snug text-white">
            {mood.mood}
          </p>
        )}
        {energy !== null && (
          <div className="mb-3">
            <div className="mb-1 flex items-center justify-between text-[11px] text-white/45">
              <span>Energy</span>
              <span className="tabular-nums">{Math.round(energy * 100)}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-panel3">
              <div
                className="h-full rounded-full bg-gradient-to-r from-high via-mid to-bass"
                style={{ width: `${energy * 100}%` }}
              />
            </div>
          </div>
        )}
        {keywords.length > 0 && <Chips items={keywords} />}
      </section>

      {/* ── MUSIC STYLE ──────────────────────────────────── */}
      <section className="mb-6 border-t border-edge pt-4">
        <SectionLabel>Music Style</SectionLabel>
        {typeof mood.tempo_bpm === 'number' && (
          <p className="mb-3 font-mono text-sm text-white/80">
            <span className="text-2xl font-semibold tabular-nums text-white">
              {Math.round(mood.tempo_bpm)}
            </span>{' '}
            <span className="text-white/40">BPM</span>
          </p>
        )}
        {genres.length > 0 && <Chips items={genres} tone="accent" />}
      </section>

      {/* ── VISUAL MOOD ──────────────────────────────────── */}
      <section className="border-t border-edge pt-4">
        <SectionLabel>Visual Mood</SectionLabel>
        {palette.length > 0 && (
          <div className="mb-4 flex overflow-hidden rounded-lg ring-1 ring-edge">
            {palette.map((hex, i) => (
              <div
                key={i}
                className="group relative h-12 flex-1"
                style={{ backgroundColor: hex }}
                title={hex}
              >
                <span className="pointer-events-none absolute inset-x-0 bottom-0 truncate bg-black/40 px-1 py-0.5 text-center font-mono text-[8px] text-white/80 opacity-0 transition-opacity group-hover:opacity-100">
                  {hex}
                </span>
              </div>
            ))}
          </div>
        )}
        {suggestions.length > 0 && (
          <ol className="space-y-2">
            {suggestions.map((s, i) => (
              <li
                key={i}
                className="flex gap-2 rounded-lg bg-panel2 p-2.5 text-xs leading-relaxed text-white/65"
              >
                <span className="mt-0.5 shrink-0 font-mono text-[10px] text-accent">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span>{s}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

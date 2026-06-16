import { useEffect, useRef } from 'react';
import { useEditor, activeLyricIndex } from '../store/editorStore';
import { fmtClock } from '../lib/format';

/** Vertical synced lyrics: highlight + auto-scroll active line, click to seek. */
export default function LyricsColumn({
  className = '',
  showHeader = true,
}: {
  className?: string;
  showHeader?: boolean;
}) {
  const lyrics = useEditor((s) => s.analysis?.lyrics ?? null);
  const currentTime = useEditor((s) => s.currentTime);
  const analysisStatus = useEditor((s) => s.analysisStatus);
  const seek = useEditor((s) => s.seek);

  const activeIdx = activeLyricIndex(lyrics, currentTime);
  const activeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (activeIdx >= 0 && activeRef.current) {
      activeRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [activeIdx]);

  return (
    <div className={`flex h-full flex-col bg-panel ${className}`}>
      {showHeader && (
        <div className="border-b border-edge px-3 py-2.5">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-white/50">
            Lyrics
          </h2>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-2 py-3">
        {!lyrics || lyrics.length === 0 ? (
          <p className="px-2 pt-6 text-center text-xs text-white/30">
            {analysisStatus === 'processing'
              ? 'Transcribing lyrics…'
              : 'No lyrics yet.'}
          </p>
        ) : (
          <div className="space-y-0.5">
            {lyrics.map((line, i) => {
              const active = i === activeIdx;
              const past = !active && currentTime >= line.end;
              return (
                <button
                  key={i}
                  ref={active ? activeRef : null}
                  onClick={() => seek(line.start)}
                  className={[
                    'block w-full rounded-md px-2 py-1.5 text-left text-sm transition-colors',
                    active
                      ? 'bg-accent/20 font-medium text-white ring-1 ring-accent/50'
                      : past
                        ? 'text-white/30 hover:bg-panel3'
                        : 'text-white/70 hover:bg-panel3',
                  ].join(' ')}
                >
                  <span className="mr-2 font-mono text-[10px] text-white/30 tabular-nums">
                    {fmtClock(line.start)}
                  </span>
                  {line.text}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

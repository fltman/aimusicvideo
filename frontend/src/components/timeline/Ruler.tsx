// Ruler — time tick marks + m:ss labels at a nice interval for the current
// zoom, plus colored beat markers from analysis.beats. Click to seek.
import { useEditor } from '../../store/editorStore';
import { RULER_H } from '../../lib/constants';

interface Props {
  laneWidth: number;
  pixelsPerSecond: number;
  duration: number;
  clientXToTime: (clientX: number) => number;
}

/** Pick a label interval (seconds) so labels are ~70px+ apart. */
function niceInterval(pps: number): number {
  const candidates = [0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
  const minPx = 70;
  for (const c of candidates) {
    if (c * pps >= minPx) return c;
  }
  return candidates[candidates.length - 1];
}

function mss(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function Ruler({ laneWidth, pixelsPerSecond, duration, clientXToTime }: Props) {
  const beats = useEditor((s) => s.analysis?.beats ?? null);
  const seek = useEditor((s) => s.seek);

  const interval = niceInterval(pixelsPerSecond);
  const ticks: number[] = [];
  for (let t = 0; t <= duration + 1e-6; t += interval) ticks.push(t);

  const bands: { key: 'bass' | 'mid' | 'high'; color: string; h: number }[] = [
    { key: 'bass', color: 'bg-bass', h: 12 },
    { key: 'mid', color: 'bg-mid', h: 9 },
    { key: 'high', color: 'bg-high', h: 6 },
  ];

  return (
    <div
      className="relative cursor-pointer select-none border-b border-edge bg-panel3"
      style={{ width: laneWidth, height: RULER_H }}
      onPointerDown={(e) => seek(Math.max(0, clientXToTime(e.clientX)))}
    >
      {/* beat markers (drawn under labels) */}
      {beats &&
        bands.map(({ key, color, h }) =>
          (beats[key] ?? []).map((t, i) => (
            <div
              key={`${key}-${i}`}
              className={`pointer-events-none absolute bottom-0 ${color}`}
              style={{ left: t * pixelsPerSecond, width: 1, height: h, opacity: 0.7 }}
            />
          )),
        )}

      {/* tick marks + labels */}
      {ticks.map((t) => {
        const x = t * pixelsPerSecond;
        return (
          <div key={t} className="pointer-events-none absolute top-0" style={{ left: x }}>
            <div className="h-2 w-px bg-edge" />
            <span className="absolute left-1 top-0 text-[10px] text-white/45">{mss(t)}</span>
          </div>
        );
      })}
    </div>
  );
}

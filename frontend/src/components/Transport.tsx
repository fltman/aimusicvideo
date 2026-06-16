import { useEditor } from '../store/editorStore';
import { fmtTime } from '../lib/format';

/** Playback transport: play/pause, stop, time readout, split, delete, zoom. */
export default function Transport({ className = '' }: { className?: string }) {
  const playing = useEditor((s) => s.playing);
  const currentTime = useEditor((s) => s.currentTime);
  const duration = useEditor((s) => s.duration);
  const selectedCount = useEditor((s) => s.selectedClipIds.length);
  const loop = useEditor((s) => s.loop);
  const hasRange = useEditor((s) => s.rangeIn != null && s.rangeOut != null);

  const togglePlay = useEditor((s) => s.togglePlay);
  const seek = useEditor((s) => s.seek);
  const pause = useEditor((s) => s.pause);
  const splitAtPlayhead = useEditor((s) => s.splitAtPlayhead);
  const removeSelected = useEditor((s) => s.removeSelected);
  const setRangeIn = useEditor((s) => s.setRangeIn);
  const setRangeOut = useEditor((s) => s.setRangeOut);
  const clearRange = useEditor((s) => s.clearRange);
  const toggleLoop = useEditor((s) => s.toggleLoop);

  const stop = () => {
    pause();
    seek(0);
  };

  const btn =
    'flex h-8 w-8 items-center justify-center rounded-md bg-panel3 text-sm text-white/80 ' +
    'hover:bg-edge hover:text-white transition-colors disabled:opacity-30 disabled:hover:bg-panel3';

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <button className={btn} onClick={stop} title="Stop">
        ■
      </button>
      <button
        className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-white hover:bg-accent/90 transition-colors"
        onClick={togglePlay}
        title={playing ? 'Pause (space)' : 'Play (space)'}
      >
        {playing ? '❚❚' : '▶'}
      </button>

      <div className="ml-2 rounded-md bg-panel px-3 py-1.5 font-mono text-sm tabular-nums ring-1 ring-edge">
        <span className="text-white">{fmtTime(currentTime)}</span>
        <span className="mx-1.5 text-white/30">/</span>
        <span className="text-white/50">{fmtTime(duration)}</span>
      </div>

      <div className="mx-1 h-6 w-px bg-edge" />

      <button
        className={btn}
        onClick={splitAtPlayhead}
        title="Split clips at playhead"
      >
        ✂
      </button>
      <button
        className={btn}
        onClick={removeSelected}
        disabled={selectedCount === 0}
        title="Delete selected clip(s) (Del)"
      >
        🗑
      </button>

      <div className="mx-1 h-6 w-px bg-edge" />

      <button className={btn} onClick={setRangeIn} title="Set range in (I)">
        ⟨
      </button>
      <button className={btn} onClick={setRangeOut} title="Set range out (O)">
        ⟩
      </button>
      <button
        className={`${btn} ${loop ? '!bg-accent/25 !text-accent' : ''}`}
        onClick={toggleLoop}
        title="Loop the range (L)"
      >
        ⟳
      </button>
      {hasRange && (
        <button
          className={`${btn} text-xs`}
          onClick={clearRange}
          title="Clear range"
        >
          ⤫
        </button>
      )}
    </div>
  );
}

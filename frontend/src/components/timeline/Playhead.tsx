// Playhead — vertical line over the lane area at currentTime*pps. Draggable to
// scrub (calls seek). Positioned absolutely inside the lane-content wrapper.
import { useRef } from 'react';
import { useEditor } from '../../store/editorStore';
import { RULER_H } from '../../lib/constants';

interface Props {
  pixelsPerSecond: number;
  /** total height of ruler + lanes, so the line spans everything */
  height: number;
  clientXToTime: (clientX: number) => number;
}

export default function Playhead({ pixelsPerSecond, height, clientXToTime }: Props) {
  const currentTime = useEditor((s) => s.currentTime);
  const seek = useEditor((s) => s.seek);
  const dragging = useRef(false);

  const x = currentTime * pixelsPerSecond;

  const onPointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    dragging.current = true;
    seek(Math.max(0, clientXToTime(e.clientX)));
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    e.stopPropagation();
    seek(Math.max(0, clientXToTime(e.clientX)));
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    e.stopPropagation();
    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    dragging.current = false;
  };

  return (
    <div
      className="pointer-events-none absolute top-0 z-30"
      style={{ left: x, height, transform: 'translateX(-0.5px)' }}
    >
      {/* the line */}
      <div className="absolute top-0 w-px bg-accent" style={{ height }} />
      {/* draggable grab handle sitting in the ruler band */}
      <div
        className="pointer-events-auto absolute -left-[5px] top-0 cursor-ew-resize"
        style={{ width: 11, height: RULER_H }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div className="mx-auto h-0 w-0 border-x-[5px] border-t-[7px] border-x-transparent border-t-accent" />
      </div>
    </div>
  );
}

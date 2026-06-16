import { useRef } from 'react';

/** A draggable divider. `vertical` bar resizes width (drag left/right → onResize(dx));
 *  `horizontal` bar resizes height (drag up/down → onResize(dy)). */
export default function ResizeHandle({
  orientation,
  onResize,
}: {
  orientation: 'vertical' | 'horizontal';
  onResize: (delta: number) => void;
}) {
  const last = useRef<number | null>(null);

  const onDown = (e: React.PointerEvent) => {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    last.current = orientation === 'vertical' ? e.clientX : e.clientY;
  };
  const onMove = (e: React.PointerEvent) => {
    if (last.current == null) return;
    const cur = orientation === 'vertical' ? e.clientX : e.clientY;
    onResize(cur - last.current);
    last.current = cur;
  };
  const onUp = (e: React.PointerEvent) => {
    last.current = null;
    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* capture already gone */
    }
  };

  return (
    <div
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onUp}
      className={
        orientation === 'vertical'
          ? 'z-10 w-1 shrink-0 cursor-col-resize bg-edge transition-colors hover:bg-accent'
          : 'z-10 h-1 shrink-0 cursor-row-resize bg-edge transition-colors hover:bg-accent'
      }
    />
  );
}

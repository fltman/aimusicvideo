import { useCallback, useRef } from 'react';
import type { FilterParam } from '../types';

/* ─────────────────────────────────────────────────────────────────────────
 * FilterControls — presentational, auto-generates controls from a filter's
 * PARAMS array. Pure: no store access, no API calls. Parent owns the values
 * and the onChange handler (typically wired to updateClipParams).
 * ───────────────────────────────────────────────────────────────────────── */

interface FilterControlsProps {
  params: FilterParam[];
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  className?: string;
}

// ── numeric helpers ─────────────────────────────────────────────────────────

const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v));

/** Snap to step grid anchored at min, then clamp to [min,max]. */
function quantize(v: number, min: number, max: number, step: number): number {
  if (!(step > 0)) return clamp(v, min, max);
  const snapped = min + Math.round((v - min) / step) * step;
  // kill floating-point dust introduced by the round-trip
  const decimals = (String(step).split('.')[1] ?? '').length;
  const fixed = decimals > 0 ? Number(snapped.toFixed(decimals)) : snapped;
  return clamp(fixed, min, max);
}

/** Coerce an unknown stored value to a number, falling back to `fallback`. */
function num(v: unknown, fallback: number): number {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

/** Readable numeric readout — trims trailing zeros, caps precision. */
function fmt(v: number): string {
  if (Number.isInteger(v)) return String(v);
  return String(Number(v.toFixed(3)));
}

// ── Knob ─────────────────────────────────────────────────────────────────────

interface KnobProps {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  label: string;
}

// Sweep: -135° (min) … +135° (max), so the dead zone sits at the bottom.
const KNOB_MIN_ANGLE = -135;
const KNOB_MAX_ANGLE = 135;
// Pixels of vertical drag to traverse the whole range (full sweep, drag up = up).
const KNOB_TRAVEL_PX = 180;

/** A real rotary knob: drag vertically (up = increase) to set the value. */
function Knob({ value, min, max, step, onChange, label }: KnobProps) {
  // Drag origin captured on pointer-down; we accumulate from there so a value
  // that was clamped mid-drag doesn't fight the pointer.
  const drag = useRef<{ y: number; value: number } | null>(null);

  const range = max - min || 1;
  const frac = clamp((value - min) / range, 0, 1);
  const angle = KNOB_MIN_ANGLE + frac * (KNOB_MAX_ANGLE - KNOB_MIN_ANGLE);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      drag.current = { y: e.clientY, value };
    },
    [value],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const d = drag.current;
      if (!d) return;
      // Drag up (negative dy) raises the value.
      const dy = d.y - e.clientY;
      // Shift = fine control (¼ sensitivity).
      const speed = e.shiftKey ? 0.25 : 1;
      const next = d.value + (dy / KNOB_TRAVEL_PX) * range * speed;
      onChange(quantize(next, min, max, step));
    },
    [min, max, step, range, onChange],
  );

  const endDrag = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
  }, []);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      const big = e.shiftKey ? 10 : 1;
      if (e.key === 'ArrowUp' || e.key === 'ArrowRight') {
        e.preventDefault();
        onChange(quantize(value + step * big, min, max, step));
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowLeft') {
        e.preventDefault();
        onChange(quantize(value - step * big, min, max, step));
      } else if (e.key === 'Home') {
        e.preventDefault();
        onChange(quantize(min, min, max, step));
      } else if (e.key === 'End') {
        e.preventDefault();
        onChange(quantize(max, min, max, step));
      }
    },
    [value, step, min, max, onChange],
  );

  return (
    <div
      role="slider"
      aria-label={label}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={value}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
      title="Drag up/down to adjust · Shift for fine"
      className="group relative h-12 w-12 shrink-0 cursor-ns-resize touch-none select-none rounded-full bg-panel3 outline-none ring-1 ring-edge transition-shadow focus-visible:ring-accent"
      style={{ WebkitTapHighlightColor: 'transparent' }}
    >
      {/* rotating dial */}
      <div
        className="absolute inset-0"
        style={{ transform: `rotate(${angle}deg)` }}
      >
        {/* indicator line from center toward the top */}
        <span className="absolute left-1/2 top-[3px] h-[34%] w-[2px] -translate-x-1/2 rounded-full bg-accent transition-colors group-active:bg-high" />
      </div>
      {/* hub */}
      <span className="absolute left-1/2 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-edge" />
    </div>
  );
}

// ── per-type control bodies ──────────────────────────────────────────────────

function SliderControl({
  p,
  value,
  onChange,
}: {
  p: FilterParam;
  value: number;
  onChange: (v: number) => void;
}) {
  const min = num(p.min, 0);
  const max = num(p.max, 1);
  const step = num(p.step, 0.01);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <label
          htmlFor={`fc-${p.key}`}
          className="truncate text-[11px] font-medium text-white/70"
        >
          {p.label}
        </label>
        <span className="shrink-0 font-mono text-[11px] tabular-nums text-accent">
          {fmt(value)}
        </span>
      </div>
      <input
        id={`fc-${p.key}`}
        type="range"
        min={min}
        max={max}
        step={step || 'any'}
        value={value}
        onChange={(e) => onChange(quantize(Number(e.target.value), min, max, step))}
        className="fc-range h-1.5 w-full cursor-pointer appearance-none rounded-full bg-panel3 accent-accent outline-none focus-visible:ring-1 focus-visible:ring-accent"
      />
    </div>
  );
}

function KnobControl({
  p,
  value,
  onChange,
}: {
  p: FilterParam;
  value: number;
  onChange: (v: number) => void;
}) {
  const min = num(p.min, 0);
  const max = num(p.max, 1);
  const step = num(p.step, 0.01);
  return (
    <div className="flex items-center gap-3">
      <Knob
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={onChange}
        label={p.label}
      />
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-[11px] font-medium text-white/70">
          {p.label}
        </span>
        <span className="font-mono text-[11px] tabular-nums text-accent">
          {fmt(value)}
        </span>
      </div>
    </div>
  );
}

function SwitchControl({
  p,
  value,
  onChange,
}: {
  p: FilterParam;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={p.label}
      onClick={() => onChange(!value)}
      className="flex w-full items-center justify-between gap-2 rounded-md bg-panel3 px-2.5 py-1.5 text-left outline-none ring-1 ring-edge transition-colors hover:ring-edge/80 focus-visible:ring-accent"
    >
      <span className="truncate text-[11px] font-medium text-white/70">
        {p.label}
      </span>
      <span
        className={`relative h-4 w-7 shrink-0 rounded-full transition-colors ${
          value ? 'bg-accent' : 'bg-edge'
        }`}
      >
        <span
          className={`absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-all ${
            value ? 'left-3.5' : 'left-0.5'
          }`}
        />
      </span>
    </button>
  );
}

function SelectControl({
  p,
  value,
  onChange,
}: {
  p: FilterParam;
  value: string;
  onChange: (v: string) => void;
}) {
  const options = p.options ?? [];
  return (
    <div className="flex flex-col gap-1">
      <label
        htmlFor={`fc-${p.key}`}
        className="truncate text-[11px] font-medium text-white/70"
      >
        {p.label}
      </label>
      <div className="relative">
        <select
          id={`fc-${p.key}`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full cursor-pointer appearance-none rounded-md bg-panel3 py-1.5 pl-2.5 pr-7 text-[11px] text-white/85 outline-none ring-1 ring-edge transition-colors hover:ring-edge/80 focus-visible:ring-accent"
        >
          {/* If the current value isn't among options, surface it so the user
              can still see what's set rather than silently snapping. */}
          {value !== '' && !options.includes(value) && (
            <option value={value}>{value}</option>
          )}
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
        <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[9px] text-white/40">
          ▼
        </span>
      </div>
    </div>
  );
}

// ── grid placement ───────────────────────────────────────────────────────────
// Sliders & knobs want width → full row (col-span-2). Switches & selects are
// compact → one column, so two pack side-by-side on a 2-col grid.
function spanClass(type: FilterParam['type']): string {
  return type === 'slider' || type === 'knob' ? 'col-span-2' : 'col-span-1';
}

// ── root ─────────────────────────────────────────────────────────────────────

export default function FilterControls({
  params,
  values,
  onChange,
  className = '',
}: FilterControlsProps) {
  if (!params.length) {
    return (
      <div
        className={`px-1 py-4 text-center text-xs text-white/30 ${className}`}
      >
        This filter has no adjustable parameters.
      </div>
    );
  }

  return (
    <div className={`grid grid-cols-2 gap-x-3 gap-y-3 ${className}`}>
      {params.map((p) => {
        const current = values[p.key] ?? p.default;
        let body: React.ReactNode;

        switch (p.type) {
          case 'slider':
            body = (
              <SliderControl
                p={p}
                value={num(current, num(p.default, 0))}
                onChange={(v) => onChange(p.key, v)}
              />
            );
            break;
          case 'knob':
            body = (
              <KnobControl
                p={p}
                value={num(current, num(p.default, 0))}
                onChange={(v) => onChange(p.key, v)}
              />
            );
            break;
          case 'switch':
            body = (
              <SwitchControl
                p={p}
                value={Boolean(current)}
                onChange={(v) => onChange(p.key, v)}
              />
            );
            break;
          case 'select':
            body = (
              <SelectControl
                p={p}
                value={current == null ? '' : String(current)}
                onChange={(v) => onChange(p.key, v)}
              />
            );
            break;
          default:
            body = null;
        }

        return (
          <div key={p.key} className={spanClass(p.type)}>
            {body}
          </div>
        );
      })}
    </div>
  );
}

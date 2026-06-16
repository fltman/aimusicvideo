// Timeline — the horizontal NLE timeline.
// Layout: a fixed 120px gutter of track headers on the left, and a horizontally
// scrollable lane area on the right whose width = duration * pixelsPerSecond.
// Stacks: a toolbar row, then [gutter | (Ruler over TrackRows + Playhead)].
//
// Coordinate math (single source of truth, shared with children):
//   lane-local time = (clientX - laneRect.left + scrollLeft) / pixelsPerSecond
// where laneRect is the on-screen rect of the scroll viewport (already past the
// gutter). This keeps every pointer interaction consistent.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useEditor } from '../../store/editorStore';
import { TRACK_HEADER_W, TRACK_H, RULER_H } from '../../lib/constants';
import type { Track, TrackKind } from '../../types';
import Ruler from './Ruler';
import TrackRow from './TrackRow';
import Playhead from './Playhead';
import FilterBrowser from '../FilterBrowser';

const KIND_ICON: Record<TrackKind, string> = {
  audio: '♪',
  video: '▣',
  image: '▦',
  effect: '✦',
};

const ADD_KINDS: TrackKind[] = ['video', 'image', 'audio', 'effect'];

export default function Timeline({ className }: { className?: string }) {
  const tracks = useEditor((s) => s.tracks);
  const pixelsPerSecond = useEditor((s) => s.pixelsPerSecond);
  const duration = useEditor((s) => s.duration);
  const playing = useEditor((s) => s.playing);
  const currentTime = useEditor((s) => s.currentTime);

  const setZoom = useEditor((s) => s.setZoom);
  const addTrack = useEditor((s) => s.addTrack);
  const removeTrack = useEditor((s) => s.removeTrack);
  const moveTrack = useEditor((s) => s.moveTrack);
  const toggleTrackHidden = useEditor((s) => s.toggleTrackHidden);
  const addEffectClip = useEditor((s) => s.addEffectClip);
  const seek = useEditor((s) => s.seek);
  const select = useEditor((s) => s.select);

  const [browserOpen, setBrowserOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const gutterRef = useRef<HTMLDivElement | null>(null);

  // keep the track-header gutter vertically aligned with the lanes
  const onLaneScroll = () => {
    const el = scrollRef.current;
    const g = gutterRef.current;
    if (el && g) g.scrollTop = el.scrollTop;
  };

  const laneWidth = Math.max(duration * pixelsPerSecond, 200);
  const lanesHeight = tracks.length * TRACK_H;
  const totalHeight = RULER_H + lanesHeight;

  // ── coordinate helpers (shared with all children) ────────────────────────
  const clientXToTime = useCallback(
    (clientX: number): number => {
      const el = scrollRef.current;
      if (!el) return 0;
      const rect = el.getBoundingClientRect();
      const localX = clientX - rect.left + el.scrollLeft;
      return localX / pixelsPerSecond;
    },
    [pixelsPerSecond],
  );

  const clientYToTrackId = useCallback((clientY: number): string | null => {
    const el = scrollRef.current;
    if (!el) return null;
    // each lane row carries data-track-id; find the one under the pointer
    const rows = el.querySelectorAll<HTMLElement>('[data-track-id]');
    for (const row of Array.from(rows)) {
      const r = row.getBoundingClientRect();
      if (clientY >= r.top && clientY < r.bottom) return row.dataset.trackId ?? null;
    }
    return null;
  }, []);

  // ── auto-scroll to keep the playhead visible during playback ──────────────
  useEffect(() => {
    if (!playing) return;
    const el = scrollRef.current;
    if (!el) return;
    const x = currentTime * pixelsPerSecond;
    const margin = 80;
    if (x < el.scrollLeft + margin) {
      el.scrollLeft = Math.max(0, x - margin);
    } else if (x > el.scrollLeft + el.clientWidth - margin) {
      el.scrollLeft = x - el.clientWidth + margin;
    }
  }, [currentTime, playing, pixelsPerSecond]);

  // click empty lane / ruler background → seek
  const onLanesBackgroundDown = (e: React.PointerEvent) => {
    // only fire for clicks on the wrapper itself, not bubbled from clips
    if (e.target === e.currentTarget) {
      select(null);
      seek(Math.max(0, clientXToTime(e.clientX)));
    }
  };

  return (
    <div className={`flex h-full flex-col bg-panel ${className ?? ''}`}>
      {/* ── toolbar ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 border-b border-edge bg-panel3 px-3 py-1.5 text-xs text-white/70">
        <span className="mr-1 text-white/40">Tracks</span>
        {ADD_KINDS.map((kind) => (
          <button
            key={kind}
            type="button"
            onClick={() => addTrack(kind)}
            className="rounded border border-edge bg-panel2 px-2 py-1 hover:border-accent hover:text-white"
            title={`Add ${kind} track`}
          >
            + {KIND_ICON[kind]} {kind}
          </button>
        ))}

        <button
          type="button"
          onClick={() => setBrowserOpen(true)}
          className="rounded border border-accent/50 bg-accent/15 px-2 py-1 text-accent hover:bg-accent/25"
          title="Add a filter effect"
        >
          ✨ Filters
        </button>

        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => setZoom(pixelsPerSecond / 1.4)}
            className="rounded border border-edge bg-panel2 px-2 py-1 hover:border-accent hover:text-white"
            title="Zoom out"
          >
            −
          </button>
          <span className="w-16 text-center tabular-nums text-white/40">
            {Math.round(pixelsPerSecond)} px/s
          </span>
          <button
            type="button"
            onClick={() => setZoom(pixelsPerSecond * 1.4)}
            className="rounded border border-edge bg-panel2 px-2 py-1 hover:border-accent hover:text-white"
            title="Zoom in"
          >
            +
          </button>
          <span className="ml-3 tabular-nums text-white/40">
            {Math.floor(duration / 60)}:{Math.floor(duration % 60).toString().padStart(2, '0')}
          </span>
        </div>
      </div>

      {/* ── gutter + scrollable lanes ───────────────────────────────────── */}
      <div className="flex min-h-0 flex-1">
        {/* track-header gutter (scrolls vertically in sync with the lanes) */}
        <div
          className="flex shrink-0 flex-col border-r border-edge bg-panel2"
          style={{ width: TRACK_HEADER_W }}
        >
          {/* spacer aligning headers below the ruler */}
          <div
            className="shrink-0 border-b border-edge bg-panel3"
            style={{ height: RULER_H }}
          />
          <div ref={gutterRef} className="min-h-0 flex-1 overflow-hidden">
            {tracks.map((track, idx) => (
              <TrackHeader
                key={track.id}
                track={track}
                index={idx}
                total={tracks.length}
                onRemove={() => removeTrack(track.id)}
                onMove={(dir) => moveTrack(track.id, dir)}
                onToggleHidden={() => toggleTrackHidden(track.id)}
              />
            ))}
          </div>
        </div>

        {/* scrollable lane viewport (horizontal + vertical) */}
        <div
          ref={scrollRef}
          onScroll={onLaneScroll}
          className="relative min-w-0 flex-1 overflow-auto"
        >
          {/* content sized to laneWidth so it scrolls horizontally */}
          <div className="relative" style={{ width: laneWidth, height: totalHeight }}>
            {/* ruler stays pinned to the top during vertical scroll */}
            <div className="sticky top-0 z-20">
              <Ruler
                laneWidth={laneWidth}
                pixelsPerSecond={pixelsPerSecond}
                duration={duration}
                clientXToTime={clientXToTime}
              />
            </div>
            <div onPointerDown={onLanesBackgroundDown}>
              {tracks.map((track) => (
                <TrackRow
                  key={track.id}
                  track={track}
                  tracks={tracks}
                  laneWidth={laneWidth}
                  pixelsPerSecond={pixelsPerSecond}
                  clientXToTime={clientXToTime}
                  clientYToTrackId={clientYToTrackId}
                />
              ))}
            </div>

            <Playhead
              pixelsPerSecond={pixelsPerSecond}
              height={totalHeight}
              clientXToTime={clientXToTime}
            />
          </div>
        </div>
      </div>

      <FilterBrowser
        open={browserOpen}
        onClose={() => setBrowserOpen(false)}
        onPick={(f) => addEffectClip(f.id, f.name)}
      />
    </div>
  );
}

// ── track header (in the 120px gutter) ───────────────────────────────────────

const SONG_TRACK_NAME = 'Music';

function EyeIcon({ hidden }: { hidden: boolean }) {
  return hidden ? (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20C5 20 1 12 1 12a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  ) : (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function TrackHeader({
  track,
  index,
  total,
  onRemove,
  onMove,
  onToggleHidden,
}: {
  track: Track;
  index: number;
  total: number;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
  onToggleHidden: () => void;
}) {
  // the music track holds the song clip; don't let it be removed
  const isSongTrack = track.kind === 'audio' && track.name === SONG_TRACK_NAME;
  const hidden = !!track.hidden;
  return (
    <div
      className="group flex items-center gap-1.5 border-b border-edge px-2 text-xs text-white/70"
      style={{ height: TRACK_H }}
    >
      {/* reorder — top track wins for overlapping visuals */}
      <div className="flex shrink-0 flex-col">
        <button
          type="button"
          onClick={() => onMove(-1)}
          disabled={index === 0}
          className="leading-none text-white/25 hover:text-accent disabled:opacity-20 disabled:hover:text-white/25"
          title="Move track up (renders on top)"
        >
          ▲
        </button>
        <button
          type="button"
          onClick={() => onMove(1)}
          disabled={index === total - 1}
          className="leading-none text-white/25 hover:text-accent disabled:opacity-20 disabled:hover:text-white/25"
          title="Move track down"
        >
          ▼
        </button>
      </div>
      <button
        type="button"
        onClick={onToggleHidden}
        className={`shrink-0 ${hidden ? 'text-bass' : 'text-white/40 hover:text-white'}`}
        title={hidden ? 'Show track' : 'Hide track'}
      >
        <EyeIcon hidden={hidden} />
      </button>
      <span className={`text-sm ${hidden ? 'text-white/20' : 'text-white/40'}`}>
        {KIND_ICON[track.kind]}
      </span>
      <span
        className={`min-w-0 flex-1 truncate ${hidden ? 'text-white/30' : ''}`}
        title={track.name}
      >
        {track.name}
      </span>
      {!isSongTrack && (
        <button
          type="button"
          onClick={onRemove}
          className="shrink-0 rounded px-1 text-white/30 hover:bg-edge hover:text-bass"
          title="Remove track"
        >
          ✕
        </button>
      )}
    </div>
  );
}

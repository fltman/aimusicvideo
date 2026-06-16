// ClipView — one absolutely-positioned clip on a track lane.
// Move (drag body → moveClip, hop tracks of same kind via pointer Y),
// trim (left/right 8px handles → trimClip), select on click, split on
// double-click, and draw a mini waveform for song / audio clips.
import { useRef } from 'react';
import { useEditor } from '../../store/editorStore';
import { filesUrl } from '../../api/client';
import { TRACK_H, MIN_CLIP } from '../../lib/constants';
import type { Clip, Track, Waveform } from '../../types';

type DragMode = 'move' | 'trim-start' | 'trim-end';

interface Props {
  clip: Clip;
  track: Track;
  /** All tracks, ordered top→bottom, so a move can hop lanes of the same kind. */
  tracks: Track[];
  /** Lane-local pixel offset (relative to the start of the lane area). */
  pixelsPerSecond: number;
  /** Maps a clientX to a lane-local time (already accounts for gutter+scroll). */
  clientXToTime: (clientX: number) => number;
  /** Maps a clientY to the trackId currently under the pointer (or null). */
  clientYToTrackId: (clientY: number) => string | null;
  selected: boolean;
  /** How many earlier clips on this lane this one overlaps — staggers it down so
   *  the covered clip stays visible. */
  overlapDepth?: number;
}

const HANDLE_W = 8;
const STAGGER = 9; // px each overlapping clip is nudged down

export default function ClipView({
  clip,
  track,
  tracks,
  pixelsPerSecond,
  clientXToTime,
  clientYToTrackId,
  selected,
  overlapDepth = 0,
}: Props) {
  const moveClip = useEditor((s) => s.moveClip);
  const trimClip = useEditor((s) => s.trimClip);
  const select = useEditor((s) => s.select);
  const splitClipAt = useEditor((s) => s.splitClipAt);
  const openFilterWorkspace = useEditor((s) => s.openFilterWorkspace);
  const toggleSelect = useEditor((s) => s.toggleSelect);
  const openTextEditor = useEditor((s) => s.openTextEditor);
  const currentTime = useEditor((s) => s.currentTime);
  const waveform = useEditor((s) => s.analysis?.waveform ?? null);
  const media = useEditor((s) => s.media);
  const openConvertPrompt = useEditor((s) => s.openConvertPrompt);
  const convertingAssets = useEditor((s) => s.convertingAssets);

  const isEffect = !!clip.filterId || track.kind === 'effect';
  const isText = track.kind === 'text' || clip.text != null;

  // image/video clips show their thumbnail as a repeating filmstrip background
  const asset = clip.assetId ? media.find((m) => m.id === clip.assetId) : null;
  const isImageClip = asset?.kind === 'image' && !isEffect && !isText;
  const converting = asset ? convertingAssets.includes(asset.id) : false;
  const thumbUrl = asset
    ? asset.thumb_path
      ? filesUrl(asset.thumb_path)
      : asset.kind === 'image'
        ? filesUrl(asset.path)
        : null
    : null;

  const drag = useRef<{
    mode: DragMode;
    grabTime: number; // lane time at pointer-down
    origStart: number;
    origDuration: number;
  } | null>(null);

  const isSong = clip.source === 'song';
  const isAudio = track.kind === 'audio';

  const left = clip.start * pixelsPerSecond;
  const width = Math.max(2, clip.duration * pixelsPerSecond);

  // overlapping clips cascade downward so a covered clip's top edge stays visible
  const depth = Math.min(Math.max(0, overlapDepth), 4);
  const topPx = 4 + depth * STAGGER;
  const heightPx = Math.max(18, TRACK_H - 8 - depth * STAGGER);

  const begin = (mode: DragMode) => (e: React.PointerEvent) => {
    e.stopPropagation();
    if (e.shiftKey && mode === 'move') {
      toggleSelect(clip.id); // shift-click → multi-select, no drag
      return;
    }
    // song clip is locked: no move/trim (it's the master timeline anchor)
    if (isSong) {
      select(clip.id);
      return;
    }
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = {
      mode,
      grabTime: clientXToTime(e.clientX),
      origStart: clip.start,
      origDuration: clip.duration,
    };
    select(clip.id);
  };

  const onMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    e.stopPropagation();
    const t = clientXToTime(e.clientX);
    if (d.mode === 'move') {
      const delta = t - d.grabTime;
      const newStart = Math.max(0, d.origStart + delta);
      const overTrackId = clientYToTrackId(e.clientY);
      // only hop to another lane of the same kind
      let targetTrackId: string | undefined;
      if (overTrackId && overTrackId !== clip.trackId) {
        const overTrack = tracks.find((tr) => tr.id === overTrackId);
        if (overTrack && overTrack.kind === track.kind) targetTrackId = overTrackId;
      }
      moveClip(clip.id, newStart, targetTrackId);
    } else if (d.mode === 'trim-start') {
      trimClip(clip.id, 'start', t);
    } else {
      trimClip(clip.id, 'end', t);
    }
  };

  const onUp = (e: React.PointerEvent) => {
    if (!drag.current) return;
    e.stopPropagation();
    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* capture may already be gone */
    }
    drag.current = null;
  };

  const onDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isText) {
      openTextEditor(clip.id); // open the styled text editor
      return;
    }
    if (isEffect) {
      openFilterWorkspace(clip.id); // double-click an effect clip → edit the filter
      return;
    }
    if (currentTime > clip.start + MIN_CLIP && currentTime < clip.start + clip.duration - MIN_CLIP) {
      splitClipAt(clip.id, currentTime);
    }
  };

  const bg = clip.color ?? (isAudio ? '#3a3d66' : '#2f5d4a');

  return (
    <div
      role="button"
      tabIndex={0}
      onPointerDown={begin('move')}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onUp}
      onClick={(e) => e.stopPropagation()}
      onDoubleClick={onDoubleClick}
      className={`absolute overflow-hidden rounded-md border text-[11px] select-none ${
        selected ? 'border-accent shadow-[0_0_0_1px_rgba(109,109,240,0.6)]' : 'border-edge'
      } ${depth > 0 ? 'ring-1 ring-black/40' : ''} ${
        isSong ? 'cursor-default' : 'cursor-grab active:cursor-grabbing'
      }`}
      style={{
        left,
        width,
        top: topPx,
        height: heightPx,
        background: bg,
        // deeper (more offset) clips sit on top, so their offset reveals the top
        // edge of the clips beneath; the selected clip always comes to the front
        zIndex: selected ? 100 : depth,
      }}
    >
      {isAudio && waveform && (
        <MiniWaveform
          waveform={waveform}
          inPoint={clip.inPoint}
          duration={clip.duration}
          width={width}
          height={heightPx}
        />
      )}

      {!isAudio && thumbUrl && (
        <>
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              backgroundImage: `url(${thumbUrl})`,
              backgroundSize: 'auto 100%',
              backgroundRepeat: 'repeat-x',
            }}
          />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-black/10" />
        </>
      )}

      <span className="pointer-events-none absolute left-2 top-1 max-w-full truncate pr-2 font-medium text-white/90 drop-shadow">
        {isEffect ? '✨ ' : isText ? 'T ' : ''}{clip.name}
      </span>

      {/* image → video: animate this still in place (and everywhere it's used) */}
      {isImageClip && (selected || converting) && (
        <button
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            if (!converting) openConvertPrompt(clip.id);
          }}
          disabled={converting}
          title={converting ? 'Generating video…' : 'Turn this image into video'}
          className={`absolute right-1 top-1 z-20 flex h-5 items-center gap-1 rounded bg-black/55 px-1.5 text-[10px] text-white/90 hover:bg-black/80 ${
            converting ? 'cursor-default' : ''
          }`}
        >
          {converting ? (
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
          ) : (
            '🎬'
          )}
          <span className="hidden sm:inline">{converting ? 'rendering' : 'to video'}</span>
        </button>
      )}

      {!isSong && (
        <>
          <div
            onPointerDown={begin('trim-start')}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={onUp}
            className="absolute inset-y-0 left-0 z-10 cursor-ew-resize bg-black/20 hover:bg-accent/60"
            style={{ width: HANDLE_W }}
          />
          <div
            onPointerDown={begin('trim-end')}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={onUp}
            className="absolute inset-y-0 right-0 z-10 cursor-ew-resize bg-black/20 hover:bg-accent/60"
            style={{ width: HANDLE_W }}
          />
        </>
      )}
    </div>
  );
}

// ── mini waveform ───────────────────────────────────────────────────────────

function MiniWaveform({
  waveform,
  inPoint,
  duration,
  width,
  height,
}: {
  waveform: Waveform;
  inPoint: number;
  duration: number;
  width: number;
  height: number;
}) {
  const { peaks, pps } = waveform;
  if (!peaks || peaks.length === 0 || !pps) return null;

  const startBucket = Math.max(0, Math.floor(inPoint * pps));
  const endBucket = Math.min(peaks.length, Math.ceil((inPoint + duration) * pps));
  const bucketCount = Math.max(1, endBucket - startBucket);

  // Down-sample to ~1 path point every 2px for performance on long clips.
  const cols = Math.max(1, Math.min(bucketCount, Math.floor(width / 2)));
  const mid = height / 2;
  const amp = height / 2 - 1;

  let dTop = '';
  let dBot = '';
  for (let i = 0; i < cols; i++) {
    const b = startBucket + Math.floor((i / cols) * bucketCount);
    const pk = peaks[b];
    if (!pk) continue;
    const x = (i / cols) * width;
    const yMax = mid - pk[1] * amp;
    const yMin = mid - pk[0] * amp;
    dTop += `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${yMax.toFixed(1)} `;
    dBot += `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${yMin.toFixed(1)} `;
  }

  return (
    <svg
      className="pointer-events-none absolute inset-0"
      width={width}
      height={height}
      preserveAspectRatio="none"
    >
      <path d={dTop} stroke="rgba(255,255,255,0.55)" fill="none" strokeWidth={1} />
      <path d={dBot} stroke="rgba(255,255,255,0.35)" fill="none" strokeWidth={1} />
    </svg>
  );
}

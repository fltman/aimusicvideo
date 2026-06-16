// TrackRow — one horizontal lane. Renders its clips and acts as a drop target
// for assets dragged from the media library. Only accepts drops whose
// asset.kind matches the track.kind.
import { useState } from 'react';
import { useEditor } from '../../store/editorStore';
import { TRACK_H } from '../../lib/constants';
import ClipView from './ClipView';
import type { Track } from '../../types';

interface Props {
  track: Track;
  /** All tracks (so a clip can hop between same-kind lanes during a move). */
  tracks: Track[];
  laneWidth: number;
  pixelsPerSecond: number;
  clientXToTime: (clientX: number) => number;
  clientYToTrackId: (clientY: number) => string | null;
}

/** A track accepts an asset kind: audio↔audio, image↔image, video↔video. */
function accepts(trackKind: Track['kind'], assetKind: string): boolean {
  if (trackKind === 'audio') return assetKind === 'audio';
  if (trackKind === 'image') return assetKind === 'image';
  if (trackKind === 'video') return assetKind === 'video';
  return false; // effect tracks take no media drops
}

export default function TrackRow({
  track,
  tracks,
  laneWidth,
  pixelsPerSecond,
  clientXToTime,
  clientYToTrackId,
}: Props) {
  // Subscribe to the stable `clips` reference and filter in render — a selector
  // that returns a fresh array each call breaks useSyncExternalStore (infinite loop).
  const allClips = useEditor((s) => s.clips);
  const clips = allClips.filter((c) => c.trackId === track.id);
  const media = useEditor((s) => s.media);
  const selectedIds = useEditor((s) => s.selectedClipIds);
  const addClipFromAsset = useEditor((s) => s.addClipFromAsset);
  const select = useEditor((s) => s.select);

  const [dragOver, setDragOver] = useState(false);

  const onDragOver = (e: React.DragEvent) => {
    // we can't read the asset id during dragover (security), so accept and
    // validate kind on drop.
    if (e.dataTransfer.types.includes('application/x-asset-id')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      if (!dragOver) setDragOver(true);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const assetId = e.dataTransfer.getData('application/x-asset-id');
    if (!assetId) return;
    const asset = media.find((m) => m.id === assetId);
    if (!asset) return;
    if (!accepts(track.kind, asset.kind)) return;
    const dropTime = Math.max(0, clientXToTime(e.clientX));
    addClipFromAsset(asset, dropTime, track.id);
  };

  return (
    <div
      data-track-id={track.id}
      onDragOver={onDragOver}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      onPointerDown={() => select(null)}
      className={`relative border-b border-edge ${dragOver ? 'bg-accent/10' : 'bg-panel2'} ${
        track.hidden ? 'opacity-40' : ''
      }`}
      style={{ width: laneWidth, height: TRACK_H }}
    >
      {clips.map((clip) => (
        <ClipView
          key={clip.id}
          clip={clip}
          track={track}
          tracks={tracks}
          pixelsPerSecond={pixelsPerSecond}
          clientXToTime={clientXToTime}
          clientYToTrackId={clientYToTrackId}
          selected={selectedIds.includes(clip.id)}
        />
      ))}
    </div>
  );
}

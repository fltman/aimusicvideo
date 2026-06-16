import { useEffect, useRef } from 'react';
import {
  useEditor,
  activeVisualClip,
  activeLyricIndex,
} from '../store/editorStore';
import { filesUrl } from '../api/client';
import type { MediaAsset } from '../types';

/** Live 16:9 compositing stage: active visual clip + karaoke lyric overlay. */
export default function PreviewStage({ className = '' }: { className?: string }) {
  const tracks = useEditor((s) => s.tracks);
  const clips = useEditor((s) => s.clips);
  const media = useEditor((s) => s.media);
  const currentTime = useEditor((s) => s.currentTime);
  const playing = useEditor((s) => s.playing);
  const lyrics = useEditor((s) => s.analysis?.lyrics ?? null);
  const palette = useEditor((s) => s.analysis?.mood?.palette ?? null);
  const previewAsset = useEditor((s) => s.previewAsset);
  const setPreviewAsset = useEditor((s) => s.setPreviewAsset);

  const videoRef = useRef<HTMLVideoElement>(null);

  const active = activeVisualClip(tracks, clips, currentTime);
  const asset: MediaAsset | null =
    active?.clip.assetId != null
      ? media.find((m) => m.id === active.clip.assetId) ?? null
      : null;

  const isVideo = asset?.kind === 'video';
  const isImage = asset?.kind === 'image';

  // Keep the reused <video> synced to the master audio clock.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !isVideo || !active) return;
    const target = active.clip.inPoint + (currentTime - active.clip.start);
    if (playing) {
      if (Math.abs(v.currentTime - target) > 0.3) v.currentTime = target;
      if (v.paused) v.play().catch(() => {});
    } else {
      if (!v.paused) v.pause();
      if (Math.abs(v.currentTime - target) > 0.05) v.currentTime = target;
    }
  }, [isVideo, active, currentTime, playing]);

  const lyricIdx = activeLyricIndex(lyrics, currentTime);
  const lyricLine = lyricIdx >= 0 && lyrics ? lyrics[lyricIdx].text : null;

  return (
    <div
      className={`flex h-full items-center justify-center bg-[#0a0a0d] p-4 ${className}`}
    >
      <div className="relative aspect-video w-full max-h-full overflow-hidden rounded-lg bg-black ring-1 ring-edge shadow-2xl">
        {/* Source preview: a media-library asset shown directly (overrides timeline) */}
        {previewAsset ? (
          <>
            {previewAsset.kind === 'video' ? (
              <video
                key={previewAsset.id}
                src={filesUrl(previewAsset.path)}
                autoPlay
                loop
                controls
                muted
                playsInline
                className="absolute inset-0 h-full w-full bg-black object-contain"
              />
            ) : previewAsset.kind === 'image' ? (
              <img
                key={previewAsset.id}
                src={filesUrl(previewAsset.path)}
                alt={previewAsset.original_name}
                className="absolute inset-0 h-full w-full object-contain"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-4xl opacity-40">
                🎵
              </div>
            )}
            <div className="absolute left-2 top-2 z-10 flex items-center gap-2 rounded bg-black/60 px-2 py-1 text-[10px] text-white/80">
              <span className="uppercase tracking-wider text-white/50">
                Source preview
              </span>
              <span className="max-w-[160px] truncate">
                {previewAsset.label || previewAsset.original_name}
              </span>
              <button
                onClick={() => setPreviewAsset(null)}
                className="text-white/50 hover:text-white"
                title="Back to timeline"
              >
                ✕
              </button>
            </div>
          </>
        ) : isImage && asset ? (
          <img
            src={filesUrl(asset.path)}
            alt={asset.original_name}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : isVideo && asset ? (
          <video
            ref={videoRef}
            src={filesUrl(asset.path)}
            muted
            playsInline
            preload="auto"
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
            {palette && palette.length > 0 ? (
              <div className="flex gap-1.5">
                {palette.slice(0, 5).map((c, i) => (
                  <div
                    key={i}
                    className="h-10 w-10 rounded-md ring-1 ring-white/10"
                    style={{ background: c }}
                  />
                ))}
              </div>
            ) : null}
            <p className="text-sm text-white/30">No visual under playhead</p>
          </div>
        )}

        {/* Text/title overlays (active text clips) */}
        {!previewAsset &&
          clips.map((c) => {
            if (c.text == null) return null;
            if (!(currentTime >= c.start && currentTime < c.start + c.duration))
              return null;
            const pos = c.textPosition ?? 'bottom';
            const posClass =
              pos === 'top'
                ? 'top-[8%] items-start'
                : pos === 'center'
                  ? 'inset-y-0 items-center'
                  : 'bottom-[12%] items-end';
            return (
              <div
                key={c.id}
                className={`pointer-events-none absolute inset-x-0 flex justify-center px-6 ${posClass}`}
              >
                <span
                  className="text-center font-bold"
                  style={{
                    color: c.textColor ?? '#ffffff',
                    fontSize: `${(c.textSize ?? 1) * 1.8}rem`,
                    textShadow: '0 2px 12px rgba(0,0,0,0.9)',
                  }}
                >
                  {c.text}
                </span>
              </div>
            );
          })}

        {/* Karaoke lyric overlay (timeline mode only) */}
        {!previewAsset && lyricLine && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center px-6 pb-8">
            <span
              className="rounded-md bg-black/45 px-4 py-2 text-center text-lg font-semibold text-white"
              style={{ textShadow: '0 2px 8px rgba(0,0,0,0.9)' }}
            >
              {lyricLine}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

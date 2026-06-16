import { useState } from 'react';
import { useEditor } from '../store/editorStore';
import { filesUrl } from '../api/client';

/** Motion-prompt dialog for turning an image clip into a video (self-gates on
 *  the store's convertPromptClipId). */
export default function ConvertVideoDialog() {
  const clipId = useEditor((s) => s.convertPromptClipId);
  const clips = useEditor((s) => s.clips);
  const media = useEditor((s) => s.media);
  const openConvertPrompt = useEditor((s) => s.openConvertPrompt);
  const convertClipToVideo = useEditor((s) => s.convertClipToVideo);

  const [prompt, setPrompt] = useState('');

  if (!clipId) return null;
  const clip = clips.find((c) => c.id === clipId);
  const asset = clip?.assetId ? media.find((m) => m.id === clip.assetId) : null;
  if (!clip || !asset) return null;

  const occurrences = clips.filter((c) => c.assetId === asset.id).length;
  const longest = clips
    .filter((c) => c.assetId === asset.id)
    .reduce((m, c) => Math.max(m, c.duration), clip.duration);
  const secs = Math.min(10, Math.max(1, Math.ceil(longest)));
  const thumb = asset.thumb_path ? filesUrl(asset.thumb_path) : filesUrl(asset.path);

  const close = () => {
    setPrompt('');
    openConvertPrompt(null);
  };
  const go = () => {
    void convertClipToVideo(clipId, prompt);
    setPrompt('');
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
      onClick={close}
    >
      <div
        className="w-full max-w-sm rounded-xl border border-edge bg-panel p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-white/60">
            🎬 Turn image into video
          </h3>
          <button onClick={close} className="text-white/40 hover:text-white">
            ✕
          </button>
        </div>

        <img src={thumb} alt="" className="mb-3 aspect-video w-full rounded object-cover" />

        <label className="mb-1 block text-[10px] uppercase tracking-wider text-white/40">
          Motion (optional)
        </label>
        <textarea
          autoFocus
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) go();
          }}
          placeholder="e.g. slow push-in, drifting steam, rippling water, hair moving"
          rows={3}
          className="mb-3 w-full resize-none rounded bg-panel3 px-2 py-1.5 text-sm text-white outline-none ring-1 ring-edge focus:ring-accent"
        />

        <p className="mb-3 text-[11px] leading-relaxed text-white/40">
          Generates a {secs}s clip
          {occurrences > 1 ? ` and places it at all ${occurrences} uses of this image` : ''}
          , trimmed to fit. Kling · ~1–2 min · runs in the background.
        </p>

        <div className="flex gap-2">
          <button
            onClick={close}
            className="flex-1 rounded bg-panel3 py-2 text-sm text-white/70 hover:bg-edge hover:text-white"
          >
            Cancel
          </button>
          <button
            onClick={go}
            className="flex-1 rounded bg-accent py-2 text-sm font-medium text-white hover:bg-accent/80"
          >
            Generate video
          </button>
        </div>
      </div>
    </div>
  );
}

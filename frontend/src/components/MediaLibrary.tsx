import { useMemo, useRef, useState } from 'react';
import { useEditor } from '../store/editorStore';
import { api, filesUrl } from '../api/client';
import type { MediaAsset, MediaKind } from '../types';

const KIND_ICON: Record<MediaKind, string> = {
  image: '🖼',
  video: '🎬',
  audio: '🎵',
};

const QUICK_TAGS = ['character', 'scene', 'prop', 'style'];
const FILTER_KINDS: (MediaKind | 'all')[] = ['all', 'image', 'video', 'audio'];
const MOTION_DURATIONS = [5, 10]; // kling supports 5s / 10s

/** Asset library: upload, draggable grid, name + tag, double-click to add. */
export default function MediaLibrary({ className = '' }: { className?: string }) {
  const projectId = useEditor((s) => s.projectId);
  const media = useEditor((s) => s.media);
  const refreshMedia = useEditor((s) => s.refreshMedia);
  const addClipFromAsset = useEditor((s) => s.addClipFromAsset);
  const setPreviewAsset = useEditor((s) => s.setPreviewAsset);
  const previewId = useEditor((s) => s.previewAsset?.id ?? null);

  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const [editing, setEditing] = useState<MediaAsset | null>(null);
  const [labelInput, setLabelInput] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const [confirmDel, setConfirmDel] = useState<MediaAsset | null>(null);

  // filter + search
  const [filterKind, setFilterKind] = useState<MediaKind | 'all'>('all');
  const [search, setSearch] = useState('');

  // animate (image → video)
  const [animateFor, setAnimateFor] = useState<MediaAsset | null>(null);
  const [motionPrompt, setMotionPrompt] = useState('');
  const [motionDuration, setMotionDuration] = useState(5);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return media.filter((a) => {
      if (filterKind !== 'all' && a.kind !== filterKind) return false;
      if (!q) return true;
      const hay = [a.label, a.original_name, ...(a.tags ?? [])]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
  }, [media, filterKind, search]);

  const onFiles = async (files: FileList | null) => {
    if (!files || !files.length || !projectId) return;
    setUploading(true);
    try {
      await api.uploadMedia(projectId, Array.from(files));
      await refreshMedia();
    } finally {
      setUploading(false);
    }
  };

  const askRemove = (e: React.MouseEvent, asset: MediaAsset) => {
    e.stopPropagation();
    setConfirmDel(asset);
  };

  const doRemove = async () => {
    if (!projectId || !confirmDel) return;
    await api.deleteMedia(projectId, confirmDel.id);
    await refreshMedia();
    setConfirmDel(null);
  };

  const openAnimate = (e: React.MouseEvent, asset: MediaAsset) => {
    e.stopPropagation();
    setAnimateFor(asset);
    setMotionPrompt('');
    setMotionDuration(5);
  };

  const doAnimate = async () => {
    if (!projectId || !animateFor) return;
    // enqueue; the global generation queue shows progress and the video lands
    // in the library when ready.
    await api.animateImage(projectId, animateFor.id, {
      prompt: motionPrompt.trim(),
      duration: motionDuration,
    });
    setAnimateFor(null);
  };

  const startEdit = (e: React.MouseEvent, asset: MediaAsset) => {
    e.stopPropagation();
    setEditing(asset);
    setLabelInput(asset.label ?? '');
    setTagsInput((asset.tags ?? []).join(', '));
  };

  const saveEdit = async () => {
    if (!projectId || !editing) return;
    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
    await api.updateMedia(projectId, editing.id, {
      label: labelInput.trim() || null,
      tags,
    });
    await refreshMedia();
    setEditing(null);
  };

  const addQuickTag = (t: string) => {
    const cur = tagsInput
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean);
    if (!cur.includes(t)) setTagsInput([...cur, t].join(', '));
  };

  const onDragStart = (e: React.DragEvent, asset: MediaAsset) => {
    e.dataTransfer.setData('application/x-asset-id', asset.id);
    e.dataTransfer.effectAllowed = 'copy';
  };

  return (
    <div className={`relative flex h-full flex-col bg-panel ${className}`}>
      <div className="flex items-center justify-between border-b border-edge px-3 py-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-white/50">
          Media
        </h2>
        <button
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
          className="rounded bg-panel3 px-2 py-1 text-xs text-white/80 hover:bg-edge hover:text-white disabled:opacity-50"
        >
          {uploading ? 'Uploading…' : '+ Upload'}
        </button>
        <input
          ref={fileInput}
          type="file"
          multiple
          accept="image/*,video/*,audio/*"
          className="hidden"
          onChange={(e) => {
            onFiles(e.target.files);
            e.target.value = '';
          }}
        />
      </div>

      {/* filter + search */}
      {media.length > 0 && (
        <div className="space-y-1.5 border-b border-edge px-2 py-2">
          <div className="flex gap-1">
            {FILTER_KINDS.map((k) => (
              <button
                key={k}
                onClick={() => setFilterKind(k)}
                className={`flex-1 rounded px-1 py-1 text-[10px] capitalize ${
                  filterKind === k
                    ? 'bg-accent/20 text-accent'
                    : 'bg-panel3 text-white/50 hover:text-white'
                }`}
              >
                {k}
              </button>
            ))}
          </div>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name or tag…"
            className="w-full rounded bg-panel3 px-2 py-1 text-xs text-white outline-none ring-1 ring-edge focus:ring-accent"
          />
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-2">
        {media.length === 0 ? (
          <p className="px-1 pt-4 text-center text-xs text-white/30">
            No media yet. Upload images, video or audio to drag onto the timeline.
          </p>
        ) : filtered.length === 0 ? (
          <p className="px-1 pt-4 text-center text-xs text-white/30">
            No matches.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {filtered.map((asset) => (
              <div
                key={asset.id}
                draggable
                onClick={() => setPreviewAsset(asset)}
                onDragStart={(e) => onDragStart(e, asset)}
                onDoubleClick={() => addClipFromAsset(asset)}
                title={`${asset.label || asset.original_name} — click to preview, double-click to add at playhead`}
                className={`group relative cursor-grab overflow-hidden rounded-md border bg-panel2 active:cursor-grabbing ${
                  previewId === asset.id
                    ? 'border-accent ring-1 ring-accent'
                    : 'border-edge hover:border-accent/60'
                }`}
              >
                <div className="flex aspect-video items-center justify-center bg-panel3">
                  {asset.thumb_path ? (
                    <img
                      src={filesUrl(asset.thumb_path)}
                      alt={asset.label || asset.original_name}
                      draggable={false}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <span className="text-2xl opacity-60">
                      {KIND_ICON[asset.kind]}
                    </span>
                  )}
                </div>
                <div className="px-1.5 py-1">
                  <div className="truncate text-[10px] font-medium text-white/85">
                    {asset.label || asset.original_name}
                  </div>
                  {asset.tags && asset.tags.length > 0 && (
                    <div className="mt-0.5 flex flex-wrap gap-0.5">
                      {asset.tags.map((t) => (
                        <span
                          key={t}
                          className="rounded bg-accent/15 px-1 text-[8px] text-accent"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="absolute right-1 top-1 hidden gap-1 group-hover:flex">
                  {asset.kind === 'image' && (
                    <>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (projectId) api.varyImage(projectId, asset.id);
                        }}
                        className="flex h-5 w-5 items-center justify-center rounded bg-black/60 text-[10px] text-white/70 hover:text-accent"
                        title="Generate a variation"
                      >
                        🎲
                      </button>
                      <button
                        onClick={(e) => openAnimate(e, asset)}
                        className="flex h-5 w-5 items-center justify-center rounded bg-black/60 text-[10px] text-white/70 hover:text-high"
                        title="Turn into video"
                      >
                        🎬
                      </button>
                    </>
                  )}
                  <button
                    onClick={(e) => startEdit(e, asset)}
                    className="flex h-5 w-5 items-center justify-center rounded bg-black/60 text-[10px] text-white/70 hover:text-accent"
                    title="Name & tag"
                  >
                    ✎
                  </button>
                  <button
                    onClick={(e) => askRemove(e, asset)}
                    className="flex h-5 w-5 items-center justify-center rounded bg-black/60 text-[10px] text-white/70 hover:text-bass"
                    title="Delete"
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* name & tag editor */}
      {editing && (
        <div className="absolute inset-0 z-10 flex flex-col bg-panel/95 p-3 backdrop-blur">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-white/60">
              Name & tag
            </h3>
            <button
              onClick={() => setEditing(null)}
              className="text-white/40 hover:text-white"
            >
              ✕
            </button>
          </div>
          {editing.thumb_path && (
            <img
              src={filesUrl(editing.thumb_path)}
              className="mb-3 aspect-video w-full rounded object-cover"
              alt=""
            />
          )}
          <label className="mb-1 text-[10px] uppercase tracking-wider text-white/40">
            Name
          </label>
          <input
            value={labelInput}
            onChange={(e) => setLabelInput(e.target.value)}
            placeholder="e.g. Kevin"
            autoFocus
            className="mb-3 rounded bg-panel3 px-2 py-1.5 text-sm text-white outline-none ring-1 ring-edge focus:ring-accent"
          />
          <label className="mb-1 text-[10px] uppercase tracking-wider text-white/40">
            Tags (comma separated)
          </label>
          <input
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            placeholder="e.g. character"
            onKeyDown={(e) => e.key === 'Enter' && saveEdit()}
            className="mb-2 rounded bg-panel3 px-2 py-1.5 text-sm text-white outline-none ring-1 ring-edge focus:ring-accent"
          />
          <div className="mb-4 flex flex-wrap gap-1">
            {QUICK_TAGS.map((t) => (
              <button
                key={t}
                onClick={() => addQuickTag(t)}
                className="rounded-full bg-panel3 px-2 py-0.5 text-[10px] text-white/60 hover:bg-accent/20 hover:text-accent"
              >
                + {t}
              </button>
            ))}
          </div>
          <div className="mt-auto flex gap-2">
            <button
              onClick={saveEdit}
              className="flex-1 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent/80"
            >
              Save
            </button>
            <button
              onClick={() => setEditing(null)}
              className="rounded bg-panel3 px-3 py-1.5 text-sm text-white/70 hover:bg-edge"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* delete confirmation */}
      {confirmDel && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/70 p-4 text-center backdrop-blur">
          {confirmDel.thumb_path && (
            <img
              src={filesUrl(confirmDel.thumb_path)}
              className="mb-3 aspect-video w-32 rounded object-cover ring-1 ring-edge"
              alt=""
            />
          )}
          <p className="mb-1 text-sm text-white">Delete this asset?</p>
          <p className="mb-4 max-w-[200px] truncate text-xs text-white/50">
            {confirmDel.label || confirmDel.original_name}
          </p>
          <div className="flex gap-2">
            <button
              onClick={doRemove}
              className="rounded bg-bass px-4 py-1.5 text-sm font-medium text-white hover:bg-bass/80"
            >
              Delete
            </button>
            <button
              onClick={() => setConfirmDel(null)}
              className="rounded bg-panel3 px-4 py-1.5 text-sm text-white/70 hover:bg-edge"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* image → video */}
      {animateFor && (
        <div className="absolute inset-0 z-20 flex flex-col bg-panel/95 p-3 backdrop-blur">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-white/60">
              Turn into video
            </h3>
            <button
              onClick={() => setAnimateFor(null)}
              className="text-white/40 hover:text-white"
            >
              ✕
            </button>
          </div>
          {animateFor.thumb_path && (
            <img
              src={filesUrl(animateFor.thumb_path)}
              className="mb-3 aspect-video w-full rounded object-cover"
              alt=""
            />
          )}
          <label className="mb-1 text-[10px] uppercase tracking-wider text-white/40">
            Motion (optional)
          </label>
          <textarea
            value={motionPrompt}
            onChange={(e) => setMotionPrompt(e.target.value)}
            placeholder="e.g. slow push-in, drifting steam, rippling water"
            rows={2}
            className="mb-3 resize-none rounded bg-panel3 px-2 py-1.5 text-sm text-white outline-none ring-1 ring-edge focus:ring-accent"
          />
          <label className="mb-1 text-[10px] uppercase tracking-wider text-white/40">
            Duration
          </label>
          <div className="mb-3 flex gap-1.5">
            {MOTION_DURATIONS.map((d) => (
              <button
                key={d}
                onClick={() => setMotionDuration(d)}
                className={`flex-1 rounded py-1.5 text-xs ${
                  motionDuration === d
                    ? 'bg-accent/20 text-accent ring-1 ring-accent/40'
                    : 'bg-panel3 text-white/60 hover:text-white'
                }`}
              >
                {d}s
              </button>
            ))}
          </div>
          <p className="mb-3 text-[10px] leading-relaxed text-white/35">
            Generated with Kling · ~1–2 min · runs in the background (watch the
            queue).
          </p>
          <div className="mt-auto flex gap-2">
            <button
              onClick={doAnimate}
              className="flex-1 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent/80"
            >
              Generate video
            </button>
            <button
              onClick={() => setAnimateFor(null)}
              className="rounded bg-panel3 px-3 py-1.5 text-sm text-white/70 hover:bg-edge"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

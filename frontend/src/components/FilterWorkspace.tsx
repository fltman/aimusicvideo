import { useCallback, useEffect, useRef, useState } from 'react';
import { useEditor } from '../store/editorStore';
import { api } from '../api/client';
import FilterControls from './FilterControls';
import type {
  Clip,
  FilterChatMsg,
  FilterDetail,
  FilterParam,
} from '../types';

type Tab = 'chat' | 'code' | 'versions';
type RenderStatus = 'idle' | 'rendering' | 'error';

/** preview_url is already a /files/... path on the produced asset. */
interface PreviewAsset {
  preview_url?: string | null;
}

const POLL_MS = 2000;

/** Build the effective param values for a clip from defaults + overrides. */
function buildValues(
  params: FilterParam[],
  overrides: Record<string, unknown> | undefined,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const p of params) out[p.key] = p.default;
  if (overrides) for (const k of Object.keys(overrides)) out[k] = overrides[k];
  return out;
}

/**
 * Full-screen filter editing workspace. Self-gates on the store: renders
 * nothing unless an effect clip is open. Left = preview + controls, right =
 * Chat (vibe-code) / Code / Versions.
 */
export default function FilterWorkspace() {
  const clipId = useEditor((s) => s.filterWorkspaceClipId);
  if (!clipId) return null;
  return <Workspace clipId={clipId} />;
}

function Workspace({ clipId }: { clipId: string }) {
  // ── narrow store slices ────────────────────────────────────────────────
  const projectId = useEditor((s) => s.projectId);
  const clip = useEditor((s) => s.clips.find((c) => c.id === clipId)) as
    | Clip
    | undefined;
  const updateClipParams = useEditor((s) => s.updateClipParams);
  const setClipFilter = useEditor((s) => s.setClipFilter);
  const closeFilterWorkspace = useEditor((s) => s.closeFilterWorkspace);

  const filterId = clip?.filterId ?? null;

  // ── local state ────────────────────────────────────────────────────────
  const [detail, setDetail] = useState<FilterDetail | null>(null);
  const [chat, setChat] = useState<FilterChatMsg[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [tab, setTab] = useState<Tab>('chat');

  // preview
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [renderStatus, setRenderStatus] = useState<RenderStatus>('idle');
  const [renderError, setRenderError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(true); // no preview yet ⇒ dirty

  // chat
  const [chatInput, setChatInput] = useState('');
  const [vibing, setVibing] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  // code editor
  const [codeDraft, setCodeDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // versions
  const [restoring, setRestoring] = useState<number | null>(null);

  // guards / async cleanup
  const renderingRef = useRef(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aliveRef = useRef(true);
  const chatScrollRef = useRef<HTMLDivElement>(null);

  const clearPoll = useCallback(() => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // effective values fed to the controls (defaults + clip overrides)
  const values = detail
    ? buildValues(detail.params, clip?.params)
    : (clip?.params ?? {});

  // ── preview render (single in-flight) ──────────────────────────────────
  // Kept in a ref so async chat/restore handlers can call the latest version.
  const renderRef = useRef<() => void>(() => {});

  const renderPreview = useCallback(() => {
    if (!projectId || !filterId) return;
    if (renderingRef.current) return;
    renderingRef.current = true;
    clearPoll();
    setRenderStatus('rendering');
    setRenderError(null);
    setDirty(false); // a render is now reflecting the current params

    const params = buildValues(detail?.params ?? [], clip?.params);
    const cursor = useEditor.getState().currentTime;

    const poll = (jobId: string) => {
      pollRef.current = setTimeout(async () => {
        if (!aliveRef.current) return;
        try {
          const job = await api.jobStatus(jobId);
          if (!aliveRef.current) return;
          if (job.status === 'done') {
            const asset = job.asset as (typeof job.asset & PreviewAsset) | null;
            const url = asset?.preview_url ?? null;
            setPreviewUrl(url);
            setRenderStatus('idle');
            renderingRef.current = false;
          } else if (job.status === 'error') {
            setRenderError(job.error ?? 'Render failed');
            setRenderStatus('error');
            renderingRef.current = false;
          } else {
            poll(jobId); // pending | running
          }
        } catch (e) {
          if (!aliveRef.current) return;
          setRenderError(e instanceof Error ? e.message : 'Render failed');
          setRenderStatus('error');
          renderingRef.current = false;
        }
      }, POLL_MS);
    };

    api
      .renderFilterPreview(projectId, filterId, params, cursor)
      .then(({ job_id }) => {
        if (!aliveRef.current) return;
        poll(job_id);
      })
      .catch((e) => {
        if (!aliveRef.current) return;
        setRenderError(e instanceof Error ? e.message : 'Render failed');
        setRenderStatus('error');
        renderingRef.current = false;
      });
  }, [projectId, filterId, detail, clip, clearPoll]);

  renderRef.current = renderPreview;

  // ── load filter detail + chat when filterId changes ────────────────────
  useEffect(() => {
    aliveRef.current = true;
    if (!filterId) {
      setLoading(false);
      setLoadError('This clip has no filter assigned.');
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setPreviewUrl(null);
    setRenderStatus('idle');
    renderingRef.current = false;
    clearPoll();

    (async () => {
      try {
        const [d, history] = await Promise.all([
          api.getFilter(filterId),
          api.getFilterChat(filterId).catch(() => [] as FilterChatMsg[]),
        ]);
        if (cancelled) return;
        setDetail(d);
        setCodeDraft(d.code);
        setChat(history);
        setLoading(false);
        setDirty(true);
        // auto-trigger the first preview once loaded
        renderRef.current();
      } catch (e) {
        if (cancelled) return;
        setLoadError(e instanceof Error ? e.message : 'Failed to load filter');
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterId]);

  // unmount cleanup
  useEffect(() => {
    return () => {
      aliveRef.current = false;
      clearPoll();
    };
  }, [clearPoll]);

  // Esc closes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeFilterWorkspace();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [closeFilterWorkspace]);

  // keep chat scrolled to the bottom
  useEffect(() => {
    chatScrollRef.current?.scrollTo({
      top: chatScrollRef.current.scrollHeight,
    });
  }, [chat, vibing]);

  // ── re-fetch detail (after chat patch / save / rollback) ───────────────
  const refetchDetail = useCallback(async () => {
    if (!filterId) return null;
    const d = await api.getFilter(filterId);
    if (!aliveRef.current) return d;
    setDetail(d);
    setCodeDraft(d.code);
    return d;
  }, [filterId]);

  // ── control change ─────────────────────────────────────────────────────
  const onParamChange = useCallback(
    (key: string, val: unknown) => {
      updateClipParams(clipId, { [key]: val });
      setDirty(true);
    },
    [clipId, updateClipParams],
  );

  // ── chat (vibe-code) ───────────────────────────────────────────────────
  const sendChat = async () => {
    const message = chatInput.trim();
    if (!message || !filterId || vibing) return;
    setChatInput('');
    setChatError(null);
    setChat((c) => [...c, { role: 'user', content: message }]);
    setVibing(true);
    try {
      const res = await api.filterChat(filterId, message);
      if (!aliveRef.current) return;
      setChat((c) => [...c, { role: 'assistant', content: res.reply }]);
      if (res.error) {
        setChatError(res.error);
      } else if (res.version != null) {
        // code / params / versions changed — re-pull and re-render
        await refetchDetail();
        if (!aliveRef.current) return;
        setDirty(true);
        renderRef.current();
      }
    } catch (e) {
      if (!aliveRef.current) return;
      setChatError(e instanceof Error ? e.message : 'Vibe-coding failed');
    } finally {
      if (aliveRef.current) setVibing(false);
    }
  };

  // ── code save ──────────────────────────────────────────────────────────
  const saveCode = async () => {
    if (!filterId || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const d = await api.saveFilter(filterId, codeDraft, 'Manual edit');
      if (!aliveRef.current) return;
      setDetail(d);
      setCodeDraft(d.code);
      setDirty(true);
      renderRef.current();
    } catch (e) {
      if (!aliveRef.current) return;
      setSaveError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      if (aliveRef.current) setSaving(false);
    }
  };

  // ── version restore ────────────────────────────────────────────────────
  const restore = async (version: number) => {
    if (!filterId || restoring != null) return;
    setRestoring(version);
    try {
      const d = await api.rollbackFilter(filterId, version);
      if (!aliveRef.current) return;
      setDetail(d);
      setCodeDraft(d.code);
      setDirty(true);
      renderRef.current();
    } catch {
      // surfaced via the (now stale) detail; keep it quiet but recoverable
    } finally {
      if (aliveRef.current) setRestoring(null);
    }
  };

  // ── fork ───────────────────────────────────────────────────────────────
  const fork = async () => {
    if (!filterId) return;
    const name = window.prompt(
      'Name for the forked filter',
      detail ? `${detail.manifest.name} copy` : 'Filter copy',
    );
    if (!name || !name.trim()) return;
    try {
      const res = await api.forkFilter(filterId, name.trim());
      if (!aliveRef.current) return;
      // reassign the clip to the new filter — the effect above reloads.
      setClipFilter(clipId, res.manifest.id, res.manifest.name);
    } catch (e) {
      window.alert(
        `Save as failed: ${e instanceof Error ? e.message : 'unknown error'}`,
      );
    }
  };

  // ── rename (custom filters only) ────────────────────────────────────────
  const renameFilter = async () => {
    if (!filterId || !detail || detail.manifest.builtin) return;
    const name = window.prompt('Rename filter', detail.manifest.name);
    if (!name || !name.trim() || name.trim() === detail.manifest.name) return;
    try {
      const res = await api.renameFilter(filterId, name.trim());
      if (!aliveRef.current) return;
      setDetail(res);
      setClipFilter(clipId, res.manifest.id, res.manifest.name);
    } catch (e) {
      window.alert(
        `Rename failed: ${e instanceof Error ? e.message : 'unknown error'}`,
      );
    }
  };

  const manifest = detail?.manifest;
  const versionsNewestFirst = detail
    ? [...detail.versions].sort((a, b) => b.version - a.version)
    : [];
  const renderHighlight = dirty || !previewUrl;

  // ── render ─────────────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-panel text-white">
      {/* header */}
      <header className="flex items-center gap-3 border-b border-edge bg-panel2 px-4 py-2.5">
        <div className="flex min-w-0 items-baseline gap-2">
          {manifest && !manifest.builtin ? (
            <button
              onClick={renameFilter}
              className="group flex items-baseline gap-1 truncate text-sm font-semibold text-white"
              title="Rename filter"
            >
              <span className="truncate">{manifest.name}</span>
              <span className="text-[11px] text-white/30 group-hover:text-accent">✎</span>
            </button>
          ) : (
            <h1 className="truncate text-sm font-semibold text-white">
              {manifest?.name ?? clip?.name ?? 'Filter'}
            </h1>
          )}
          {manifest && (
            <span className="font-mono text-[11px] text-white/40">
              v{manifest.version}
            </span>
          )}
          {manifest?.builtin && (
            <span className="rounded bg-panel3 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-white/40">
              built-in
            </span>
          )}
          {manifest?.forkedFrom && (
            <span className="rounded bg-panel3 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-white/40">
              custom
            </span>
          )}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={fork}
            disabled={!filterId}
            className="rounded bg-high/15 px-2.5 py-1 text-xs text-high ring-1 ring-high/30 hover:bg-high/25 disabled:opacity-40"
            title="Save the current filter as a new named filter in your library"
          >
            💾 Save as…
          </button>
          <button
            onClick={closeFilterWorkspace}
            className="flex h-7 w-7 items-center justify-center rounded text-white/50 hover:bg-panel3 hover:text-white"
            title="Close (Esc)"
          >
            ✕
          </button>
        </div>
      </header>

      {loadError ? (
        <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-bass">
          {loadError}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          {/* LEFT: preview + controls */}
          <section className="flex min-h-0 w-[55%] flex-col border-r border-edge">
            <div className="flex flex-col gap-3 p-4">
              {/* 16:9 preview */}
              <div className="relative aspect-video w-full overflow-hidden rounded-lg border border-edge bg-black">
                {previewUrl ? (
                  <video
                    key={previewUrl}
                    src={previewUrl}
                    className="h-full w-full object-contain"
                    autoPlay
                    loop
                    muted
                    playsInline
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-center text-xs text-white/30">
                    {renderStatus === 'rendering'
                      ? 'Rendering preview…'
                      : renderStatus === 'error'
                        ? 'Preview failed — try rendering again.'
                        : 'No preview yet.'}
                  </div>
                )}
                {renderStatus === 'rendering' && (
                  <div className="absolute inset-x-0 bottom-0 flex items-center gap-2 bg-black/60 px-3 py-1.5 text-[11px] text-white/70">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                    rendering…
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => renderRef.current()}
                  disabled={renderStatus === 'rendering' || loading || !filterId}
                  className={[
                    'rounded px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50',
                    renderHighlight
                      ? 'bg-accent text-white hover:bg-accent/80'
                      : 'bg-panel3 text-white/70 hover:bg-edge hover:text-white',
                  ].join(' ')}
                >
                  {renderStatus === 'rendering'
                    ? 'Rendering…'
                    : renderHighlight
                      ? '▶ Render preview'
                      : '↻ Re-render'}
                </button>
                {dirty && renderStatus !== 'rendering' && (
                  <span className="text-[11px] text-mid">
                    params changed — preview is stale
                  </span>
                )}
                {renderError && (
                  <span className="truncate text-[11px] text-bass">
                    {renderError}
                  </span>
                )}
              </div>
            </div>

            {/* controls */}
            <div className="min-h-0 flex-1 overflow-y-auto border-t border-edge px-4 py-3">
              {loading ? (
                <p className="text-xs text-white/30">Loading controls…</p>
              ) : detail && detail.params.length > 0 ? (
                <FilterControls
                  params={detail.params}
                  values={values}
                  onChange={onParamChange}
                />
              ) : (
                <p className="text-xs text-white/30">
                  This filter exposes no parameters.
                </p>
              )}
            </div>
          </section>

          {/* RIGHT: chat / code / versions */}
          <section className="flex min-h-0 w-[45%] flex-col bg-panel">
            <div className="flex border-b border-edge">
              {(['chat', 'code', 'versions'] as Tab[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={[
                    'flex-1 px-3 py-2 text-xs font-medium capitalize transition-colors',
                    tab === t
                      ? 'border-b-2 border-accent text-white'
                      : 'border-b-2 border-transparent text-white/40 hover:text-white/70',
                  ].join(' ')}
                >
                  {t === 'chat'
                    ? 'Chat'
                    : t === 'code'
                      ? 'Code'
                      : `Versions${
                          detail ? ` (${detail.versions.length})` : ''
                        }`}
                </button>
              ))}
            </div>

            {/* ── CHAT ── */}
            {tab === 'chat' && (
              <div className="flex min-h-0 flex-1 flex-col">
                <div
                  ref={chatScrollRef}
                  className="flex-1 space-y-3 overflow-y-auto px-3 py-3"
                >
                  {chat.length === 0 && !vibing && (
                    <p className="pt-4 text-center text-xs leading-relaxed text-white/30">
                      Describe how the look should change and I'll rewrite the
                      filter.
                      <br />
                      <span className="text-white/20">
                        e.g. “add chromatic aberration that pulses on the bass”.
                      </span>
                    </p>
                  )}
                  {chat.map((m, i) => (
                    <div
                      key={i}
                      className={m.role === 'user' ? 'text-right' : 'text-left'}
                    >
                      <div
                        className={[
                          'inline-block max-w-[92%] rounded-lg px-2.5 py-1.5 text-left text-xs leading-relaxed',
                          m.role === 'user'
                            ? 'bg-accent/20 text-white'
                            : 'bg-panel2 text-white/80',
                        ].join(' ')}
                      >
                        <p className="whitespace-pre-wrap">{m.content}</p>
                      </div>
                    </div>
                  ))}
                  {vibing && (
                    <div className="text-left">
                      <div className="inline-flex items-center gap-2 rounded-lg bg-panel2 px-2.5 py-1.5 text-xs text-white/50">
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-high" />
                        vibe-coding… (this can take ~30–60s)
                      </div>
                    </div>
                  )}
                  {chatError && (
                    <div className="text-left">
                      <div className="inline-block max-w-[92%] rounded-lg bg-bass/20 px-2.5 py-1.5 text-xs text-bass">
                        {chatError}
                      </div>
                    </div>
                  )}
                </div>
                <div className="border-t border-edge p-2">
                  <div className="flex gap-1.5">
                    <input
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && sendChat()}
                      disabled={vibing}
                      placeholder="Describe the change…"
                      className="min-w-0 flex-1 rounded-md bg-panel3 px-2.5 py-1.5 text-xs text-white outline-none ring-1 ring-edge focus:ring-accent disabled:opacity-50"
                    />
                    <button
                      onClick={sendChat}
                      disabled={vibing || !chatInput.trim()}
                      className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/80 disabled:opacity-40"
                    >
                      ↑
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* ── CODE ── */}
            {tab === 'code' && (
              <div className="flex min-h-0 flex-1 flex-col">
                <textarea
                  value={codeDraft}
                  onChange={(e) => setCodeDraft(e.target.value)}
                  spellCheck={false}
                  placeholder={loading ? 'Loading…' : ''}
                  className="min-h-0 flex-1 resize-none bg-panel3 px-3 py-3 font-mono text-[11px] leading-relaxed text-white/90 outline-none"
                />
                <div className="flex items-center gap-2 border-t border-edge p-2">
                  <button
                    onClick={saveCode}
                    disabled={saving || loading || codeDraft === detail?.code}
                    className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/80 disabled:opacity-40"
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                  {codeDraft !== detail?.code && !saving && (
                    <span className="text-[11px] text-mid">unsaved changes</span>
                  )}
                  {saveError && (
                    <span className="truncate text-[11px] text-bass">
                      {saveError}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* ── VERSIONS ── */}
            {tab === 'versions' && (
              <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {versionsNewestFirst.length === 0 ? (
                  <p className="pt-4 text-center text-xs text-white/30">
                    No version history yet.
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {versionsNewestFirst.map((v) => {
                      const current = v.version === manifest?.version;
                      return (
                        <li
                          key={v.version}
                          className="flex items-start gap-2 rounded-md bg-panel2 px-2.5 py-2"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-[11px] text-white/80">
                                v{v.version}
                              </span>
                              {current && (
                                <span className="rounded bg-accent/20 px-1 text-[9px] uppercase tracking-wider text-accent">
                                  current
                                </span>
                              )}
                              <span className="ml-auto text-[10px] text-white/30">
                                {v.ts}
                              </span>
                            </div>
                            <p className="mt-0.5 truncate text-xs text-white/60">
                              {v.message || '—'}
                            </p>
                          </div>
                          <button
                            onClick={() => restore(v.version)}
                            disabled={current || restoring != null}
                            className="shrink-0 rounded bg-panel3 px-2 py-1 text-[11px] text-white/70 hover:bg-edge hover:text-white disabled:opacity-30"
                          >
                            {restoring === v.version ? 'Restoring…' : 'Restore'}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

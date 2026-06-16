import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { FilterManifest } from '../types';

interface Props {
  open: boolean;
  onClose: () => void;
  onPick: (filter: FilterManifest) => void;
}

/** Modal overlay to browse, create and pick filter plugins. Self-contained:
 *  owns its own filter list + loading state, fetched on open. */
export default function FilterBrowser({ open, onClose, onPick }: Props) {
  const [filters, setFilters] = useState<FilterManifest[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  // inline "new filter" name entry
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);

  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await api.listFilters();
      setFilters(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load filters');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    setSearch('');
    setCreating(false);
    setNewName('');
    setError(null);
    void load();
  }, [open]);

  // Esc to close
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return filters;
    return filters.filter((f) => {
      const hay = [f.name, f.description, ...(f.tags ?? [])]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
  }, [filters, search]);

  // template (empty starting point) shown first + distinctly
  const ordered = useMemo(() => {
    const tpl = filtered.filter((f) => f.template === true);
    const rest = filtered.filter((f) => f.template !== true);
    return [...tpl, ...rest];
  }, [filtered]);

  const pick = (f: FilterManifest) => {
    onPick(f);
    onClose();
  };

  const doCreate = async () => {
    const name = newName.trim();
    if (!name || busy) return;
    setBusy(true);
    setError(null);
    try {
      const detail = await api.createFilter(name);
      onPick(detail.manifest);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create filter');
      setBusy(false);
    }
  };

  const doDelete = async (e: React.MouseEvent, f: FilterManifest) => {
    e.stopPropagation();
    if (deletingId) return;
    setDeletingId(f.id);
    setError(null);
    try {
      await api.deleteFilter(f.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete filter');
    } finally {
      setDeletingId(null);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-edge bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-center justify-between border-b border-edge px-5 py-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white/70">
            Filters
          </h2>
          <div className="flex items-center gap-2">
            {creating ? (
              <div className="flex items-center gap-1.5">
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void doCreate();
                    if (e.key === 'Escape') {
                      setCreating(false);
                      setNewName('');
                    }
                  }}
                  autoFocus
                  placeholder="Filter name…"
                  disabled={busy}
                  className="w-44 rounded bg-panel3 px-2 py-1 text-xs text-white outline-none ring-1 ring-edge focus:ring-accent disabled:opacity-50"
                />
                <button
                  onClick={() => void doCreate()}
                  disabled={busy || !newName.trim()}
                  className="rounded bg-accent px-2.5 py-1 text-xs font-medium text-white hover:bg-accent/80 disabled:opacity-40"
                >
                  {busy ? 'Creating…' : 'Create'}
                </button>
                <button
                  onClick={() => {
                    setCreating(false);
                    setNewName('');
                  }}
                  disabled={busy}
                  className="rounded bg-panel3 px-2 py-1 text-xs text-white/60 hover:bg-edge hover:text-white disabled:opacity-40"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => {
                  setCreating(true);
                  setNewName('');
                }}
                className="rounded bg-accent px-3 py-1 text-xs font-medium text-white hover:bg-accent/80"
              >
                + New filter
              </button>
            )}
            <button
              onClick={onClose}
              title="Close"
              className="flex h-6 w-6 items-center justify-center rounded text-white/40 hover:bg-panel3 hover:text-white"
            >
              ✕
            </button>
          </div>
        </div>

        {/* search */}
        <div className="border-b border-edge px-5 py-2.5">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search filters by name, description or tag…"
            className="w-full rounded bg-panel3 px-3 py-1.5 text-xs text-white outline-none ring-1 ring-edge focus:ring-accent"
          />
        </div>

        {error && (
          <div className="border-b border-edge bg-bass/10 px-5 py-2 text-xs text-bass">
            {error}
          </div>
        )}

        {/* body */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading ? (
            <p className="pt-8 text-center text-xs text-white/30">Loading…</p>
          ) : ordered.length === 0 ? (
            <p className="pt-8 text-center text-xs text-white/30">
              {filters.length === 0
                ? 'No filters yet. Create one to get started.'
                : 'No matches.'}
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {ordered.map((f) => {
                const isTemplate = f.template === true;
                const canDelete = f.builtin !== true;
                return (
                  <button
                    key={f.id}
                    onClick={() => pick(f)}
                    title={`Use “${f.name}”`}
                    className={[
                      'group relative flex flex-col rounded-lg border p-3 text-left transition-colors',
                      isTemplate
                        ? 'border-dashed border-accent/50 bg-accent/5 hover:border-accent hover:bg-accent/10'
                        : 'border-edge bg-panel2 hover:border-accent/60 hover:bg-panel3',
                    ].join(' ')}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          {isTemplate && (
                            <span className="text-xs leading-none text-accent">
                              ✦
                            </span>
                          )}
                          <span className="truncate text-sm font-medium text-white/90">
                            {isTemplate ? 'Start from scratch' : f.name}
                          </span>
                        </div>
                        <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-white/45">
                          {f.description ||
                            (isTemplate
                              ? 'A blank filter to build your own effect.'
                              : 'No description.')}
                        </p>
                      </div>
                      {!isTemplate && (
                        <span className="shrink-0 rounded bg-panel3 px-1.5 py-0.5 font-mono text-[9px] text-white/40">
                          v{f.version}
                        </span>
                      )}
                    </div>

                    {f.tags && f.tags.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {f.tags.map((t) => (
                          <span
                            key={t}
                            className="rounded bg-accent/15 px-1.5 py-0.5 text-[9px] text-accent"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    )}

                    {(f.builtin === true ||
                      typeof f.param_count === 'number') && (
                      <div className="mt-2 flex items-center gap-2 text-[9px] text-white/30">
                        {f.builtin === true && (
                          <span className="rounded bg-high/15 px-1.5 py-0.5 text-high/80">
                            built-in
                          </span>
                        )}
                        {typeof f.param_count === 'number' && (
                          <span>
                            {f.param_count} param
                            {f.param_count === 1 ? '' : 's'}
                          </span>
                        )}
                      </div>
                    )}

                    {canDelete && !isTemplate && (
                      <span
                        role="button"
                        tabIndex={-1}
                        onClick={(e) => void doDelete(e, f)}
                        title="Delete filter"
                        className="absolute right-2 top-2 hidden h-5 w-5 items-center justify-center rounded bg-black/40 text-[10px] text-white/50 hover:bg-bass/20 hover:text-bass group-hover:flex"
                      >
                        {deletingId === f.id ? '…' : '✕'}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

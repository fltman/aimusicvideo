import { useCallback, useEffect, useState } from 'react';
import { api, filesUrl } from '../api/client';
import type { ProjectSummary, AnalysisStatus } from '../types';
import { fmtClock } from '../lib/format';

const STATUS_STYLE: Record<AnalysisStatus, string> = {
  none: 'bg-panel3 text-white/50',
  processing: 'bg-mid/20 text-mid',
  done: 'bg-accent/20 text-accent',
  error: 'bg-bass/20 text-bass',
};

const STATUS_LABEL: Record<AnalysisStatus, string> = {
  none: 'No song',
  processing: 'Analyzing…',
  done: 'Ready',
  error: 'Error',
};

export default function ProjectsView() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');

  const refresh = useCallback(async () => {
    try {
      setProjects(await api.listProjects());
    } catch {
      /* ignore — backend may not be up yet */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const open = (id: string) => {
    window.location.hash = `#/project/${id}`;
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    const n = name.trim();
    if (!n) return;
    const proj = await api.createProject(n);
    setName('');
    setCreating(false);
    open(proj.id);
  };

  const remove = async (e: React.MouseEvent, p: ProjectSummary) => {
    e.stopPropagation();
    if (!window.confirm(`Delete project “${p.name}”? This cannot be undone.`)) return;
    await api.deleteProject(p.id);
    refresh();
  };

  return (
    <div className="h-full overflow-y-auto bg-[#0f1014]">
      <header className="sticky top-0 z-10 border-b border-edge bg-panel/95 backdrop-blur px-8 py-5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-accent to-high" />
          <h1 className="text-xl font-semibold tracking-tight">AI Music Video Studio</h1>
        </div>
        <button
          onClick={() => setCreating((c) => !c)}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 transition-colors"
        >
          + New Project
        </button>
      </header>

      <main className="mx-auto max-w-6xl px-8 py-8">
        {creating && (
          <form
            onSubmit={create}
            className="mb-6 flex gap-2 rounded-lg border border-edge bg-panel2 p-3"
          >
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Project name…"
              className="flex-1 rounded-md bg-panel3 px-3 py-2 text-sm outline-none ring-1 ring-edge focus:ring-accent"
            />
            <button
              type="submit"
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90"
            >
              Create
            </button>
            <button
              type="button"
              onClick={() => {
                setCreating(false);
                setName('');
              }}
              className="rounded-md px-3 py-2 text-sm text-white/60 hover:text-white"
            >
              Cancel
            </button>
          </form>
        )}

        {loading ? (
          <p className="text-white/40">Loading…</p>
        ) : projects.length === 0 ? (
          <div className="rounded-xl border border-dashed border-edge bg-panel2/50 py-20 text-center">
            <p className="text-white/50">No projects yet.</p>
            <button
              onClick={() => setCreating(true)}
              className="mt-3 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90"
            >
              Create your first project
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <div
                key={p.id}
                onClick={() => open(p.id)}
                className="group relative cursor-pointer rounded-xl border border-edge bg-panel2 p-4 transition-colors hover:border-accent/60 hover:bg-panel3"
              >
                <div className="mb-3 aspect-video overflow-hidden rounded-lg bg-gradient-to-br from-panel3 to-panel">
                  {p.thumb ? (
                    <img
                      src={filesUrl(p.thumb)}
                      alt=""
                      className="h-full w-full object-cover transition-transform group-hover:scale-[1.03]"
                    />
                  ) : p.palette && p.palette.length > 0 ? (
                    <div className="flex h-full w-full">
                      {p.palette.slice(0, 5).map((c, i) => (
                        <div key={i} className="flex-1" style={{ background: c }} />
                      ))}
                    </div>
                  ) : (
                    <div className="flex h-full w-full items-center justify-center">
                      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/20 text-accent ring-1 ring-accent/40">
                        ♪
                      </div>
                    </div>
                  )}
                </div>
                <div className="flex items-start justify-between gap-2">
                  <h3 className="truncate font-medium">{p.name}</h3>
                  <button
                    onClick={(e) => remove(e, p)}
                    className="opacity-0 group-hover:opacity-100 rounded px-1.5 text-white/40 hover:text-bass transition"
                    title="Delete"
                  >
                    ✕
                  </button>
                </div>
                <div className="mt-2 flex items-center justify-between text-xs">
                  <span
                    className={`rounded px-2 py-0.5 ${STATUS_STYLE[p.analysis_status]}`}
                  >
                    {STATUS_LABEL[p.analysis_status]}
                    {p.analysis_status === 'processing' &&
                      ` ${Math.round(p.analysis_progress * 100)}%`}
                  </span>
                  <span className="text-white/40 tabular-nums">
                    {p.duration_sec != null ? fmtClock(p.duration_sec) : '—'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

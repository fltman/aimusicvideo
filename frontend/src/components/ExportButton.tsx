import { useRef, useState } from 'react';
import { useEditor } from '../store/editorStore';
import { api } from '../api/client';

const RESOLUTIONS = ['480p', '720p', '1080p'];

/** Export the full timeline (with the effect-clip filter chain) to an mp4. */
export default function ExportButton() {
  const projectId = useEditor((s) => s.projectId);

  const [open, setOpen] = useState(false);
  const [resolution, setResolution] = useState('720p');
  const [burnLyrics, setBurnLyrics] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const run = async () => {
    if (!projectId || exporting) return;
    setExporting(true);
    setProgress(0);
    setDownloadUrl(null);
    setError(null);
    try {
      const { job_id, export_id } = await api.exportVideo(
        projectId,
        resolution,
        burnLyrics,
      );
      timer.current = setInterval(async () => {
        try {
          const [p, job] = await Promise.all([
            api.exportProgress(projectId, export_id),
            api.jobStatus(job_id),
          ]);
          setProgress(p.progress);
          if (job.status === 'done') {
            stop();
            const url = (job.asset as unknown as { export_url?: string } | null)
              ?.export_url;
            setDownloadUrl(url ?? null);
            setExporting(false);
            setProgress(1);
          } else if (job.status === 'error') {
            stop();
            setError(job.error ?? 'Export failed');
            setExporting(false);
          }
        } catch {
          /* keep polling */
        }
      }, 1500);
    } catch (e) {
      setExporting(false);
      setError(e instanceof Error ? e.message : 'Export failed');
    }
  };

  const stop = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/90"
        title="Export video"
      >
        ⬇ Export
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-64 rounded-lg border border-edge bg-panel2 p-3 shadow-xl shadow-black/50">
          <div className="mb-2 text-[10px] uppercase tracking-wider text-white/40">
            Export video
          </div>
          <div className="mb-3 flex gap-1.5">
            {RESOLUTIONS.map((r) => (
              <button
                key={r}
                onClick={() => setResolution(r)}
                disabled={exporting}
                className={`flex-1 rounded py-1.5 text-xs ${
                  resolution === r
                    ? 'bg-accent/20 text-accent ring-1 ring-accent/40'
                    : 'bg-panel3 text-white/60 hover:text-white'
                } disabled:opacity-40`}
              >
                {r}
              </button>
            ))}
          </div>

          <label className="mb-3 flex items-center gap-2 text-xs text-white/70">
            <input
              type="checkbox"
              checked={burnLyrics}
              onChange={(e) => setBurnLyrics(e.target.checked)}
              disabled={exporting}
              className="accent-accent"
            />
            Burn lyrics into video
          </label>

          {exporting ? (
            <div>
              <div className="mb-1 flex justify-between text-[11px] text-white/50">
                <span>Rendering…</span>
                <span className="tabular-nums">{Math.round(progress * 100)}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-panel3">
                <div
                  className="h-full rounded-full bg-accent transition-all"
                  style={{ width: `${Math.round(progress * 100)}%` }}
                />
              </div>
              <p className="mt-2 text-[10px] text-white/35">
                Compositing the timeline + effect chain. This can take a few
                minutes for a full song.
              </p>
            </div>
          ) : downloadUrl ? (
            <a
              href={downloadUrl}
              download
              className="block rounded bg-high/20 py-2 text-center text-sm font-medium text-high ring-1 ring-high/40 hover:bg-high/30"
            >
              ⬇ Download video
            </a>
          ) : (
            <button
              onClick={run}
              className="w-full rounded bg-accent py-2 text-sm font-medium text-white hover:bg-accent/80"
            >
              Render video
            </button>
          )}
          {error && <p className="mt-2 text-[11px] text-bass">{error}</p>}
        </div>
      )}
    </div>
  );
}

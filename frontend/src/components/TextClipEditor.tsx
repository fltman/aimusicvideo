import { useEditor } from '../store/editorStore';
import { textTypography } from '../lib/textStyle';
import type { Clip } from '../types';

const FONTS = ['sans', 'serif', 'mono', 'display', 'elegant'] as const;
const ANIMS = ['none', 'fade', 'typewriter', 'slide'] as const;
const POSITIONS = ['top', 'center', 'bottom'] as const;

/** Styled text-overlay editor (modal). Self-gates on textEditorClipId. */
export default function TextClipEditor() {
  const clipId = useEditor((s) => s.textEditorClipId);
  const clip = useEditor((s) =>
    s.clips.find((c) => c.id === s.textEditorClipId),
  ) as Clip | undefined;
  const updateClipText = useEditor((s) => s.updateClipText);
  const openTextEditor = useEditor((s) => s.openTextEditor);

  if (!clipId || !clip) return null;
  const set = (patch: Partial<Clip>) => updateClipText(clipId, patch);
  const close = () => openTextEditor(null);

  const Label = ({ children }: { children: React.ReactNode }) => (
    <span className="mb-1 block text-[10px] uppercase tracking-wider text-white/40">
      {children}
    </span>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={close}
    >
      <div
        className="flex max-h-[88vh] w-[560px] max-w-full flex-col overflow-hidden rounded-xl border border-edge bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-edge bg-panel2 px-4 py-2.5">
          <span className="text-xs font-semibold uppercase tracking-wider text-white/70">
            Text overlay
          </span>
          <button onClick={close} className="text-white/40 hover:text-white">
            ✕
          </button>
        </div>

        {/* live preview */}
        <div className="flex h-28 items-center justify-center border-b border-edge bg-[#0a0a0d] px-4">
          <span
            style={{ ...textTypography(clip), fontSize: `${(clip.textSize ?? 1) * 1.6}rem` }}
          >
            {clip.text || 'Your title'}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-3 overflow-y-auto p-4">
          <div className="col-span-2">
            <Label>Text</Label>
            <textarea
              value={clip.text ?? ''}
              onChange={(e) => set({ text: e.target.value })}
              rows={2}
              className="w-full resize-none rounded bg-panel3 px-2 py-1.5 text-sm text-white outline-none ring-1 ring-edge focus:ring-accent"
            />
          </div>

          <div>
            <Label>Font</Label>
            <select
              value={clip.textFont ?? 'sans'}
              onChange={(e) => set({ textFont: e.target.value as Clip['textFont'] })}
              className="w-full rounded bg-panel3 px-2 py-1.5 text-sm text-white capitalize outline-none ring-1 ring-edge"
            >
              {FONTS.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
          <div>
            <Label>Animation</Label>
            <select
              value={clip.textAnim ?? 'none'}
              onChange={(e) => set({ textAnim: e.target.value as Clip['textAnim'] })}
              className="w-full rounded bg-panel3 px-2 py-1.5 text-sm text-white capitalize outline-none ring-1 ring-edge"
            >
              {ANIMS.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>

          <div>
            <Label>Size ({(clip.textSize ?? 1).toFixed(2)}×)</Label>
            <input
              type="range" min={0.4} max={3} step={0.05}
              value={clip.textSize ?? 1}
              onChange={(e) => set({ textSize: Number(e.target.value) })}
              className="w-full accent-accent"
            />
          </div>
          <div>
            <Label>Placement</Label>
            <div className="flex gap-1">
              {POSITIONS.map((pos) => (
                <button
                  key={pos}
                  onClick={() => set({ textPosition: pos })}
                  className={`flex-1 rounded py-1.5 text-[11px] capitalize ${
                    (clip.textPosition ?? 'bottom') === pos
                      ? 'bg-accent/20 text-accent ring-1 ring-accent/40'
                      : 'bg-panel3 text-white/60 hover:text-white'
                  }`}
                >
                  {pos}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-end gap-3">
            <div>
              <Label>Color</Label>
              <input
                type="color"
                value={clip.textColor ?? '#ffffff'}
                onChange={(e) => set({ textColor: e.target.value })}
                className="h-8 w-12 cursor-pointer rounded bg-panel3 ring-1 ring-edge"
              />
            </div>
            <label className="flex items-center gap-2 pb-1.5 text-xs text-white/70">
              <input
                type="checkbox"
                checked={!!clip.textBold}
                onChange={(e) => set({ textBold: e.target.checked })}
                className="accent-accent"
              />
              Bold
            </label>
            <label className="flex items-center gap-2 pb-1.5 text-xs text-white/70">
              <input
                type="checkbox"
                checked={!!clip.textShadow}
                onChange={(e) => set({ textShadow: e.target.checked })}
                className="accent-accent"
              />
              Shadow
            </label>
          </div>

          <div>
            <Label>Border ({clip.textStroke ?? 0}px)</Label>
            <div className="flex items-center gap-2">
              <input
                type="range" min={0} max={8} step={1}
                value={clip.textStroke ?? 0}
                onChange={(e) => set({ textStroke: Number(e.target.value) })}
                className="flex-1 accent-accent"
              />
              <input
                type="color"
                value={clip.textStrokeColor ?? '#000000'}
                onChange={(e) => set({ textStrokeColor: e.target.value })}
                className="h-8 w-10 cursor-pointer rounded bg-panel3 ring-1 ring-edge"
              />
            </div>
          </div>

          <div className="col-span-2 flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-white/70">
              <input
                type="checkbox"
                checked={!!clip.textBg}
                onChange={(e) => set({ textBg: e.target.checked })}
                className="accent-accent"
              />
              Background box
            </label>
            {clip.textBg && (
              <input
                type="color"
                value={clip.textBgColor ?? '#000000'}
                onChange={(e) => set({ textBgColor: e.target.value })}
                className="h-8 w-12 cursor-pointer rounded bg-panel3 ring-1 ring-edge"
              />
            )}
            <button
              onClick={close}
              className="ml-auto rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/80"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

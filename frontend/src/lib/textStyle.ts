import type { CSSProperties } from 'react';
import type { Clip } from '../types';

export const FONT_CSS: Record<string, string> = {
  sans: 'system-ui, "Helvetica Neue", Arial, sans-serif',
  serif: 'Georgia, "Times New Roman", serif',
  mono: 'ui-monospace, "Courier New", monospace',
  display: 'Impact, "Arial Black", system-ui, sans-serif',
  elegant: 'Georgia, "Hoefler Text", serif',
};

/** Typographic CSS (font, weight, colour, outline, shadow, background) for a
 *  text clip — shared by the editor preview and the live stage. */
export function textTypography(clip: Clip): CSSProperties {
  const s: CSSProperties = {
    fontFamily: FONT_CSS[clip.textFont ?? 'sans'] ?? FONT_CSS.sans,
    fontWeight: clip.textBold ? 800 : 600,
    color: clip.textColor ?? '#ffffff',
    lineHeight: 1.15,
    whiteSpace: 'pre-wrap',
  };
  if (clip.textStroke) {
    (s as Record<string, unknown>).WebkitTextStroke =
      `${clip.textStroke}px ${clip.textStrokeColor ?? '#000000'}`;
  }
  if (clip.textShadow) s.textShadow = '0 3px 14px rgba(0,0,0,0.95)';
  if (clip.textBg) {
    s.backgroundColor = clip.textBgColor ?? '#000000';
    s.padding = '0.12em 0.5em';
    s.borderRadius = '0.18em';
    s.boxDecorationBreak = 'clone';
    (s as Record<string, unknown>).WebkitBoxDecorationBreak = 'clone';
  }
  return s;
}

/** Per-frame animation state for a text clip at the given progress (0..1). */
export function textAnimation(clip: Clip, progress: number) {
  const anim = clip.textAnim ?? 'none';
  let opacity = 1;
  let translateY = 0;
  let text = clip.text ?? '';
  const p = Math.max(0, Math.min(1, progress));
  if (anim === 'fade') {
    opacity = Math.max(0, Math.min(1, Math.min(p / 0.18, (1 - p) / 0.18)));
  } else if (anim === 'slide') {
    const ease = Math.max(0, Math.min(1, p / 0.25));
    opacity = ease;
    translateY = (1 - ease) * 22;
  } else if (anim === 'typewriter') {
    const n = Math.floor((text.length || 0) * Math.min(1, p / 0.6));
    text = text.slice(0, Math.max(0, n));
  }
  return { opacity, translateY, text };
}

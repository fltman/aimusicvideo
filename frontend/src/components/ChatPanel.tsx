import { useRef, useState, useEffect } from 'react';
import { useEditor } from '../store/editorStore';
import { api } from '../api/client';
import { fmtClock } from '../lib/format';
import type { ChatMessage } from '../types';

interface Msg extends ChatMessage {
  queued?: number;
  edits?: number;
}

/** Live playhead time — isolated so the chat list doesn't re-render each frame. */
function CursorBadge() {
  const t = useEditor((s) => s.currentTime);
  return <span className="font-mono tabular-nums text-accent">{fmtClock(t)}</span>;
}

/** Creative-director chat. Image requests are queued (async) and dropped onto
 *  the timeline at the playhead by the global generation poller when ready. */
export default function ChatPanel({ className = '' }: { className?: string }) {
  const projectId = useEditor((s) => s.projectId);
  const addTextClip = useEditor((s) => s.addTextClip);
  const addEffectClip = useEditor((s) => s.addEffectClip);

  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, sending]);

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || !projectId || sending) return;
    setInput('');
    const cursor = useEditor.getState().currentTime;
    const history: Msg[] = [...messages, { role: 'user', content }];
    setMessages(history);
    setSending(true);
    try {
      const apiHistory: ChatMessage[] = history.map((m) => ({
        role: m.role,
        content: m.content,
      }));
      const res = await api.chat(projectId, apiHistory, cursor);
      // apply any timeline edits the director requested
      for (const a of res.actions ?? []) {
        if (a.type === 'add_text' && a.text) {
          addTextClip(a.text, a.at, a.duration, a.position);
        } else if (a.type === 'apply_effect' && a.filter_id) {
          addEffectClip(a.filter_id, a.name ?? a.filter_id, a.at, a.duration);
        }
      }
      // a full auto-direct: lay the title card, effects and graphic interludes
      // now; the shot images auto-place via the generation queue as they finish.
      let edits = (res.actions ?? []).length;
      if (res.direct) {
        for (const t of res.direct.texts ?? []) {
          addTextClip(t.text, t.at, t.duration, t.position);
        }
        for (const e of res.direct.effects ?? []) {
          addEffectClip(e.filter_id, e.name, e.at, e.duration, e.params, false);
        }
        for (const c of res.direct.interlude_clips ?? []) {
          addEffectClip(c.filterId, c.name, c.start, c.duration, c.params, false);
        }
        useEditor.getState().closeFilterWorkspace();
        useEditor.getState().openTextEditor(null);
        edits +=
          (res.direct.texts?.length ?? 0) +
          (res.direct.effects?.length ?? 0) +
          (res.direct.interlude_clips?.length ?? 0);
      }
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          content: res.reply,
          queued: res.queued.length,
          edits,
        },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          content: `⚠️ ${e instanceof Error ? e.message : 'Request failed'}`,
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className={`flex h-full flex-col bg-panel ${className}`}>
      <div className="border-b border-edge px-3 py-1.5 text-[11px] text-white/40">
        asking about <CursorBadge />
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && (
          <div className="pt-4 text-center text-xs leading-relaxed text-white/30">
            Ask me to <span className="text-white/50">direct the whole video</span> —
            I read the song as a story and board it.
            <br />
            Or place the playhead and ask for a visual for that moment.
            <br />
            <span className="text-white/20">
              Tip: name &amp; tag media (e.g. “Kevin”, “bathroom”) then say
              “Kevin in the bathroom”.
            </span>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
            <div
              className={[
                'inline-block max-w-[92%] rounded-lg px-2.5 py-1.5 text-left text-xs leading-relaxed',
                m.role === 'user'
                  ? 'bg-accent/20 text-white'
                  : 'bg-panel2 text-white/80',
              ].join(' ')}
            >
              <p className="whitespace-pre-wrap">{m.content}</p>
              {!!m.queued && (
                <p className="mt-1.5 flex items-center gap-1.5 text-[10px] text-accent">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                  Queued {m.queued} image{m.queued > 1 ? 's' : ''} — generating…
                </p>
              )}
              {!!m.edits && (
                <p className="mt-1 text-[10px] text-high">
                  ✓ {m.edits} timeline edit{m.edits > 1 ? 's' : ''} applied
                </p>
              )}
            </div>
          </div>
        ))}
        {sending && (
          <div className="text-left">
            <div className="inline-flex items-center gap-2 rounded-lg bg-panel2 px-2.5 py-1.5 text-xs text-white/50">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
              thinking…
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-edge p-2">
        <div className="mb-2 flex gap-1.5">
          <button
            onClick={() => send('Direct the whole video — storyboard the song into a complete draft.')}
            disabled={sending}
            className="flex-1 rounded-md bg-gradient-to-r from-accent to-high py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            🎬 Direct the whole video
          </button>
          <button
            onClick={() => send('Generate a suitable image for this moment.')}
            disabled={sending}
            className="rounded-md bg-panel3 px-2.5 py-1.5 text-xs text-white/80 hover:bg-edge hover:text-white disabled:opacity-40"
            title="Image for the current playhead moment"
          >
            ✨ Shot
          </button>
        </div>
        <div className="flex gap-1.5">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send(input)}
            disabled={sending}
            placeholder="e.g. Kevin in the bathroom…"
            className="min-w-0 flex-1 rounded-md bg-panel3 px-2.5 py-1.5 text-xs text-white outline-none ring-1 ring-edge focus:ring-accent disabled:opacity-50"
          />
          <button
            onClick={() => send(input)}
            disabled={sending || !input.trim()}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/80 disabled:opacity-40"
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}

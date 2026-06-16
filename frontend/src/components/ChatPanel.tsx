import { useRef, useState, useEffect } from 'react';
import { useEditor } from '../store/editorStore';
import { api } from '../api/client';
import { fmtClock } from '../lib/format';
import type { ChatMessage } from '../types';

interface Msg extends ChatMessage {
  queued?: number;
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
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: res.reply, queued: res.queued.length },
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
            Place the playhead, then ask for a visual for that moment.
            <br />I use the mood, the section lyrics and the actual sound.
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
        <button
          onClick={() => send('Generate a suitable image for this moment.')}
          disabled={sending}
          className="mb-2 w-full rounded-md bg-panel3 py-1.5 text-xs text-white/80 hover:bg-edge hover:text-white disabled:opacity-40"
        >
          ✨ Image for this moment
        </button>
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

import { useState } from 'react';
import ChatPanel from './ChatPanel';

/** Floating director-chat: a bottom-right button that toggles an overlay panel. */
export default function ChatDock() {
  const [open, setOpen] = useState(false);

  return (
    <>
      {open && (
        <div className="fixed bottom-24 right-5 z-50 flex h-[540px] max-h-[75vh] w-[380px] max-w-[90vw] flex-col overflow-hidden rounded-2xl border border-edge bg-panel shadow-2xl shadow-black/50">
          <div className="flex items-center justify-between border-b border-edge bg-panel2 px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-white/70">
              ✨ Director Chat
            </span>
            <button
              onClick={() => setOpen(false)}
              className="text-white/40 hover:text-white"
              title="Close"
            >
              ✕
            </button>
          </div>
          <ChatPanel className="min-h-0 flex-1" />
        </div>
      )}

      <button
        onClick={() => setOpen((o) => !o)}
        className={[
          'fixed bottom-5 right-5 z-50 flex h-14 w-14 items-center justify-center rounded-full text-2xl shadow-xl shadow-black/40 transition-all',
          open
            ? 'bg-panel3 text-white/70 hover:bg-edge'
            : 'bg-accent text-white hover:scale-105 hover:bg-accent/90',
        ].join(' ')}
        title="Director chat"
      >
        {open ? '✕' : '💬'}
      </button>
    </>
  );
}

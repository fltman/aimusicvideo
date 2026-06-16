import { useState } from 'react';
import LyricsColumn from './LyricsColumn';
import AnalysisPanel from './AnalysisPanel';

type Tab = 'lyrics' | 'analysis';

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        'flex-1 px-3 py-2.5 text-xs font-semibold uppercase tracking-wider transition-colors',
        active
          ? 'text-white shadow-[inset_0_-2px_0_0_theme(colors.accent)]'
          : 'text-white/40 hover:text-white/70',
      ].join(' ')}
    >
      {children}
    </button>
  );
}

/** Tabbed right column: synced Lyrics and the Gemini music Analysis. */
export default function RightPanel({ className = '' }: { className?: string }) {
  const [tab, setTab] = useState<Tab>('lyrics');
  return (
    <div className={`flex h-full flex-col bg-panel ${className}`}>
      <div className="flex border-b border-edge">
        <TabButton active={tab === 'lyrics'} onClick={() => setTab('lyrics')}>
          Lyrics
        </TabButton>
        <TabButton active={tab === 'analysis'} onClick={() => setTab('analysis')}>
          Analysis
        </TabButton>
      </div>
      <div className="min-h-0 flex-1">
        {tab === 'lyrics' && <LyricsColumn showHeader={false} />}
        {tab === 'analysis' && <AnalysisPanel />}
      </div>
    </div>
  );
}

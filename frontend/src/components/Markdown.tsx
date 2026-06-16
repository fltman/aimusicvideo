import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';

/** Compact markdown styling tuned for the dark chat bubbles. */
const components: Components = {
  p: ({ children }) => <p className="my-1 first:mt-0 last:mb-0">{children}</p>,
  strong: ({ children }) => (
    <strong className="font-semibold text-white">{children}</strong>
  ),
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => (
    <ul className="my-1 ml-4 list-disc space-y-0.5 marker:text-white/40">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="my-1 ml-4 list-decimal space-y-0.5 marker:text-white/40">{children}</ol>
  ),
  li: ({ children }) => <li className="pl-0.5">{children}</li>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-accent underline underline-offset-2 hover:text-accent/80"
    >
      {children}
    </a>
  ),
  code: ({ className, children }) => {
    const block = (className ?? '').includes('language-');
    if (block) {
      return (
        <code className="block overflow-x-auto rounded bg-black/40 p-2 font-mono text-[11px] text-white/90">
          {children}
        </code>
      );
    }
    return (
      <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-[11px] text-white/90">
        {children}
      </code>
    );
  },
  pre: ({ children }) => <pre className="my-1.5">{children}</pre>,
  h1: ({ children }) => <h1 className="mb-1 mt-2 text-sm font-semibold text-white">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-1 mt-2 text-xs font-semibold text-white">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-0.5 mt-1.5 text-xs font-semibold text-white/90">{children}</h3>,
  blockquote: ({ children }) => (
    <blockquote className="my-1 border-l-2 border-edge pl-2 italic text-white/60">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-2 border-edge" />,
  table: ({ children }) => (
    <div className="my-1.5 overflow-x-auto">
      <table className="w-full border-collapse text-[11px]">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-edge px-1.5 py-0.5 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => <td className="border border-edge px-1.5 py-0.5">{children}</td>,
};

/** Render assistant chat text as GitHub-flavoured markdown. */
export default function Markdown({ children }: { children: string }) {
  return (
    <div className="text-xs leading-relaxed [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}

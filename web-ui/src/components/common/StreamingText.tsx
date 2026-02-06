import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';

interface StreamingTextProps {
  text: string;
  isStreaming?: boolean;
  className?: string;
  /** When not streaming, render as Markdown */
  markdown?: boolean;
}

export function StreamingText({ text, isStreaming = false, className = '', markdown = true }: StreamingTextProps): JSX.Element {
  const [displayLength, setDisplayLength] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!isStreaming) {
      setDisplayLength(text.length);
      return;
    }
    if (text.length <= displayLength) return;
    const step = Math.max(1, Math.ceil((text.length - displayLength) / 4));
    const target = text.length;
    const tick = () => {
      setDisplayLength((n) => {
        const next = Math.min(n + step, target);
        if (next < target && rafRef.current != null) {
          rafRef.current = requestAnimationFrame(tick);
        }
        return next;
      });
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [text, isStreaming, displayLength]);

  const visible = text.slice(0, displayLength);
  const showCursor = isStreaming && displayLength < text.length;

  if (markdown && !isStreaming && visible.length === text.length) {
    return (
      <span className={className}>
        <ReactMarkdown
          components={{
            p: ({ children }) => <span className="inline">{children}</span>,
            strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
            code: ({ children }) => <code className="bg-slate-200 px-1 rounded text-xs">{children}</code>,
          }}
        >
          {visible}
        </ReactMarkdown>
        {showCursor && <span className="inline-block w-2 h-4 ml-0.5 bg-blue-500 animate-pulse" />}
      </span>
    );
  }

  return (
    <span className={className}>
      {visible}
      {showCursor && <span className="inline-block w-2 h-4 ml-0.5 bg-blue-500 animate-pulse" />}
    </span>
  );
}

export default StreamingText;

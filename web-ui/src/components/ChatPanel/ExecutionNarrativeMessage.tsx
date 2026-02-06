import { useState } from 'react';
import { Zap, ChevronDown, ChevronRight } from 'lucide-react';
import { StreamingText } from '../common/StreamingText';

export interface ExecutionNarrativeMessageProps {
  nodeName: string;
  /** Main narrative text (e.g. "Currently searching for quarterly revenue data...") */
  content: string;
  /** Whether content is still streaming */
  isStreaming?: boolean;
  /** Optional thinking/reasoning text (collapsible) */
  thinkingContent?: string;
  className?: string;
}

export function ExecutionNarrativeMessage({
  nodeName,
  content,
  isStreaming = false,
  thinkingContent,
  className = '',
}: ExecutionNarrativeMessageProps): JSX.Element {
  const [showThinking, setShowThinking] = useState(false);
  const hasThinking = Boolean(thinkingContent && thinkingContent.trim());

  return (
    <div className={`rounded-lg border border-slate-200 bg-slate-50/70 pl-3 pr-3 py-2 ${className}`}>
      <div className="flex items-start gap-2">
        <Zap className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-slate-700">{nodeName}</div>
          <div className="text-sm text-slate-600 mt-0.5">
            <StreamingText text={content} isStreaming={isStreaming} markdown={!isStreaming} />
          </div>
          {hasThinking && (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => setShowThinking((v) => !v)}
                className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
              >
                {showThinking ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                <span>{showThinking ? '收起思考过程' : '展开思考过程'}</span>
              </button>
              {showThinking && thinkingContent && (
                <div className="mt-1 p-2 rounded bg-slate-100 text-xs text-slate-600 whitespace-pre-wrap">
                  {thinkingContent}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ExecutionNarrativeMessage;

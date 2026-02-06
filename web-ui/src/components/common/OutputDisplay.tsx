import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { formatNodeOutput } from '../../utils/outputFormatter';
import type { FormatNodeOutputResult } from '../../utils/outputFormatter';
import { ChevronDown, ChevronRight, FileJson, FileText } from 'lucide-react';

export type OutputDisplayProps = {
  /** Raw node output (object with summary/narrative/data or any value) */
  output: unknown;
  /** Optional pre-formatted result; if not provided, formatNodeOutput(output) is used */
  formatted?: FormatNodeOutputResult | null;
  /** Compact mode: hide layer 2/3 toggles when no narrative */
  compact?: boolean;
  className?: string;
};

// 技术字段黑名单（对用户无意义，应在展示时过滤）
const TECHNICAL_FIELDS = new Set([
  'agent_id', 'task_id', 'workspace_path', '_workspace_path',
  'duration_ms', 'success', 'verification_score', 'iterations',
  'output_files', 'agentid', 'taskid', 'workspacepath',
  'durationms', 'verificationscore', 'outputfiles'
]);

/**
 * 过滤对象中的技术字段
 */
function filterTechnicalFields(obj: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(obj).filter(([key]) => {
      const normalizedKey = key.toLowerCase().replace(/_/g, '');
      return !TECHNICAL_FIELDS.has(normalizedKey) && !key.startsWith('_');
    })
  );
}

const proseClasses = 'prose prose-sm max-w-none prose-slate';

export function OutputDisplay({ output, formatted: formattedProp, compact = false, className = '' }: OutputDisplayProps): JSX.Element {
  const [showNarrative, setShowNarrative] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [rawViewMode, setRawViewMode] = useState<'markdown' | 'json'>('markdown');

  const formatted = formattedProp ?? formatNodeOutput(output);
  const { summary, narrative, highlights, markdown } = formatted;

  const hasNarrative = Boolean(narrative && narrative.trim());
  const hasHighlights = Array.isArray(highlights) && highlights.length > 0;

  // Layer 1 优先显示 narrative，其次是 summary
  const layer1Text = (hasNarrative ? narrative : summary) || summary;

  // 过滤后的 output 用于 JSON 展示
  const filteredOutput = typeof output === 'object' && output !== null
    ? filterTechnicalFields(output as Record<string, unknown>)
    : output;

  return (
    <div className={`rounded-lg border border-slate-200 bg-slate-50/50 ${className}`}>
      {/* Layer 1: Summary/Narrative (always visible, prioritize narrative) */}
      <div className="px-3 py-2.5 border-b border-slate-100">
        {/* 主要内容：使用较小字号和较浅颜色，与节点名称形成层级对比 */}
        <p className="text-xs leading-relaxed text-slate-600">{layer1Text}</p>
        {hasHighlights && (
          <ul className="mt-2 space-y-1">
            {highlights.map((h, i) => (
              <li key={i} className="flex items-start gap-1.5 text-xs text-slate-500">
                <span className="text-emerald-500 mt-0.5">•</span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Layer 2: Narrative (expandable) */}
      {hasNarrative && !compact && (
        <div className="border-b border-slate-100">
          <button
            type="button"
            onClick={() => setShowNarrative((v) => !v)}
            className="w-full px-3 py-2 flex items-center gap-2 text-left text-sm text-slate-600 hover:bg-slate-100/80 transition-colors"
          >
            {showNarrative ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            <span>{showNarrative ? '收起详情' : '展开详情'}</span>
          </button>
          {showNarrative && narrative && (
            <div className={`px-3 pb-3 ${proseClasses}`}>
              <ReactMarkdown
                components={{
                  p: ({ children }) => <p className="mb-1 last:mb-0 text-slate-600 text-sm">{children}</p>,
                  strong: ({ children }) => <strong className="font-semibold text-slate-700">{children}</strong>,
                }}
              >
                {narrative}
              </ReactMarkdown>
            </div>
          )}
        </div>
      )}

      {/* Layer 3: Detailed data (Markdown | JSON toggle) */}
      <div>
        <button
          type="button"
          onClick={() => setShowRaw((v) => !v)}
          className="w-full px-3 py-2 flex items-center gap-2 text-left text-sm text-slate-500 hover:bg-slate-100/80 transition-colors"
        >
          {showRaw ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          <span>查看详细数据</span>
        </button>
        {showRaw && (
          <div className="px-3 pb-3 space-y-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setRawViewMode('markdown')}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${rawViewMode === 'markdown' ? 'bg-slate-200 text-slate-800' : 'text-slate-500 hover:bg-slate-100'}`}
              >
                <FileText className="w-3.5 h-3.5" /> Markdown
              </button>
              <button
                type="button"
                onClick={() => setRawViewMode('json')}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${rawViewMode === 'json' ? 'bg-slate-200 text-slate-800' : 'text-slate-500 hover:bg-slate-100'}`}
              >
                <FileJson className="w-3.5 h-3.5" /> JSON
              </button>
            </div>
            <div className="rounded border border-slate-200 bg-white p-2 max-h-64 overflow-auto">
              {rawViewMode === 'markdown' ? (
                <div className={`${proseClasses} text-xs`}>
                  <ReactMarkdown
                    components={{
                      code: ({ children, className: c }) =>
                        c ? (
                          <code className="block bg-slate-800 text-slate-100 p-2 rounded text-xs font-mono overflow-x-auto">{children}</code>
                        ) : (
                          <code className="bg-slate-200 px-1 py-0.5 rounded font-mono">{children}</code>
                        ),
                      pre: ({ children }) => <pre className="my-1 text-xs">{children}</pre>,
                    }}
                  >
                    {markdown}
                  </ReactMarkdown>
                </div>
              ) : (
                <pre className="text-xs font-mono text-slate-700 whitespace-pre-wrap break-words">
                  {typeof filteredOutput === 'object' && filteredOutput !== null
                    ? JSON.stringify(filteredOutput, null, 2)
                    : String(filteredOutput)}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default OutputDisplay;

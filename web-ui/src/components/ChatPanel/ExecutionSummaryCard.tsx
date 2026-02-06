import { useState } from 'react';
import {
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  Layers,
  FileText,
  AlertTriangle,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import type { ExecutionSummary, ExecutionNodeResult } from '../../types';
import { formatDuration, formatOutputToMarkdown, generateOutputSummary } from '../../utils/outputFormatter';

interface ExecutionSummaryCardProps {
  summary: ExecutionSummary;
}

function NodeResultItem({ node, onNodeClick }: {
  node: ExecutionNodeResult;
  onNodeClick?: (nodeId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasOutput = node.outputMarkdown || node.fullOutput;

  const getStatusIcon = () => {
    switch (node.status) {
      case 'completed':
        return <CheckCircle2 className="w-4 h-4 text-emerald-500" />;
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-500" />;
      default:
        return <AlertTriangle className="w-4 h-4 text-amber-500" />;
    }
  };

  // 获取输出摘要
  const getOutputSummary = () => {
    if (node.outputSummary) return node.outputSummary;
    if (node.outputPreview) return node.outputPreview;
    if (node.fullOutput) return generateOutputSummary(node.fullOutput);
    return null;
  };

  // 获取完整 Markdown 输出
  const getFullMarkdown = () => {
    if (node.outputMarkdown) return node.outputMarkdown;
    if (node.fullOutput) return formatOutputToMarkdown(node.fullOutput);
    return null;
  };

  const outputSummary = getOutputSummary();
  const fullMarkdown = getFullMarkdown();

  return (
    <div className="border-b border-slate-100 last:border-b-0">
      <div
        className={`flex items-start gap-3 py-3 px-4 ${hasOutput ? 'cursor-pointer hover:bg-slate-50' : ''} transition-colors`}
        onClick={() => hasOutput && setExpanded(!expanded)}
      >
        {/* 状态图标 */}
        <div className="flex-shrink-0 mt-0.5">
          {getStatusIcon()}
        </div>

        {/* 节点信息 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="text-sm font-medium text-slate-700 cursor-pointer hover:underline"
              onClick={(e) => {
                e.stopPropagation();
                onNodeClick?.(node.nodeId);
              }}
            >
              {node.nodeName}
            </span>
            {node.durationMs && (
              <span className="text-xs text-slate-400">
                {formatDuration(node.durationMs)}
              </span>
            )}
          </div>

          {/* 输出摘要 */}
          {outputSummary && !expanded && (
            <div className="text-xs text-slate-500 mt-1 truncate">
              {outputSummary}
            </div>
          )}

          {/* 错误信息 */}
          {node.error && (
            <div className="text-xs text-red-500 mt-1">
              {node.error}
            </div>
          )}
        </div>

        {/* 展开按钮 */}
        {hasOutput && (
          <div className="flex-shrink-0 text-slate-400">
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </div>
        )}
      </div>

      {/* 展开后显示完整输出 */}
      {expanded && fullMarkdown && (
        <div className="mx-4 mb-3 p-3 bg-slate-50 rounded-lg border border-slate-100">
          <div className="prose prose-sm max-w-none prose-slate">
            <ReactMarkdown
              components={{
                code: ({ children, className }) => {
                  const isInline = !className;
                  if (isInline) {
                    return (
                      <code className="bg-slate-200 px-1 py-0.5 rounded text-xs font-mono">
                        {children}
                      </code>
                    );
                  }
                  return (
                    <code className="block bg-slate-800 text-slate-100 p-2 rounded text-xs font-mono overflow-x-auto">
                      {children}
                    </code>
                  );
                },
                pre: ({ children }) => (
                  <pre className="bg-slate-800 p-3 rounded-lg overflow-auto text-sm my-2">
                    {children}
                  </pre>
                ),
                p: ({ children }) => (
                  <p className="mb-1 last:mb-0 text-slate-600">{children}</p>
                ),
                ul: ({ children }) => (
                  <ul className="list-disc list-inside space-y-0.5 text-slate-600">{children}</ul>
                ),
                strong: ({ children }) => (
                  <strong className="font-semibold text-slate-700">{children}</strong>
                ),
              }}
            >
              {fullMarkdown}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ExecutionSummaryCard({ summary }: ExecutionSummaryCardProps) {
  const [showFinalOutput, setShowFinalOutput] = useState(true);
  const [showNodeDetails, setShowNodeDetails] = useState(false);

  const isSuccess = summary.status === 'completed';
  const hasFinalOutput = summary.finalOutput || summary.finalOutputMarkdown;

  // 获取最终输出的 Markdown
  const getFinalOutputMarkdown = () => {
    if (summary.finalOutputMarkdown) return summary.finalOutputMarkdown;
    if (summary.finalOutput) return formatOutputToMarkdown(summary.finalOutput);
    return null;
  };

  const finalOutputMarkdown = getFinalOutputMarkdown();

  const handleNodeClick = (nodeId: string) => {
    // 触发画布选中节点的事件
    window.dispatchEvent(new CustomEvent('select-node', { detail: { nodeId } }));
  };

  return (
    <div className="mt-3 bg-white rounded-2xl overflow-hidden border border-slate-200 shadow-sm">
      {/* 标题栏 */}
      <div className={`px-4 py-3 flex items-center justify-between border-b ${isSuccess ? 'bg-emerald-50 border-emerald-100' : 'bg-red-50 border-red-100'
        }`}>
        <h3 className={`font-medium flex items-center gap-2 text-sm ${isSuccess ? 'text-emerald-700' : 'text-red-700'
          }`}>
          {isSuccess ? (
            <>
              <CheckCircle2 className="w-4 h-4" />
              工作流执行完成
            </>
          ) : (
            <>
              <XCircle className="w-4 h-4" />
              工作流执行失败
            </>
          )}
        </h3>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1 text-slate-500">
            <Clock className="w-3.5 h-3.5" />
            {formatDuration(summary.totalDurationMs)}
          </span>
          <span className={`flex items-center gap-1 ${isSuccess ? 'text-emerald-600' : 'text-slate-500'
            }`}>
            <Layers className="w-3.5 h-3.5" />
            {summary.nodesCompleted}/{summary.totalNodes}
          </span>
        </div>
      </div>

      {/* 统计概览 */}
      <div className="px-4 py-3 bg-slate-50 border-b border-slate-100 flex items-center gap-4 text-xs">
        <span className="text-emerald-600">
          {summary.nodesCompleted} 个节点完成
        </span>
        {summary.nodesFailed > 0 && (
          <span className="text-red-500">
            {summary.nodesFailed} 个节点失败
          </span>
        )}
      </div>

      {/* 错误信息 */}
      {summary.error && (
        <div className="px-4 py-3 bg-red-50 border-b border-red-100">
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-red-700">{summary.error}</p>
          </div>
        </div>
      )}

      {/* 最终输出 */}
      {hasFinalOutput && (
        <div className="border-b border-slate-100">
          <div
            className="px-4 py-3 flex items-center justify-between cursor-pointer hover:bg-slate-50 transition-colors"
            onClick={() => setShowFinalOutput(!showFinalOutput)}
          >
            <span className="text-sm font-medium text-slate-700 flex items-center gap-2">
              <FileText className="w-4 h-4 text-blue-500" />
              最终输出
            </span>
            {showFinalOutput ? (
              <ChevronDown className="w-4 h-4 text-slate-400" />
            ) : (
              <ChevronRight className="w-4 h-4 text-slate-400" />
            )}
          </div>

          {showFinalOutput && finalOutputMarkdown && (
            <div className="px-4 pb-4">
              <div className="p-4 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl border border-blue-100">
                <div className="prose prose-sm max-w-none prose-slate">
                  <ReactMarkdown
                    components={{
                      code: ({ children, className }) => {
                        const isInline = !className;
                        if (isInline) {
                          return (
                            <code className="bg-white/70 px-1.5 py-0.5 rounded text-xs font-mono text-blue-700">
                              {children}
                            </code>
                          );
                        }
                        return (
                          <code className="block bg-slate-800 text-slate-100 p-3 rounded-lg text-xs font-mono overflow-x-auto">
                            {children}
                          </code>
                        );
                      },
                      pre: ({ children }) => (
                        <pre className="bg-slate-800 p-3 rounded-lg overflow-auto text-sm my-2">
                          {children}
                        </pre>
                      ),
                      h1: ({ children }) => (
                        <h1 className="text-lg font-bold text-slate-800 mb-2">{children}</h1>
                      ),
                      h2: ({ children }) => (
                        <h2 className="text-base font-semibold text-slate-800 mb-2">{children}</h2>
                      ),
                      h3: ({ children }) => (
                        <h3 className="text-sm font-semibold text-slate-700 mb-1">{children}</h3>
                      ),
                      p: ({ children }) => (
                        <p className="mb-2 last:mb-0 text-slate-600 leading-relaxed">{children}</p>
                      ),
                      ul: ({ children }) => (
                        <ul className="list-disc list-inside space-y-1 text-slate-600 mb-2">{children}</ul>
                      ),
                      ol: ({ children }) => (
                        <ol className="list-decimal list-inside space-y-1 text-slate-600 mb-2">{children}</ol>
                      ),
                      strong: ({ children }) => (
                        <strong className="font-semibold text-slate-800">{children}</strong>
                      ),
                      blockquote: ({ children }) => (
                        <blockquote className="border-l-4 border-blue-300 pl-3 my-2 text-slate-600 italic">
                          {children}
                        </blockquote>
                      ),
                    }}
                  >
                    {finalOutputMarkdown}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 各节点输出详情 */}
      <div>
        <div
          className="px-4 py-3 flex items-center justify-between cursor-pointer hover:bg-slate-50 transition-colors"
          onClick={() => setShowNodeDetails(!showNodeDetails)}
        >
          <span className="text-sm font-medium text-slate-700 flex items-center gap-2">
            <Layers className="w-4 h-4 text-slate-400" />
            各节点输出详情
          </span>
          {showNodeDetails ? (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-400" />
          )}
        </div>

        {showNodeDetails && (
          <div className="border-t border-slate-100">
            {summary.nodeResults.map((node) => (
              <NodeResultItem
                key={node.nodeId}
                node={node}
                onNodeClick={handleNodeClick}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

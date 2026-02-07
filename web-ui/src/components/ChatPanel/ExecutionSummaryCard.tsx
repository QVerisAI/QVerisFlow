import { useState } from 'react';
import {
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  Layers,
  AlertTriangle,
  Play,
  List,
  PlayCircle,
  StopCircle,
  FileText,
} from 'lucide-react';
import type { ExecutionSummary, ExecutionNodeResult } from '../../types';
import { formatDuration, formatNodeOutput, formatStartNodeInput } from '../../utils/outputFormatter';
import { OutputDisplay } from '../common/OutputDisplay';
import { openReport } from '../../utils/reportGenerator';

interface ExecutionSummaryCardProps {
  summary: ExecutionSummary;
  onReExecute?: () => void;
}

/**
 * 判断是否为开始节点
 */
function isStartNode(node: ExecutionNodeResult): boolean {
  const nodeId = node.nodeId.toLowerCase();
  const nodeName = node.nodeName.toLowerCase();
  return nodeId === 'start' || nodeName === '开始节点' || nodeName === 'start';
}

/**
 * 判断开始节点是否有有意义的用户输入
 */
function hasUserInput(node: ExecutionNodeResult): boolean {
  const output = node.fullOutput as Record<string, unknown> | null;
  if (!output) return false;

  const context = output.context as Record<string, unknown> | null;
  if (!context) return false;

  const systemFields = ['workflow_id', 'global_context'];

  for (const key of Object.keys(context)) {
    if (systemFields.includes(key)) {
      if (key === 'global_context') {
        const gc = context[key] as Record<string, unknown> | null;
        if (gc && Object.keys(gc).length > 0) {
          return true;
        }
      }
      continue;
    }
    const value = context[key];
    if (value != null && JSON.stringify(value) !== '{}' && JSON.stringify(value) !== '[]') {
      return true;
    }
  }

  return false;
}

/**
 * 判断是否应该显示开始节点
 */
function shouldShowStartNode(node: ExecutionNodeResult): boolean {
  if (!isStartNode(node)) return true;
  return hasUserInput(node);
}

/**
 * 开始节点的展示组件（带输入参数）
 */
function StartNodeResultItem({ node }: { node: ExecutionNodeResult }) {
  const [expanded, setExpanded] = useState(false);
  const inputInfo = formatStartNodeInput(node.fullOutput);

  if (!inputInfo) return null;

  return (
    <div className="border-b border-slate-100 last:border-b-0">
      <div
        className="flex items-start gap-3 py-3 px-4 cursor-pointer hover:bg-slate-50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-shrink-0 mt-0.5">
          <PlayCircle className="w-4 h-4 text-emerald-500" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-700">执行输入</span>
            {node.durationMs != null && (
              <span className="text-xs text-slate-400">{formatDuration(node.durationMs)}</span>
            )}
          </div>
          {!expanded && inputInfo.summary && (
            <div className="text-xs text-slate-500 mt-1 truncate">{inputInfo.summary}</div>
          )}
        </div>
        <div className="flex-shrink-0 text-slate-400">
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </div>
      </div>
      {expanded && (
        <div className="mx-4 mb-3 rounded border border-slate-100 bg-slate-50 p-2">
          <div className="text-xs font-medium text-slate-500 mb-1.5">输入参数</div>
          <div className="space-y-1">
            {inputInfo.params.map((param, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="text-slate-500 font-medium min-w-[60px]">{param.label}:</span>
                <span className="text-slate-700 break-words">{param.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function NodeResultItem({ node, onNodeClick }: {
  node: ExecutionNodeResult;
  onNodeClick?: (nodeId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasOutput = node.outputNarrative ?? node.outputMarkdown ?? node.fullOutput;

  const getStatusIcon = () => {
    switch (node.status) {
      case 'completed':
      case 'success':  // 兼容后端 NodeExecutionResult 的 "success" 状态值
        return <CheckCircle2 className="w-4 h-4 text-emerald-500" />;
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-500" />;
      default:
        return <AlertTriangle className="w-4 h-4 text-amber-500" />;
    }
  };

  const formatted = formatNodeOutput(node.fullOutput);
  const displaySummary = node.outputSummary ?? node.outputPreview ?? formatted.summary;

  return (
    <div className="border-b border-slate-100 last:border-b-0">
      <div
        className={`flex items-start gap-3 py-3 px-4 ${hasOutput ? 'cursor-pointer hover:bg-slate-50' : ''} transition-colors`}
        onClick={() => hasOutput && setExpanded(!expanded)}
      >
        <div className="flex-shrink-0 mt-0.5">{getStatusIcon()}</div>
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
            {node.durationMs != null && (
              <span className="text-xs text-slate-400">{formatDuration(node.durationMs)}</span>
            )}
          </div>
          {displaySummary && !expanded && (
            <div className="text-xs text-slate-500 mt-1 truncate">{displaySummary}</div>
          )}
          {node.error && (
            <div className="text-xs text-red-500 mt-1">{node.error}</div>
          )}
        </div>
        {hasOutput ? (
          <div className="flex-shrink-0 text-slate-400">
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </div>
        ) : null}
      </div>
      {expanded && hasOutput && node.fullOutput != null ? (
        <div className="mx-4 mb-3">
          <OutputDisplay output={node.fullOutput as Record<string, unknown>} compact />
        </div>
      ) : null}
    </div>
  );
}

export default function ExecutionSummaryCard({ summary, onReExecute }: ExecutionSummaryCardProps) {
  const [showFinalOutput, setShowFinalOutput] = useState(true);
  const [showNodeDetails, setShowNodeDetails] = useState(false);

  const isSuccess = summary.status === 'completed';
  const isCancelled = summary.status === 'cancelled';
  const hasFinalOutput = summary.finalOutput != null || summary.finalOutputMarkdown != null || summary.finalNarrative != null;

  // 计算显示的节点数（排除隐藏的空开始节点）
  const visibleNodes = summary.nodeResults.filter(shouldShowStartNode);
  const hiddenStartNodes = summary.nodeResults.length - visibleNodes.length;
  const displayTotalNodes = summary.totalNodes - hiddenStartNodes;
  const displayCompletedNodes = Math.max(0, summary.nodesCompleted - hiddenStartNodes);

  const conclusionText = summary.finalNarrative ?? (summary.finalOutput != null ? formatNodeOutput(summary.finalOutput).summary : null) ?? (isSuccess ? '执行已完成。' : isCancelled ? '执行已停止。' : '执行未完成。');
  const highlights = summary.finalHighlights ?? (summary.finalOutput != null && typeof summary.finalOutput === 'object' && summary.finalOutput !== null && 'highlights' in summary.finalOutput && Array.isArray((summary.finalOutput as Record<string, unknown>).highlights) ? (summary.finalOutput as Record<string, unknown>).highlights as string[] : null);

  const handleNodeClick = (nodeId: string) => {
    window.dispatchEvent(new CustomEvent('select-node', { detail: { nodeId } }));
  };

  return (
    <div className="mt-3 bg-white rounded-2xl overflow-hidden border border-slate-200 shadow-sm w-full max-w-[400px]">
      {/* 标题栏 */}
      <div className={`px-4 py-3 flex items-center justify-between border-b ${isSuccess ? 'bg-emerald-50 border-emerald-100' : isCancelled ? 'bg-amber-50 border-amber-100' : 'bg-red-50 border-red-100'}`}>
        <h3 className={`font-medium flex items-center gap-2 text-sm ${isSuccess ? 'text-emerald-700' : isCancelled ? 'text-amber-700' : 'text-red-700'}`}>
          {isSuccess ? <CheckCircle2 className="w-4 h-4" /> : isCancelled ? <StopCircle className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
          {isSuccess ? '工作流执行完成' : isCancelled ? '工作流已停止' : '工作流执行失败'}
        </h3>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1 text-slate-500">
            <Clock className="w-3.5 h-3.5" />
            {formatDuration(summary.totalDurationMs)}
          </span>
          <span className={`flex items-center gap-1 ${isSuccess ? 'text-emerald-600' : 'text-slate-500'}`}>
            <Layers className="w-3.5 h-3.5" />
            {displayCompletedNodes}/{displayTotalNodes}
          </span>
        </div>
      </div>

      {/* 结论区：一句话 + 要点（优先展示） */}
      {hasFinalOutput && (
        <div className="px-4 py-4 border-b border-slate-100 bg-gradient-to-br from-slate-50 to-white">
          <p className="text-base font-medium text-slate-800 leading-snug">{conclusionText}</p>
          {highlights && highlights.length > 0 && (
            <ul className="mt-2 list-disc list-inside text-sm text-slate-600 space-y-1">
              {highlights.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* 最终输出（三层展示：摘要 / 叙述 / 原始数据） */}
      {hasFinalOutput && (
        <div className="border-b border-slate-100">
          <button
            type="button"
            className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-slate-50 transition-colors"
            onClick={() => setShowFinalOutput(!showFinalOutput)}
          >
            <span className="text-sm font-medium text-slate-700">最终输出详情</span>
            {showFinalOutput ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
          </button>
          {showFinalOutput && summary.finalOutput != null && (
            <div className="px-4 pb-4">
              <OutputDisplay output={summary.finalOutput as Record<string, unknown>} />
            </div>
          )}
        </div>
      )}

      {/* 错误信息 */}
      {summary.error && (
        <div className="px-4 py-3 bg-red-50 border-b border-red-100">
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-red-700">{summary.error}</p>
          </div>
        </div>
      )}

      {/* 操作栏 */}
      <div className="px-4 py-2 flex items-center gap-2 border-b border-slate-100">
        <button
          type="button"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-600 hover:bg-slate-100 transition-colors"
          onClick={() => setShowNodeDetails((v) => !v)}
        >
          <List className="w-3.5 h-3.5" />
          {showNodeDetails ? '收起节点详情' : '查看节点详情'}
        </button>
        <button
          type="button"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-600 hover:bg-slate-100 transition-colors"
          onClick={() => openReport(summary)}
        >
          <FileText className="w-3.5 h-3.5" />
          查看完整报告
        </button>
        <button
          type="button"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-blue-600 hover:bg-blue-50 transition-colors"
          onClick={() => onReExecute?.()}
        >
          <Play className="w-3.5 h-3.5" />
          重新执行
        </button>
      </div>

      {/* 各节点输出详情（默认折叠） */}
      <div>
        <button
          type="button"
          className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-slate-50 transition-colors"
          onClick={() => setShowNodeDetails(!showNodeDetails)}
        >
          <span className="text-sm font-medium text-slate-700 flex items-center gap-2">
            <Layers className="w-4 h-4 text-slate-400" />
            各节点输出详情
          </span>
          {showNodeDetails ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
        </button>
        {showNodeDetails && (
          <div className="border-t border-slate-100">
            {summary.nodeResults
              .filter(shouldShowStartNode)
              .map((node) => (
                isStartNode(node) ? (
                  <StartNodeResultItem key={node.nodeId} node={node} />
                ) : (
                  <NodeResultItem key={node.nodeId} node={node} onNodeClick={handleNodeClick} />
                )
              ))}
          </div>
        )}
      </div>
    </div>
  );
}

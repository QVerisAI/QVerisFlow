import React, { useState } from 'react';
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  ChevronDown,
  ChevronRight,
  Zap,
  Circle,
  Wrench,
  MessageSquare,
  ListOrdered,
  PlayCircle,
} from 'lucide-react';
import type { ExecutionProgress, ExecutionNodeResult, NodeActivity } from '../../types';
import { formatDuration, formatNodeOutput, formatStartNodeInput } from '../../utils/outputFormatter';
import { OutputDisplay } from '../common/OutputDisplay';

interface ExecutionProgressCardProps {
  progress: ExecutionProgress;
}

/**
 * 判断是否为开始节点
 */
function isStartNode(node: ExecutionNodeResult): boolean {
  const nodeId = (node.nodeId ?? '').toLowerCase();
  const nodeName = (node.nodeName ?? '').toLowerCase();
  return nodeId === 'start' || nodeName === '开始节点' || nodeName === 'start';
}

/**
 * 判断开始节点是否有有意义的用户输入
 * 只有 workflow_id 和 global_context: {} 的开始节点被视为"空"
 */
function hasUserInput(node: ExecutionNodeResult): boolean {
  const output = node.fullOutput as Record<string, unknown> | null;
  if (!output) return false;

  const context = output.context as Record<string, unknown> | null;
  if (!context) return false;

  // 系统字段列表
  const systemFields = ['workflow_id', 'global_context'];

  // 检查是否有非系统字段的用户输入
  for (const key of Object.keys(context)) {
    if (systemFields.includes(key)) {
      // 检查 global_context 是否为空
      if (key === 'global_context') {
        const gc = context[key] as Record<string, unknown> | null;
        if (gc && Object.keys(gc).length > 0) {
          return true;
        }
      }
      continue;
    }
    // 发现非系统字段，说明有用户输入
    const value = context[key];
    if (value != null && JSON.stringify(value) !== '{}' && JSON.stringify(value) !== '[]') {
      return true;
    }
  }

  return false;
}

/**
 * 判断是否应该显示开始节点
 * - 有用户输入时显示
 * - 没有用户输入时隐藏
 */
function shouldShowStartNode(node: ExecutionNodeResult): boolean {
  if (!isStartNode(node)) return true;
  return hasUserInput(node);
}

function ActivityIcon({ type }: { type: NodeActivity['type'] }) {
  switch (type) {
    case 'tool_start':
    case 'tool_result':
    case 'tool_failed':
      return <Wrench className="w-3.5 h-3.5 text-slate-500" />;
    case 'decision':
      return <ListOrdered className="w-3.5 h-3.5 text-blue-500" />;
    case 'iteration':
      return <ListOrdered className="w-3.5 h-3.5 text-slate-500" />;
    default:
      return <MessageSquare className="w-3.5 h-3.5 text-slate-400" />;
  }
}

function StartNodeItem({ node }: { node: ExecutionNodeResult }) {
  const [expanded, setExpanded] = useState(false);
  const inputInfo = formatStartNodeInput(node.fullOutput);

  // 如果没有用户输入，不渲染（由 shouldShowStartNode 控制）
  if (!inputInfo) return null;

  return (
    <div className="group rounded-lg">
      <div
        className="flex items-start gap-2 py-1.5 cursor-pointer hover:bg-slate-50/50 -mx-2 px-2 rounded"
        onClick={() => setExpanded(!expanded)}
      >
        {/* 状态图标 - 使用播放图标表示开始 */}
        <div className="flex-shrink-0 mt-0.5">
          <PlayCircle className="w-4 h-4 text-emerald-500" />
        </div>

        {/* 节点信息 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-700">
              执行输入
            </span>
            <span className="text-xs text-emerald-600">
              {node.durationMs ? formatDuration(node.durationMs) : '已就绪'}
            </span>
          </div>

          {/* 输入摘要（一行） */}
          {!expanded && inputInfo.summary && (
            <div className="text-xs text-slate-500 mt-0.5 truncate">
              {inputInfo.summary}
            </div>
          )}
        </div>

        {/* 展开按钮 */}
        <div className="flex-shrink-0 text-slate-400">
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </div>
      </div>

      {/* 展开后显示输入参数详情 */}
      {expanded && (
        <div className="ml-6 mt-1 mb-2 rounded border border-slate-100 bg-slate-50 p-2">
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

function NodeProgressItem({ node, onNodeClick, isCurrent }: {
  node: ExecutionNodeResult;
  onNodeClick?: (nodeId: string) => void;
  isCurrent?: boolean;
}) {
  const [expanded, setExpanded] = useState(isCurrent ?? false);
  const hasOutput: boolean = Boolean(node.outputPreview ?? node.outputMarkdown ?? node.fullOutput);
  const hasActivities: boolean = (node.activities?.length ?? 0) > 0 || Boolean(node.runningStatus) || Boolean(node.streamContent);

  const getStatusIcon = () => {
    switch (node.status) {
      case 'completed':
        return <CheckCircle2 className="w-4 h-4 text-emerald-500" />;
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-500" />;
      case 'running':
        return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
      default:
        return <Circle className="w-3.5 h-3.5 text-slate-300" />;
    }
  };

  const getStatusText = () => {
    switch (node.status) {
      case 'completed':
        return node.durationMs ? formatDuration(node.durationMs) : '已完成';
      case 'failed':
        return '失败';
      case 'running':
        return '运行中';
      default:
        return '等待';
    }
  };

  const getStatusColor = () => {
    switch (node.status) {
      case 'completed':
        return 'text-emerald-600';
      case 'failed':
        return 'text-red-600';
      case 'running':
        return 'text-blue-600';
      default:
        return 'text-slate-400';
    }
  };

  const formatted = node.fullOutput != null ? formatNodeOutput(node.fullOutput) : null;

  // 获取安全的输出摘要（确保是有意义的字符串）
  const getSafeOutputSummary = (): string | null => {
    // 优先使用 outputNarrative（叙事性更强）
    const candidates = [
      node.outputNarrative,
      node.outputSummary,
      node.outputPreview,
      formatted?.narrative,
      formatted?.summary,
    ];

    for (const candidate of candidates) {
      if (candidate == null) continue;

      // 如果是字符串
      if (typeof candidate === 'string') {
        const trimmed = candidate.trim();
        // 跳过空字符串、markdown 代码块标记、[object Object]
        if (trimmed && !trimmed.startsWith('```') && trimmed !== '[object Object]') {
          return trimmed;
        }
      }

      // 如果是对象，尝试从中提取摘要
      if (typeof candidate === 'object') {
        const obj = candidate as Record<string, unknown>;
        if (typeof obj.summary === 'string' && obj.summary.trim()) {
          return obj.summary.trim();
        }
        if (typeof obj.narrative === 'string' && obj.narrative.trim()) {
          return obj.narrative.trim();
        }
      }
    }

    return null;
  };

  const outputSummary = getSafeOutputSummary();

  const activitiesBlock = (
    expanded && hasActivities
      ? (
        <div className="ml-6 mt-1 mb-2 space-y-2">
          {node.activities != null && node.activities.length > 0 ? (
            <div className="rounded border border-slate-100 bg-white p-2 space-y-1.5 max-h-32 overflow-y-auto overflow-x-hidden">
              <div className="text-xs font-medium text-slate-500 mb-1">活动</div>
              {node.activities.map((a: NodeActivity, i: number) => (
                <div key={i} className="flex items-start gap-2 text-xs min-w-0">
                  <ActivityIcon type={a.type} />
                  <span className="text-slate-600 break-words min-w-0">{a.message}</span>
                </div>
              ))}
            </div>
          ) : null}
          {node.streamContent != null && String(node.streamContent).trim() !== '' ? (
            <div className="text-xs text-slate-600 rounded bg-slate-50 p-2 whitespace-pre-wrap break-words overflow-hidden">
              {String(node.streamContent)}
            </div>
          ) : null}
        </div>
      )
      : null
  ) as React.ReactNode;

  return (
    <div className={`group rounded-lg ${isCurrent ? 'bg-blue-50/50 -mx-1 px-1' : ''}`}>
      <div
        className={`flex items-start gap-2 py-1.5 ${(hasOutput || hasActivities) ? 'cursor-pointer hover:bg-slate-50/50 -mx-2 px-2 rounded' : ''}`}
        onClick={() => (hasOutput || hasActivities) && setExpanded(!expanded)}
      >
        {/* 状态图标 */}
        <div className="flex-shrink-0 mt-0.5">
          {getStatusIcon()}
        </div>

        {/* 节点信息 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span
              className={`text-sm font-medium ${node.status === 'pending' ? 'text-slate-400' : 'text-slate-700'} cursor-pointer hover:underline`}
              onClick={(e) => {
                e.stopPropagation();
                onNodeClick?.(node.nodeId);
              }}
            >
              {String(node.nodeName)}
            </span>
            <span className={`text-xs ${getStatusColor()}`}>
              {getStatusText()}
            </span>
          </div>

          {/* 运行中状态描述或输出摘要（一行） */}
          {node.status === 'running' && node.runningStatus ? (
            <div className="text-xs text-blue-500 mt-0.5 truncate">
              {node.runningStatus}
            </div>
          ) : outputSummary != null && !expanded && (
            <div className="text-xs text-slate-500 mt-0.5 truncate">
              {String(outputSummary)}
            </div>
          )}

          {/* 错误信息 */}
          {node.error && (
            <div className="text-xs text-red-500 mt-0.5">
              {node.error}
            </div>
          )}
        </div>

        {/* 展开按钮 */}
        {(hasOutput || hasActivities) && (
          <div className="flex-shrink-0 text-slate-400">
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </div>
        )}
      </div>

      {/* 展开后：活动时间线 + 输出 */}
      {activitiesBlock}

      {/* 展开后显示三层输出（摘要/叙述/原始数据） */}
      {expanded && hasOutput && node.fullOutput != null && (
        <div className="ml-6 mt-1 mb-2">
          <OutputDisplay output={node.fullOutput as Record<string, unknown>} compact />
        </div>
      )}
    </div>
  );
}

export default function ExecutionProgressCard({ progress }: ExecutionProgressCardProps) {
  const isRunning = progress.status === 'running';
  const isCompleted = progress.status === 'completed';
  const isFailed = progress.status === 'failed';

  // 计算显示的节点数（排除隐藏的空开始节点）
  const visibleNodes = progress.nodeResults.filter(shouldShowStartNode);
  const hiddenStartNodes = progress.nodeResults.length - visibleNodes.length;
  const displayTotalNodes = progress.totalNodes - hiddenStartNodes;
  const displayCompletedNodes = Math.max(0, progress.nodesCompleted - hiddenStartNodes);

  const handleNodeClick = (nodeId: string) => {
    // 触发画布选中节点的事件
    window.dispatchEvent(new CustomEvent('select-node', { detail: { nodeId } }));
  };

  return (
    <div className="mt-3 bg-white rounded-2xl overflow-hidden border border-slate-200 shadow-sm w-full max-w-[400px]">
      {/* 标题栏 */}
      <div className={`px-4 py-3 flex items-center justify-between border-b ${isFailed ? 'bg-red-50 border-red-100' :
        isCompleted ? 'bg-emerald-50 border-emerald-100' :
          'bg-blue-50 border-blue-100'
        }`}>
        <h3 className={`font-medium flex items-center gap-2 text-sm ${isFailed ? 'text-red-700' :
          isCompleted ? 'text-emerald-700' :
            'text-blue-700'
          }`}>
          {isRunning && <Loader2 className="w-4 h-4 animate-spin" />}
          {isCompleted && <CheckCircle2 className="w-4 h-4" />}
          {isFailed && <XCircle className="w-4 h-4" />}
          {isRunning ? '工作流执行中' : isCompleted ? '执行完成' : '执行失败'}
        </h3>
        <div className="flex items-center gap-2 text-xs">
          <Zap className={`w-3.5 h-3.5 ${isFailed ? 'text-red-400' :
            isCompleted ? 'text-emerald-400' :
              'text-blue-400'
            }`} />
          <span className={
            isFailed ? 'text-red-600' :
              isCompleted ? 'text-emerald-600' :
                'text-blue-600'
          }>
            {displayCompletedNodes}/{displayTotalNodes} 节点
          </span>
        </div>
      </div>

      {/* 进度条 */}
      {isRunning && (
        <div className="px-4 py-2 bg-slate-50 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="flex-1 h-1.5 bg-slate-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500 ease-out"
                style={{ width: `${progress.progress}%` }}
              />
            </div>
            <span className="text-xs text-slate-500 font-mono w-10 text-right">
              {progress.progress}%
            </span>
          </div>
        </div>
      )}

      {/* 节点列表（活动时间线风格） */}
      <div className="px-4 py-3 space-y-1">
        {progress.nodeResults
          .filter(shouldShowStartNode)
          .map((node) => (
            isStartNode(node) ? (
              <StartNodeItem key={node.nodeId} node={node} />
            ) : (
              <NodeProgressItem
                key={node.nodeId}
                node={node}
                onNodeClick={handleNodeClick}
                isCurrent={isRunning && (progress.currentNode === node.nodeId || progress.currentNode === node.nodeName)}
              />
            )
          ))}
      </div>

      {/* 当前执行节点提示 */}
      {isRunning && progress.currentNode && (
        <div className="px-4 py-2 bg-blue-50/50 border-t border-blue-100 flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-blue-400" />
          <span className="text-xs text-blue-600">
            正在执行: {progress.currentNode != null ? String(progress.currentNode) : ''}
          </span>
        </div>
      )}
    </div>
  );
}

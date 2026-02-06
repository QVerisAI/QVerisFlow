import { useState } from 'react';
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  ChevronDown,
  ChevronRight,
  Zap,
  Circle,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import type { ExecutionProgress, ExecutionNodeResult } from '../../types';
import { formatDuration, formatOutputToMarkdown, generateOutputSummary } from '../../utils/outputFormatter';

interface ExecutionProgressCardProps {
  progress: ExecutionProgress;
}

function NodeProgressItem({ node, onNodeClick }: {
  node: ExecutionNodeResult;
  onNodeClick?: (nodeId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasOutput = node.outputPreview || node.outputMarkdown || node.fullOutput;

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

  // 获取输出摘要（一行）
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
    <div className="group">
      <div
        className={`flex items-start gap-2 py-1.5 ${hasOutput ? 'cursor-pointer hover:bg-slate-50/50 -mx-2 px-2 rounded' : ''}`}
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
              className={`text-sm font-medium ${node.status === 'pending' ? 'text-slate-400' : 'text-slate-700'} cursor-pointer hover:underline`}
              onClick={(e) => {
                e.stopPropagation();
                onNodeClick?.(node.nodeId);
              }}
            >
              {node.nodeName}
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
          ) : outputSummary && !expanded && (
            <div className="text-xs text-slate-500 mt-0.5 truncate">
              {outputSummary}
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
        {hasOutput && (
          <div className="flex-shrink-0 text-slate-400">
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </div>
        )}
      </div>

      {/* 展开后显示完整输出 */}
      {expanded && fullMarkdown && (
        <div className="ml-6 mt-1 mb-2 p-3 bg-slate-50 rounded-lg border border-slate-100">
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

export default function ExecutionProgressCard({ progress }: ExecutionProgressCardProps) {
  const isRunning = progress.status === 'running';
  const isCompleted = progress.status === 'completed';
  const isFailed = progress.status === 'failed';

  const handleNodeClick = (nodeId: string) => {
    // 触发画布选中节点的事件
    window.dispatchEvent(new CustomEvent('select-node', { detail: { nodeId } }));
  };

  return (
    <div className="mt-3 bg-white rounded-2xl overflow-hidden border border-slate-200 shadow-sm min-w-[320px] w-full max-w-md">
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
            {progress.nodesCompleted}/{progress.totalNodes} 节点
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

      {/* 节点列表 */}
      <div className="px-4 py-3 space-y-1">
        {progress.nodeResults.map((node) => (
          <NodeProgressItem
            key={node.nodeId}
            node={node}
            onNodeClick={handleNodeClick}
          />
        ))}
      </div>

      {/* 当前执行节点提示 */}
      {isRunning && progress.currentNode && (
        <div className="px-4 py-2 bg-blue-50/50 border-t border-blue-100 flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-blue-400" />
          <span className="text-xs text-blue-600">
            正在执行: {progress.currentNode}
          </span>
        </div>
      )}
    </div>
  );
}

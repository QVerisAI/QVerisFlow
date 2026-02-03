import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import { CheckCircle, XCircle, Clock, SkipForward, Loader2, CircleDot } from 'lucide-react';

interface AgentNodeData {
  label: string;
  nodeType: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'preview';
  duration?: number;
  agent?: {
    name: string;
    description?: string;
    domainType: string;
    tools?: string[];
  };
  description?: string;
  tools?: string[];
  dependencies?: string[];
  isHighlighted?: boolean;
  isCurrentNode?: boolean;
}

function AgentNodeComponent({ data, selected }: NodeProps<AgentNodeData>) {
  const { label, status, duration, description, tools } = data;
  const isPreview = status === 'preview' || data.nodeType === 'preview';
  const displayTools = tools || data.agent?.tools || [];

  // 状态配置 - 极简风格
  const statusConfig = {
    preview: {
      bg: 'bg-white',
      border: 'border-slate-200',
      accent: 'bg-blue-500',
      icon: <CircleDot className="w-3.5 h-3.5 text-blue-500" />,
      text: 'text-slate-700',
    },
    pending: {
      bg: 'bg-white',
      border: 'border-slate-200',
      accent: 'bg-slate-400',
      icon: <Clock className="w-3.5 h-3.5 text-slate-400" />,
      text: 'text-slate-600',
    },
    running: {
      bg: 'bg-white',
      border: 'border-blue-300',
      accent: 'bg-blue-500',
      icon: <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />,
      text: 'text-slate-700',
    },
    completed: {
      bg: 'bg-white',
      border: 'border-emerald-300',
      accent: 'bg-emerald-500',
      icon: <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />,
      text: 'text-slate-700',
    },
    failed: {
      bg: 'bg-white',
      border: 'border-red-300',
      accent: 'bg-red-500',
      icon: <XCircle className="w-3.5 h-3.5 text-red-500" />,
      text: 'text-slate-700',
    },
    skipped: {
      bg: 'bg-white',
      border: 'border-amber-300',
      accent: 'bg-amber-500',
      icon: <SkipForward className="w-3.5 h-3.5 text-amber-500" />,
      text: 'text-slate-700',
    },
  };

  const config = statusConfig[status] || statusConfig.pending;

  return (
    <div
      className={`
        group relative w-[240px]
        ${config.bg} ${config.border}
        rounded-2xl border
        shadow-sm hover:shadow-md
        transition-all duration-300 ease-out
        ${selected ? 'shadow-lg ring-2 ring-blue-500/20' : ''}
        ${isPreview ? 'border-dashed' : ''}
      `}
    >
      {/* 顶部连接点 - 极简隐藏式 */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-2 !h-2 !bg-slate-300 !border-0 !-top-1 opacity-0 group-hover:opacity-100 transition-opacity"
      />

      {/* 顶部状态指示条 */}
      <div className={`h-1 ${config.accent} rounded-t-2xl`} />

      {/* 内容区域 */}
      <div className="px-4 py-3">
        {/* 标题行 */}
        <div className="flex items-center justify-between mb-2">
          <h3 className={`font-medium text-sm ${config.text} truncate pr-2`}>
            {label}
          </h3>
          <div className="flex-shrink-0 flex items-center gap-1.5">
            {isPreview && (
              <span className="px-1.5 py-0.5 text-[10px] font-medium text-blue-600 bg-blue-50 rounded">
                预览
              </span>
            )}
            {config.icon}
          </div>
        </div>

        {/* 描述 */}
        {description && (
          <p className="text-xs text-slate-500 leading-relaxed line-clamp-2 mb-2">
            {description}
          </p>
        )}

        {/* 工具标签 - 简洁胶囊式 */}
        {displayTools.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-slate-100">
            {displayTools.slice(0, 2).map((tool, i) => (
              <span
                key={i}
                className="px-2 py-0.5 text-[10px] font-medium text-slate-500 bg-slate-50 rounded-full"
              >
                {tool.length > 16 ? tool.slice(0, 16) + '...' : tool}
              </span>
            ))}
            {displayTools.length > 2 && (
              <span className="px-2 py-0.5 text-[10px] text-slate-400">
                +{displayTools.length - 2}
              </span>
            )}
          </div>
        )}

        {/* 执行耗时 */}
        {duration !== undefined && status === 'completed' && (
          <div className="mt-2 pt-2 border-t border-slate-100 text-[10px] text-slate-400 text-right">
            {(duration / 1000).toFixed(1)}s
          </div>
        )}
      </div>

      {/* 底部连接点 */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-2 !h-2 !bg-slate-300 !border-0 !-bottom-1 opacity-0 group-hover:opacity-100 transition-opacity"
      />
    </div>
  );
}

export const AgentNode = memo(AgentNodeComponent);

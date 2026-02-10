import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
  X,
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  AlertCircle,
  Timer,
  Calendar,
  Play,
  SkipForward,
} from 'lucide-react';
import { wsService } from '../services/websocket';
import { WSMessageType, type WSMessage, type ExecutionRecord, type NodeExecutionResult } from '../types';
import { formatDuration } from '../utils/outputFormatter';

interface ExecutionDetailModalProps {
  executionId: string;
  workflowId: string;
  workflowName: string;
  executionNumber?: number;
  triggeredBy?: 'scheduler' | 'manual';
  onClose: () => void;
}

// 状态配置映射
const statusConfig: Record<string, {
  label: string;
  color: string;
  bgColor: string;
  borderColor: string;
  icon: React.ComponentType<{ className?: string }>;
}> = {
  success: {
    label: '成功',
    color: 'text-emerald-600',
    bgColor: 'bg-emerald-50',
    borderColor: 'border-emerald-200',
    icon: CheckCircle,
  },
  completed: {
    label: '成功',
    color: 'text-emerald-600',
    bgColor: 'bg-emerald-50',
    borderColor: 'border-emerald-200',
    icon: CheckCircle,
  },
  failed: {
    label: '失败',
    color: 'text-red-600',
    bgColor: 'bg-red-50',
    borderColor: 'border-red-200',
    icon: XCircle,
  },
  running: {
    label: '运行中',
    color: 'text-blue-600',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-200',
    icon: Loader2,
  },
  pending: {
    label: '等待中',
    color: 'text-slate-500',
    bgColor: 'bg-slate-50',
    borderColor: 'border-slate-200',
    icon: Clock,
  },
  skipped: {
    label: '已跳过',
    color: 'text-amber-600',
    bgColor: 'bg-amber-50',
    borderColor: 'border-amber-200',
    icon: SkipForward,
  },
  cancelled: {
    label: '已取消',
    color: 'text-slate-500',
    bgColor: 'bg-slate-50',
    borderColor: 'border-slate-200',
    icon: XCircle,
  },
};

export const ExecutionDetailModal: React.FC<ExecutionDetailModalProps> = ({
  executionId,
  workflowId: _workflowId, // 保留以备后用
  workflowName,
  executionNumber,
  triggeredBy = 'manual',
  onClose,
}) => {
  // workflowId 可用于后续扩展，如跳转到工作流画布
  void _workflowId;
  
  const [detail, setDetail] = useState<ExecutionRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 格式化日期时间
  const formatDateTime = (dateStr?: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // 计算运行时长
  const calculateDuration = useCallback(() => {
    if (detail?.totalDurationMs) {
      return formatDuration(detail.totalDurationMs);
    }
    if (detail?.startedAt) {
      const start = new Date(detail.startedAt).getTime();
      const end = detail.completedAt
        ? new Date(detail.completedAt).getTime()
        : Date.now();
      return formatDuration(end - start);
    }
    return '-';
  }, [detail]);

  // 处理 EXECUTION_DETAIL 响应
  const handleExecutionDetail = useCallback((msg: WSMessage) => {
    const payload = msg.payload as { executionId: string; detail: ExecutionRecord };
    if (payload.executionId === executionId) {
      setDetail(payload.detail);
      setLoading(false);
      setError(null);
    }
  }, [executionId]);

  // 处理 ERROR 响应
  const handleError = useCallback((msg: WSMessage) => {
    const payload = msg.payload as { error: string };
    setError(payload.error);
    setLoading(false);
  }, []);

  // 通用事件状态更新逻辑（供 SCHEDULED_EXECUTION_EVENT 和 EXECUTION_EVENT 共用）
  const applyEventUpdate = useCallback((event: {
    event_type: string;
    node_id?: string;
    node_name?: string;
    error?: string;
    total_nodes?: number;
    nodes_completed?: number;
    nodes_failed?: number;
    total_duration_ms?: number;
    data?: {
      total_duration_ms?: number;
      nodes_completed?: number;
      total_nodes?: number;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  }) => {
    setDetail((prev) => {
      if (!prev) return prev;

      // 根据事件类型更新状态
      switch (event.event_type) {
        case 'workflow_started':
          return {
            ...prev,
            status: 'running' as const,
            nodesTotal: event.total_nodes || (event.data?.total_nodes as number) || prev.nodesTotal,
          };

        case 'workflow_completed':
          return {
            ...prev,
            status: 'success' as const,
            completedAt: new Date().toISOString(),
            nodesCompleted: event.nodes_completed || (event.data?.nodes_completed as number) || prev.nodesCompleted,
            totalDurationMs: event.total_duration_ms || (event.data?.total_duration_ms as number) || prev.totalDurationMs,
          };

        case 'workflow_failed':
          return {
            ...prev,
            status: 'failed' as const,
            completedAt: new Date().toISOString(),
            nodesFailed: (prev.nodesFailed || 0) + 1,
          };

        case 'workflow_cancelled':
          return {
            ...prev,
            status: 'cancelled' as const,
            completedAt: new Date().toISOString(),
            totalDurationMs: event.total_duration_ms || (event.data?.total_duration_ms as number) || prev.totalDurationMs,
            // 将所有 running 状态的节点标记为 cancelled
            nodeResults: prev.nodeResults
              ? Object.fromEntries(
                  Object.entries(prev.nodeResults).map(([id, node]) => [
                    id,
                    node.status === 'running'
                      ? { ...node, status: 'cancelled' as const, completedAt: new Date().toISOString() }
                      : node,
                  ])
                )
              : prev.nodeResults,
          };

        case 'node_started':
          if (event.node_id && prev.nodeResults) {
            return {
              ...prev,
              nodeResults: {
                ...prev.nodeResults,
                [event.node_id]: {
                  ...prev.nodeResults[event.node_id],
                  nodeId: event.node_id,
                  nodeName: event.node_name || event.node_id,
                  status: 'running' as const,
                  startedAt: new Date().toISOString(),
                },
              },
            };
          }
          return prev;

        case 'node_completed':
          if (event.node_id && prev.nodeResults) {
            return {
              ...prev,
              nodesCompleted: (prev.nodesCompleted || 0) + 1,
              nodeResults: {
                ...prev.nodeResults,
                [event.node_id]: {
                  ...prev.nodeResults[event.node_id],
                  nodeId: event.node_id,
                  nodeName: event.node_name || event.node_id,
                  status: 'success' as const,
                  completedAt: new Date().toISOString(),
                  durationMs: event.total_duration_ms as number | undefined,
                },
              },
            };
          }
          return {
            ...prev,
            nodesCompleted: (prev.nodesCompleted || 0) + 1,
          };

        case 'node_failed':
          if (event.node_id && prev.nodeResults) {
            return {
              ...prev,
              nodesFailed: (prev.nodesFailed || 0) + 1,
              nodeResults: {
                ...prev.nodeResults,
                [event.node_id]: {
                  ...prev.nodeResults[event.node_id],
                  nodeId: event.node_id,
                  nodeName: event.node_name || event.node_id,
                  status: 'failed' as const,
                  completedAt: new Date().toISOString(),
                  error: event.error,
                },
              },
            };
          }
          return {
            ...prev,
            nodesFailed: (prev.nodesFailed || 0) + 1,
          };

        default:
          return prev;
      }
    });
  }, []);

  // 处理 SCHEDULED_EXECUTION_EVENT 实时更新（定时任务执行）
  const handleScheduledEvent = useCallback((msg: WSMessage) => {
    const payload = msg.payload as {
      execution_id: string;
      workflow_id: string;
      event: {
        event_type: string;
        node_id?: string;
        node_name?: string;
        error?: string;
        total_nodes?: number;
        nodes_completed?: number;
        nodes_failed?: number;
        total_duration_ms?: number;
        [key: string]: unknown;
      };
    };
    
    if (payload.execution_id !== executionId) return;
    applyEventUpdate(payload.event);
  }, [executionId, applyEventUpdate]);

  // 处理 EXECUTION_EVENT 实时更新（交互式执行）
  const handleExecutionEvent = useCallback((msg: WSMessage) => {
    // EXECUTION_EVENT 的 payload 是扁平结构（事件字段直接在 payload 上）
    const payload = msg.payload as {
      event_type: string;
      workflow_id?: string;
      node_id?: string;
      node_name?: string;
      error?: string;
      total_nodes?: number;
      nodes_completed?: number;
      nodes_failed?: number;
      total_duration_ms?: number;
      data?: {
        total_duration_ms?: number;
        nodes_completed?: number;
        total_nodes?: number;
        [key: string]: unknown;
      };
      [key: string]: unknown;
    };

    // 通过 workflow_id 匹配当前执行（executionId 格式为 workflowId_xxxx）
    if (payload.workflow_id && !executionId.startsWith(payload.workflow_id.split('_').slice(0, -1).join('_'))) {
      // 尝试直接匹配
      if (payload.workflow_id !== executionId) return;
    }
    applyEventUpdate(payload);
  }, [executionId, applyEventUpdate]);

  // 订阅 WebSocket 消息
  useEffect(() => {
    setLoading(true);
    setError(null);

    // 发送获取执行详情请求
    wsService.getExecutionDetail(executionId);

    // 订阅响应
    const unsubDetail = wsService.on(
      WSMessageType.EXECUTION_DETAIL,
      handleExecutionDetail,
      `modal_execution_detail_${executionId}`
    );

    const unsubError = wsService.on(
      WSMessageType.ERROR,
      handleError,
      `modal_error_${executionId}`
    );

    // 订阅实时事件（定时任务执行）
    const unsubScheduledEvent = wsService.on(
      WSMessageType.SCHEDULED_EXECUTION_EVENT,
      handleScheduledEvent,
      `modal_scheduled_event_${executionId}`
    );

    // 订阅实时事件（交互式执行）
    const unsubExecutionEvent = wsService.on(
      WSMessageType.EXECUTION_EVENT,
      handleExecutionEvent,
      `modal_execution_event_${executionId}`
    );

    return () => {
      unsubDetail();
      unsubError();
      unsubScheduledEvent();
      unsubExecutionEvent();
    };
  }, [executionId, handleExecutionDetail, handleError, handleScheduledEvent, handleExecutionEvent]);

  // 获取节点列表
  const getNodeList = (): NodeExecutionResult[] => {
    if (!detail?.nodeResults) return [];
    return Object.values(detail.nodeResults);
  };

  // 渲染节点状态图标
  const renderNodeStatusIcon = (status: string) => {
    const config = statusConfig[status] || statusConfig.pending;
    const Icon = config.icon;
    const isRunning = status === 'running';
    return (
      <Icon
        className={`w-4 h-4 ${config.color} ${isRunning ? 'animate-spin' : ''}`}
      />
    );
  };

  // 渲染整体状态徽章
  const renderStatusBadge = () => {
    if (!detail) return null;
    const config = statusConfig[detail.status] || statusConfig.pending;
    const Icon = config.icon;
    const isRunning = detail.status === 'running';

    return (
      <span
        className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-full ${config.bgColor} ${config.color} border ${config.borderColor}`}
      >
        <Icon className={`w-3.5 h-3.5 ${isRunning ? 'animate-spin' : ''}`} />
        {config.label}
      </span>
    );
  };

  // 使用 Portal 将 Modal 渲染到 document.body，避免被父组件的 backdrop-filter 影响
  return createPortal(
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[60] p-4">
      <div className="w-[560px] max-h-[85vh] flex flex-col bg-white rounded-2xl shadow-xl border border-slate-200/50 overflow-hidden">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
              <Play className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-800">
                {workflowName}
                {executionNumber && (
                  <span className="text-slate-400 font-normal ml-2">
                    - 执行 #{executionNumber}
                  </span>
                )}
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">执行详情</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-100 rounded-xl transition-colors"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 className="w-8 h-8 text-blue-500 animate-spin mb-3" />
              <p className="text-sm text-slate-500">加载执行详情...</p>
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center py-16">
              <AlertCircle className="w-12 h-12 text-red-400 mb-3" />
              <p className="text-sm text-red-600">{error}</p>
              <button
                onClick={() => {
                  setLoading(true);
                  setError(null);
                  wsService.getExecutionDetail(executionId);
                }}
                className="mt-4 px-4 py-2 text-sm text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
              >
                重试
              </button>
            </div>
          ) : detail ? (
            <>
              {/* 信息栏 */}
              <div className="px-6 py-4 bg-slate-50/50 border-b border-slate-100">
                <div className="flex flex-wrap items-center gap-4 text-sm">
                  <div className="flex items-center gap-2 text-slate-600">
                    <Timer className="w-4 h-4 text-slate-400" />
                    <span>触发方式:</span>
                    <span className="font-medium">
                      {triggeredBy === 'scheduler' ? '定时任务' : '手动执行'}
                    </span>
                  </div>
                  <div className="w-px h-4 bg-slate-200" />
                  <div className="flex items-center gap-2 text-slate-600">
                    <Calendar className="w-4 h-4 text-slate-400" />
                    <span>开始时间:</span>
                    <span className="font-medium">
                      {formatDateTime(detail.startedAt)}
                    </span>
                  </div>
                  <div className="w-px h-4 bg-slate-200" />
                  <div className="flex items-center gap-2 text-slate-600">
                    <Clock className="w-4 h-4 text-slate-400" />
                    <span>耗时:</span>
                    <span className="font-medium">{calculateDuration()}</span>
                  </div>
                  <div className="ml-auto">{renderStatusBadge()}</div>
                </div>
              </div>

              {/* 进度概览 */}
              <div className="px-6 py-3 border-b border-slate-100">
                <div className="flex items-center gap-4 text-sm">
                  <span className="text-slate-500">节点进度:</span>
                  <span className="font-medium text-slate-700">
                    {detail.nodesCompleted}/{detail.nodesTotal} 完成
                  </span>
                  {detail.nodesFailed > 0 && (
                    <span className="text-red-600">
                      {detail.nodesFailed} 失败
                    </span>
                  )}
                  {/* 进度条 */}
                  <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all duration-300 ${
                        detail.nodesFailed > 0
                          ? 'bg-red-500'
                          : detail.status === 'success'
                          ? 'bg-emerald-500'
                          : 'bg-blue-500'
                      }`}
                      style={{
                        width: `${
                          detail.nodesTotal > 0
                            ? ((detail.nodesCompleted + detail.nodesFailed) /
                                detail.nodesTotal) *
                              100
                            : 0
                        }%`,
                      }}
                    />
                  </div>
                </div>
              </div>

              {/* 节点列表 */}
              <div className="px-6 py-4">
                <h3 className="text-sm font-medium text-slate-700 mb-3">
                  节点执行状态
                </h3>
                <div className="space-y-2">
                  {getNodeList().length > 0 ? (
                    getNodeList().map((node) => {
                      const nodeConfig =
                        statusConfig[node.status] || statusConfig.pending;
                      return (
                        <div
                          key={node.nodeId}
                          className={`flex items-center justify-between px-4 py-3 rounded-lg border ${nodeConfig.bgColor} ${nodeConfig.borderColor}`}
                        >
                          <div className="flex items-center gap-3">
                            {renderNodeStatusIcon(node.status)}
                            <span className="text-sm font-medium text-slate-700">
                              {node.nodeName || node.nodeId}
                            </span>
                          </div>
                          <div className="flex items-center gap-3 text-xs text-slate-500">
                            <span>{nodeConfig.label}</span>
                            {node.durationMs && (
                              <span className="text-slate-400">
                                ({formatDuration(node.durationMs)})
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="text-center py-8 text-sm text-slate-400">
                      暂无节点执行信息
                    </div>
                  )}
                </div>
              </div>

              {/* 错误信息（仅失败时显示） */}
              {detail.status === 'failed' && (
                <div className="px-6 py-4 border-t border-slate-100">
                  <div className="flex items-start gap-3 p-4 bg-red-50 rounded-lg border border-red-100">
                    <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                    <div>
                      <h4 className="text-sm font-medium text-red-700">
                        执行失败
                      </h4>
                      <p className="text-sm text-red-600 mt-1">
                        {getNodeList().find((n) => n.error)?.error ||
                          '工作流执行过程中发生错误'}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : null}
        </div>

        {/* 底部 */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50/50">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
          >
            关闭
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
};

export default ExecutionDetailModal;

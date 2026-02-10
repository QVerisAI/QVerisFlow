import React, { useEffect, useState, useRef } from 'react';
import {
  X,
  Search,
  GitBranch,
  Link2,
  Clock,
  Play,
  Calendar,
  MoreHorizontal,
  Trash2,
  Copy,
  Download,
  CheckCircle,
  XCircle,
  Loader2,
  FolderOpen,
  Workflow,
  History,
  Timer,
  Filter,
} from 'lucide-react';
import { useAppStore } from '../stores/appStore';
import { wsService } from '../services/websocket';
import { WSMessageType, type WorkflowSummary } from '../types';

interface WorkflowListPanelProps {
  onClose: () => void;
  onSchedule?: (workflow: WorkflowSummary) => void;
}

type TabType = 'all' | 'recent' | 'scheduled';
type SortType = 'updated' | 'name' | 'executions';

export const WorkflowListPanel: React.FC<WorkflowListPanelProps> = ({ onClose, onSchedule }) => {
  const [activeTab, setActiveTab] = useState<TabType>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<SortType>('updated');
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const {
    workflowList,
    workflowListLoading,
    setWorkflowListLoading,
  } = useAppStore();

  // 加载工作流列表
  useEffect(() => {
    setWorkflowListLoading(true);
    wsService.send(WSMessageType.LIST_WORKFLOWS, {});
  }, [setWorkflowListLoading]);

  // 点击外部关闭菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setActiveMenuId(null);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleLoadWorkflow = (workflow: WorkflowSummary) => {
    wsService.send(WSMessageType.LOAD_WORKFLOW, {
      workflow_db_id: workflow.id,
    });
    onClose();
  };

  const handleExecuteWorkflow = (workflow: WorkflowSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    // 先加载工作流，然后执行
    wsService.send(WSMessageType.LOAD_WORKFLOW, {
      workflow_db_id: workflow.id,
    });
    // 延迟发送执行命令，等待工作流加载完成
    setTimeout(() => {
      wsService.send(WSMessageType.USER_ACTION, { action: 'execute' });
    }, 500);
    onClose();
  };

  const handleDeleteWorkflow = (workflow: WorkflowSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    setActiveMenuId(null);
    if (confirm(`确定要删除工作流 "${workflow.name}" 吗？`)) {
      wsService.send(WSMessageType.DELETE_WORKFLOW, {
        workflow_db_id: workflow.id,
      });
    }
  };

  const handleCopyWorkflow = (workflow: WorkflowSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    setActiveMenuId(null);
    // TODO: 实现复制工作流功能
    navigator.clipboard.writeText(workflow.workflowId);
  };

  const handleScheduleWorkflow = (workflow: WorkflowSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    setActiveMenuId(null);
    onSchedule?.(workflow);
  };

  const formatDate = (dateStr: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatRelativeTime = (dateStr?: string) => {
    if (!dateStr) return null;
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return '刚刚';
    if (diffMins < 60) return `${diffMins}分钟前`;
    if (diffHours < 24) return `${diffHours}小时前`;
    if (diffDays < 7) return `${diffDays}天前`;
    return formatDate(dateStr);
  };

  // 过滤和排序工作流
  const filteredWorkflows = workflowList
    .filter(workflow => {
      // 搜索过滤
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        if (!workflow.name.toLowerCase().includes(query) &&
          !workflow.description?.toLowerCase().includes(query)) {
          return false;
        }
      }
      // Tab 过滤
      if (activeTab === 'recent') {
        return workflow.lastExecutionAt;
      }
      if (activeTab === 'scheduled') {
        return workflow.scheduleConfig?.enabled;
      }
      return true;
    })
    .sort((a, b) => {
      switch (sortBy) {
        case 'name':
          return a.name.localeCompare(b.name);
        case 'executions':
          return (b.executionCount || 0) - (a.executionCount || 0);
        case 'updated':
        default:
          return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
      }
    });

  const getExecutionStatusInfo = (status?: string) => {
    switch (status) {
      case 'success':
        return { icon: CheckCircle, color: 'text-emerald-500', label: '成功', bgColor: 'bg-emerald-50' };
      case 'failed':
        return { icon: XCircle, color: 'text-red-500', label: '失败', bgColor: 'bg-red-50' };
      case 'running':
        return { icon: Loader2, color: 'text-blue-500', label: '运行中', bgColor: 'bg-blue-50', animate: true };
      default:
        return null;
    }
  };

  const tabCounts = {
    all: workflowList.length,
    recent: workflowList.filter(w => w.lastExecutionAt).length,
    scheduled: workflowList.filter(w => w.scheduleConfig?.enabled).length,
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200/50 w-[720px] max-h-[85vh] flex flex-col overflow-hidden">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
              <Workflow className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-800">工作流列表</h2>
              <p className="text-xs text-slate-500 mt-0.5">管理和执行您的工作流</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* 搜索框 */}
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索工作流..."
                className="w-48 pl-9 pr-4 py-2 rounded-xl border border-slate-200 bg-slate-50 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 focus:bg-white transition-all"
              />
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-slate-100 rounded-xl transition-colors"
            >
              <X className="w-5 h-5 text-slate-400" />
            </button>
          </div>
        </div>

        {/* Tab 和筛选 */}
        <div className="px-6 py-3 border-b border-slate-100 flex items-center justify-between">
          <div className="flex gap-1">
            <button
              onClick={() => setActiveTab('all')}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                activeTab === 'all'
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
              }`}
            >
              <span className="flex items-center gap-2">
                <FolderOpen className="w-4 h-4" />
                全部
                <span className={`px-1.5 py-0.5 text-xs rounded-full ${
                  activeTab === 'all' ? 'bg-blue-100' : 'bg-slate-100'
                }`}>
                  {tabCounts.all}
                </span>
              </span>
            </button>
            <button
              onClick={() => setActiveTab('recent')}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                activeTab === 'recent'
                  ? 'bg-emerald-50 text-emerald-700'
                  : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
              }`}
            >
              <span className="flex items-center gap-2">
                <History className="w-4 h-4" />
                最近执行
                <span className={`px-1.5 py-0.5 text-xs rounded-full ${
                  activeTab === 'recent' ? 'bg-emerald-100' : 'bg-slate-100'
                }`}>
                  {tabCounts.recent}
                </span>
              </span>
            </button>
            <button
              onClick={() => setActiveTab('scheduled')}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                activeTab === 'scheduled'
                  ? 'bg-purple-50 text-purple-700'
                  : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
              }`}
            >
              <span className="flex items-center gap-2">
                <Timer className="w-4 h-4" />
                定时任务
                <span className={`px-1.5 py-0.5 text-xs rounded-full ${
                  activeTab === 'scheduled' ? 'bg-purple-100' : 'bg-slate-100'
                }`}>
                  {tabCounts.scheduled}
                </span>
              </span>
            </button>
          </div>

          {/* 排序 */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-slate-400" />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortType)}
              className="text-sm text-slate-600 bg-transparent border-none focus:outline-none cursor-pointer"
            >
              <option value="updated">最近更新</option>
              <option value="name">名称排序</option>
              <option value="executions">执行次数</option>
            </select>
          </div>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto p-4">
          {workflowListLoading ? (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 className="w-10 h-10 text-blue-500 animate-spin mb-4" />
              <span className="text-slate-500">加载中...</span>
            </div>
          ) : filteredWorkflows.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400">
              <FolderOpen className="w-16 h-16 mb-4 opacity-40" />
              <p className="text-slate-600 font-medium">
                {searchQuery ? '未找到匹配的工作流' : '暂无保存的工作流'}
              </p>
              <p className="text-sm mt-2">
                {searchQuery
                  ? '尝试使用其他关键词搜索'
                  : '通过对话创建工作流后，点击"保存"按钮保存'}
              </p>
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="mt-4 px-4 py-2 text-sm text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                >
                  清除搜索条件
                </button>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {filteredWorkflows.map((workflow) => {
                const statusInfo = getExecutionStatusInfo(workflow.lastExecutionStatus);
                return (
                  <div
                    key={workflow.id}
                    onClick={() => handleLoadWorkflow(workflow)}
                    className="p-5 rounded-2xl border border-slate-100 bg-white hover:border-blue-200 hover:shadow-lg hover:shadow-blue-500/5 cursor-pointer transition-all duration-200 group"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        {/* 标题行 */}
                        <div className="flex items-center gap-3">
                          <h3 className="font-semibold text-slate-800 truncate group-hover:text-blue-600 transition-colors">
                            {workflow.name}
                          </h3>
                          {workflow.scheduleConfig?.enabled && (
                            <span className="flex items-center gap-1 px-2 py-0.5 text-xs font-medium text-purple-600 bg-purple-50 rounded-full">
                              <Timer className="w-3 h-3" />
                              定时
                            </span>
                          )}
                        </div>

                        {/* 描述 */}
                        <p className="text-sm text-slate-500 mt-1.5 line-clamp-2">
                          {workflow.description || '暂无描述'}
                        </p>

                        {/* 统计信息 */}
                        <div className="flex items-center gap-4 mt-3">
                          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-50 rounded-lg">
                            <GitBranch className="w-3.5 h-3.5 text-blue-500" />
                            <span className="text-xs font-medium text-slate-600">{workflow.nodeCount} 节点</span>
                          </div>
                          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-50 rounded-lg">
                            <Link2 className="w-3.5 h-3.5 text-violet-500" />
                            <span className="text-xs font-medium text-slate-600">{workflow.edgeCount} 连接</span>
                          </div>
                          <span className="text-xs text-slate-400">v{workflow.version}</span>
                          <span className="text-xs text-slate-400">{formatDate(workflow.updatedAt)}</span>
                        </div>

                        {/* 标签 */}
                        {workflow.tags.length > 0 && (
                          <div className="flex gap-1.5 mt-3">
                            {workflow.tags.slice(0, 3).map((tag) => (
                              <span
                                key={tag}
                                className="px-2 py-0.5 text-xs text-slate-500 bg-slate-100 rounded-md"
                              >
                                {tag}
                              </span>
                            ))}
                            {workflow.tags.length > 3 && (
                              <span className="text-xs text-slate-400">+{workflow.tags.length - 3}</span>
                            )}
                          </div>
                        )}

                        {/* 执行历史 */}
                        {(workflow.lastExecutionAt || workflow.executionCount) && (
                          <div className="flex items-center gap-3 mt-3 pt-3 border-t border-slate-100">
                            {statusInfo && (
                              <span className={`flex items-center gap-1.5 px-2 py-1 text-xs font-medium rounded-lg ${statusInfo.bgColor}`}>
                                <statusInfo.icon className={`w-3.5 h-3.5 ${statusInfo.color} ${statusInfo.animate ? 'animate-spin' : ''}`} />
                                <span className={statusInfo.color}>{statusInfo.label}</span>
                              </span>
                            )}
                            {workflow.lastExecutionAt && (
                              <span className="text-xs text-slate-400">
                                {formatRelativeTime(workflow.lastExecutionAt)}
                              </span>
                            )}
                            {workflow.executionCount !== undefined && workflow.executionCount > 0 && (
                              <span className="text-xs text-slate-400">
                                共执行 {workflow.executionCount} 次
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      {/* 操作按钮 */}
                      <div className="flex items-center gap-2 ml-4 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={(e) => handleExecuteWorkflow(workflow, e)}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 rounded-lg shadow-sm transition-all"
                          title="执行工作流"
                        >
                          <Play className="w-3.5 h-3.5" />
                          执行
                        </button>
                        <button
                          onClick={(e) => handleScheduleWorkflow(workflow, e)}
                          className="p-2 text-slate-400 hover:text-purple-600 hover:bg-purple-50 rounded-lg transition-colors"
                          title="配置定时任务"
                        >
                          <Calendar className="w-4 h-4" />
                        </button>
                        <div className="relative" ref={activeMenuId === workflow.id ? menuRef : null}>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setActiveMenuId(activeMenuId === workflow.id ? null : workflow.id);
                            }}
                            className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
                            title="更多操作"
                          >
                            <MoreHorizontal className="w-4 h-4" />
                          </button>
                          {/* 下拉菜单 */}
                          {activeMenuId === workflow.id && (
                            <div className="absolute right-0 top-full mt-1 w-40 bg-white rounded-xl shadow-lg border border-slate-200 py-1 z-10">
                              <button
                                onClick={(e) => handleCopyWorkflow(workflow, e)}
                                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 transition-colors"
                              >
                                <Copy className="w-4 h-4" />
                                复制 ID
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setActiveMenuId(null);
                                  // TODO: 实现导出功能
                                }}
                                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 transition-colors"
                              >
                                <Download className="w-4 h-4" />
                                导出
                              </button>
                              <div className="h-px bg-slate-100 my-1" />
                              <button
                                onClick={(e) => handleDeleteWorkflow(workflow, e)}
                                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
                              >
                                <Trash2 className="w-4 h-4" />
                                删除
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 底部 */}
        <div className="px-6 py-4 border-t border-slate-100 bg-slate-50/50 flex items-center justify-between">
          <p className="text-sm text-slate-500">
            共 {filteredWorkflows.length} 个工作流
            {searchQuery && ` (搜索: "${searchQuery}")`}
          </p>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Clock className="w-3.5 h-3.5" />
            点击工作流加载，或使用右侧按钮快速操作
          </div>
        </div>
      </div>
    </div>
  );
};

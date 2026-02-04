import React, { useEffect } from 'react';
import { useAppStore } from '../stores/appStore';
import { wsService } from '../services/websocket';
import { WSMessageType, type WorkflowSummary } from '../types';

interface WorkflowListPanelProps {
  onClose: () => void;
}

export const WorkflowListPanel: React.FC<WorkflowListPanelProps> = ({ onClose }) => {
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

  const handleLoadWorkflow = (workflow: WorkflowSummary) => {
    wsService.send(WSMessageType.LOAD_WORKFLOW, {
      workflow_db_id: workflow.id,
    });
    onClose();
  };

  const handleDeleteWorkflow = (workflow: WorkflowSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm(`确定要删除工作流 "${workflow.name}" 吗？`)) {
      wsService.send(WSMessageType.DELETE_WORKFLOW, {
        workflow_db_id: workflow.id,
      });
    }
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

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-[600px] max-h-[80vh] flex flex-col">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            📋 工作流列表
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto p-4">
          {workflowListLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
              <span className="ml-3 text-gray-500">加载中...</span>
            </div>
          ) : workflowList.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <div className="text-4xl mb-3">📭</div>
              <p>暂无保存的工作流</p>
              <p className="text-sm mt-2">通过对话创建工作流后，点击"保存"按钮保存</p>
            </div>
          ) : (
            <div className="space-y-3">
              {workflowList.map((workflow) => (
                <div
                  key={workflow.id}
                  onClick={() => handleLoadWorkflow(workflow)}
                  className="p-4 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 cursor-pointer transition-all group"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-gray-900 dark:text-white truncate">
                        {workflow.name}
                      </h3>
                      <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 line-clamp-2">
                        {workflow.description || '暂无描述'}
                      </p>
                      <div className="flex items-center gap-4 mt-2 text-xs text-gray-400">
                        <span>📊 {workflow.nodeCount} 节点</span>
                        <span>🔗 {workflow.edgeCount} 连接</span>
                        <span>v{workflow.version}</span>
                        <span>{formatDate(workflow.updatedAt)}</span>
                      </div>
                      {workflow.tags.length > 0 && (
                        <div className="flex gap-1 mt-2">
                          {workflow.tags.slice(0, 3).map((tag) => (
                            <span
                              key={tag}
                              className="px-2 py-0.5 text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={(e) => handleDeleteWorkflow(workflow, e)}
                      className="ml-4 p-2 text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                      title="删除工作流"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 底部 */}
        <div className="px-6 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 rounded-b-xl">
          <p className="text-xs text-gray-500 text-center">
            共 {workflowList.length} 个工作流
          </p>
        </div>
      </div>
    </div>
  );
};

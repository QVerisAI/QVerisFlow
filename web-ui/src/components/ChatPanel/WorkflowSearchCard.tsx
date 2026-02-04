import {
  FolderOpen,
  GitBranch,
  Tag,
  User,
  Calendar,
  Play,
  ChevronRight,
} from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { wsService } from '../../services/websocket';
import { WSMessageType } from '../../types';
import type { WorkflowSearchResult, WorkflowSearchItem } from '../../types';

interface WorkflowSearchCardProps {
  data: WorkflowSearchResult;
}

function WorkflowItem({ workflow, onLoad }: { workflow: WorkflowSearchItem; onLoad: () => void }) {
  return (
    <div
      className="group p-3 bg-white rounded-xl border border-slate-200 hover:border-blue-300 hover:shadow-sm transition-all cursor-pointer"
      onClick={onLoad}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {/* 名称 */}
          <h4 className="text-sm font-semibold text-slate-800 truncate group-hover:text-blue-600 transition-colors">
            {workflow.name}
          </h4>
          {/* 描述 */}
          {workflow.description && (
            <p className="text-xs text-slate-500 mt-1 line-clamp-2">
              {workflow.description}
            </p>
          )}
          {/* 元信息 */}
          <div className="flex items-center gap-3 mt-2 text-[10px] text-slate-400">
            <span className="flex items-center gap-1">
              <GitBranch className="w-3 h-3" />
              {workflow.node_count} 节点
            </span>
            <span className="flex items-center gap-1">
              <User className="w-3 h-3" />
              {workflow.author || 'system'}
            </span>
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {new Date(workflow.updated_at || workflow.created_at).toLocaleDateString('zh-CN')}
            </span>
          </div>
          {/* 标签 */}
          {workflow.tags && workflow.tags.length > 0 && (
            <div className="flex items-center gap-1 mt-2">
              <Tag className="w-3 h-3 text-slate-400" />
              <div className="flex flex-wrap gap-1">
                {workflow.tags.slice(0, 3).map((tag, i) => (
                  <span
                    key={i}
                    className="px-1.5 py-0.5 text-[9px] bg-slate-100 text-slate-500 rounded"
                  >
                    {tag}
                  </span>
                ))}
                {workflow.tags.length > 3 && (
                  <span className="text-[9px] text-slate-400">+{workflow.tags.length - 3}</span>
                )}
              </div>
            </div>
          )}
        </div>
        {/* 加载按钮 */}
        <div className="flex-shrink-0 flex items-center gap-1 px-2 py-1 text-xs text-blue-600 bg-blue-50 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity">
          <Play className="w-3 h-3" />
          <span>加载</span>
          <ChevronRight className="w-3 h-3" />
        </div>
      </div>
    </div>
  );
}

export default function WorkflowSearchCard({ data }: WorkflowSearchCardProps) {
  const { addMessage } = useAppStore();

  const handleLoadWorkflow = (databaseId: string, name: string) => {
    // 使用数据库主键 id 进行精确加载（唯一标识符）
    wsService.send(WSMessageType.LOAD_WORKFLOW, {
      workflow_db_id: databaseId,
    });

    // 添加用户消息，保持对话连续性
    addMessage({
      role: 'user',
      content: `加载工作流 ${name}`,
      timestamp: new Date().toISOString(),
      messageType: 'text',
    });
  };

  if (!data.workflows || data.workflows.length === 0) {
    return (
      <div className="mt-3 p-4 bg-slate-50 rounded-xl border border-slate-200 text-center">
        <FolderOpen className="w-8 h-8 mx-auto text-slate-300 mb-2" />
        <p className="text-sm text-slate-500">没有找到工作流</p>
        <p className="text-xs text-slate-400 mt-1">尝试不同的搜索关键词</p>
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-3">
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-blue-100 flex items-center justify-center">
            <FolderOpen className="w-3.5 h-3.5 text-blue-600" />
          </div>
          <span className="text-sm font-medium text-slate-700">
            工作流库
          </span>
          <span className="text-xs text-slate-400">
            ({data.total} 个结果)
          </span>
        </div>
      </div>

      {/* 工作流列表 */}
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {data.workflows.map((workflow) => (
          <WorkflowItem
            key={workflow.id || workflow.workflow_id}
            workflow={workflow}
            onLoad={() => handleLoadWorkflow(workflow.id, workflow.name)}
          />
        ))}
      </div>

      {/* 提示 */}
      <p className="text-[10px] text-slate-400 text-center">
        点击工作流卡片加载到当前会话
      </p>
    </div>
  );
}

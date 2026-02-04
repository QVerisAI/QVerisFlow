import {
  CheckCircle2,
  FileText,
  Bot,
  GitBranch,
  Tag,
  User,
  Calendar,
  Database,
  FolderOpen,
  Copy,
  ExternalLink
} from 'lucide-react';
import type { WorkflowInfoCard as WorkflowInfoCardType } from '../../types';

interface WorkflowInfoCardProps {
  info: WorkflowInfoCardType;
}

export default function WorkflowInfoCard({ info }: WorkflowInfoCardProps) {
  const isSavedToDb = info.saved_to === 'database';

  const handleCopyId = () => {
    if (info.workflow_id) {
      navigator.clipboard.writeText(info.workflow_id);
    }
  };

  return (
    <div className="mt-3 bg-white rounded-2xl overflow-hidden border border-slate-200 shadow-sm">
      {/* 标题栏 */}
      <div className={`px-4 py-3 flex items-center justify-between border-b ${isSavedToDb ? 'bg-emerald-50 border-emerald-200' : 'bg-amber-50 border-amber-200'
        }`}>
        <h3 className={`font-medium flex items-center gap-2 text-sm ${isSavedToDb ? 'text-emerald-800' : 'text-amber-800'
          }`}>
          {isSavedToDb ? (
            <>
              <CheckCircle2 className="w-4 h-4" />
              工作流已保存到数据库
            </>
          ) : (
            <>
              <FolderOpen className="w-4 h-4" />
              工作流已保存到本地
            </>
          )}
        </h3>
        {isSavedToDb && (
          <div className="flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5 text-emerald-600" />
            <span className="text-[10px] text-emerald-600 font-medium">PostgreSQL</span>
          </div>
        )}
      </div>

      {/* 主要信息 */}
      <div className="p-4">
        {/* 名称和描述 */}
        <div className="mb-4">
          <h4 className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <FileText className="w-4 h-4 text-slate-400" />
            {info.name}
          </h4>
          {info.description && (
            <p className="text-sm text-slate-500 mt-1 pl-6">
              {info.description}
            </p>
          )}
        </div>

        {/* ID 信息 */}
        {info.workflow_id && (
          <div className="flex items-center gap-2 mb-3 pl-6">
            <span className="text-[10px] font-mono text-slate-400 bg-slate-100 px-2 py-0.5 rounded">
              ID: {info.workflow_id}
            </span>
            <button
              onClick={handleCopyId}
              className="text-slate-400 hover:text-slate-600 transition-colors"
              title="复制 ID"
            >
              <Copy className="w-3 h-3" />
            </button>
          </div>
        )}

        {/* 统计信息 */}
        <div className="grid grid-cols-2 gap-3 mt-4">
          <div className="bg-slate-50 rounded-lg p-3 flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
              <Bot className="w-4 h-4 text-blue-600" />
            </div>
            <div>
              <div className="text-lg font-semibold text-slate-800">{info.agent_count}</div>
              <div className="text-[10px] text-slate-500">Agent 数量</div>
            </div>
          </div>

          <div className="bg-slate-50 rounded-lg p-3 flex items-center gap-3">
            <div className="w-8 h-8 bg-purple-100 rounded-full flex items-center justify-center">
              <GitBranch className="w-4 h-4 text-purple-600" />
            </div>
            <div>
              <div className="text-lg font-semibold text-slate-800">{info.node_count}</div>
              <div className="text-[10px] text-slate-500">节点数量</div>
            </div>
          </div>
        </div>

        {/* 标签 */}
        {info.tags && info.tags.length > 0 && (
          <div className="mt-4 flex items-start gap-2">
            <Tag className="w-3.5 h-3.5 text-slate-400 mt-0.5 flex-shrink-0" />
            <div className="flex flex-wrap gap-1">
              {info.tags.map((tag, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 text-[10px] bg-blue-50 text-blue-600 rounded-full"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* 元信息 */}
        <div className="mt-4 pt-3 border-t border-slate-100 flex flex-wrap items-center gap-4 text-[10px] text-slate-400">
          {info.author && (
            <div className="flex items-center gap-1">
              <User className="w-3 h-3" />
              <span>{info.author}</span>
            </div>
          )}
          {info.created_at && (
            <div className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              <span>
                {new Date(info.created_at).toLocaleString('zh-CN', {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
            </div>
          )}
          {info.version && (
            <div className="flex items-center gap-1">
              <span>v{info.version}</span>
            </div>
          )}
        </div>
      </div>

      {/* 底部提示 */}
      <div className="px-4 py-3 bg-blue-50 border-t border-blue-100">
        <p className="text-xs text-blue-700 flex items-center gap-1.5">
          <ExternalLink className="w-3 h-3" />
          可在「工作流列表」中查看和加载此工作流
        </p>
      </div>
    </div>
  );
}

import { FolderOpen, Save, Play, Settings } from 'lucide-react';
import { useAppStore } from '../stores/appStore';
import { useWebSocket } from '../hooks/useWebSocket';

export function Header() {
  const { mode, workflowState } = useAppStore();
  const { sendAction } = useWebSocket();

  const hasWorkflow = workflowState?.nodes?.length ?? 0 > 0;
  const canExecute = hasWorkflow && mode !== 'executing';

  return (
    <header className="h-14 bg-white border-b flex items-center justify-between px-4">
      {/* 左侧：标题 */}
      <div className="flex items-center gap-3">
        <div className="text-xl">🚀</div>
        <div>
          <h1 className="font-semibold text-gray-800">对话式工作流构建器</h1>
          <p className="text-xs text-gray-500">AI 驱动的智能工作流设计</p>
        </div>
      </div>

      {/* 右侧：工具栏 */}
      <div className="flex items-center gap-2">
        {/* 打开 */}
        <button
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
          title="打开工作流"
        >
          <FolderOpen className="w-4 h-4" />
          <span className="hidden sm:inline">打开</span>
        </button>

        {/* 保存 */}
        <button
          onClick={() => sendAction('save')}
          disabled={!hasWorkflow}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title="保存工作流"
        >
          <Save className="w-4 h-4" />
          <span className="hidden sm:inline">保存</span>
        </button>

        {/* 执行 */}
        <button
          onClick={() => sendAction('execute')}
          disabled={!canExecute}
          className={`
            flex items-center gap-1.5 px-4 py-1.5 text-sm rounded-md transition-colors
            ${canExecute 
              ? 'bg-primary text-white hover:bg-primary/90' 
              : 'bg-gray-100 text-gray-400 cursor-not-allowed'}
          `}
          title="执行工作流"
        >
          <Play className="w-4 h-4" />
          <span>执行</span>
        </button>

        {/* 分隔 */}
        <div className="w-px h-6 bg-gray-200 mx-1" />

        {/* 设置 */}
        <button
          className="p-2 text-gray-500 hover:bg-gray-100 rounded-md transition-colors"
          title="设置"
        >
          <Settings className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}

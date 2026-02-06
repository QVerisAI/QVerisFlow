import { FolderOpen, Save, Play, Settings } from 'lucide-react';
import { useAppStore } from '../stores/appStore';
import { useWebSocket } from '../hooks/useWebSocket';

export function Header() {
  const { mode, workflowState } = useAppStore();
  const { sendAction, smartSave } = useWebSocket();

  const hasWorkflow = workflowState?.nodes?.length ?? 0 > 0;
  const canExecute = hasWorkflow && mode !== 'executing';

  return (
    <header className="h-14 bg-white border-b flex items-center justify-between px-4">
      {/* 左侧：品牌标识 */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center">
          <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div>
          <h1 className="font-semibold text-gray-800 tracking-tight">QVeris Flow</h1>
          <p className="text-xs text-gray-500">AI-Powered Workflow Studio</p>
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

        {/* 保存 - 使用智能保存：已有名称直接保存，否则弹出对话框 */}
        <button
          onClick={smartSave}
          disabled={!hasWorkflow}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title="保存工作流 (Cmd/Ctrl+S)"
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

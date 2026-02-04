import { useEffect, useState, useCallback, useRef } from 'react';
import { ReactFlowProvider } from 'reactflow';
import 'reactflow/dist/style.css';

import { ChatPanel } from './components/ChatPanel';
import { WorkflowCanvas } from './components/WorkflowCanvas';
import { Header } from './components/Header';
import { WorkflowListPanel } from './components/WorkflowListPanel';
import { AgentLibraryPanel } from './components/AgentLibraryPanel';
import { SaveWorkflowDialog } from './components/SaveWorkflowDialog';
import { useAppStore } from './stores/appStore';
import { useWebSocket } from './hooks/useWebSocket';

function App() {
  const {
    sessionId,
    setSessionId,
    showWorkflowListPanel,
    showAgentLibraryPanel,
    showSaveWorkflowDialog,
    setShowWorkflowListPanel,
    setShowAgentLibraryPanel,
    setShowSaveWorkflowDialog,
  } = useAppStore();
  const { connect, isConnected } = useWebSocket();

  // 可调节宽度状态（默认 675px，约为原来的 1.5 倍）
  const [panelWidth, setPanelWidth] = useState(675);
  const [isResizing, setIsResizing] = useState(false);
  const resizeRef = useRef<HTMLDivElement>(null);

  // 初始化会话（优先从 localStorage 恢复，支持断点续传）
  useEffect(() => {
    if (!sessionId) {
      // 尝试从 localStorage 恢复 session ID
      const savedSessionId = localStorage.getItem('workflow_session_id');
      if (savedSessionId) {
        console.log('恢复会话:', savedSessionId);
        setSessionId(savedSessionId);
      } else {
        // 创建新的 session ID 并保存到 localStorage
        const newSessionId = `session_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
        localStorage.setItem('workflow_session_id', newSessionId);
        console.log('创建新会话:', newSessionId);
        setSessionId(newSessionId);
      }
    } else {
      // 确保当前 session ID 保存到 localStorage
      localStorage.setItem('workflow_session_id', sessionId);
    }
  }, [sessionId, setSessionId]);

  // 连接 WebSocket（只在初始化时连接一次，重连由 wsService 自动处理）
  const hasConnectedRef = useRef(false);
  useEffect(() => {
    if (sessionId && !hasConnectedRef.current) {
      hasConnectedRef.current = true;
      connect(sessionId);
    }
  }, [sessionId, connect]);

  // 监听页面可见性变化，在页面重新可见时检查连接
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && sessionId && !isConnected) {
        console.log('页面可见，检查连接状态');
        connect(sessionId);
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [sessionId, isConnected, connect]);

  // 处理拖拽调整宽度
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isResizing) return;
    const newWidth = Math.max(400, Math.min(1000, e.clientX));
    setPanelWidth(newWidth);
  }, [isResizing]);

  const handleMouseUp = useCallback(() => {
    setIsResizing(false);
  }, []);

  useEffect(() => {
    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    } else {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, handleMouseMove, handleMouseUp]);

  return (
    <ReactFlowProvider>
      <div className="h-screen flex flex-col bg-gray-50">
        {/* 顶部导航 */}
        <Header />

        {/* 主内容区 */}
        <div className="flex-1 flex overflow-hidden">
          {/* 左侧：对话面板 */}
          <div
            className="border-r bg-white flex flex-col flex-shrink-0"
            style={{ width: panelWidth }}
          >
            <ChatPanel />
          </div>

          {/* 可拖拽的分隔条 */}
          <div
            ref={resizeRef}
            onMouseDown={handleMouseDown}
            className={`
              w-1 hover:w-1.5 bg-gray-200 hover:bg-primary/50 cursor-col-resize 
              transition-all duration-150 flex-shrink-0
              ${isResizing ? 'w-1.5 bg-primary/50' : ''}
            `}
          />

          {/* 右侧：工作流画布 */}
          <div className="flex-1 min-w-[400px]">
            <WorkflowCanvas />
          </div>
        </div>

        {/* 底部状态栏 */}
        <div className="h-8 bg-gray-100 border-t flex items-center justify-between px-4 text-xs text-gray-500">
          <div className="flex items-center">
            <span className={`w-2 h-2 rounded-full mr-2 ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
            <span>{isConnected ? '已连接' : '未连接'}</span>
            <span className="mx-2">|</span>
            <span>会话: {sessionId?.slice(0, 20)}...</span>
          </div>

          {/* 快捷按钮 */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowWorkflowListPanel(true)}
              className="px-2 py-1 hover:bg-gray-200 rounded text-gray-600 hover:text-gray-900 transition-colors"
              title="打开工作流列表"
            >
              📋 工作流
            </button>
            <button
              onClick={() => setShowAgentLibraryPanel(true)}
              className="px-2 py-1 hover:bg-gray-200 rounded text-gray-600 hover:text-gray-900 transition-colors"
              title="打开 Agent 库"
            >
              🤖 Agent 库
            </button>
            <button
              onClick={() => setShowSaveWorkflowDialog(true)}
              className="px-2 py-1 hover:bg-gray-200 rounded text-gray-600 hover:text-gray-900 transition-colors"
              title="保存当前工作流"
            >
              💾 保存
            </button>
          </div>
        </div>

        {/* 弹窗 */}
        {showWorkflowListPanel && (
          <WorkflowListPanel onClose={() => setShowWorkflowListPanel(false)} />
        )}
        {showAgentLibraryPanel && (
          <AgentLibraryPanel onClose={() => setShowAgentLibraryPanel(false)} />
        )}
        {showSaveWorkflowDialog && (
          <SaveWorkflowDialog onClose={() => setShowSaveWorkflowDialog(false)} />
        )}
      </div>
    </ReactFlowProvider>
  );
}

export default App;

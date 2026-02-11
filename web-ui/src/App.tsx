import { useEffect, useState, useCallback, useRef } from 'react';
import { ReactFlowProvider } from 'reactflow';
import 'reactflow/dist/style.css';

import { ChatPanel } from './components/ChatPanel';
import { WorkflowCanvas } from './components/WorkflowCanvas';
import { Header } from './components/Header';
import { WorkflowListPanel } from './components/WorkflowListPanel';
import { AgentLibraryPanel } from './components/AgentLibraryPanel';
import { SaveWorkflowDialog } from './components/SaveWorkflowDialog';
import { ScheduleTaskDialog } from './components/ScheduleTaskDialog';
import { LoginPage } from './components/LoginPage';
import { useAppStore } from './stores/appStore';
import { useWebSocket } from './hooks/useWebSocket';
import { getCurrentUser, isAuthenticated as checkAuth } from './services/auth';
import type { AuthUser } from './services/auth';
import type { WorkflowSummary } from './types';

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
    isAuthenticated: isAuthed,
    setAuth,
  } = useAppStore();
  const { connect, isConnected, isReconnecting, reconnectAttempt, smartSave } = useWebSocket();

  // 初始化认证状态（从 localStorage 恢复）
  const authInitRef = useRef(false);
  useEffect(() => {
    if (!authInitRef.current) {
      authInitRef.current = true;
      if (checkAuth()) {
        const user = getCurrentUser();
        if (user) {
          setAuth(user);
        }
      }
    }
  }, [setAuth]);

  // 登录成功回调
  const handleLoginSuccess = useCallback((user: AuthUser) => {
    setAuth(user);
  }, [setAuth]);

  // 如果未认证，显示登录页面
  if (!isAuthed) {
    return <LoginPage onLoginSuccess={handleLoginSuccess} />;
  }

  // 定时任务弹窗状态
  const [scheduleWorkflow, setScheduleWorkflow] = useState<WorkflowSummary | null>(null);

  // 全局快捷键：Cmd/Ctrl + S 保存工作流
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        smartSave();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [smartSave]);

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
        {/* 重连状态提示 */}
        {isReconnecting && (
          <div className="bg-yellow-500 text-white text-center py-2 text-sm animate-pulse">
            🔄 正在重连... (尝试 {reconnectAttempt})
          </div>
        )}

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
        <div className="h-7 bg-gray-100 border-t flex items-center px-4 text-xs text-gray-500">
          <span className={`w-2 h-2 rounded-full mr-2 ${isConnected ? 'bg-green-500' :
            isReconnecting ? 'bg-yellow-500 animate-pulse' :
              'bg-red-500'
            }`} />
          <span>{
            isConnected ? '已连接' :
              isReconnecting ? `重连中 (${reconnectAttempt})` :
                '未连接'
          }</span>
          <span className="mx-2">|</span>
          <span>会话: {sessionId?.slice(0, 20)}...</span>
        </div>

        {/* 弹窗 */}
        {showWorkflowListPanel && (
          <WorkflowListPanel
            onClose={() => setShowWorkflowListPanel(false)}
            onSchedule={(workflow) => {
              setShowWorkflowListPanel(false);
              setScheduleWorkflow(workflow);
            }}
          />
        )}
        {showAgentLibraryPanel && (
          <AgentLibraryPanel onClose={() => setShowAgentLibraryPanel(false)} />
        )}
        {showSaveWorkflowDialog && (
          <SaveWorkflowDialog onClose={() => setShowSaveWorkflowDialog(false)} />
        )}
        {scheduleWorkflow && (
          <ScheduleTaskDialog
            workflow={scheduleWorkflow}
            onClose={() => setScheduleWorkflow(null)}
          />
        )}
      </div>
    </ReactFlowProvider>
  );
}

export default App;

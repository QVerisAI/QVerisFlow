import { useRef, useEffect, useState, useCallback } from 'react';
import { Send, Loader2, FolderOpen, Bot, Plus, Pause, Square } from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { useWebSocket } from '../../hooks/useWebSocket';
import { MessageBubble } from './MessageBubble';
import { CheckpointList } from './CheckpointList';

export function ChatPanel() {
  const {
    messages,
    isLoading,
    suggestedActions,
    checkpoints,
    mode,
    setShowWorkflowListPanel,
    setShowAgentLibraryPanel,
  } = useAppStore();
  const { sendMessage, sendAction } = useWebSocket();
  const [input, setInput] = useState('');
  const [showQuickMenu, setShowQuickMenu] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const quickMenuRef = useRef<HTMLDivElement>(null);
  const lastMessageCountRef = useRef(0);
  const isUserScrollingRef = useRef(false);

  // 智能滚动：仅在新消息添加时滚动到底部，且用户未手动滚动时
  const scrollToBottom = useCallback((force = false) => {
    if (!messagesContainerRef.current || !messagesEndRef.current) return;

    const container = messagesContainerRef.current;
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;

    // 只有在接近底部或强制滚动时才滚动
    if (isNearBottom || force) {
      // 使用 requestAnimationFrame 确保在 DOM 更新后滚动
      requestAnimationFrame(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
      });
    }
  }, []);

  // 监听消息变化，只在新消息添加时滚动
  useEffect(() => {
    const newCount = messages.length;
    const oldCount = lastMessageCountRef.current;

    if (newCount > oldCount) {
      // 新消息添加，滚动到底部
      scrollToBottom(true);
    }

    lastMessageCountRef.current = newCount;
  }, [messages.length, scrollToBottom]);

  // 监听用户滚动
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
      isUserScrollingRef.current = !isNearBottom;
    };

    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, []);

  // 点击外部关闭快捷菜单
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (quickMenuRef.current && !quickMenuRef.current.contains(e.target as Node)) {
        setShowQuickMenu(false);
      }
    };

    if (showQuickMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showQuickMenu]);

  // 处理发送
  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    sendMessage(trimmed);
    setInput('');

    // 重新聚焦输入框
    setTimeout(() => {
      inputRef.current?.focus();
    }, 100);
  };

  // 处理快捷键
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 处理建议点击 - 直接调用后端操作，避免依赖 LLM 识别
  const handleSuggestionClick = (suggestion: string) => {
    // 将建议操作映射为直接的 WebSocket action（含自然语言建议）
    const actionMap: Record<string, string | null> = {
      '确认规划': 'approve',
      '确认 Agents': 'approve',
      '确认工作流': 'approve',
      '确认': 'approve',
      '看起来不错': 'approve',
      '修改规划': null,
      '添加 Agent': null,
      '修改 Agent': null,
      '重新生成': 'regenerate',
      '回滚': 'rollback',
      '执行工作流': 'execute',
      '执行': 'execute',
      '试试看效果': 'execute',
      '保存工作流': 'save',
      '保存': 'save',
      '先保存': 'save',
      '先保存下来': 'save',
      '修改工作流': null,
      '我想调整一下': null,
      '我想调整': null,
      '查看详情': null,
    };

    const directAction = actionMap[suggestion];
    if (directAction) {
      // 直接调用 WebSocket action，绕过 LLM
      sendAction(directAction);
    } else {
      // 其他情况作为聊天消息发送
      sendMessage(suggestion);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 标题 */}
      <div className="px-4 py-3 border-b bg-white">
        <h2 className="font-semibold text-gray-800">对话</h2>
        <p className="text-xs text-gray-500 mt-0.5">
          {mode === 'executing' ? '执行中 - 可随时干预' :
            mode === 'building' ? '构建中 - 描述您的需求' :
              '描述您要创建的工作流'}
        </p>
      </div>

      {/* 消息列表 */}
      <div
        ref={messagesContainerRef}
        className="flex-1 overflow-y-auto p-4 space-y-4"
      >
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full px-6">
            {/* 欢迎标题 */}
            <div className="text-center mb-8">
              <h3 className="text-xl font-medium text-gray-800">开始构建</h3>
              <p className="text-sm text-gray-500 mt-1">创建新工作流或从库中选择</p>
            </div>

            {/* 两个主入口 */}
            <div className="flex gap-4 mb-8">
              <button
                onClick={() => setShowWorkflowListPanel(true)}
                className="flex flex-col items-center gap-2 p-5 w-32 rounded-xl border border-gray-200 hover:border-primary/50 hover:bg-primary/5 transition-all group"
              >
                <FolderOpen className="w-7 h-7 text-gray-400 group-hover:text-primary transition-colors" />
                <span className="text-sm font-medium text-gray-700 group-hover:text-primary">工作流</span>
              </button>
              <button
                onClick={() => setShowAgentLibraryPanel(true)}
                className="flex flex-col items-center gap-2 p-5 w-32 rounded-xl border border-gray-200 hover:border-primary/50 hover:bg-primary/5 transition-all group"
              >
                <Bot className="w-7 h-7 text-gray-400 group-hover:text-primary transition-colors" />
                <span className="text-sm font-medium text-gray-700 group-hover:text-primary">Agent 库</span>
              </button>
            </div>

            {/* 分隔线 */}
            <div className="flex items-center gap-3 w-full max-w-xs mb-6">
              <div className="flex-1 h-px bg-gray-200" />
              <span className="text-xs text-gray-400">或直接描述需求</span>
              <div className="flex-1 h-px bg-gray-200" />
            </div>

            {/* 快速开始示例 */}
            <div className="space-y-2 w-full max-w-sm">
              {[
                '帮我创建一个分析苹果股票的工作流',
                '构建一个自动化数据处理流程',
                '设计一个多 Agent 协作的研究助手',
              ].map((example, i) => (
                <button
                  key={i}
                  onClick={() => sendMessage(example)}
                  className="w-full text-left px-4 py-2.5 text-sm text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
                >
                  "{example}"
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages
            // 过滤过期的进度类消息（超过 5 分钟）
            .filter((message) => {
              const msgData = message.data as { type?: string } | undefined;
              // 只过滤进度类消息
              if (msgData?.type === 'agent_generation_progress') {
                const msgTime = new Date(message.timestamp).getTime();
                const now = Date.now();
                const MAX_AGE_MS = 5 * 60 * 1000; // 5 分钟
                if (now - msgTime > MAX_AGE_MS) {
                  return false; // 过滤掉过期的进度消息
                }
              }
              return true;
            })
            .map((message, index) => (
              <MessageBubble key={message.id || `fallback_${index}`} message={message} />
            ))
        )}

        {isLoading && (
          <div className="flex items-center gap-2 text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-sm">思考中...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 建议操作 - 使用固定最小高度避免布局跳动 */}
      <div className={`px-4 py-2 border-t bg-gray-50 transition-all duration-150 ${suggestedActions.length > 0 ? 'min-h-[44px]' : 'h-0 py-0 overflow-hidden border-t-0'}`}>
        {suggestedActions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {suggestedActions.slice(0, 3).map((action, index) => (
              <button
                key={`action_${action}_${index}`}
                onClick={() => handleSuggestionClick(action)}
                className="px-3 py-1.5 text-xs bg-white border rounded-full hover:bg-gray-100 transition-colors"
              >
                {action}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 检查点列表 - 使用平滑过渡 */}
      <div className={`transition-all duration-150 ${checkpoints.length > 0 ? '' : 'h-0 overflow-hidden'}`}>
        {checkpoints.length > 0 && (
          <CheckpointList
            checkpoints={checkpoints}
            onRollback={(id: string) => sendMessage(`回滚到 ${id}`)}
          />
        )}
      </div>

      {/* 输入区域 */}
      <div className="p-4 border-t bg-white">
        <div className="flex items-end gap-2">
          {/* "+"按钮和快捷菜单 */}
          <div className="relative" ref={quickMenuRef}>
            <button
              onClick={() => setShowQuickMenu(!showQuickMenu)}
              className="p-2 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
              title="快速访问"
            >
              <Plus className="w-5 h-5" />
            </button>

            {/* 弹出菜单 */}
            {showQuickMenu && (
              <div className="absolute bottom-full left-0 mb-2 w-36 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-10">
                <button
                  onClick={() => {
                    setShowWorkflowListPanel(true);
                    setShowQuickMenu(false);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 transition-colors"
                >
                  <FolderOpen className="w-4 h-4 text-gray-400" />
                  工作流库
                </button>
                <button
                  onClick={() => {
                    setShowAgentLibraryPanel(true);
                    setShowQuickMenu(false);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 transition-colors"
                >
                  <Bot className="w-4 h-4 text-gray-400" />
                  Agent 库
                </button>
              </div>
            )}
          </div>

          {mode === 'executing' && (
            <div className="flex items-center gap-1 mr-1">
              <button
                type="button"
                onClick={() => sendMessage('暂停')}
                disabled={isLoading}
                className="p-2 rounded-lg text-amber-600 hover:bg-amber-50 disabled:opacity-50 transition-colors"
                title="暂停执行"
              >
                <Pause className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={() => sendMessage('停止')}
                disabled={isLoading}
                className="p-2 rounded-lg text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors"
                title="停止执行"
              >
                <Square className="w-4 h-4" />
              </button>
            </div>
          )}
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              mode === 'idle'
                ? '描述你想创建的工作流，或从库中选择...'
                : mode === 'building'
                  ? '对方案有什么想法？可以直接说出修改意见...'
                  : mode === 'executing'
                    ? '执行中，你可以随时说"暂停"、"跳过"或补充指令...'
                    : mode === 'completed'
                      ? '对结果满意吗？可以调整后重新执行...'
                      : '输入消息...'
            }
            className="flex-1 resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary min-h-[40px] max-h-[120px]"
            rows={1}
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="p-2 rounded-lg bg-primary text-white hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

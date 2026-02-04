import { useRef, useEffect, useState, useCallback } from 'react';
import { Send, Loader2, FolderOpen, Bot, Save } from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { useWebSocket } from '../../hooks/useWebSocket';
import { MessageBubble } from './MessageBubble';
import { CheckpointList } from './CheckpointList';

export function ChatPanel() {
  const { messages, isLoading, suggestedActions, checkpoints, mode } = useAppStore();
  const { sendMessage, sendAction } = useWebSocket();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
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
    // 将建议操作映射为直接的 WebSocket action
    const actionMap: Record<string, string | null> = {
      '确认规划': 'approve',
      '确认 Agents': 'approve',
      '确认工作流': 'approve',
      '确认': 'approve',
      '修改规划': null,  // 保持为聊天消息
      '添加 Agent': null,
      '修改 Agent': null,
      '重新生成': 'regenerate',
      '回滚': 'rollback',
      '执行工作流': 'execute',
      '执行': 'execute',
      '保存工作流': 'save',
      '保存': 'save',
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
          <div className="text-center text-gray-400 mt-8">
            <p>👋 您好！</p>
            <p className="text-sm mt-2">描述您想创建的工作流，例如：</p>
            <p className="text-sm mt-1 text-gray-500">
              "帮我创建一个分析苹果股票的工作流"
            </p>
          </div>
        ) : (
          messages.map((message, index) => (
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
            {suggestedActions.map((action, index) => (
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

      {/* 快捷工具栏 */}
      <div className="px-4 py-2 border-t bg-slate-50 flex items-center gap-2">
        <button
          onClick={() => sendMessage("列出所有工作流")}
          disabled={isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-slate-300 transition-colors disabled:opacity-50"
          title="浏览工作流库"
        >
          <FolderOpen className="w-3.5 h-3.5" />
          <span>工作流库</span>
        </button>
        <button
          onClick={() => sendMessage("列出所有 Agent")}
          disabled={isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-slate-300 transition-colors disabled:opacity-50"
          title="浏览 Agent 库"
        >
          <Bot className="w-3.5 h-3.5" />
          <span>Agent 库</span>
        </button>
        <button
          onClick={() => sendMessage("保存当前工作流")}
          disabled={isLoading || mode === 'idle'}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-slate-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title="保存当前工作流"
        >
          <Save className="w-3.5 h-3.5" />
          <span>保存</span>
        </button>
        <div className="flex-1" />
        <span className="text-[10px] text-slate-400">
          通过对话搜索和管理
        </span>
      </div>

      {/* 输入区域 */}
      <div className="p-4 border-t bg-white">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              mode === 'executing'
                ? "输入干预指令... (暂停/跳过/停止)"
                : "描述您的需求或修改意见..."
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

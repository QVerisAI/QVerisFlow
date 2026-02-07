import { useRef, useCallback, useMemo, forwardRef, useImperativeHandle, useState } from 'react';
import { Virtuoso, VirtuosoHandle } from 'react-virtuoso';
import { Loader2, ChevronUp } from 'lucide-react';
import { MessageBubble } from './MessageBubble';
import type { Message } from '../../types';

export interface VirtualizedMessageListHandle {
  scrollToBottom: () => void;
}

interface VirtualizedMessageListProps {
  messages: Message[];
  isLoading?: boolean;
  hasMoreHistory?: boolean;
  isLoadingHistory?: boolean;
  onLoadMore?: () => void;
}

// 使用一个大的起始索引，以便在头部插入消息时不会跳动
const FIRST_INDEX_BASE = 1000000;

export const VirtualizedMessageList = forwardRef<
  VirtualizedMessageListHandle,
  VirtualizedMessageListProps
>(({ messages, isLoading, hasMoreHistory, isLoadingHistory, onLoadMore }, ref) => {
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const [atTop, setAtTop] = useState(false);

  // 暴露滚动方法
  useImperativeHandle(ref, () => ({
    scrollToBottom: () => {
      virtuosoRef.current?.scrollToIndex({
        index: 'LAST',
        behavior: 'smooth',
      });
    },
  }));

  // 过滤过期的进度消息（useMemo 避免每次渲染重新计算）
  const filteredMessages = useMemo(() => {
    const now = Date.now();
    const MAX_AGE_MS = 5 * 60 * 1000;

    return messages.filter((message) => {
      const msgData = message.data as { type?: string } | undefined;
      if (msgData?.type === 'agent_generation_progress') {
        const msgTime = new Date(message.timestamp).getTime();
        if (!isNaN(msgTime) && now - msgTime > MAX_AGE_MS) {
          return false;
        }
      }
      return true;
    });
  }, [messages]);

  // 计算 firstItemIndex：用于支持向上无限滚动而不跳动
  const firstItemIndex = useMemo(() => {
    return FIRST_INDEX_BASE - filteredMessages.length;
  }, [filteredMessages.length]);

  // 渲染单条消息
  const itemContent = useCallback((_index: number, message: Message) => {
    return <MessageBubble message={message} />;
  }, []);

  // 计算 key
  const computeItemKey = useCallback((_index: number, message: Message) => {
    return message.id || `msg_${_index}`;
  }, []);

  // 当用户滚动到顶部时触发加载更多
  const handleStartReached = useCallback(() => {
    if (hasMoreHistory && !isLoadingHistory && onLoadMore) {
      console.log('滚动到顶部，加载更多历史消息');
      onLoadMore();
    }
  }, [hasMoreHistory, isLoadingHistory, onLoadMore]);

  // 顶部加载指示器
  const Header = useCallback(() => {
    if (isLoadingHistory) {
      return (
        <div className="flex items-center justify-center gap-2 text-gray-500 py-3">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">加载更多历史...</span>
        </div>
      );
    }
    if (hasMoreHistory && atTop) {
      return (
        <div className="flex items-center justify-center gap-1 text-gray-400 py-2">
          <ChevronUp className="w-4 h-4" />
          <span className="text-xs">继续向上滚动加载更多</span>
        </div>
      );
    }
    if (!hasMoreHistory && filteredMessages.length > 0) {
      return (
        <div className="flex items-center justify-center text-gray-400 py-2">
          <span className="text-xs">已加载全部历史消息</span>
        </div>
      );
    }
    return null;
  }, [isLoadingHistory, hasMoreHistory, atTop, filteredMessages.length]);

  // 底部加载指示器
  const Footer = useCallback(() => {
    if (!isLoading) return <div className="h-1" />; // 保留底部间距
    return (
      <div className="flex items-center gap-2 text-gray-500 py-2">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-sm">思考中...</span>
      </div>
    );
  }, [isLoading]);

  return (
    <Virtuoso
      ref={virtuosoRef}
      data={filteredMessages}
      firstItemIndex={firstItemIndex}
      itemContent={itemContent}
      computeItemKey={computeItemKey}
      followOutput="smooth"
      initialTopMostItemIndex={FIRST_INDEX_BASE - 1}
      alignToBottom={true}
      overscan={300}
      increaseViewportBy={{ top: 200, bottom: 200 }}
      startReached={handleStartReached}
      atTopStateChange={setAtTop}
      components={{ Header, Footer }}
      className="h-full px-4"
    />
  );
});

VirtualizedMessageList.displayName = 'VirtualizedMessageList';

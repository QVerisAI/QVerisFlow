/**
 * Socket.IO 服务
 * 
 * 替代原有 WebSocket 服务，保持 API 兼容。
 * Socket.IO 提供：
 * - 内置健壮的心跳机制
 * - 自动重连（指数退避）
 * - 断网期间消息缓冲
 * - 传输层自动降级（WebSocket → Long Polling）
 */

import { io, Socket } from 'socket.io-client';
import { WSMessageType, type WSMessage } from '../types';
import { getToken } from './auth';

type MessageHandler = (message: WSMessage) => void;

class SocketIOService {
  private socket: Socket | null = null;
  private handlers: Map<WSMessageType, Set<MessageHandler>> = new Map();
  private handlerIds: Map<string, MessageHandler> = new Map();
  private sessionId: string | null = null;
  /** 主动断开时设为 true，用于在 disconnect 事件中区分用户断开与意外断开 */
  private intentionalDisconnect = false;

  // 连接状态回调（保持与原接口兼容）
  private onConnectionChange: ((connected: boolean) => void) | null = null;
  private onReconnectingChange: ((reconnecting: boolean, attempt: number) => void) | null = null;
  private onAuthError: (() => void) | null = null;

  get isConnected(): boolean {
    return this.socket?.connected ?? false;
  }

  setConnectionChangeCallback(callback: (connected: boolean) => void): void {
    this.onConnectionChange = callback;
  }

  setReconnectingCallback(callback: (reconnecting: boolean, attempt: number) => void): void {
    this.onReconnectingChange = callback;
  }

  setAuthErrorCallback(callback: () => void): void {
    this.onAuthError = callback;
  }

  connect(sessionId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      // 如果已连接到相同的 session，跳过
      if (this.socket?.connected && this.sessionId === sessionId) {
        console.log('Socket.IO: 已连接到相同会话，跳过');
        resolve();
        return;
      }

      // 关闭旧连接
      if (this.socket) {
        this.socket.disconnect();
        this.socket = null;
      }

      this.sessionId = sessionId;
      this.intentionalDisconnect = false;

      // 构建连接 URL
      const protocol = window.location.protocol === 'https:' ? 'https' : 'http';
      const host = window.location.host;
      const url = `${protocol}://${host}`;

      console.log('Socket.IO: 连接到', url, '会话:', sessionId);

      // 创建 Socket.IO 连接
      this.socket = io(url, {
        // 认证信息（含 JWT token）
        auth: {
          session_id: sessionId,
          token: getToken(),
        },
        // Socket.IO 内置重连配置
        reconnection: true,
        reconnectionAttempts: Infinity,  // 无限重试
        reconnectionDelay: 1000,         // 初始延迟 1s
        reconnectionDelayMax: 30000,     // 最大延迟 30s
        // 超时配置
        timeout: 20000,
        // 传输配置（优先 WebSocket，自动降级为 polling）
        transports: ['websocket', 'polling'],
      });

      // 连接超时处理
      const connectionTimeout = setTimeout(() => {
        if (!this.socket?.connected) {
          console.warn('Socket.IO: 连接超时');
          this.socket?.disconnect();
          reject(new Error('Connection timeout'));
        }
      }, 20000);

      // 连接成功
      this.socket.on('connect', () => {
        clearTimeout(connectionTimeout);
        console.log('Socket.IO: 已连接');
        this.onConnectionChange?.(true);
        resolve();
      });

      // 断开连接（仅对意外断开通知 UI，避免用户主动断开时闪一下“已断开”）
      this.socket.on('disconnect', (reason) => {
        console.log('Socket.IO: 断开连接，原因:', reason);
        if (!this.intentionalDisconnect) {
          this.onConnectionChange?.(false);
        }
      });

      // 重连中
      this.socket.io.on('reconnect_attempt', (attempt) => {
        console.log(`Socket.IO: 正在重连... 尝试 ${attempt}`);
        this.onReconnectingChange?.(true, attempt);
      });

      // 重连成功
      this.socket.io.on('reconnect', () => {
        console.log('Socket.IO: 重连成功');
        this.onReconnectingChange?.(false, 0);
        this.onConnectionChange?.(true);
      });

      // 重连失败
      this.socket.io.on('reconnect_failed', () => {
        console.error('Socket.IO: 重连失败');
        this.onReconnectingChange?.(false, 0);
      });

      // 错误处理
      this.socket.on('connect_error', (error) => {
        console.error('Socket.IO: 连接错误:', error.message);
        // 如果是认证错误，通知上层处理（不自动重连）
        if (error.message?.includes('认证失败') || error.message?.includes('token')) {
          console.error('Socket.IO: 认证失败，停止重连');
          this.socket?.disconnect();
          this.onAuthError?.();
          return;
        }
        // 其他错误让 Socket.IO 自动重连
      });

      // 注册所有消息类型的监听器
      this.registerEventListeners();
    });
  }

  private registerEventListeners(): void {
    if (!this.socket) return;

    // 为每个消息类型注册监听器
    const eventTypes = Object.values(WSMessageType);

    eventTypes.forEach((eventType) => {
      this.socket!.on(eventType, (data: WSMessage) => {
        this.dispatch(data);
      });
    });
  }

  disconnect(): void {
    this.intentionalDisconnect = true;
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
    }
  }

  // ==================== 发送方法（保持与原接口兼容）====================

  send(type: WSMessageType, payload: Record<string, unknown>): void {
    if (!this.socket?.connected) {
      console.error('Socket.IO: 未连接');
      return;
    }

    const message: WSMessage = {
      type,
      payload,
      timestamp: new Date().toISOString(),
    };

    // Socket.IO 使用事件名发送
    this.socket.emit(type, message);
  }

  sendChatMessage(content: string): void {
    this.send(WSMessageType.CHAT_MESSAGE, { content });
  }

  sendUserAction(action: string, params?: Record<string, unknown>): void {
    this.send(WSMessageType.USER_ACTION, { action, params });
  }

  subscribe(channel: string): void {
    this.send(WSMessageType.SUBSCRIBE, { channel });
  }

  unsubscribe(channel: string): void {
    this.send(WSMessageType.UNSUBSCRIBE, { channel });
  }

  /**
   * 发送智能体更新请求
   */
  updateAgent(agentName: string, updates: Record<string, unknown>): void {
    this.send(WSMessageType.UPDATE_AGENT, { agent_name: agentName, updates });
  }

  /**
   * 发送 Prompt 优化请求
   */
  optimizePrompt(
    agentName: string,
    field: string,
    currentValue: string,
    optimizationGoal?: string
  ): void {
    this.send(WSMessageType.OPTIMIZE_PROMPT, {
      agent_name: agentName,
      field,
      current_value: currentValue,
      optimization_goal: optimizationGoal,
    });
  }

  /**
   * 获取执行详情
   */
  getExecutionDetail(executionId: string): void {
    this.send(WSMessageType.GET_EXECUTION_DETAIL, { execution_id: executionId });
  }

  /**
   * 注册消息处理器（带去重）
   * @param type 消息类型
   * @param handler 处理函数
   * @param handlerId 可选的处理器 ID，用于防止重复注册
   */
  on(type: WSMessageType, handler: MessageHandler, handlerId?: string): () => void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set());
    }

    // 如果提供了 handlerId，检查是否已存在
    if (handlerId) {
      const existingHandler = this.handlerIds.get(handlerId);
      if (existingHandler) {
        // 先移除旧的处理器
        this.handlers.get(type)?.delete(existingHandler);
      }
      this.handlerIds.set(handlerId, handler);
    }

    this.handlers.get(type)!.add(handler);

    // 返回取消订阅函数
    return () => {
      const handlers = this.handlers.get(type);
      if (handlers) {
        handlers.delete(handler);
      }
      if (handlerId) {
        this.handlerIds.delete(handlerId);
      }
    };
  }

  off(type: WSMessageType, handler?: MessageHandler): void {
    if (!handler) {
      this.handlers.delete(type);
    } else {
      const handlers = this.handlers.get(type);
      if (handlers) {
        handlers.delete(handler);
      }
    }
  }

  /**
   * 清除所有处理器
   */
  clearAllHandlers(): void {
    this.handlers.clear();
    this.handlerIds.clear();
  }

  /**
   * 兼容原有 handlePong 方法
   * Socket.IO 自动处理心跳，此方法保留仅用于接口兼容
   */
  handlePong(): void {
    // Socket.IO 自动处理心跳，无需手动实现
  }

  private dispatch(message: WSMessage): void {
    const handlers = this.handlers.get(message.type);
    if (handlers) {
      handlers.forEach(handler => {
        try {
          handler(message);
        } catch (e) {
          console.error('Handler error:', e);
        }
      });
    }

    // 同时触发通配符处理器
    const allHandlers = this.handlers.get('*' as WSMessageType);
    if (allHandlers) {
      allHandlers.forEach(handler => {
        try {
          handler(message);
        } catch (e) {
          console.error('Handler error:', e);
        }
      });
    }
  }
}

// 单例导出
export const wsService = new SocketIOService();

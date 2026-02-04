import { WSMessageType, type WSMessage } from '../types';

type MessageHandler = (message: WSMessage) => void;

class WebSocketService {
  private ws: WebSocket | null = null;
  private handlers: Map<WSMessageType, Set<MessageHandler>> = new Map();
  private handlerIds: Map<string, MessageHandler> = new Map(); // 用于去重
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 20;  // 增加重连次数
  private reconnectDelay = 1000;
  private sessionId: string | null = null;
  private intentionalDisconnect = false;  // 标记是否为主动断开
  private isReconnecting = false;  // 防止重复重连

  // 心跳机制 - 更频繁的心跳以保持连接
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private heartbeatTimeout: ReturnType<typeof setTimeout> | null = null;
  private readonly HEARTBEAT_INTERVAL = 15000;  // 15秒发送一次心跳（更频繁）
  private readonly HEARTBEAT_TIMEOUT = 8000;    // 8秒内未收到响应视为断开
  private lastPongTime = 0;

  // 连接状态回调
  private onConnectionChange: ((connected: boolean) => void) | null = null;

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  setConnectionChangeCallback(callback: (connected: boolean) => void): void {
    this.onConnectionChange = callback;
  }

  connect(sessionId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      // 如果正在重连，等待重连完成
      if (this.isReconnecting) {
        console.log('正在重连中，跳过连接请求');
        resolve();
        return;
      }

      // 如果已连接到相同的 session，跳过
      if (this.ws?.readyState === WebSocket.OPEN && this.sessionId === sessionId) {
        console.log('已连接到相同会话，跳过');
        resolve();
        return;
      }

      // 关闭旧连接
      if (this.ws && this.ws.readyState !== WebSocket.CLOSED) {
        this.ws.close(1000, 'New connection');
      }

      this.sessionId = sessionId;
      this.intentionalDisconnect = false;  // 重置标记

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      const url = `${protocol}//${host}/ws/${sessionId}`;

      console.log('Connecting to WebSocket:', url);

      this.ws = new WebSocket(url);

      const connectionTimeout = setTimeout(() => {
        if (this.ws?.readyState !== WebSocket.OPEN) {
          console.warn('WebSocket 连接超时');
          this.ws?.close();
          reject(new Error('Connection timeout'));
        }
      }, 10000);  // 10秒连接超时

      this.ws.onopen = () => {
        clearTimeout(connectionTimeout);
        console.log('WebSocket connected');
        this.reconnectAttempts = 0;
        this.isReconnecting = false;
        this.startHeartbeat();
        this.onConnectionChange?.(true);
        resolve();
      };

      this.ws.onclose = (event) => {
        clearTimeout(connectionTimeout);
        console.log('WebSocket closed:', event.code, event.reason);
        this.stopHeartbeat();
        this.onConnectionChange?.(false);

        // 只有非主动断开时才重连
        if (!this.intentionalDisconnect) {
          this.handleReconnect();
        }
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        // 不要在这里 reject，让 onclose 处理重连
      };

      this.ws.onmessage = (event) => {
        try {
          const message: WSMessage = JSON.parse(event.data);
          this.dispatch(message);
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };
    });
  }

  disconnect(): void {
    this.intentionalDisconnect = true;  // 标记为主动断开
    this.stopHeartbeat();
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');  // 使用正常关闭代码
      this.ws = null;
    }
  }

  // 启动心跳
  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.lastPongTime = Date.now();

    // 立即发送第一个心跳
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send(WSMessageType.PING, { timestamp: Date.now() });
    }

    // 定期发送心跳
    this.heartbeatInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.send(WSMessageType.PING, { timestamp: Date.now() });

        // 设置超时检测 - 如果在超时时间内没有收到 pong，视为断开
        if (this.heartbeatTimeout) {
          clearTimeout(this.heartbeatTimeout);
        }
        this.heartbeatTimeout = setTimeout(() => {
          // 检查是否在超时时间内收到了 pong
          const timeSinceLastPong = Date.now() - this.lastPongTime;
          // 只有当超过心跳间隔时才判定为超时（说明上一次 ping 没有收到 pong）
          if (timeSinceLastPong > this.HEARTBEAT_INTERVAL) {
            console.warn(`心跳超时 (${timeSinceLastPong}ms)，连接可能已断开，尝试重连`);
            // 标记为需要重连
            this.intentionalDisconnect = false;
            // 强制关闭并触发重连
            this.ws?.close(4000, 'Heartbeat timeout');
          }
        }, this.HEARTBEAT_TIMEOUT);
      } else {
        console.warn('WebSocket 未连接，停止心跳');
        this.stopHeartbeat();
        // 触发重连
        if (!this.intentionalDisconnect) {
          this.handleReconnect();
        }
      }
    }, this.HEARTBEAT_INTERVAL);
  }

  // 停止心跳
  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
    if (this.heartbeatTimeout) {
      clearTimeout(this.heartbeatTimeout);
      this.heartbeatTimeout = null;
    }
  }

  // 处理 pong 响应
  handlePong(): void {
    this.lastPongTime = Date.now();
    if (this.heartbeatTimeout) {
      clearTimeout(this.heartbeatTimeout);
      this.heartbeatTimeout = null;
    }
  }

  private handleReconnect(): void {
    if (this.isReconnecting) {
      console.log('已在重连中，跳过');
      return;
    }

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnect attempts reached');
      this.isReconnecting = false;
      return;
    }

    this.isReconnecting = true;
    this.reconnectAttempts++;

    // 使用指数退避，但设置最大延迟为 30 秒
    const delay = Math.min(
      this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1),
      30000
    );

    console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

    setTimeout(() => {
      if (this.sessionId && !this.intentionalDisconnect) {
        this.isReconnecting = false;  // 在尝试连接前重置
        this.connect(this.sessionId).catch((error) => {
          console.error('Reconnect failed:', error);
          // 重连失败，继续尝试
          this.handleReconnect();
        });
      } else {
        this.isReconnecting = false;
      }
    }, delay);
  }

  send(type: WSMessageType, payload: Record<string, unknown>): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.error('WebSocket is not connected');
      return;
    }

    const message: WSMessage = {
      type,
      payload,
      timestamp: new Date().toISOString(),
    };

    this.ws.send(JSON.stringify(message));
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
   * 发送 Agent 更新请求
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
export const wsService = new WebSocketService();

import { useEffect, useCallback, useState, useRef } from 'react';
import { wsService } from '../services/websocket';
import { useAppStore } from '../stores/appStore';
import { WSMessageType, type Message, type WorkflowState, type GenerationProgressEvent, type ExecutionRecord, type ExecutionProgress, type ExecutionSummary, type ExecutionNodeResult, type NodeActivity } from '../types';
import { generateOutputSummary, formatOutputToMarkdown } from '../utils/outputFormatter';

/**
 * 拓扑排序函数：按执行顺序排列节点，同层级按字母排序
 * @param nodes 节点列表，包含 nodeId 和 name
 * @param edges 边列表，包含 source 和 target
 * @returns 按执行顺序排序的节点 ID 数组
 */
function topologicalSort(
  nodes: Array<{ nodeId: string; name: string }>,
  edges: Array<{ source: string; target: string }>
): string[] {
  // 构建入度和邻接表
  const inDegree: Record<string, number> = {};
  const outEdges: Record<string, string[]> = {};
  const nodeNameMap: Record<string, string> = {};

  nodes.forEach(n => {
    inDegree[n.nodeId] = 0;
    outEdges[n.nodeId] = [];
    nodeNameMap[n.nodeId] = n.name;
  });

  edges.forEach(e => {
    if (inDegree[e.target] !== undefined) {
      inDegree[e.target]++;
    }
    if (outEdges[e.source]) {
      outEdges[e.source].push(e.target);
    }
  });

  // BFS 分层拓扑排序
  const result: string[] = [];
  // 获取入度为 0 的节点作为起始层，按名称字母排序
  let currentLayer = nodes
    .filter(n => inDegree[n.nodeId] === 0)
    .map(n => n.nodeId)
    .sort((a, b) => (nodeNameMap[a] || '').localeCompare(nodeNameMap[b] || ''));

  while (currentLayer.length > 0) {
    result.push(...currentLayer);
    const nextLayer: string[] = [];

    currentLayer.forEach(id => {
      outEdges[id]?.forEach(targetId => {
        inDegree[targetId]--;
        if (inDegree[targetId] === 0) {
          nextLayer.push(targetId);
        }
      });
    });

    // 同层节点按名称字母排序
    currentLayer = nextLayer.sort((a, b) =>
      (nodeNameMap[a] || '').localeCompare(nodeNameMap[b] || '')
    );
  }

  return result;
}

/**
 * 事件序列号追踪器
 * 用于检测事件丢失，每个工作流独立追踪
 */
interface EventSequenceTracker {
  workflowId: string;
  lastSequence: number;
  missedEvents: number;
}

export function useWebSocket() {
  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const currentExecutionRef = useRef<ExecutionRecord | null>(null);
  // 跟踪当前执行进度消息的状态
  const executionProgressRef = useRef<{
    messageId: string;
    progress: ExecutionProgress;
    nodeResults: Map<string, ExecutionNodeResult>;
  } | null>(null);
  // 事件序列号追踪（用于检测事件丢失）
  const eventSequenceRef = useRef<EventSequenceTracker | null>(null);
  const {
    addMessage,
    updateOrAddProgressMessage,
    updateMessageById,
    setWorkflowState,
    setHighlightedNodes,
    setSuggestedActions,
    setExecutionProgress,
    updateNodeState,
    setIsLoading,
    setCheckpoints,
    setGenerationProgress,
    updateAgentInWorkflow,
    addExecutionRecord,
    updateExecutionRecord,
    setWorkflowNodeIdMap,
    setExecutionHistory,
    setCurrentWorkflowMeta,
    updateRealtimeNodeOutput,
    clearRealtimeNodeOutputs,
    setMode,
    // 批量消息相关
    prependMessagesBatch,
    addMessagesBatch,
    setHasMoreHistory,
    setIsLoadingHistory,
  } = useAppStore();

  // 注册 Socket.IO 连接状态回调
  useEffect(() => {
    // 连接状态变化回调
    wsService.setConnectionChangeCallback((connected) => {
      setIsConnected(connected);
    });

    // 重连状态变化回调
    wsService.setReconnectingCallback((reconnecting, attempt) => {
      setIsReconnecting(reconnecting);
      setReconnectAttempt(attempt);
    });

    return () => {
      // 清理回调
      wsService.setConnectionChangeCallback(() => { });
      wsService.setReconnectingCallback(() => { });
    };
  }, []);

  // 连接
  const connect = useCallback(async (sessionId: string) => {
    try {
      await wsService.connect(sessionId);
      setIsConnected(true);
    } catch (error) {
      console.error('Failed to connect:', error);
      setIsConnected(false);
    }
  }, []);

  // 断开
  const disconnect = useCallback(() => {
    wsService.disconnect();
    setIsConnected(false);
  }, []);

  // 发送消息
  const sendMessage = useCallback((content: string) => {
    // 添加用户消息到列表
    addMessage({
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
      messageType: 'text',
    });

    setIsLoading(true);
    wsService.sendChatMessage(content);
  }, [addMessage, setIsLoading]);

  // 发送快捷操作
  const sendAction = useCallback((action: string, params?: Record<string, unknown>) => {
    wsService.sendUserAction(action, params);
  }, []);

  // 智能保存：已有名称直接保存，否则弹出对话框
  const smartSave = useCallback(() => {
    const { currentWorkflowMeta, workflowState, setShowSaveWorkflowDialog } = useAppStore.getState();

    // 检查是否有工作流可保存
    if (!workflowState?.nodes?.length) {
      console.log('没有工作流可保存');
      return;
    }

    if (currentWorkflowMeta?.name) {
      // 已有名称，直接保存
      wsService.send(WSMessageType.SAVE_WORKFLOW, {
        name: currentWorkflowMeta.name,
        description: currentWorkflowMeta.description || '',
        tags: [],
      });
    } else {
      // 首次保存，弹出对话框
      setShowSaveWorkflowDialog(true);
    }
  }, []);

  // 设置消息处理器（使用 handlerId 防止重复注册）
  useEffect(() => {
    // 连接成功
    const unsubConnected = wsService.on(WSMessageType.CONNECTED, (msg) => {
      const payload = msg.payload as {
        message: string;
        is_reconnect?: boolean;
        history_count?: number;
        mode?: string;
        session_id?: string;
      };

      console.log('Connected:', payload);

      // 确保连接状态同步
      setIsConnected(true);

      // 根据服务端返回的模式同步前端状态
      // 这确保服务重启后前端状态与后端一致
      if (payload.mode) {
        const serverMode = payload.mode as 'idle' | 'building' | 'executing' | 'completed';
        const currentMode = useAppStore.getState().mode;
        if (currentMode !== serverMode) {
          console.log(`同步会话模式: ${currentMode} -> ${serverMode}`);
          setMode(serverMode);
          // 如果服务端不在执行状态，清理执行进度（执行任务可能已丢失）
          if (serverMode !== 'executing') {
            setExecutionProgress({ nodesCompleted: 0, totalNodes: 0, currentNode: null });
            // 清理实时节点输出
            clearRealtimeNodeOutputs();
          }
        }
      }

      // 获取当前前端消息数量
      const currentMessages = useAppStore.getState().messages;
      const clientMessageCount = currentMessages.length;
      const serverHistoryCount = payload.history_count || 0;

      // 如果服务端有历史消息且前端没有消息，使用分页模式加载最新消息
      if (serverHistoryCount > 0 && clientMessageCount === 0) {
        console.log(`请求分页同步（初始加载）: 服务端=${serverHistoryCount}条, 请求最新50条`);
        setIsLoadingHistory(true);
        wsService.send(WSMessageType.SYNC_MESSAGES, {
          limit: 50,
          offset: 0,  // 从最新消息开始
        });
      } else if (serverHistoryCount > clientMessageCount) {
        // 如果服务端有更多消息（可能是新消息），使用旧协议同步增量
        console.log(`请求增量同步: 客户端=${clientMessageCount}, 服务端=${serverHistoryCount}`);
        wsService.send(WSMessageType.SYNC_MESSAGES, {
          client_message_count: clientMessageCount
        });
      }

      // 只在首次连接（非重连）时添加欢迎消息
      if (!payload.is_reconnect && clientMessageCount === 0) {
        addMessage({
          role: 'system',
          content: payload.message || '连接成功',
          timestamp: new Date().toISOString(),
          messageType: 'text',
        });
      } else if (payload.is_reconnect) {
        // 重连时只在控制台记录，不添加消息
        console.log('重连成功，会话模式:', payload.mode);
      }
    }, 'hook_connected');

    // 聊天消息
    const unsubChat = wsService.on(WSMessageType.CHAT_MESSAGE, (msg) => {
      setIsLoading(false);
      const payload = msg.payload as { role: string; content: string; message_type?: string; data?: Record<string, unknown> };

      const message: Message = {
        role: payload.role as 'user' | 'assistant' | 'system',
        content: payload.content,
        timestamp: msg.timestamp,
        messageType: (payload.message_type || 'text') as Message['messageType'],
        data: payload.data,
      };

      // 如果是执行摘要消息（从后端同步），检查是否已存在相同的摘要
      if (payload.message_type === 'execution_summary' || payload.data?.type === 'execution_summary') {
        const summaryData = payload.data as { executionId?: string } | undefined;
        const executionId = summaryData?.executionId;

        if (executionId) {
          // 检查是否已存在该执行的摘要消息（防止重复）
          const existingMessages = useAppStore.getState().messages;
          const existingSummary = existingMessages.find(
            m => m.messageType === 'execution_summary' &&
              (m.data as { executionId?: string } | undefined)?.executionId === executionId
          );

          if (existingSummary) {
            console.log('[WS] 跳过重复的执行摘要消息:', executionId);
            return;
          }
        }

        // 直接添加执行摘要消息
        addMessage(message);
        console.log('[WS] 添加执行摘要消息:', executionId);
        return;
      }

      // 如果是进度消息，使用更新逻辑（同一个 agent 只保留一条卡片）
      if (payload.data?.type === 'agent_generation_progress') {
        // 过滤过期的进度消息（超过 5 分钟）
        const msgTime = new Date(msg.timestamp).getTime();
        const now = Date.now();
        const MAX_AGE_MS = 5 * 60 * 1000; // 5 分钟
        if (now - msgTime > MAX_AGE_MS) {
          console.log('[WS] 忽略过期的进度消息:', msg.timestamp);
          return;
        }

        const agentName = (payload.data as { agent_name?: string }).agent_name;
        if (agentName) {
          updateOrAddProgressMessage(agentName, message);
          return;
        }
      }

      // 如果是工作流加载结果，处理执行历史
      if (payload.data?.type === 'workflow_loaded') {
        const loadedData = payload.data as {
          type: string;
          workflow?: { id?: string; workflow_id: string; name: string; description?: string };
          execution_history?: Array<{
            execution_id: string;
            status: string;
            started_at: string;
            completed_at?: string;
            total_duration_ms?: number;
            nodes_completed?: number;
            nodes_failed?: number;
          }>;
        };

        // 更新当前工作流元数据
        if (loadedData.workflow) {
          setCurrentWorkflowMeta({
            id: loadedData.workflow.id || '',
            workflowId: loadedData.workflow.workflow_id,
            name: loadedData.workflow.name,
            description: loadedData.workflow.description || '',
          });
        }

        // 更新执行历史
        if (loadedData.execution_history && loadedData.execution_history.length > 0) {
          const normalizeStatus = (raw?: string) => {
            if (raw === 'completed') return 'success';
            return raw as 'running' | 'success' | 'failed' | 'cancelled';
          };
          const records: ExecutionRecord[] = loadedData.execution_history.map((h) => ({
            executionId: h.execution_id,
            workflowId: loadedData.workflow?.workflow_id || '',
            status: normalizeStatus(h.status),
            startedAt: h.started_at,
            completedAt: h.completed_at,
            totalDurationMs: h.total_duration_ms,
            nodesTotal: (h.nodes_completed || 0) + (h.nodes_failed || 0),
            nodesCompleted: h.nodes_completed || 0,
            nodesFailed: h.nodes_failed || 0,
          }));
          setExecutionHistory(records);
        }
      }

      // 其他消息正常添加
      addMessage(message);
    }, 'hook_chat');

    // 批量消息同步（渐进式加载）
    const unsubSyncBatch = wsService.on(WSMessageType.SYNC_MESSAGES_BATCH, (msg) => {
      const payload = msg.payload as {
        messages: Array<{ role: string; content: string; message_type?: string; data?: Record<string, unknown>; timestamp?: string }>;
        total_count: number;
        offset: number;
        has_more: boolean;
      };

      console.log(`收到批量消息: ${payload.messages.length}条, offset=${payload.offset}, has_more=${payload.has_more}, total=${payload.total_count}`);

      // 转换消息格式
      const messages: Message[] = payload.messages.map(m => ({
        role: m.role as 'user' | 'assistant' | 'system',
        content: m.content,
        timestamp: m.timestamp || new Date().toISOString(),
        messageType: (m.message_type || 'text') as Message['messageType'],
        data: m.data,
      }));

      if (payload.offset === 0) {
        // 初始加载（最新消息），追加到列表
        addMessagesBatch(messages);
      } else {
        // 加载更早的消息，插入到列表头部
        prependMessagesBatch(messages);
      }

      // 更新是否还有更多历史
      setHasMoreHistory(payload.has_more);
      setIsLoadingHistory(false);
    }, 'hook_sync_batch');

    // 工作流更新
    const unsubWorkflow = wsService.on(WSMessageType.WORKFLOW_UPDATE, (msg) => {
      const payload = msg.payload as unknown as WorkflowState;

      // 构建多重映射：workflowNodeId/name/agentId -> frontendNodeId
      // 增加匹配成功率，因为执行事件的 node_id 可能来自不同的源
      const nodeIdMap: Record<string, string> = {};
      if (payload.nodes) {
        payload.nodes.forEach(node => {
          // 使用 workflowNodeId 作为主 key
          if (node.workflowNodeId) {
            nodeIdMap[node.workflowNodeId] = node.nodeId;
          }
          // 也用 name 作为备用 key
          if (node.name) {
            nodeIdMap[node.name] = node.nodeId;
            nodeIdMap[node.name.replace(/ /g, '_')] = node.nodeId;
          }
          // 用 agentId 作为备用 key
          if (node.agentId) {
            nodeIdMap[node.agentId] = node.nodeId;
          }
          // 用 nodeId 本身作为 key（直接匹配的情况）
          nodeIdMap[node.nodeId] = node.nodeId;
        });
      }
      setWorkflowNodeIdMap(nodeIdMap);

      setWorkflowState({
        mode: payload.mode,
        stage: payload.stage,
        agents: payload.agents || [],
        nodes: payload.nodes || [],
        edges: payload.edges || [],
        checkpoints: payload.checkpoints || [],
        agentDefinitions: payload.agentDefinitions,  // 完整的 AgentDefinition 数据
        availableTools: payload.availableTools,       // 可用工具列表
        availableModels: payload.availableModels,     // 可用模型列表
      });
    }, 'hook_workflow');

    // 节点高亮
    const unsubHighlight = wsService.on(WSMessageType.NODE_HIGHLIGHT, (msg) => {
      const payload = msg.payload as { nodes: string[] };
      setHighlightedNodes(payload.nodes);

      // 3秒后取消高亮
      setTimeout(() => {
        setHighlightedNodes([]);
      }, 3000);
    }, 'hook_highlight');

    // 建议操作
    const unsubSuggestions = wsService.on(WSMessageType.SUGGESTED_ACTIONS, (msg) => {
      const payload = msg.payload as { actions: string[] };
      setSuggestedActions(payload.actions);
    }, 'hook_suggestions');

    // 执行事件
    const unsubExecution = wsService.on(WSMessageType.EXECUTION_EVENT, (msg) => {
      // 过滤过期的执行事件（超过 5 分钟）
      const msgTime = new Date(msg.timestamp).getTime();
      const now = Date.now();
      const MAX_AGE_MS = 5 * 60 * 1000; // 5 分钟
      if (now - msgTime > MAX_AGE_MS) {
        console.log('[WS] 忽略过期的执行事件:', msg.timestamp);
        return;
      }

      const event = msg.payload as {
        event_type: string;
        workflow_id?: string;
        node_id?: string;
        node_name?: string;
        total_nodes?: number;
        nodes_completed?: number;
        nodes_failed?: number;
        progress?: number;
        duration_ms?: number;
        total_duration_ms?: number;
        error?: string;
        status?: string;
        data?: Record<string, unknown>;
        // 事件追踪字段（新增）
        event_id?: string;
        sequence?: number;
      };

      // === 事件序列号检测（检测事件丢失）===
      const workflowId = event.workflow_id || 'unknown';
      const sequence = event.sequence;
      const eventId = event.event_id;

      if (sequence !== undefined) {
        const tracker = eventSequenceRef.current;

        // 重置追踪器（新工作流或 workflow_started 事件）
        if (event.event_type === 'workflow_started' || tracker?.workflowId !== workflowId) {
          eventSequenceRef.current = {
            workflowId,
            lastSequence: sequence,
            missedEvents: 0,
          };
          console.debug(`[事件追踪] 开始追踪 workflow=${workflowId}, seq=${sequence}`);
        } else if (tracker) {
          // 检测序列号跳跃
          const expectedSeq = tracker.lastSequence + 1;
          if (sequence > expectedSeq) {
            const missed = sequence - expectedSeq;
            tracker.missedEvents += missed;
            console.warn(
              `[事件追踪] 检测到事件丢失! workflow=${workflowId}, ` +
              `expected=${expectedSeq}, got=${sequence}, missed=${missed}, ` +
              `total_missed=${tracker.missedEvents}`
            );
          }
          tracker.lastSequence = sequence;
        }

        console.debug(
          `[事件接收] type=${event.event_type}, node=${event.node_id || ''}, ` +
          `seq=${sequence}, event_id=${eventId || ''}`
        );
      }

      // 获取最新的 workflowNodeIdMap（用于将后端 node_id 映射到前端 nodeId）
      const currentNodeIdMap = useAppStore.getState().workflowNodeIdMap;

      // 将后端 node_id 转换为前端 nodeId
      // 尝试多种方式查找，以处理各种命名不一致的情况
      const resolveNodeId = (nodeId: string | undefined, nodeName?: string): string | null => {
        if (!nodeId && !nodeName) return null;

        // 尝试直接用 nodeId 查找
        if (nodeId && currentNodeIdMap[nodeId]) {
          return currentNodeIdMap[nodeId];
        }
        // 尝试用 nodeName 查找
        if (nodeName && currentNodeIdMap[nodeName]) {
          return currentNodeIdMap[nodeName];
        }
        // 尝试用处理过的 nodeName 查找
        if (nodeName && currentNodeIdMap[nodeName.replace(/ /g, '_')]) {
          return currentNodeIdMap[nodeName.replace(/ /g, '_')];
        }
        // 尝试直接返回 nodeId（如果它本身就是前端 nodeId）
        if (nodeId && nodeId.startsWith('agent_')) {
          return nodeId;
        }
        // 回退：添加 agent_ 前缀
        if (nodeId) {
          const prefixed = `agent_${nodeId}`;
          if (currentNodeIdMap[prefixed]) {
            return currentNodeIdMap[prefixed];
          }
          return prefixed;
        }
        return null;
      };

      const frontendNodeId = resolveNodeId(event.node_id, event.node_name);

      // === 处理工作流级别的执行事件 ===

      // 执行开始：创建新的执行记录和进度消息
      if (event.event_type === 'execution_started' || event.event_type === 'workflow_started') {
        const totalNodes = (event.data?.total_nodes as number) || event.total_nodes || 0;
        const executionId = event.workflow_id || `exec_${Date.now()}`;
        const workflowName = (event.data?.workflow_name as string) || '';

        const newRecord: ExecutionRecord = {
          executionId,
          workflowId: event.workflow_id || '',
          status: 'running',
          startedAt: new Date().toISOString(),
          nodesTotal: totalNodes,
          nodesCompleted: 0,
          nodesFailed: 0,
        };
        currentExecutionRef.current = newRecord;
        addExecutionRecord(newRecord);

        // 清除旧的实时节点输出
        clearRealtimeNodeOutputs();

        // 获取当前工作流节点列表，按执行顺序初始化节点结果
        const workflowState = useAppStore.getState().workflowState;
        const nodeResults: Map<string, ExecutionNodeResult> = new Map();

        if (workflowState?.nodes) {
          // 使用拓扑排序获取执行顺序
          const sortedNodeIds = topologicalSort(
            workflowState.nodes.map(n => ({ nodeId: n.nodeId, name: n.name })),
            workflowState.edges || []
          );

          // 按排序后的顺序初始化节点结果
          sortedNodeIds.forEach(nodeId => {
            const node = workflowState.nodes?.find(n => n.nodeId === nodeId);
            if (node) {
              nodeResults.set(node.nodeId, {
                nodeId: node.nodeId,
                nodeName: node.displayName || node.name,
                status: 'pending',
              });
            }
          });
        }

        // 创建执行进度消息
        const progressMessageId = `exec_progress_${executionId}`;
        const initialProgress: ExecutionProgress = {
          type: 'execution_progress',
          executionId,
          workflowId: event.workflow_id || '',
          workflowName,
          status: 'running',
          progress: 0,
          nodesCompleted: 0,
          totalNodes,
          currentNode: null,
          startedAt: new Date().toISOString(),
          nodeResults: Array.from(nodeResults.values()),
        };

        executionProgressRef.current = {
          messageId: progressMessageId,
          progress: initialProgress,
          nodeResults,
        };

        // 添加进度消息到聊天区
        addMessage({
          id: progressMessageId,
          role: 'assistant',
          content: '工作流开始执行...',
          timestamp: new Date().toISOString(),
          messageType: 'execution_progress',
          data: initialProgress as unknown as Record<string, unknown>,
        });

        // 重置 isLoading 状态，允许用户在执行过程中输入干预指令（暂停/跳过/停止）
        setIsLoading(false);
      }

      // 执行完成：更新执行记录，并将进度消息转换为摘要消息
      if (event.event_type === 'execution_completed' || event.event_type === 'workflow_completed') {
        const executionId = currentExecutionRef.current?.executionId || event.workflow_id;
        if (executionId) {
          // 判断执行状态：
          // 1. 首先检查 event.status 字段
          // 2. 如果没有，检查 event.data?.status
          // 3. 如果事件类型是 workflow_completed，默认视为成功
          const eventStatus = event.status || (event.data?.status as string);
          const isSuccess = eventStatus === 'completed' ||
            eventStatus === 'success' ||
            (event.event_type === 'workflow_completed' && eventStatus !== 'failed');

          const completedAt = new Date().toISOString();
          const totalDurationMs = event.total_duration_ms || (event.data?.total_duration_ms as number) || 0;
          const nodesCompleted = event.nodes_completed || (event.data?.nodes_completed as number) || 0;
          const nodesFailed = event.nodes_failed || (event.data?.nodes_failed as number) || 0;

          updateExecutionRecord(executionId, {
            status: isSuccess ? 'success' : 'failed',
            completedAt,
            totalDurationMs,
            nodesCompleted,
            nodesFailed,
          });

          // 检查是否已存在该执行的摘要消息（可能从后端同步）
          const existingMessages = useAppStore.getState().messages;
          const existingSummary = existingMessages.find(
            m => m.messageType === 'execution_summary' &&
              (m.data as { executionId?: string } | undefined)?.executionId === executionId
          );

          if (existingSummary) {
            // 已有摘要消息（从后端同步），只需清理进度状态
            console.log('[Execution] 已存在摘要消息，跳过创建:', executionId);
            executionProgressRef.current = null;
          } else if (executionProgressRef.current) {
            // 将进度消息转换为摘要消息
            const { messageId, progress, nodeResults } = executionProgressRef.current;
            const finalOutput = event.data?.final_output || event.data?.result;
            const finalNarrative = event.data?.final_narrative as string | undefined;
            const finalHighlights = event.data?.final_highlights as string[] | undefined;

            const summary: ExecutionSummary = {
              type: 'execution_summary',
              executionId,
              workflowId: progress.workflowId,
              workflowName: progress.workflowName,
              status: isSuccess ? 'completed' : 'failed',
              totalDurationMs,
              nodesCompleted,
              nodesFailed,
              totalNodes: progress.totalNodes,
              startedAt: progress.startedAt,
              completedAt,
              nodeResults: Array.from(nodeResults.values()),
              finalOutput,
              finalOutputMarkdown: finalOutput ? formatOutputToMarkdown(finalOutput) : undefined,
              finalNarrative: finalNarrative ?? undefined,
              finalHighlights: finalHighlights ?? undefined,
            };

            // 更新消息为摘要类型
            updateMessageById(messageId, {
              content: isSuccess ? '工作流执行完成' : '工作流执行失败',
              messageType: 'execution_summary',
              data: summary as unknown as Record<string, unknown>,
            });

            executionProgressRef.current = null;
          }
        }
        currentExecutionRef.current = null;
      }

      // 执行失败：更新执行记录
      if (event.event_type === 'execution_failed' || event.event_type === 'workflow_failed') {
        const executionId = currentExecutionRef.current?.executionId || event.workflow_id;
        if (executionId) {
          const completedAt = new Date().toISOString();
          const errorMsg = event.error || (event.data?.error as string) || '执行失败';

          updateExecutionRecord(executionId, {
            status: 'failed',
            completedAt,
          });

          // 检查是否已存在该执行的摘要消息（可能从后端同步）
          const existingMessages = useAppStore.getState().messages;
          const existingSummary = existingMessages.find(
            m => m.messageType === 'execution_summary' &&
              (m.data as { executionId?: string } | undefined)?.executionId === executionId
          );

          if (existingSummary) {
            // 已有摘要消息（从后端同步），只需清理进度状态
            console.log('[Execution] 已存在失败摘要消息，跳过创建:', executionId);
            executionProgressRef.current = null;
          } else if (executionProgressRef.current) {
            // 将进度消息转换为失败摘要
            const { messageId, progress, nodeResults } = executionProgressRef.current;

            const summary: ExecutionSummary = {
              type: 'execution_summary',
              executionId,
              workflowId: progress.workflowId,
              workflowName: progress.workflowName,
              status: 'failed',
              totalDurationMs: 0,
              nodesCompleted: progress.nodesCompleted,
              nodesFailed: 1,
              totalNodes: progress.totalNodes,
              startedAt: progress.startedAt,
              completedAt,
              nodeResults: Array.from(nodeResults.values()),
              error: errorMsg,
            };

            updateMessageById(messageId, {
              content: '工作流执行失败',
              messageType: 'execution_summary',
              data: summary as unknown as Record<string, unknown>,
            });

            executionProgressRef.current = null;
          }
        }
        currentExecutionRef.current = null;
      }

      // 执行取消：更新执行记录并转换为取消摘要消息
      if (event.event_type === 'workflow_cancelled') {
        const executionId = currentExecutionRef.current?.executionId || event.workflow_id;
        if (executionId) {
          const completedAt = new Date().toISOString();

          updateExecutionRecord(executionId, {
            status: 'cancelled',
            completedAt,
          });

          // 检查是否已存在该执行的摘要消息（可能从后端同步）
          const existingMessages = useAppStore.getState().messages;
          const existingSummary = existingMessages.find(
            m => m.messageType === 'execution_summary' &&
              (m.data as { executionId?: string } | undefined)?.executionId === executionId
          );

          if (existingSummary) {
            // 已有摘要消息（从后端同步），只需清理进度状态
            console.log('[Execution] 已存在取消摘要消息，跳过创建:', executionId);
            executionProgressRef.current = null;
          } else if (executionProgressRef.current) {
            // 将进度消息转换为取消摘要
            const { messageId, progress, nodeResults } = executionProgressRef.current;

            const summary: ExecutionSummary = {
              type: 'execution_summary',
              executionId,
              workflowId: progress.workflowId,
              workflowName: progress.workflowName,
              status: 'cancelled',
              totalDurationMs: 0,
              nodesCompleted: progress.nodesCompleted,
              nodesFailed: 0,
              totalNodes: progress.totalNodes,
              startedAt: progress.startedAt,
              completedAt,
              nodeResults: Array.from(nodeResults.values()),
            };

            updateMessageById(messageId, {
              content: '工作流已停止',
              messageType: 'execution_summary',
              data: summary as unknown as Record<string, unknown>,
            });

            executionProgressRef.current = null;
          }
        }
        currentExecutionRef.current = null;
      }

      // === 处理节点级别的执行事件 ===

      // 校验事件是否属于当前执行，忽略来自旧执行的延迟事件
      // 这避免了用户停止后重新执行时，旧执行的事件污染新执行的状态
      const currentExecId = currentExecutionRef.current?.executionId;
      const eventExecId = event.workflow_id;

      if (currentExecId && eventExecId && currentExecId !== eventExecId) {
        console.debug(
          `[事件忽略] 节点事件属于旧执行 ${eventExecId}，当前执行是 ${currentExecId}，事件类型: ${event.event_type}`
        );
        return; // 忽略不属于当前执行的节点事件
      }

      // 更新节点状态
      if (frontendNodeId) {
        let nodeStatus: 'pending' | 'running' | 'completed' | 'failed' = 'pending';
        if (event.event_type === 'node_started') nodeStatus = 'running';
        else if (event.event_type === 'node_completed') nodeStatus = 'completed';
        else if (event.event_type === 'node_failed') nodeStatus = 'failed';
        else if (event.event_type === 'node_skipped') nodeStatus = 'completed';

        updateNodeState(frontendNodeId, {
          status: nodeStatus,
          duration: (event.data?.duration_ms as number) || (event.duration_ms as number) || undefined,
        });

        // 更新当前执行节点和进度
        if (event.event_type === 'node_started') {
          setExecutionProgress({
            nodesCompleted: (event.data?.nodes_completed as number) || event.nodes_completed || 0,
            totalNodes: (event.data?.total_nodes as number) || event.total_nodes || 0,
            currentNode: frontendNodeId,
          });

          // 更新实时节点输出状态
          updateRealtimeNodeOutput(frontendNodeId, {
            status: 'running',
          });

          // 更新进度消息中的节点状态
          if (executionProgressRef.current) {
            const { messageId, progress, nodeResults } = executionProgressRef.current;
            const nodeName = event.node_name || event.node_id || frontendNodeId;

            nodeResults.set(frontendNodeId, {
              nodeId: frontendNodeId,
              nodeName,
              status: 'running',
            });

            const newProgress: ExecutionProgress = {
              ...progress,
              currentNode: nodeName,
              nodeResults: Array.from(nodeResults.values()),
            };

            executionProgressRef.current.progress = newProgress;

            updateMessageById(messageId, {
              data: newProgress as unknown as Record<string, unknown>,
            });
          }
        }

        // 节点完成时更新当前执行记录的进度和进度消息
        if (event.event_type === 'node_completed' && currentExecutionRef.current) {
          const completed = (event.data?.nodes_completed as number) || event.nodes_completed ||
            (currentExecutionRef.current.nodesCompleted + 1);
          const totalNodes = (event.data?.total_nodes as number) || event.total_nodes ||
            currentExecutionRef.current.nodesTotal;

          // 同步更新 ref 中的 nodesCompleted（确保下一次节点完成时计算正确）
          currentExecutionRef.current.nodesCompleted = completed;

          updateExecutionRecord(currentExecutionRef.current.executionId, {
            nodesCompleted: completed,
          });

          // 提取输出信息
          const output = event.data?.output || event.data?.result;
          const outputPreview = event.data?.output_preview as string | undefined;
          const outputSummary = event.data?.output_summary as string | undefined;
          const outputNarrative = event.data?.output_narrative as string | undefined;
          const outputHighlights = event.data?.output_highlights as string[] | undefined;
          const durationMs = (event.data?.duration_ms as number) || event.duration_ms;

          // 更新实时节点输出
          updateRealtimeNodeOutput(frontendNodeId, {
            status: 'completed',
            outputPreview: outputSummary || outputPreview || (output ? generateOutputSummary(output) : undefined),
            outputSummary: outputSummary || (output ? generateOutputSummary(output) : undefined),
            fullOutput: output,
          });

          // 更新进度消息
          if (executionProgressRef.current) {
            const { messageId, progress, nodeResults } = executionProgressRef.current;
            const nodeName = event.node_name || event.node_id || frontendNodeId;

            nodeResults.set(frontendNodeId, {
              nodeId: frontendNodeId,
              nodeName,
              status: 'completed',
              durationMs,
              outputPreview: outputSummary || outputPreview,
              outputSummary: outputSummary || (output ? generateOutputSummary(output) : undefined),
              outputMarkdown: output ? formatOutputToMarkdown(output) : undefined,
              outputNarrative: outputNarrative ?? undefined,
              outputHighlights: outputHighlights ?? undefined,
              fullOutput: output,
            });

            const progressPercent = Math.round((completed / totalNodes) * 100);
            const newProgress: ExecutionProgress = {
              ...progress,
              progress: progressPercent,
              nodesCompleted: completed,
              currentNode: null,
              nodeResults: Array.from(nodeResults.values()),
            };

            executionProgressRef.current.progress = newProgress;

            updateMessageById(messageId, {
              content: `工作流执行中... (${completed}/${totalNodes})`,
              data: newProgress as unknown as Record<string, unknown>,
            });
          }
        }

        // 节点失败时更新失败计数
        if (event.event_type === 'node_failed' && currentExecutionRef.current) {
          // 同步更新 ref 中的 nodesFailed（确保连续失败时计算正确）
          currentExecutionRef.current.nodesFailed = currentExecutionRef.current.nodesFailed + 1;

          updateExecutionRecord(currentExecutionRef.current.executionId, {
            nodesFailed: currentExecutionRef.current.nodesFailed,
          });

          const errorMsg = event.error || (event.data?.error as string) || '执行失败';

          // 更新实时节点输出
          updateRealtimeNodeOutput(frontendNodeId, {
            status: 'failed',
            error: errorMsg,
          });

          // 更新进度消息
          if (executionProgressRef.current) {
            const { messageId, progress, nodeResults } = executionProgressRef.current;
            const nodeName = event.node_name || event.node_id || frontendNodeId;

            nodeResults.set(frontendNodeId, {
              nodeId: frontendNodeId,
              nodeName,
              status: 'failed',
              error: errorMsg,
            });

            const newProgress: ExecutionProgress = {
              ...progress,
              nodeResults: Array.from(nodeResults.values()),
            };

            executionProgressRef.current.progress = newProgress;

            updateMessageById(messageId, {
              data: newProgress as unknown as Record<string, unknown>,
            });
          }
        }

        // 处理节点思考/流式内容（node_thinking, node_stream）
        if (event.event_type === 'node_thinking' || event.event_type === 'node_stream') {
          const content = (event.data?.content as string) || '';
          if (!content || !executionProgressRef.current) return;
          const { messageId, progress, nodeResults } = executionProgressRef.current;
          const nodeName = (event.node_name || event.node_id || frontendNodeId) ?? '';
          const existingNode = nodeResults.get(frontendNodeId);
          const key = event.event_type === 'node_thinking' ? 'thinkingContent' : 'streamContent';
          const prev = existingNode?.[key as keyof typeof existingNode] as string | undefined;
          const next = (prev ?? '') + content;
          if (existingNode) {
            nodeResults.set(frontendNodeId, { ...existingNode, [key]: next, status: 'running' });
          } else {
            nodeResults.set(frontendNodeId, {
              nodeId: frontendNodeId,
              nodeName,
              status: 'running',
              [key]: next,
            });
          }
          const newProgress: ExecutionProgress = { ...progress, nodeResults: Array.from(nodeResults.values()) };
          executionProgressRef.current.progress = newProgress;
          updateMessageById(messageId, { data: newProgress as unknown as Record<string, unknown> });
        }

        // 处理节点活动（node_activity：工具开始/结果、思考、决策等）
        if (event.event_type === 'node_activity') {
          const data = event.data as { type?: string; message?: string; tool_name?: string } | undefined;
          const activityMessage = data?.message ?? '';
          if (!executionProgressRef.current) return;
          const { messageId, progress, nodeResults } = executionProgressRef.current;
          const nodeName = event.node_name || event.node_id || frontendNodeId;
          const existingNode = nodeResults.get(frontendNodeId);
          const activity: NodeActivity = {
            type: (data?.type ?? 'thinking') as NodeActivity['type'],
            message: activityMessage,
            timestamp: new Date().toISOString(),
            toolName: data?.tool_name,
          };
          const activities = [...(existingNode?.activities ?? []), activity];
          if (existingNode) {
            nodeResults.set(frontendNodeId, {
              ...existingNode,
              status: 'running',
              runningStatus: activityMessage,
              activities,
            });
          } else {
            nodeResults.set(frontendNodeId, {
              nodeId: frontendNodeId,
              nodeName,
              status: 'running',
              runningStatus: activityMessage,
              activities,
            });
          }
          updateRealtimeNodeOutput(frontendNodeId, { status: 'running', runningStatus: activityMessage });
          const newProgress: ExecutionProgress = { ...progress, nodeResults: Array.from(nodeResults.values()) };
          executionProgressRef.current.progress = newProgress;
          updateMessageById(messageId, { data: newProgress as unknown as Record<string, unknown> });
        }

        // 处理节点进度事件（工具调用等中间状态）
        if (event.event_type === 'node_progress') {
          const status = event.status as string || event.data?.status as string || (event.data as { status?: string })?.status as string || '';

          // 更新实时节点输出的运行状态
          updateRealtimeNodeOutput(frontendNodeId, {
            status: 'running',
            runningStatus: status,
          });

          // 更新进度消息中的节点状态
          if (executionProgressRef.current) {
            const { messageId, progress, nodeResults } = executionProgressRef.current;
            const existingNode = nodeResults.get(frontendNodeId);

            if (existingNode) {
              nodeResults.set(frontendNodeId, {
                ...existingNode,
                runningStatus: status,
              });
            } else {
              const nodeName = event.node_name || event.node_id || frontendNodeId;
              nodeResults.set(frontendNodeId, {
                nodeId: frontendNodeId,
                nodeName,
                status: 'running',
                runningStatus: status,
              });
            }

            const newProgress: ExecutionProgress = {
              ...progress,
              nodeResults: Array.from(nodeResults.values()),
            };

            executionProgressRef.current.progress = newProgress;

            updateMessageById(messageId, {
              data: newProgress as unknown as Record<string, unknown>,
            });
          }
        }
      }

      // 处理进度更新事件 - 从 event.data 中正确读取
      if (event.event_type === 'progress_update') {
        const completed = (event.data?.nodes_completed as number) || event.nodes_completed || 0;
        const total = (event.data?.total_nodes as number) || event.total_nodes || 0;
        setExecutionProgress({
          nodesCompleted: completed,
          totalNodes: total,
          currentNode: resolveNodeId(event.node_id),
        });

        // 同步更新执行记录和 ref
        if (currentExecutionRef.current) {
          currentExecutionRef.current.nodesCompleted = completed;
          updateExecutionRecord(currentExecutionRef.current.executionId, {
            nodesCompleted: completed,
          });
        }
      }

      // 注意：不再为每个节点事件添加单独的消息
      // 现在使用统一的进度卡片（ExecutionProgressCard）来展示所有节点状态
      // 只保留工具调用事件作为补充信息
      if (event.event_type === 'tool_call') {
        addMessage({
          role: 'system',
          content: `   → 调用工具: ${event.data?.tool_id}`,
          timestamp: msg.timestamp,
          messageType: 'execution_event',
          data: event.data,
        });
      }
    }, 'hook_execution');

    // 进度更新
    const unsubProgress = wsService.on(WSMessageType.PROGRESS_UPDATE, (msg) => {
      const payload = msg.payload as {
        nodes_completed: number;
        total_nodes: number;
        current_node?: string;
        data?: { nodes_completed?: number; total_nodes?: number };
      };
      // 使用 workflowNodeIdMap 解析节点 ID
      const currentNodeIdMap = useAppStore.getState().workflowNodeIdMap;
      const resolveNodeId = (nodeId: string | undefined): string | null => {
        if (!nodeId) return null;
        if (currentNodeIdMap[nodeId]) return currentNodeIdMap[nodeId];
        return nodeId.startsWith('agent_') ? nodeId : `agent_${nodeId}`;
      };
      setExecutionProgress({
        nodesCompleted: payload.data?.nodes_completed ?? payload.nodes_completed ?? 0,
        totalNodes: payload.data?.total_nodes ?? payload.total_nodes ?? 0,
        currentNode: resolveNodeId(payload.current_node),
      });
    }, 'hook_progress');

    // 错误
    const unsubError = wsService.on(WSMessageType.ERROR, (msg) => {
      setIsLoading(false);
      const payload = msg.payload as { error: string };
      addMessage({
        role: 'system',
        content: `❌ 错误: ${payload.error}`,
        timestamp: msg.timestamp,
        messageType: 'error',
      });
    }, 'hook_error');

    // 检查点
    const unsubCheckpoint = wsService.on(WSMessageType.CHECKPOINT_CREATED, (msg) => {
      const payload = msg.payload as { checkpoints: Array<{ checkpoint_id: string; label: string; stage: string; timestamp: string }> };
      setCheckpoints(payload.checkpoints.map(c => ({
        checkpointId: c.checkpoint_id,
        label: c.label,
        stage: c.stage,
        timestamp: c.timestamp,
      })));
    }, 'hook_checkpoint');

    // Agent 生成进度
    const unsubGenerationProgress = wsService.on(WSMessageType.AGENT_GENERATION_PROGRESS, (msg) => {
      // 过滤过期的进度消息（超过 5 分钟）
      const msgTime = new Date(msg.timestamp).getTime();
      const now = Date.now();
      const MAX_AGE_MS = 5 * 60 * 1000; // 5 分钟
      if (now - msgTime > MAX_AGE_MS) {
        console.log('[WS] 忽略过期的 Agent 生成进度:', msg.timestamp);
        return;
      }

      const payload = msg.payload as unknown as GenerationProgressEvent;
      setGenerationProgress({
        current: payload.current,
        total: payload.total,
        agentName: payload.agent_name,
        displayName: payload.display_name,
        status: payload.status,
        message: payload.message,
      });

      // 如果生成完成或失败，3秒后清除进度
      if (payload.status === 'completed' && payload.current === payload.total) {
        setTimeout(() => {
          setGenerationProgress(null);
        }, 3000);
      }
    }, 'hook_generation_progress');

    // Agent 更新
    const unsubAgentUpdated = wsService.on(WSMessageType.AGENT_UPDATED, (msg) => {
      const payload = msg.payload as {
        agent_name: string;
        message: string;
        data?: Record<string, unknown>;
        updates?: Record<string, unknown>;  // 兼容旧格式
      };
      // 后端可能发送 data 或 updates，兼容两种格式
      const updates = payload.data || payload.updates || {};
      console.log('Agent updated:', payload.agent_name, updates);
      updateAgentInWorkflow(payload.agent_name, updates);
    }, 'hook_agent_updated');

    // 执行历史响应
    const unsubExecutionHistory = wsService.on(WSMessageType.EXECUTION_HISTORY, (msg) => {
      const payload = msg.payload as { history: ExecutionRecord[] };
      useAppStore.getState().setExecutionHistory(payload.history || []);
    }, 'hook_execution_history');

    // 执行详情响应 - 【关键修复】检查 executionId 匹配，避免响应顺序不一致导致的状态错乱
    const unsubExecutionDetail = wsService.on(WSMessageType.EXECUTION_DETAIL, (msg) => {
      const payload = msg.payload as { executionId: string; detail: ExecutionRecord };
      const state = useAppStore.getState();

      // 只有当响应的 executionId 与当前选中的执行 ID 匹配时才更新状态
      // 这避免了快速切换执行记录时，旧请求的响应覆盖新数据的问题
      if (state.selectedExecutionId === payload.executionId) {
        state.setCurrentExecutionDetail(payload.detail || null);
      } else {
        console.log(`[ExecutionDetail] 忽略过期响应: 期望=${state.selectedExecutionId}, 收到=${payload.executionId}`);
      }
    }, 'hook_execution_detail');

    // 心跳响应
    const unsubPong = wsService.on(WSMessageType.PONG, () => {
      wsService.handlePong();
    }, 'hook_pong');

    // === 工作流管理响应 ===

    // 工作流列表
    const unsubWorkflowsList = wsService.on(WSMessageType.WORKFLOWS_LIST, (msg) => {
      const payload = msg.payload as { workflows: Array<Record<string, unknown>>; total: number };
      const store = useAppStore.getState();
      store.setWorkflowListLoading(false);
      store.setWorkflowList(payload.workflows.map(w => ({
        id: w.id as string,
        workflowId: w.workflow_id as string,
        name: w.name as string,
        description: w.description as string || '',
        version: w.version as string || '1.0.0',
        status: w.status as string || 'draft',
        nodeCount: w.node_count as number || 0,
        edgeCount: w.edge_count as number || 0,
        isActive: w.is_active as boolean || false,
        tags: w.tags as string[] || [],
        author: w.author as string || 'system',
        createdAt: w.created_at as string || '',
        updatedAt: w.updated_at as string || '',
      })));
    }, 'hook_workflows_list');

    // 工作流已加载
    const unsubWorkflowLoaded = wsService.on(WSMessageType.WORKFLOW_LOADED, (msg) => {
      const payload = msg.payload as {
        id?: string;
        workflow_id: string;
        name: string;
        description: string;
        message: string;
        execution_history?: Array<{
          execution_id: string;
          status: string;
          started_at: string;
          completed_at?: string;
          total_duration_ms?: number;
          nodes_completed?: number;
          nodes_failed?: number;
        }>;
      };
      const store = useAppStore.getState();

      // 清理旧的工作流相关卡片消息，避免加载新工作流时显示旧的信息
      store.removeMessagesByDataType('workflow_info_card');
      store.removeMessagesByDataType('workflow_loaded');

      store.setCurrentWorkflowMeta({
        id: payload.id || '',
        workflowId: payload.workflow_id,
        name: payload.name,
        description: payload.description,
      });
      if (payload.execution_history) {
        const normalizeStatus = (raw?: string) => {
          if (raw === 'completed') return 'success';
          return raw as 'running' | 'success' | 'failed' | 'cancelled';
        };
        const records: ExecutionRecord[] = payload.execution_history.map((h) => ({
          executionId: h.execution_id,
          workflowId: payload.workflow_id,
          status: normalizeStatus(h.status),
          startedAt: h.started_at,
          completedAt: h.completed_at,
          totalDurationMs: h.total_duration_ms,
          nodesTotal: (h.nodes_completed || 0) + (h.nodes_failed || 0),
          nodesCompleted: h.nodes_completed || 0,
          nodesFailed: h.nodes_failed || 0,
        }));
        store.setExecutionHistory(records);
      }
      addMessage({
        role: 'system',
        content: `✅ ${payload.message}`,
        timestamp: new Date().toISOString(),
        messageType: 'text',
      });
    }, 'hook_workflow_loaded');

    // 工作流已保存
    const unsubWorkflowSaved = wsService.on(WSMessageType.WORKFLOW_SAVED, (msg) => {
      const payload = msg.payload as { id: string; workflow_id: string; name: string; message: string };
      const store = useAppStore.getState();
      store.setCurrentWorkflowMeta({
        id: payload.id,
        workflowId: payload.workflow_id,
        name: payload.name,
        description: '',
      });
      store.setShowSaveWorkflowDialog(false);
      addMessage({
        role: 'system',
        content: `✅ ${payload.message}`,
        timestamp: new Date().toISOString(),
        messageType: 'text',
      });
    }, 'hook_workflow_saved');

    // 工作流已删除
    const unsubWorkflowDeleted = wsService.on(WSMessageType.WORKFLOW_DELETED, (msg) => {
      const payload = msg.payload as { workflow_id: string; message: string };
      // 刷新工作流列表
      wsService.send(WSMessageType.LIST_WORKFLOWS, {});
      addMessage({
        role: 'system',
        content: `🗑️ ${payload.message}`,
        timestamp: new Date().toISOString(),
        messageType: 'text',
      });
    }, 'hook_workflow_deleted');

    // === Agent 管理响应 ===

    // Agent 列表
    const unsubAgentsList = wsService.on(WSMessageType.AGENTS_LIST, (msg) => {
      const payload = msg.payload as { agents: Array<Record<string, unknown>>; total: number };
      const store = useAppStore.getState();
      store.setAgentLibraryLoading(false);
      store.setAgentLibrary(payload.agents.map(a => ({
        id: a.id as string,
        agentId: a.agent_id as string,
        name: a.name as string,
        description: a.description as string || '',
        version: a.version as string || '1.0.0',
        status: a.status as string || 'draft',
        domainType: a.domain_type as string || 'general',
        executionType: a.execution_type as string || 'executor',
        modelName: a.model_name as string || '',
        tags: a.tags as string[] || [],
        isTemplate: a.is_template as boolean || false,
        createdAt: a.created_at as string || '',
        updatedAt: a.updated_at as string || '',
      })));
    }, 'hook_agents_list');

    // Agent 模板列表
    const unsubAgentTemplates = wsService.on(WSMessageType.AGENT_TEMPLATES, (msg) => {
      const payload = msg.payload as { templates: Array<Record<string, unknown>>; total: number };
      const store = useAppStore.getState();
      store.setAgentTemplates(payload.templates.map(t => ({
        id: t.id as string,
        agentId: t.agent_id as string,
        name: t.name as string,
        description: t.description as string || '',
        version: t.version as string || '1.0.0',
        status: 'active',
        domainType: t.domain_type as string || 'general',
        executionType: t.execution_type as string || 'executor',
        modelName: t.model_name as string || '',
        tags: t.tags as string[] || [],
        isTemplate: true,
        createdAt: '',
        updatedAt: '',
      })));
    }, 'hook_agent_templates');

    // Agent 已复用
    const unsubAgentReused = wsService.on(WSMessageType.AGENT_REUSED, (msg) => {
      const payload = msg.payload as { agent_id: string; name: string; message: string };
      addMessage({
        role: 'system',
        content: `✅ ${payload.message}`,
        timestamp: new Date().toISOString(),
        messageType: 'text',
      });
    }, 'hook_agent_reused');

    // 清理
    return () => {
      unsubConnected();
      unsubChat();
      unsubSyncBatch();
      unsubWorkflow();
      unsubHighlight();
      unsubSuggestions();
      unsubExecution();
      unsubProgress();
      unsubError();
      unsubCheckpoint();
      unsubGenerationProgress();
      unsubAgentUpdated();
      unsubExecutionHistory();
      unsubExecutionDetail();
      unsubPong();
      unsubWorkflowsList();
      unsubWorkflowLoaded();
      unsubWorkflowSaved();
      unsubWorkflowDeleted();
      unsubAgentsList();
      unsubAgentTemplates();
      unsubAgentReused();
    };
  }, [addMessage, updateOrAddProgressMessage, setWorkflowState, setHighlightedNodes, setSuggestedActions, setExecutionProgress, updateNodeState, setIsLoading, setCheckpoints, setGenerationProgress, updateAgentInWorkflow, setMode, clearRealtimeNodeOutputs, prependMessagesBatch, addMessagesBatch, setHasMoreHistory, setIsLoadingHistory]);

  // 加载更多历史消息
  const loadMoreHistory = useCallback(() => {
    const { messages, hasMoreHistory, isLoadingHistory } = useAppStore.getState();

    // 如果没有更多历史或正在加载，跳过
    if (!hasMoreHistory || isLoadingHistory) {
      return;
    }

    const currentCount = messages.length;
    console.log(`请求更多历史消息: 当前=${currentCount}条`);

    setIsLoadingHistory(true);
    wsService.send(WSMessageType.SYNC_MESSAGES, {
      limit: 50,
      offset: currentCount,  // 从当前已有消息数量开始往前加载
    });
  }, [setIsLoadingHistory]);

  return {
    isConnected,
    isReconnecting,
    reconnectAttempt,
    connect,
    disconnect,
    sendMessage,
    sendAction,
    smartSave,
    loadMoreHistory,
  };
}

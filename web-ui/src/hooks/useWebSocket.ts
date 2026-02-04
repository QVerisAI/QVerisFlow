import { useEffect, useCallback, useState, useRef } from 'react';
import { wsService } from '../services/websocket';
import { useAppStore } from '../stores/appStore';
import { WSMessageType, type Message, type WorkflowState, type GenerationProgressEvent, type ExecutionRecord } from '../types';

export function useWebSocket() {
  const [isConnected, setIsConnected] = useState(false);
  const currentExecutionRef = useRef<ExecutionRecord | null>(null);
  const {
    addMessage,
    updateOrAddProgressMessage,
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
  } = useAppStore();

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

      // 获取当前前端消息数量
      const currentMessages = useAppStore.getState().messages;
      const clientMessageCount = currentMessages.length;
      const serverHistoryCount = payload.history_count || 0;

      // 如果服务端有更多消息，请求增量同步（无论是否重连）
      if (serverHistoryCount > clientMessageCount) {
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

      // 如果是进度消息，使用更新逻辑（同一个 agent 只保留一条卡片）
      if (payload.data?.type === 'agent_generation_progress') {
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
        data?: Record<string, unknown>
      };

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

      // 执行开始：创建新的执行记录
      if (event.event_type === 'execution_started' || event.event_type === 'workflow_started') {
        const totalNodes = (event.data?.total_nodes as number) || event.total_nodes || 0;
        const newRecord: ExecutionRecord = {
          executionId: event.workflow_id || `exec_${Date.now()}`,
          workflowId: event.workflow_id || '',
          status: 'running',
          startedAt: new Date().toISOString(),
          nodesTotal: totalNodes,
          nodesCompleted: 0,
          nodesFailed: 0,
        };
        currentExecutionRef.current = newRecord;
        addExecutionRecord(newRecord);
      }

      // 执行完成：更新执行记录
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

          updateExecutionRecord(executionId, {
            status: isSuccess ? 'success' : 'failed',
            completedAt: new Date().toISOString(),
            totalDurationMs: event.total_duration_ms || (event.data?.total_duration_ms as number),
            nodesCompleted: event.nodes_completed || (event.data?.nodes_completed as number) || 0,
            nodesFailed: event.nodes_failed || (event.data?.nodes_failed as number) || 0,
          });
        }
        currentExecutionRef.current = null;
      }

      // 执行失败：更新执行记录
      if (event.event_type === 'execution_failed' || event.event_type === 'workflow_failed') {
        const executionId = currentExecutionRef.current?.executionId || event.workflow_id;
        if (executionId) {
          updateExecutionRecord(executionId, {
            status: 'failed',
            completedAt: new Date().toISOString(),
          });
        }
        currentExecutionRef.current = null;
      }

      // === 处理节点级别的执行事件 ===

      // 更新节点状态
      if (frontendNodeId) {
        let status = 'pending';
        if (event.event_type === 'node_started') status = 'running';
        else if (event.event_type === 'node_completed') status = 'completed';
        else if (event.event_type === 'node_failed') status = 'failed';
        else if (event.event_type === 'node_skipped') status = 'skipped';

        updateNodeState(frontendNodeId, {
          status,
          duration: (event.data?.duration_ms as number) || (event.duration_ms as number) || undefined,
        });

        // 更新当前执行节点和进度
        if (event.event_type === 'node_started') {
          setExecutionProgress({
            nodesCompleted: (event.data?.nodes_completed as number) || event.nodes_completed || 0,
            totalNodes: (event.data?.total_nodes as number) || event.total_nodes || 0,
            currentNode: frontendNodeId,
          });
        }

        // 节点完成时更新当前执行记录的进度
        if (event.event_type === 'node_completed' && currentExecutionRef.current) {
          const completed = (event.data?.nodes_completed as number) || event.nodes_completed ||
            (currentExecutionRef.current.nodesCompleted + 1);
          updateExecutionRecord(currentExecutionRef.current.executionId, {
            nodesCompleted: completed,
          });
        }

        // 节点失败时更新失败计数
        if (event.event_type === 'node_failed' && currentExecutionRef.current) {
          updateExecutionRecord(currentExecutionRef.current.executionId, {
            nodesFailed: currentExecutionRef.current.nodesFailed + 1,
          });
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

        // 同步更新执行记录
        if (currentExecutionRef.current) {
          updateExecutionRecord(currentExecutionRef.current.executionId, {
            nodesCompleted: completed,
          });
        }
      }

      // 添加执行消息（过滤重复的 - 后端已通过 on_message 发送了格式化消息）
      // 这里只处理节点级别的事件作为备份
      if (['node_started', 'node_completed', 'node_failed', 'tool_call'].includes(event.event_type)) {
        let content = '';
        switch (event.event_type) {
          case 'node_started':
            content = `📊 [${event.node_name || event.node_id}] 开始执行...`;
            break;
          case 'node_completed':
            content = `✅ [${event.node_name || event.node_id}] 完成! (${((event.data?.duration_ms as number || event.duration_ms || 0) / 1000).toFixed(1)}s)`;
            break;
          case 'node_failed':
            content = `❌ [${event.node_name || event.node_id}] 失败: ${event.data?.error || event.error}`;
            break;
          case 'tool_call':
            content = `   → 调用工具: ${event.data?.tool_id}`;
            break;
        }

        if (content) {
          addMessage({
            role: 'system',
            content,
            timestamp: msg.timestamp,
            messageType: 'execution_event',
            data: event.data,
          });
        }
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

    // 执行详情响应
    const unsubExecutionDetail = wsService.on(WSMessageType.EXECUTION_DETAIL, (msg) => {
      const payload = msg.payload as { executionId: string; detail: ExecutionRecord };
      useAppStore.getState().setCurrentExecutionDetail(payload.detail || null);
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
  }, [addMessage, updateOrAddProgressMessage, setWorkflowState, setHighlightedNodes, setSuggestedActions, setExecutionProgress, updateNodeState, setIsLoading, setCheckpoints, setGenerationProgress, updateAgentInWorkflow]);

  return {
    isConnected,
    connect,
    disconnect,
    sendMessage,
    sendAction,
  };
}

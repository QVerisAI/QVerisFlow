import { create } from 'zustand';
import type {
  Message,
  WorkflowState,
  CheckpointInfo,
  AgentDefinition,
  ExecutionRecord,
  WorkflowSummary,
  AgentLibraryItem,
  RealtimeNodeOutput,
} from '../types';
import type { AuthUser } from '../services/auth';

interface GenerationProgress {
  current: number;
  total: number;
  agentName: string;
  displayName: string;
  status: 'generating' | 'completed' | 'failed';
  message: string;
}

interface AppState {
  // 认证
  isAuthenticated: boolean;
  currentUser: AuthUser | null;
  setAuth: (user: AuthUser) => void;
  clearAuth: () => void;

  // 会话
  sessionId: string | null;
  setSessionId: (id: string) => void;

  // 模式
  mode: 'idle' | 'building' | 'executing' | 'completed';
  setMode: (mode: 'idle' | 'building' | 'executing' | 'completed') => void;

  // 对话消息
  messages: Message[];
  addMessage: (message: Message) => void;
  updateOrAddProgressMessage: (agentName: string, message: Message) => void;
  updateMessageById: (messageId: string, updates: Partial<Message>) => void;
  clearMessages: () => void;
  resetConversation: () => void;  // 重置整个对话状态到初始空白状态
  removeMessagesByDataType: (dataType: string) => void;
  // 批量消息操作（用于渐进式加载）
  prependMessagesBatch: (messages: Message[]) => void;  // 头部插入（加载更早的消息）
  addMessagesBatch: (messages: Message[]) => void;      // 尾部追加（初始加载）
  hasMoreHistory: boolean;
  setHasMoreHistory: (has: boolean) => void;
  isLoadingHistory: boolean;
  setIsLoadingHistory: (loading: boolean) => void;

  // 工作流状态
  workflowState: WorkflowState | null;
  setWorkflowState: (state: WorkflowState) => void;

  // 高亮节点
  highlightedNodes: string[];
  setHighlightedNodes: (nodes: string[]) => void;

  // 节点执行状态
  nodeStates: Record<string, { status: string; duration?: number }>;
  updateNodeState: (nodeId: string, state: { status: string; duration?: number }) => void;

  // 实时节点输出（用于执行过程中查看节点详情）
  realtimeNodeOutputs: Record<string, RealtimeNodeOutput>;
  updateRealtimeNodeOutput: (nodeId: string, output: Partial<RealtimeNodeOutput>) => void;
  clearRealtimeNodeOutputs: () => void;

  // 工作流节点ID映射：workflowNodeId -> frontendNodeId
  workflowNodeIdMap: Record<string, string>;
  setWorkflowNodeIdMap: (map: Record<string, string>) => void;

  // 检查点
  checkpoints: CheckpointInfo[];
  setCheckpoints: (checkpoints: CheckpointInfo[]) => void;

  // 建议操作
  suggestedActions: string[];
  setSuggestedActions: (actions: string[]) => void;

  // 执行进度
  executionProgress: {
    nodesCompleted: number;
    totalNodes: number;
    currentNode: string | null;
    status?: 'running' | 'paused';
  };
  setExecutionProgress: (progress: { nodesCompleted: number; totalNodes: number; currentNode: string | null; status?: 'running' | 'paused' }) => void;

  // 加载状态
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;

  // === 智能体生成相关 ===

  // 智能体生成进度
  generationProgress: GenerationProgress | null;
  setGenerationProgress: (progress: GenerationProgress | null) => void;

  // 选中的智能体（用于详情面板）
  selectedAgent: AgentDefinition | null;
  selectedNodeId: string | null;
  setSelectedAgent: (agent: AgentDefinition | null, nodeId?: string | null) => void;

  // 智能体编辑模式
  isEditingAgent: boolean;
  setIsEditingAgent: (editing: boolean) => void;

  // 更新智能体定义
  updateAgentInWorkflow: (agentName: string, updates: Partial<AgentDefinition>) => void;

  // === 执行历史 ===
  executionHistory: ExecutionRecord[];
  selectedExecutionId: string | null;  // null = 当前构建模式
  currentExecutionDetail: ExecutionRecord | null;  // 当前查看的执行详情
  executionDetailLoading: boolean;  // 执行详情加载中
  setExecutionHistory: (history: ExecutionRecord[]) => void;
  selectExecution: (executionId: string | null) => void;
  addExecutionRecord: (record: ExecutionRecord) => void;
  updateExecutionRecord: (executionId: string, updates: Partial<ExecutionRecord>) => void;
  setCurrentExecutionDetail: (detail: ExecutionRecord | null) => void;
  setExecutionDetailLoading: (loading: boolean) => void;
  // 待选中的执行ID（用于"查看详情"功能：先加载工作流，加载完成后自动选中该执行）
  pendingExecutionId: string | null;
  setPendingExecutionId: (executionId: string | null) => void;

  // === 工作流库 ===
  workflowList: WorkflowSummary[];
  workflowListLoading: boolean;
  currentWorkflowMeta: {
    id: string;
    workflowId: string;
    name: string;
    description: string;
  } | null;
  setWorkflowList: (workflows: WorkflowSummary[]) => void;
  setWorkflowListLoading: (loading: boolean) => void;
  setCurrentWorkflowMeta: (meta: { id: string; workflowId: string; name: string; description: string } | null) => void;

  // === 智能体库 ===
  agentLibrary: AgentLibraryItem[];
  agentTemplates: AgentLibraryItem[];
  agentLibraryLoading: boolean;
  setAgentLibrary: (agents: AgentLibraryItem[]) => void;
  setAgentTemplates: (templates: AgentLibraryItem[]) => void;
  setAgentLibraryLoading: (loading: boolean) => void;

  // === UI 面板状态 ===
  showWorkflowListPanel: boolean;
  showAgentLibraryPanel: boolean;
  showSaveWorkflowDialog: boolean;
  setShowWorkflowListPanel: (show: boolean) => void;
  setShowAgentLibraryPanel: (show: boolean) => void;
  setShowSaveWorkflowDialog: (show: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // 认证
  isAuthenticated: false,
  currentUser: null,
  setAuth: (user) => set({ isAuthenticated: true, currentUser: user }),
  clearAuth: () => set({ isAuthenticated: false, currentUser: null, sessionId: null }),

  // 会话
  sessionId: null,
  setSessionId: (id) => set({ sessionId: id }),

  // 模式
  mode: 'idle',
  setMode: (mode) => set({ mode }),

  // 对话消息
  messages: [],
  addMessage: (message) => set((state) => {
    // 检查是否重复消息（相同角色、内容且时间差在 2 秒内）
    const lastMessages = state.messages.slice(-5);
    const isDuplicate = lastMessages.some(m =>
      m.role === message.role &&
      m.content === message.content &&
      Math.abs(new Date(m.timestamp).getTime() - new Date(message.timestamp).getTime()) < 2000
    );

    if (isDuplicate) {
      console.log('Skipping duplicate message:', message.content.substring(0, 50));
      return state;
    }

    // 确保消息有唯一 ID
    const messageWithId = {
      ...message,
      id: message.id || `msg_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`,
    };

    return { messages: [...state.messages, messageWithId] };
  }),

  // 更新或添加进度消息（同一个 agent 只保留一条，状态更新时原地修改）
  updateOrAddProgressMessage: (agentName, message) => set((state) => {
    // 查找同一个 agent 的现有进度消息
    const existingIndex = state.messages.findIndex(m => {
      const mData = m.data as { type?: string; agent_name?: string } | undefined;
      return mData?.type === 'agent_generation_progress' && mData?.agent_name === agentName;
    });

    if (existingIndex !== -1) {
      // 更新现有消息，保持原有 ID
      const updatedMessages = [...state.messages];
      updatedMessages[existingIndex] = {
        ...message,
        id: updatedMessages[existingIndex].id,  // 保持原有 ID，避免 React 重新创建组件
        timestamp: message.timestamp,
      };
      return { messages: updatedMessages };
    }

    // 没有找到，添加新消息（带新 ID）
    const messageWithId = {
      ...message,
      id: message.id || `progress_${agentName}_${Date.now()}`,
    };
    return { messages: [...state.messages, messageWithId] };
  }),

  // 根据 ID 更新消息
  updateMessageById: (messageId, updates) => set((state) => {
    const messageIndex = state.messages.findIndex(m => m.id === messageId);
    if (messageIndex === -1) {
      return state;
    }

    const updatedMessages = [...state.messages];
    updatedMessages[messageIndex] = {
      ...updatedMessages[messageIndex],
      ...updates,
    };
    return { messages: updatedMessages };
  }),

  clearMessages: () => set({ messages: [], hasMoreHistory: false }),

  // 重置整个对话状态到初始空白状态（包含工作流状态、节点状态等）
  resetConversation: () => set({
    messages: [],
    hasMoreHistory: false,
    workflowState: null,
    mode: 'idle',
    highlightedNodes: [],
    nodeStates: {},
    realtimeNodeOutputs: {},
    workflowNodeIdMap: {},
    checkpoints: [],
    suggestedActions: [],
    executionProgress: { nodesCompleted: 0, totalNodes: 0, currentNode: null },
    generationProgress: null,
    selectedAgent: null,
    selectedNodeId: null,
    isEditingAgent: false,
    currentWorkflowMeta: null,
    isLoading: false,
  }),

  // 按 data.type 清理消息（用于加载新工作流时清理旧的工作流卡片消息）
  removeMessagesByDataType: (dataType) => set((state) => ({
    messages: state.messages.filter(m => m.data?.type !== dataType)
  })),

  // 批量消息操作（用于渐进式加载）
  prependMessagesBatch: (messages) => set((state) => {
    // 头部插入（加载更早的消息）
    const messagesWithIds = messages.map(msg => ({
      ...msg,
      id: msg.id || `msg_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`,
    }));
    return { messages: [...messagesWithIds, ...state.messages] };
  }),

  addMessagesBatch: (messages) => set((state) => {
    // 尾部追加（初始加载最新消息）
    const messagesWithIds = messages.map(msg => ({
      ...msg,
      id: msg.id || `msg_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`,
    }));
    return { messages: [...state.messages, ...messagesWithIds] };
  }),

  hasMoreHistory: false,
  setHasMoreHistory: (has) => set({ hasMoreHistory: has }),

  isLoadingHistory: false,
  setIsLoadingHistory: (loading) => set({ isLoadingHistory: loading }),

  // 工作流状态
  workflowState: null,
  setWorkflowState: (workflowState) => set({
    workflowState,
    mode: workflowState.mode as 'idle' | 'building' | 'executing' | 'completed',
  }),

  // 高亮节点
  highlightedNodes: [],
  setHighlightedNodes: (nodes) => set({ highlightedNodes: nodes }),

  // 节点执行状态
  nodeStates: {},
  updateNodeState: (nodeId, state) => set((prev) => ({
    nodeStates: { ...prev.nodeStates, [nodeId]: state }
  })),

  // 实时节点输出
  realtimeNodeOutputs: {},
  updateRealtimeNodeOutput: (nodeId, output) => set((state) => ({
    realtimeNodeOutputs: {
      ...state.realtimeNodeOutputs,
      [nodeId]: {
        ...state.realtimeNodeOutputs[nodeId],
        ...output,
      },
    },
  })),
  clearRealtimeNodeOutputs: () => set({ realtimeNodeOutputs: {} }),

  // 工作流节点ID映射
  workflowNodeIdMap: {},
  setWorkflowNodeIdMap: (map) => set({ workflowNodeIdMap: map }),

  // 检查点
  checkpoints: [],
  setCheckpoints: (checkpoints) => set({ checkpoints }),

  // 建议操作
  suggestedActions: [],
  setSuggestedActions: (actions) => set({ suggestedActions: actions }),

  // 执行进度
  executionProgress: {
    nodesCompleted: 0,
    totalNodes: 0,
    currentNode: null,
  },
  setExecutionProgress: (progress) => set({ executionProgress: progress }),

  // 加载状态
  isLoading: false,
  setIsLoading: (loading) => set({ isLoading: loading }),

  // === 智能体生成相关 ===

  // 智能体生成进度
  generationProgress: null,
  setGenerationProgress: (progress) => set({ generationProgress: progress }),

  // 选中的智能体
  selectedAgent: null,
  selectedNodeId: null,
  setSelectedAgent: (agent, nodeId = null) => set({
    selectedAgent: agent,
    selectedNodeId: nodeId,
  }),

  // 智能体编辑模式
  isEditingAgent: false,
  setIsEditingAgent: (editing) => set({ isEditingAgent: editing }),

  // 更新智能体定义
  updateAgentInWorkflow: (agentName, updates) => set((state) => {
    const result: Partial<AppState> = {};

    // 更新 workflowState.agents 列表中对应的智能体
    if (state.workflowState?.agents) {
      const updatedAgents = state.workflowState.agents.map((agent) => {
        if (agent.name === agentName) {
          return { ...agent, ...updates };
        }
        return agent;
      });
      result.workflowState = {
        ...state.workflowState,
        agents: updatedAgents,
      };
    }

    // 如果当前选中的智能体是要更新的，也更新 selectedAgent
    if (state.selectedAgent?.name === agentName) {
      result.selectedAgent = { ...state.selectedAgent, ...updates } as AgentDefinition;
    }

    return result;
  }),

  // === 执行历史 ===
  executionHistory: [],
  selectedExecutionId: null,
  currentExecutionDetail: null,
  executionDetailLoading: false,
  setExecutionHistory: (history) => set({ executionHistory: history }),
  selectExecution: (executionId) => set({
    selectedExecutionId: executionId,
    // 切换时清空旧的详情，等待新的详情加载
    currentExecutionDetail: executionId === null ? null : undefined,
    // 如果选择了执行记录，设置为加载中状态
    executionDetailLoading: executionId !== null,
  }),
  addExecutionRecord: (record) => set((state) => ({
    executionHistory: [record, ...state.executionHistory].slice(0, 20),  // 保留最近 20 条
  })),
  updateExecutionRecord: (executionId, updates) => set((state) => ({
    executionHistory: state.executionHistory.map((record) =>
      record.executionId === executionId ? { ...record, ...updates } : record
    ),
  })),
  setCurrentExecutionDetail: (detail) => set({
    currentExecutionDetail: detail,
    // 详情加载完成，关闭加载状态
    executionDetailLoading: false,
  }),
  setExecutionDetailLoading: (loading) => set({ executionDetailLoading: loading }),
  pendingExecutionId: null,
  setPendingExecutionId: (executionId) => set({ pendingExecutionId: executionId }),

  // === 工作流库 ===
  workflowList: [],
  workflowListLoading: false,
  currentWorkflowMeta: null,
  setWorkflowList: (workflows) => set({ workflowList: workflows }),
  setWorkflowListLoading: (loading) => set({ workflowListLoading: loading }),
  setCurrentWorkflowMeta: (meta) => set({ currentWorkflowMeta: meta }),

  // === 智能体库 ===
  agentLibrary: [],
  agentTemplates: [],
  agentLibraryLoading: false,
  setAgentLibrary: (agents) => set({ agentLibrary: agents }),
  setAgentTemplates: (templates) => set({ agentTemplates: templates }),
  setAgentLibraryLoading: (loading) => set({ agentLibraryLoading: loading }),

  // === UI 面板状态 ===
  showWorkflowListPanel: false,
  showAgentLibraryPanel: false,
  showSaveWorkflowDialog: false,
  setShowWorkflowListPanel: (show) => set({ showWorkflowListPanel: show }),
  setShowAgentLibraryPanel: (show) => set({ showAgentLibraryPanel: show }),
  setShowSaveWorkflowDialog: (show) => set({ showSaveWorkflowDialog: show }),
}));

import { create } from 'zustand';
import type { 
  Message, 
  WorkflowState, 
  CheckpointInfo, 
  AgentDefinition,
  ExecutionRecord 
} from '../types';

interface GenerationProgress {
  current: number;
  total: number;
  agentName: string;
  displayName: string;
  status: 'generating' | 'completed' | 'failed';
  message: string;
}

interface AppState {
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
  clearMessages: () => void;

  // 工作流状态
  workflowState: WorkflowState | null;
  setWorkflowState: (state: WorkflowState) => void;
  
  // 高亮节点
  highlightedNodes: string[];
  setHighlightedNodes: (nodes: string[]) => void;

  // 节点执行状态
  nodeStates: Record<string, { status: string; duration?: number }>;
  updateNodeState: (nodeId: string, state: { status: string; duration?: number }) => void;
  
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
  };
  setExecutionProgress: (progress: { nodesCompleted: number; totalNodes: number; currentNode: string | null }) => void;

  // 加载状态
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;

  // === Agent 生成相关 ===
  
  // Agent 生成进度
  generationProgress: GenerationProgress | null;
  setGenerationProgress: (progress: GenerationProgress | null) => void;
  
  // 选中的 Agent（用于详情面板）
  selectedAgent: AgentDefinition | null;
  selectedNodeId: string | null;
  setSelectedAgent: (agent: AgentDefinition | null, nodeId?: string | null) => void;
  
  // Agent 编辑模式
  isEditingAgent: boolean;
  setIsEditingAgent: (editing: boolean) => void;
  
  // 更新 Agent 定义
  updateAgentInWorkflow: (agentName: string, updates: Partial<AgentDefinition>) => void;
  
  // === 执行历史 ===
  executionHistory: ExecutionRecord[];
  selectedExecutionId: string | null;  // null = 当前构建模式
  currentExecutionDetail: ExecutionRecord | null;  // 当前查看的执行详情
  setExecutionHistory: (history: ExecutionRecord[]) => void;
  selectExecution: (executionId: string | null) => void;
  addExecutionRecord: (record: ExecutionRecord) => void;
  updateExecutionRecord: (executionId: string, updates: Partial<ExecutionRecord>) => void;
  setCurrentExecutionDetail: (detail: ExecutionRecord | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
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
  
  clearMessages: () => set({ messages: [] }),

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

  // === Agent 生成相关 ===
  
  // Agent 生成进度
  generationProgress: null,
  setGenerationProgress: (progress) => set({ generationProgress: progress }),
  
  // 选中的 Agent
  selectedAgent: null,
  selectedNodeId: null,
  setSelectedAgent: (agent, nodeId = null) => set({ 
    selectedAgent: agent,
    selectedNodeId: nodeId,
  }),
  
  // Agent 编辑模式
  isEditingAgent: false,
  setIsEditingAgent: (editing) => set({ isEditingAgent: editing }),
  
  // 更新 Agent 定义
  updateAgentInWorkflow: (agentName, updates) => set((state) => {
    // 如果当前选中的 agent 是要更新的，也更新 selectedAgent
    if (state.selectedAgent?.name === agentName) {
      return {
        selectedAgent: { ...state.selectedAgent, ...updates } as AgentDefinition,
      };
    }
    return state;
  }),
  
  // === 执行历史 ===
  executionHistory: [],
  selectedExecutionId: null,
  currentExecutionDetail: null,
  setExecutionHistory: (history) => set({ executionHistory: history }),
  selectExecution: (executionId) => set({ 
    selectedExecutionId: executionId,
    // 切换时清空旧的详情，等待新的详情加载
    currentExecutionDetail: executionId === null ? null : undefined,
  }),
  addExecutionRecord: (record) => set((state) => ({
    executionHistory: [record, ...state.executionHistory].slice(0, 20),  // 保留最近 20 条
  })),
  updateExecutionRecord: (executionId, updates) => set((state) => ({
    executionHistory: state.executionHistory.map((record) =>
      record.executionId === executionId ? { ...record, ...updates } : record
    ),
  })),
  setCurrentExecutionDetail: (detail) => set({ currentExecutionDetail: detail }),
}));

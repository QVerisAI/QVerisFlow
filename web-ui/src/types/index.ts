// WebSocket 消息类型
export enum WSMessageType {
  CHAT_MESSAGE = 'chat_message',
  USER_ACTION = 'user_action',
  SUBSCRIBE = 'subscribe',
  UNSUBSCRIBE = 'unsubscribe',
  UPDATE_AGENT = 'update_agent',  // 更新 Agent 配置
  OPTIMIZE_PROMPT = 'optimize_prompt',  // 优化 Prompt
  GET_EXECUTION_HISTORY = 'get_execution_history',  // 获取执行历史
  GET_EXECUTION_DETAIL = 'get_execution_detail',  // 获取执行详情
  SYNC_MESSAGES = 'sync_messages',  // 同步缺失的消息（增量同步）
  WORKFLOW_UPDATE = 'workflow_update',
  NODE_HIGHLIGHT = 'node_highlight',
  PROGRESS_UPDATE = 'progress_update',
  EXECUTION_EVENT = 'execution_event',
  CHECKPOINT_CREATED = 'checkpoint',
  SUGGESTED_ACTIONS = 'suggestions',
  ERROR = 'error',
  CONNECTED = 'connected',
  EXECUTION_HISTORY = 'execution_history',  // 执行历史响应
  EXECUTION_DETAIL = 'execution_detail',  // 执行详情响应
  // Agent 生成相关
  AGENT_GENERATION_PROGRESS = 'agent_generation_progress',
  AGENT_UPDATED = 'agent_updated',
  // 心跳
  PING = 'ping',
  PONG = 'pong',

  // 工作流管理 (Client -> Server)
  LOAD_WORKFLOW = 'load_workflow',
  SAVE_WORKFLOW = 'save_workflow',
  LIST_WORKFLOWS = 'list_workflows',
  DELETE_WORKFLOW = 'delete_workflow',

  // Agent 管理 (Client -> Server)
  LIST_AGENTS = 'list_agents',
  REUSE_AGENT = 'reuse_agent',
  GET_AGENT_TEMPLATES = 'get_agent_templates',

  // 工作流管理响应 (Server -> Client)
  WORKFLOW_LOADED = 'workflow_loaded',
  WORKFLOW_SAVED = 'workflow_saved',
  WORKFLOWS_LIST = 'workflows_list',
  WORKFLOW_DELETED = 'workflow_deleted',

  // Agent 管理响应 (Server -> Client)
  AGENTS_LIST = 'agents_list',
  AGENT_REUSED = 'agent_reused',
  AGENT_TEMPLATES = 'agent_templates',
}

// 消息
export interface Message {
  id?: string;  // 唯一标识符，用于 React key（由 store 自动生成）
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  messageType: 'text' | 'execution_event' | 'workflow_update' | 'error' | 'progress';
  data?: Record<string, unknown>;
}

// Agent 信息
export interface AgentInfo {
  agentId: string;
  name: string;
  displayName?: string;  // 用户友好的显示名称
  description?: string;
  domainType: string;
  executionType?: string;
  version?: string;
  tools?: string[];
  // 完整配置字段（用于详情面板）
  llmConfig?: ModelConfig;
  backgroundInstruction?: BackgroundInstruction;
  outputInstruction?: OutputInstruction;
  userInstruction?: UserInstruction;
  toolReferences?: ToolReference[];
}

// 节点信息
export interface NodeInfo {
  nodeId: string;
  workflowNodeId?: string;  // WorkflowDefinition 中的 node_id，用于匹配执行事件
  name: string;
  displayName?: string;  // 用户友好的显示名称
  nodeType: string;
  agentId?: string;
  status?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'preview';
  // 预览节点额外字段
  description?: string;
  tools?: string[];
  dependencies?: string[];
  context_refs?: string[];
}

// 边信息
export interface EdgeInfo {
  source: string;
  target: string;
  edgeType?: string;
}

// 检查点
export interface CheckpointInfo {
  checkpointId: string;
  label: string;
  stage: string;
  timestamp: string;
}

// 可用工具信息
export interface ToolInfo {
  tool_id: string;
  name: string;
  description: string;
  tool_type: string;
  alias?: string;
}

// 可用模型信息
export interface ModelInfo {
  value: string;       // 模型标识符（用于 API 调用）
  label: string;       // 显示名称
  type?: string;       // 模型类型：language, multimodal, embedding
  capabilities?: string[];  // 能力列表：reasoning, coding, vision 等
  costTier?: string;   // 成本级别：low, medium, high
  maxTokens?: number;  // 最大 tokens
}

// 工作流状态
export interface WorkflowState {
  mode: 'idle' | 'building' | 'executing' | 'completed';
  stage: string;
  agents: AgentInfo[];
  nodes: NodeInfo[];
  edges: EdgeInfo[];
  checkpoints: CheckpointInfo[];
  highlightedNodes?: string[];
  agentDefinitions?: Record<string, AgentDefinition>;  // 完整的 AgentDefinition 映射
  availableTools?: ToolInfo[];  // 可用工具列表
  availableModels?: ModelInfo[];  // 可用模型列表
}

// 执行事件
export interface ExecutionEvent {
  eventType: string;
  workflowId: string;
  nodeId?: string;
  nodeName?: string;
  timestamp: string;
  data: Record<string, unknown>;
}

// 节点执行状态
export interface NodeExecutionState {
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  startTime?: number;
  duration?: number;
  progress?: number;
  currentStep?: string;
  outputPreview?: unknown;
}

// WebSocket 消息
export interface WSMessage {
  type: WSMessageType;
  payload: Record<string, unknown>;
  timestamp: string;
}

// 会话信息
export interface SessionInfo {
  sessionId: string;
  mode: string;
  stage?: string;
  createdAt: string;
  agentsCount: number;
  hasWorkflow: boolean;
  messageCount: number;
}

// Agent 规格（规划阶段）
export interface AgentSpec {
  name: string;
  display_name?: string;  // 用户友好的显示名称
  task: string;
  suggested_tools: string[];
  dependencies: string[];
  context_refs: string[];
  constraints?: Record<string, unknown>;
}

// 工作流规划
export interface WorkflowPlan {
  task_description: string;
  agent_specs: AgentSpec[];
  workflow_structure: string;
  estimated_steps: number;
  notes?: string;
}

// Agent 生成摘要（单个 Agent）
export interface GeneratedAgentInfo {
  name: string;
  display_name: string;
  description: string;
  domain_type: string;
  tools_count: number;
  tools: string[];
  status: 'success' | 'failed';
}

// 生成失败的 Agent
export interface FailedAgentInfo {
  name: string;
  display_name: string;
  reason: string;
}

// Agent 生成摘要
export interface GenerationSummary {
  total_agents: number;
  failed_count: number;
  agents: GeneratedAgentInfo[];
  failed_agents?: FailedAgentInfo[];
  next_step: string;
}

// 生成进度事件
export interface GenerationProgressEvent {
  type: 'agent_generation_progress';
  current: number;
  total: number;
  agent_name: string;
  display_name: string;
  status: 'generating' | 'completed' | 'failed';
  message: string;
  progress?: number;
}

// 背景指令
export interface BackgroundInstruction {
  role_description: string;
  core_capability: string;
  task_context: string;
}

// 输出指令
export interface OutputInstruction {
  format_type: string;
  format_requirements: string[];
  quality_standards?: string[];
  example_output?: string;
}

// 用户指令
export interface UserInstruction {
  task_description: string;
  tool_references?: string[];
  context_references?: string[];
}

// 模型配置
export interface ModelConfig {
  model_name: string;
  temperature: number;
  max_tokens: number;
  max_iterations?: number;
  enable_online?: boolean;
}

// 工具引用
export interface ToolReference {
  tool_id: string;
  alias?: string;
  tool_type: string;
  enabled: boolean;
}

// 完整的 Agent 定义
export interface AgentDefinition {
  agent_id: string;
  name: string;
  display_name: string;
  description: string;
  version: string;
  execution_type: string;
  domain_type: string;
  background_instruction: BackgroundInstruction;
  output_instruction: OutputInstruction;
  user_instruction: UserInstruction;
  llm_config: ModelConfig;
  tool_references: ToolReference[];
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  tags?: string[];
  author?: string;
  created_at?: string;
  is_active?: boolean;
}

// 执行记录（用于执行历史）
export interface ExecutionRecord {
  executionId: string;
  workflowId: string;
  status: 'running' | 'success' | 'failed' | 'cancelled';
  startedAt: string;
  completedAt?: string;
  totalDurationMs?: number;
  nodesTotal: number;
  nodesCompleted: number;
  nodesFailed: number;
  nodeResults?: Record<string, NodeExecutionResult>;
}

// 节点执行结果
export interface NodeExecutionResult {
  nodeId: string;
  nodeName: string;
  status: 'success' | 'failed' | 'skipped' | 'pending' | 'running';
  startedAt?: string;
  completedAt?: string;
  durationMs?: number;
  input?: unknown;
  output?: unknown;
  error?: string;
}

// 工作流摘要（用于列表展示）
export interface WorkflowSummary {
  id: string;
  workflowId: string;
  name: string;
  description: string;
  version: string;
  status: string;
  nodeCount: number;
  edgeCount: number;
  isActive: boolean;
  tags: string[];
  author: string;
  createdAt: string;
  updatedAt: string;
}

// Agent 库条目（用于列表展示）
export interface AgentLibraryItem {
  id: string;
  agentId: string;
  name: string;
  description: string;
  version: string;
  status: string;
  domainType: string;
  executionType: string;
  modelName: string;
  tags: string[];
  isTemplate: boolean;
  createdAt: string;
  updatedAt: string;
}

// 保存工作流请求
export interface SaveWorkflowRequest {
  name: string;
  description: string;
  tags?: string[];
}

// 加载工作流请求
export interface LoadWorkflowRequest {
  workflowId: string;
}

// 工作流信息卡片（保存后显示）
export interface WorkflowInfoCard {
  type: 'workflow_info_card';
  id?: string;
  workflow_id?: string;
  name: string;
  description: string;
  version?: string;
  agent_count: number;
  saved_agents_count?: number;
  node_count: number;
  edge_count?: number;
  tags?: string[];
  author?: string;
  created_at?: string;
  saved_to: 'database' | 'local';
  local_path?: string;
}

// 工作流搜索结果
export interface WorkflowSearchResult {
  type: 'workflow_search_result';
  workflows: WorkflowSearchItem[];
  total: number;
}

// 工作流搜索条目
export interface WorkflowSearchItem {
  id: string;
  workflow_id: string;
  name: string;
  description: string;
  version: string;
  node_count: number;
  edge_count: number;
  tags: string[];
  author: string;
  created_at: string;
  updated_at: string;
}

// Agent 搜索结果
export interface AgentSearchResult {
  type: 'agent_search_result';
  agents: AgentSearchItem[];
  total: number;
}

// Agent 搜索条目
export interface AgentSearchItem {
  id: string;
  agent_id: string;
  name: string;
  description: string;
  version: string;
  domain_type: string;
  execution_type: string;
  model_name: string;
  tags: string[];
  is_template: boolean;
  created_at: string;
  updated_at: string;
}

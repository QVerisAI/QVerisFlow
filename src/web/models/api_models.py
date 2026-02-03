"""
API 数据模型

定义 REST API 请求和响应的数据结构。
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


# ============ 通用模型 ============

class BaseResponse(BaseModel):
    """基础响应"""
    success: bool = True
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = False
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


# ============ 会话相关 ============

class SessionCreate(BaseModel):
    """创建会话请求"""
    task_description: Optional[str] = None
    user_id: Optional[str] = None
    workspace_name: Optional[str] = None


class SessionResponse(BaseModel):
    """会话响应"""
    session_id: str
    mode: str  # idle, building, executing, completed
    stage: Optional[str] = None  # plan, agent, workflow
    created_at: datetime
    agents_count: int = 0
    has_workflow: bool = False
    message_count: int = 0


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[SessionResponse]
    total: int


# ============ 消息相关 ============

class MessageRequest(BaseModel):
    """消息请求"""
    content: str
    metadata: Optional[Dict[str, Any]] = None


class ChatMessage(BaseModel):
    """对话消息"""
    role: str  # user, assistant, system
    content: str
    timestamp: datetime
    message_type: str = "text"  # text, execution_event, workflow_update, error
    data: Optional[Dict[str, Any]] = None


class MessageResponse(BaseModel):
    """消息响应"""
    message: ChatMessage
    workflow_changed: bool = False
    suggested_actions: List[str] = Field(default_factory=list)
    highlighted_nodes: List[str] = Field(default_factory=list)
    data: Optional[Dict[str, Any]] = None


# ============ 工作流相关 ============

class NodeInfo(BaseModel):
    """节点信息"""
    node_id: str
    name: str
    node_type: str
    agent_id: Optional[str] = None
    status: str = "pending"  # pending, running, completed, failed, skipped


class EdgeInfo(BaseModel):
    """边信息"""
    source: str
    target: str
    edge_type: str = "dependency"


class AgentInfo(BaseModel):
    """Agent 信息"""
    agent_id: str
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    domain_type: str
    execution_type: str = "executor"
    version: str = "1.0.0"
    tools: List[str] = Field(default_factory=list)
    # 完整配置字段（用于详情面板编辑）
    llm_config: Optional[Dict[str, Any]] = None
    background_instruction: Optional[Dict[str, Any]] = None
    output_instruction: Optional[Dict[str, Any]] = None
    user_instruction: Optional[Dict[str, Any]] = None
    tool_references: Optional[List[Dict[str, Any]]] = None


class WorkflowState(BaseModel):
    """工作流状态"""
    mode: str
    stage: str
    agents: List[AgentInfo] = Field(default_factory=list)
    nodes: List[NodeInfo] = Field(default_factory=list)
    edges: List[EdgeInfo] = Field(default_factory=list)
    checkpoints: List[Dict[str, Any]] = Field(default_factory=list)


class WorkflowResponse(BaseModel):
    """工作流响应"""
    workflow_id: str
    name: str
    description: Optional[str] = None
    version: str = "1.0.0"
    state: WorkflowState
    created_at: datetime
    updated_at: Optional[datetime] = None


class WorkflowSaveRequest(BaseModel):
    """保存工作流请求"""
    name: Optional[str] = None
    description: Optional[str] = None


class WorkflowLoadRequest(BaseModel):
    """加载工作流请求"""
    workflow_path: str


# ============ 执行相关 ============

class ExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionRequest(BaseModel):
    """执行请求"""
    params: Dict[str, Any] = Field(default_factory=dict)
    streaming: bool = True


class ExecutionResponse(BaseModel):
    """执行响应"""
    execution_id: str
    workflow_id: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    current_node: Optional[str] = None
    nodes_completed: int = 0
    total_nodes: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ExecutionEventPayload(BaseModel):
    """执行事件负载"""
    event_type: str
    workflow_id: str
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    timestamp: datetime
    data: Dict[str, Any] = Field(default_factory=dict)


class InterventionRequest(BaseModel):
    """干预请求"""
    action: str  # pause, resume, stop, skip_node, inject_context
    node_id: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)


# ============ 检查点相关 ============

class CheckpointInfo(BaseModel):
    """检查点信息"""
    checkpoint_id: str
    label: str
    stage: str
    timestamp: datetime
    description: Optional[str] = None


class CheckpointListResponse(BaseModel):
    """检查点列表响应"""
    checkpoints: List[CheckpointInfo]
    current: Optional[str] = None


class RollbackRequest(BaseModel):
    """回滚请求"""
    checkpoint_id: str

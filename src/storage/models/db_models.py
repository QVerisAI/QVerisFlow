"""
数据库模型

使用 SQLAlchemy ORM 定义框架的持久化数据模型。
支持 PostgreSQL 和 SQLite（开发环境）。
"""

from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    JSON,
    ForeignKey,
    Index,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
import enum

Base = declarative_base()


class AgentStatus(str, enum.Enum):
    """Agent 状态"""

    DRAFT = "draft"  # 草稿
    ACTIVE = "active"  # 激活
    INACTIVE = "inactive"  # 停用
    ARCHIVED = "archived"  # 归档


class TaskStatus(str, enum.Enum):
    """任务状态"""

    PENDING = "pending"  # 等待中
    RUNNING = "running"  # 运行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消
    PAUSED = "paused"  # 已暂停


class WorkflowStatus(str, enum.Enum):
    """工作流状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


# ==================== Agent 相关模型 ====================


class AgentDefinitionModel(Base):
    """Agent 定义模型"""

    __tablename__ = "agent_definitions"

    id = Column(String(64), primary_key=True)
    agent_id = Column(String(128), nullable=False, index=True)
    version = Column(String(32), nullable=False, default="1.0.0")
    name = Column(String(256), nullable=False)
    description = Column(Text)

    # JSON 存储完整定义
    definition_json = Column(JSON, nullable=False)

    # 状态 - 使用 values_callable 确保使用枚举值而不是名称
    status = Column(
        SQLEnum(
            AgentStatus,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=AgentStatus.DRAFT,
    )

    # 配置快照
    model_name = Column(String(128))
    max_iterations = Column(Integer)

    # 元数据
    tags = Column(JSON, default=list)
    author = Column(String(128))

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    executions = relationship("TaskExecutionModel", back_populates="agent")

    # 索引
    __table_args__ = (
        Index("ix_agent_id_version", "agent_id", "version"),
        Index("ix_agent_status", "status"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "definition": self.definition_json,
            "status": self.status.value if self.status else None,
            "model_name": self.model_name,
            "max_iterations": self.max_iterations,
            "tags": self.tags,
            "author": self.author,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ==================== 工作流相关模型 ====================


class WorkflowDefinitionModel(Base):
    """工作流定义模型"""

    __tablename__ = "workflow_definitions"

    id = Column(String(64), primary_key=True)
    workflow_id = Column(String(128), nullable=False, index=True)
    version = Column(String(32), nullable=False, default="1.0.0")
    name = Column(String(256), nullable=False)
    description = Column(Text)

    # JSON 存储完整定义
    definition_json = Column(JSON, nullable=False)

    # 节点和边的数量（用于快速查询）
    node_count = Column(Integer, default=0)
    edge_count = Column(Integer, default=0)

    # 状态
    is_active = Column(Boolean, default=True)

    # 元数据
    tags = Column(JSON, default=list)
    author = Column(String(128))

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    executions = relationship("WorkflowExecutionModel", back_populates="workflow")

    __table_args__ = (Index("ix_workflow_id_version", "workflow_id", "version"),)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "definition": self.definition_json,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "is_active": self.is_active,
            "tags": self.tags,
            "author": self.author,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WorkflowExecutionModel(Base):
    """工作流执行记录模型"""

    __tablename__ = "workflow_executions"

    id = Column(String(64), primary_key=True)
    workflow_definition_id = Column(String(64), ForeignKey("workflow_definitions.id"))

    # 状态 - 使用 values_callable 确保使用枚举值而不是名称
    status = Column(
        SQLEnum(
            WorkflowStatus,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=WorkflowStatus.PENDING,
    )

    # 执行信息
    initial_context = Column(JSON)
    final_output = Column(JSON)
    error = Column(Text)

    # 节点执行结果
    node_results = Column(JSON, default=dict)

    # 性能指标
    total_duration_ms = Column(Float, default=0.0)

    # 检查点
    checkpoint_id = Column(String(128))

    # 时间戳
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    workflow = relationship("WorkflowDefinitionModel", back_populates="executions")

    __table_args__ = (
        Index("ix_workflow_exec_status", "status"),
        Index("ix_workflow_exec_started", "started_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workflow_definition_id": self.workflow_definition_id,
            "status": self.status.value if self.status else None,
            "initial_context": self.initial_context,
            "final_output": self.final_output,
            "error": self.error,
            "node_results": self.node_results,
            "total_duration_ms": self.total_duration_ms,
            "checkpoint_id": self.checkpoint_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==================== 任务相关模型 ====================


class TaskExecutionModel(Base):
    """任务执行记录模型"""

    __tablename__ = "task_executions"

    id = Column(String(64), primary_key=True)
    task_id = Column(String(128), nullable=False, index=True)
    agent_definition_id = Column(String(64), ForeignKey("agent_definitions.id"))

    # 任务信息
    task_description = Column(Text)
    input_data = Column(JSON)

    # 状态 - 使用 values_callable 确保使用枚举值而不是名称
    status = Column(
        SQLEnum(
            TaskStatus,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=TaskStatus.PENDING,
    )

    # 结果
    result = Column(JSON)
    error = Column(Text)

    # 性能指标
    duration_ms = Column(Float, default=0.0)
    iterations = Column(Integer, default=0)
    token_usage = Column(Integer, default=0)

    # 验证结果
    verification_passed = Column(Boolean)
    verification_score = Column(Float)
    verification_feedback = Column(Text)

    # 工作空间
    workspace_path = Column(String(512))
    output_files = Column(JSON, default=list)

    # 时间戳
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    agent = relationship("AgentDefinitionModel", back_populates="executions")
    tool_calls = relationship("ToolCallLogModel", back_populates="task")

    __table_args__ = (
        Index("ix_task_exec_status", "status"),
        Index("ix_task_exec_started", "started_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "agent_definition_id": self.agent_definition_id,
            "task_description": self.task_description,
            "input_data": self.input_data,
            "status": self.status.value if self.status else None,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "iterations": self.iterations,
            "token_usage": self.token_usage,
            "verification_passed": self.verification_passed,
            "verification_score": self.verification_score,
            "verification_feedback": self.verification_feedback,
            "workspace_path": self.workspace_path,
            "output_files": self.output_files,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==================== 工具调用日志模型 ====================


class ToolCallLogModel(Base):
    """工具调用日志模型"""

    __tablename__ = "tool_call_logs"

    id = Column(String(64), primary_key=True)
    task_execution_id = Column(String(64), ForeignKey("task_executions.id"))

    # 工具信息
    tool_id = Column(String(128), nullable=False, index=True)
    tool_name = Column(String(256))

    # 调用信息
    input_params = Column(JSON)
    output = Column(JSON)
    error = Column(Text)

    # 状态
    phase = Column(String(32))  # start, success, error

    # 性能
    duration_ms = Column(Float, default=0.0)

    # 时间戳
    timestamp = Column(DateTime, default=datetime.utcnow)

    # 关系
    task = relationship("TaskExecutionModel", back_populates="tool_calls")

    __table_args__ = (
        Index("ix_tool_call_tool_id", "tool_id"),
        Index("ix_tool_call_timestamp", "timestamp"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task_execution_id": self.task_execution_id,
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "input_params": self.input_params,
            "output": self.output,
            "error": self.error,
            "phase": self.phase,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


# ==================== 反馈模型 ====================


class FeedbackModel(Base):
    """执行反馈模型"""

    __tablename__ = "feedbacks"

    id = Column(String(64), primary_key=True)
    agent_id = Column(String(128), nullable=False, index=True)
    task_id = Column(String(128), index=True)
    task_execution_id = Column(
        String(64), ForeignKey("task_executions.id"), nullable=True
    )

    # 任务信息
    task_description = Column(Text)

    # 结果
    success = Column(Boolean, nullable=False)
    result_summary = Column(Text)
    error = Column(Text)

    # 性能指标
    duration_ms = Column(Float, default=0.0)
    iterations = Column(Integer, default=0)
    token_usage = Column(Integer, default=0)

    # 评分
    user_rating = Column(Float)  # 0-5
    user_feedback = Column(Text)
    automated_score = Column(Float)  # 0-1

    # 元数据
    extra_metadata = Column("metadata", JSON, default=dict)

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_feedback_agent_created", "agent_id", "created_at"),
        Index("ix_feedback_success", "success"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "task_execution_id": self.task_execution_id,
            "task_description": self.task_description,
            "success": self.success,
            "result_summary": self.result_summary,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "iterations": self.iterations,
            "token_usage": self.token_usage,
            "user_rating": self.user_rating,
            "user_feedback": self.user_feedback,
            "automated_score": self.automated_score,
            "metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==================== 会话模型 ====================


class SessionStatus(str, enum.Enum):
    """会话状态"""

    idle = "idle"  # 空闲
    planning = "planning"  # 规划中
    building = "building"  # 构建中
    confirming = "confirming"  # 确认中
    executing = "executing"  # 执行中
    completed = "completed"  # 已完成


class ConversationSessionModel(Base):
    """对话会话模型"""

    __tablename__ = "conversation_sessions"

    id = Column(String(64), primary_key=True)
    session_id = Column(String(128), nullable=False, unique=True, index=True)

    # 会话状态
    status = Column(
        SQLEnum(
            SessionStatus,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=SessionStatus.idle,
    )

    # 关联的工作流
    workflow_definition_id = Column(
        String(64), ForeignKey("workflow_definitions.id"), nullable=True
    )

    # 任务描述
    task_description = Column(Text)

    # 消息数量（用于快速查询）
    message_count = Column(Integer, default=0)

    # 元数据
    extra_metadata = Column("metadata", JSON, default=dict)

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_activity_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    messages = relationship(
        "ConversationMessageModel",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationMessageModel.sequence",
    )

    __table_args__ = (
        Index("ix_session_status", "status"),
        Index("ix_session_last_activity", "last_activity_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "status": self.status.value if self.status else None,
            "workflow_definition_id": self.workflow_definition_id,
            "task_description": self.task_description,
            "message_count": self.message_count,
            "metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_activity_at": (
                self.last_activity_at.isoformat() if self.last_activity_at else None
            ),
        }


class ConversationMessageModel(Base):
    """对话消息模型"""

    __tablename__ = "conversation_messages"

    id = Column(String(64), primary_key=True)
    session_id = Column(
        String(64), ForeignKey("conversation_sessions.id"), nullable=False
    )

    # 消息内容
    role = Column(String(32), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)

    # 消息类型
    message_type = Column(String(32), default="text")  # text, workflow_update, etc.

    # 序号（用于排序）
    sequence = Column(Integer, nullable=False, index=True)

    # 额外数据
    extra_data = Column("data", JSON, default=dict)

    # 时间戳
    timestamp = Column(DateTime, default=datetime.utcnow)

    # 关系
    session = relationship("ConversationSessionModel", back_populates="messages")

    __table_args__ = (
        Index("ix_message_session_sequence", "session_id", "sequence"),
        Index("ix_message_timestamp", "timestamp"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "message_type": self.message_type,
            "sequence": self.sequence,
            "data": self.extra_data,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


# 导出所有模型
__all__ = [
    "Base",
    # 枚举
    "AgentStatus",
    "TaskStatus",
    "SessionStatus",
    "WorkflowStatus",
    # Agent 模型
    "AgentDefinitionModel",
    # 工作流模型
    "WorkflowDefinitionModel",
    "WorkflowExecutionModel",
    # 任务模型
    "TaskExecutionModel",
    # 工具日志模型
    "ToolCallLogModel",
    # 反馈模型
    "FeedbackModel",
    # 会话模型
    "ConversationSessionModel",
    "ConversationMessageModel",
]

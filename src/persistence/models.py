"""
持久化数据模型

定义用于存储追踪数据的数据模型。
这些模型用于将运行时数据持久化到存储后端。

注意：
- observability.Span 用于运行时追踪
- persistence.SpanRecord 用于存储
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class ExecutionStatus(str, Enum):
    """执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SpanType(str, Enum):
    """Span 类型"""

    AGENT = "agent"
    PHASE = "phase"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    SUB_AGENT = "sub_agent"
    VERIFICATION = "verification"
    CUSTOM = "custom"


@dataclass
class SpanRecord:
    """
    可持久化的 Span 记录

    从 observability.Span 转换而来，用于存储。
    """

    span_id: str
    trace_id: str
    parent_span_id: Optional[str]
    name: str
    start_time: datetime
    end_time: Optional[datetime]
    duration_ms: float
    status: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_observability_span(cls, span: Any) -> "SpanRecord":
        """
        从 observability.Span 转换

        Args:
            span: 运行时 Span 对象 (from observability.tracing)

        Returns:
            可持久化的 SpanRecord
        """
        return cls(
            span_id=span.context.span_id,
            trace_id=span.context.trace_id,
            parent_span_id=span.context.parent_span_id,
            name=span.name,
            start_time=span.start_time,
            end_time=span.end_time,
            duration_ms=span.duration_ms,
            status=span.status,
            attributes=span.attributes.copy(),
            events=span.events.copy(),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpanRecord":
        """从字典创建"""
        return cls(
            span_id=data["span_id"],
            trace_id=data["trace_id"],
            parent_span_id=data.get("parent_span_id"),
            name=data["name"],
            start_time=(
                datetime.fromisoformat(data["start_time"])
                if data.get("start_time")
                else None
            ),
            end_time=(
                datetime.fromisoformat(data["end_time"])
                if data.get("end_time")
                else None
            ),
            duration_ms=data.get("duration_ms", 0),
            status=data.get("status", "ok"),
            attributes=data.get("attributes", {}),
            events=data.get("events", []),
        )


@dataclass
class LLMCallRecord:
    """LLM 调用记录"""

    call_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    span_id: str = ""
    trace_id: str = ""

    # 模型信息
    provider: str = ""
    model: str = ""

    # 输入
    messages: List[Dict[str, Any]] = field(default_factory=list)
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None

    # 输出
    response: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: Optional[str] = None

    # Token 使用
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # 成本
    cost_usd: float = 0.0

    # 性能
    latency_ms: int = 0

    # 时间
    timestamp: datetime = field(default_factory=datetime.now)

    # 状态
    success: bool = True
    error: Optional[str] = None

    # 缓存
    cache_hit: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "call_id": self.call_id,
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "provider": self.provider,
            "model": self.model,
            "messages": self.messages,
            "system_prompt": self.system_prompt,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response": self.response,
            "tool_calls": self.tool_calls,
            "finish_reason": self.finish_reason,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "error": self.error,
            "cache_hit": self.cache_hit,
        }


@dataclass
class ToolCallRecord:
    """工具调用记录"""

    call_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    span_id: str = ""
    trace_id: str = ""

    # 工具信息
    tool_id: str = ""
    tool_name: str = ""
    tool_category: str = ""

    # 输入输出
    input_params: Dict[str, Any] = field(default_factory=dict)
    output: Optional[Any] = None
    output_truncated: bool = False

    # 性能
    latency_ms: int = 0

    # 时间
    timestamp: datetime = field(default_factory=datetime.now)

    # 状态
    success: bool = True
    error: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "call_id": self.call_id,
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "tool_category": self.tool_category,
            "input_params": self.input_params,
            "output": self.output,
            "output_truncated": self.output_truncated,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "error": self.error,
            "retry_count": self.retry_count,
        }


@dataclass
class ExecutionTrace:
    """
    完整的执行追踪

    包含一次 Agent 执行的所有数据。
    """

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # 关联信息
    task_id: str = ""
    agent_id: str = ""
    workflow_id: Optional[str] = None
    parent_trace_id: Optional[str] = None

    # 输入
    input_data: Dict[str, Any] = field(default_factory=dict)
    task_description: str = ""

    # 输出
    output_data: Optional[Dict[str, Any]] = None
    output_files: List[str] = field(default_factory=list)

    # 状态
    status: ExecutionStatus = ExecutionStatus.PENDING

    # 时间
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    # 执行详情
    spans: List[SpanRecord] = field(default_factory=list)
    llm_calls: List[LLMCallRecord] = field(default_factory=list)
    tool_calls: List[ToolCallRecord] = field(default_factory=list)

    # 汇总统计
    summary: Dict[str, Any] = field(default_factory=dict)

    # 错误信息
    error: Optional[str] = None
    error_stack: Optional[str] = None

    # 元数据
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 工作空间路径
    workspace_path: Optional[str] = None

    def start(self) -> None:
        """开始追踪"""
        self.started_at = datetime.now()
        self.status = ExecutionStatus.RUNNING

    def complete(self, output: Dict[str, Any] = None) -> None:
        """完成追踪"""
        self.completed_at = datetime.now()
        if self.started_at:
            self.duration_ms = int(
                (self.completed_at - self.started_at).total_seconds() * 1000
            )
        self.status = ExecutionStatus.COMPLETED
        self.output_data = output
        self._calculate_summary()

    def fail(self, error: str, error_stack: str = None) -> None:
        """标记失败"""
        self.completed_at = datetime.now()
        if self.started_at:
            self.duration_ms = int(
                (self.completed_at - self.started_at).total_seconds() * 1000
            )
        self.status = ExecutionStatus.FAILED
        self.error = error
        self.error_stack = error_stack
        self._calculate_summary()

    def _calculate_summary(self) -> None:
        """计算汇总统计"""
        self.summary = {
            "total_spans": len(self.spans),
            "total_llm_calls": len(self.llm_calls),
            "total_tool_calls": len(self.tool_calls),
            # Token 统计
            "total_prompt_tokens": sum(c.prompt_tokens for c in self.llm_calls),
            "total_completion_tokens": sum(c.completion_tokens for c in self.llm_calls),
            "total_tokens": sum(c.total_tokens for c in self.llm_calls),
            # 成本统计
            "total_cost_usd": sum(c.cost_usd for c in self.llm_calls),
            # 成功率
            "llm_success_rate": (
                sum(1 for c in self.llm_calls if c.success) / len(self.llm_calls)
                if self.llm_calls
                else 1.0
            ),
            "tool_success_rate": (
                sum(1 for c in self.tool_calls if c.success) / len(self.tool_calls)
                if self.tool_calls
                else 1.0
            ),
            # 延迟统计
            "avg_llm_latency_ms": (
                sum(c.latency_ms for c in self.llm_calls) / len(self.llm_calls)
                if self.llm_calls
                else 0
            ),
            "avg_tool_latency_ms": (
                sum(c.latency_ms for c in self.tool_calls) / len(self.tool_calls)
                if self.tool_calls
                else 0
            ),
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "workflow_id": self.workflow_id,
            "parent_trace_id": self.parent_trace_id,
            "input_data": self.input_data,
            "task_description": self.task_description,
            "output_data": self.output_data,
            "output_files": self.output_files,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "duration_ms": self.duration_ms,
            "spans": [s.to_dict() for s in self.spans],
            "llm_calls": [c.to_dict() for c in self.llm_calls],
            "tool_calls": [c.to_dict() for c in self.tool_calls],
            "summary": self.summary,
            "error": self.error,
            "error_stack": self.error_stack,
            "tags": self.tags,
            "metadata": self.metadata,
            "workspace_path": self.workspace_path,
        }


@dataclass
class TraceFilters:
    """追踪查询过滤器"""

    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    workflow_id: Optional[str] = None
    status: Optional[ExecutionStatus] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    tags: Optional[List[str]] = None
    limit: int = 100
    offset: int = 0


__all__ = [
    "ExecutionStatus",
    "SpanType",
    "SpanRecord",
    "LLMCallRecord",
    "ToolCallRecord",
    "ExecutionTrace",
    "TraceFilters",
]

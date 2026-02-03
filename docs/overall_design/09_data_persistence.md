# 全流程数据持久化设计

> **存储介质**: 本模块的数据持久化基于 PostgreSQL + OSS + Redis 架构，详见 [11_storage_infrastructure.md](./11_storage_infrastructure.md)

## 1. 设计目标

全流程数据持久化旨在记录 Agent 执行的完整生命周期数据，支持：

| 目标 | 说明 |
|------|------|
| **可追溯性** | 任何执行结果都能追溯到完整的执行过程 |
| **可审计性** | 满足合规要求，记录所有 LLM 调用和决策 |
| **可调试性** | 问题排查时能够重现完整执行上下文 |
| **可分析性** | 支持性能分析、成本统计、质量评估 |
| **可恢复性** | 支持从任意检查点恢复执行 |

### 1.1 系统架构与模块边界

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          数据持久化三层架构                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    observability/ (运行时采集层)                     │    │
│  │  ├── tracing.py         # Span 采集、上下文传播                      │    │
│  │  ├── metrics.py         # 指标采集                                   │    │
│  │  └── exporters.py       # 导出器（连接到 persistence）               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    persistence/ (存储 API 层)                        │    │
│  │  ├── models.py          # 持久化数据模型                             │    │
│  │  ├── trace_storage.py   # 追踪存储接口 + 实现                        │    │
│  │  └── trace_collector.py # 追踪收集器                                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    storage/ (基础设施层)                             │    │
│  │  ├── config.py              # 统一配置管理                           │    │
│  │  ├── database.py            # AsyncDatabaseManager                   │    │
│  │  ├── redis_client.py        # RedisClient (异步 + 同步)              │    │
│  │  ├── oss_client.py          # OSS 客户端                             │    │
│  │  ├── checkpointers/         # LangGraph 检查点存储                   │    │
│  │  │   ├── base.py            # 基类                                   │    │
│  │  │   ├── redis_saver.py     # Redis 检查点                           │    │
│  │  │   ├── postgres_saver.py  # PostgreSQL 检查点                      │    │
│  │  │   ├── file_saver.py      # 文件系统检查点                         │    │
│  │  │   └── factory.py         # 工厂类                                 │    │
│  │  └── repositories/          # Repository 模式                        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 存储介质分工

```
┌─────────────────────────────────────────────────────────────┐
│                    数据持久化存储架构                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  PostgreSQL (结构化数据)              OSS (大内容)           │
│  ├── execution_traces                 ├── traces/           │
│  │   (追踪元数据)                     │   └── {trace_id}/   │
│  ├── trace_spans                      │       ├── llm_calls/│
│  │   (执行跨度)                       │       ├── tool_calls/│
│  ├── trace_llm_calls                  │       └── checkpoints/│
│  │   (LLM 调用记录)                   │                      │
│  ├── trace_tool_calls                 Redis (缓存 + 检查点) │
│  │   (工具调用记录)                   ├── llm_response_cache │
│  ├── trace_checkpoints                ├── session_state     │
│  │   (检查点)                         └── langgraph:checkpoint:│
│  ├── langgraph_checkpoints            │   (LangGraph 检查点) │
│  │   (LangGraph 检查点)               │                      │
│  └── trace_verifications                                     │
│      (验证记录)                                              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**存储策略：**
- **元数据** → PostgreSQL：追踪 ID、时间戳、统计信息、状态
- **大内容** → OSS：LLM 消息/响应、工具输出、检查点状态
- **热数据** → Redis：活跃会话、LLM 响应缓存、LangGraph 检查点（分布式场景）
- **检查点** → 可配置：Memory（开发）、Redis（分布式）、PostgreSQL（持久化）

---

## 2. 数据模型

### 2.1 执行追踪数据结构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ExecutionTrace（执行追踪）                    │
├─────────────────────────────────────────────────────────────────────┤
│  trace_id: "trace_20240101_001"                                      │
│  task_id: "analysis_001"                                             │
│  agent_id: "financial_analyst"                                       │
│  workflow_id: "signal_verification_v1"                               │
│  status: "completed" / "running" / "failed"                          │
│  started_at: "2024-01-01T10:00:00Z"                                  │
│  completed_at: "2024-01-01T10:05:30Z"                                │
│  duration_ms: 330000                                                 │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Spans（执行跨度）                         │    │
│  ├─────────────────────────────────────────────────────────────┤    │
│  │  span_1: {                                                   │    │
│  │    span_id: "span_001",                                      │    │
│  │    parent_span_id: null,                                     │    │
│  │    phase: "gather_context",                                  │    │
│  │    started_at: ..., duration_ms: 5000                        │    │
│  │  }                                                           │    │
│  │  span_2: {                                                   │    │
│  │    span_id: "span_002",                                      │    │
│  │    parent_span_id: "span_001",                               │    │
│  │    operation: "llm_call",                                    │    │
│  │    ...                                                       │    │
│  │  }                                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                  LLM Calls（LLM 调用记录）                   │    │
│  ├─────────────────────────────────────────────────────────────┤    │
│  │  call_1: {                                                   │    │
│  │    call_id: "llm_001",                                       │    │
│  │    model: "deepseek/deepseek-v3",                            │    │
│  │    prompt_tokens: 1500,                                      │    │
│  │    completion_tokens: 800,                                   │    │
│  │    cost_usd: 0.0023,                                         │    │
│  │    latency_ms: 2300,                                         │    │
│  │    messages: [...],                                          │    │
│  │    response: "...",                                          │    │
│  │  }                                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                Tool Calls（工具调用记录）                    │    │
│  ├─────────────────────────────────────────────────────────────┤    │
│  │  tool_1: {                                                   │    │
│  │    call_id: "tool_001",                                      │    │
│  │    tool_id: "stock_price",                                   │    │
│  │    input: {"ticker": "600519.SH"},                           │    │
│  │    output: {...},                                            │    │
│  │    latency_ms: 150,                                          │    │
│  │    success: true                                             │    │
│  │  }                                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              Checkpoints（检查点快照）                       │    │
│  ├─────────────────────────────────────────────────────────────┤    │
│  │  checkpoint_1: {                                             │    │
│  │    checkpoint_id: "cp_001",                                  │    │
│  │    iteration: 1,                                             │    │
│  │    phase: "verify_work",                                     │    │
│  │    state_snapshot: {...},                                    │    │
│  │    recoverable: true                                         │    │
│  │  }                                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  summary: {                                                          │
│    total_llm_calls: 5,                                               │
│    total_tool_calls: 12,                                             │
│    total_tokens: 15000,                                              │
│    total_cost_usd: 0.015,                                            │
│    iterations: 2,                                                    │
│    verification_score: 0.92                                          │
│  }                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心数据模型定义

```python
# etf_common/agent_framework/persistence/models.py

from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class ExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SpanType(str, Enum):
    """跨度类型"""
    AGENT = "agent"
    PHASE = "phase"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    SUB_AGENT = "sub_agent"
    VERIFICATION = "verification"
    CUSTOM = "custom"


# ============================================================================
# 执行跨度（Span）- OpenTelemetry 风格
# ============================================================================

class Span(BaseModel):
    """执行跨度 - 记录单个操作的执行信息"""
    
    span_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    trace_id: str = Field(description="所属追踪 ID")
    parent_span_id: Optional[str] = Field(default=None, description="父跨度 ID")
    
    name: str = Field(description="跨度名称")
    span_type: SpanType = Field(description="跨度类型")
    
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: Optional[datetime] = Field(default=None)
    duration_ms: Optional[int] = Field(default=None)
    
    status: ExecutionStatus = Field(default=ExecutionStatus.RUNNING)
    error: Optional[str] = Field(default=None)
    
    # 属性（键值对）
    attributes: Dict[str, Any] = Field(default_factory=dict)
    
    # 事件（时间点标记）
    events: List[Dict[str, Any]] = Field(default_factory=list)
    
    def end(self, status: ExecutionStatus = ExecutionStatus.COMPLETED, error: str = None):
        """结束跨度"""
        self.ended_at = datetime.now()
        self.duration_ms = int((self.ended_at - self.started_at).total_seconds() * 1000)
        self.status = status
        self.error = error
    
    def add_event(self, name: str, attributes: Dict[str, Any] = None):
        """添加事件"""
        self.events.append({
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "attributes": attributes or {}
        })
    
    def set_attribute(self, key: str, value: Any):
        """设置属性"""
        self.attributes[key] = value


# ============================================================================
# LLM 调用记录
# ============================================================================

class LLMCallRecord(BaseModel):
    """LLM 调用记录"""
    
    call_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    span_id: str = Field(description="所属跨度 ID")
    trace_id: str = Field(description="所属追踪 ID")
    
    # 模型信息
    provider: str = Field(description="提供商：openrouter, openai, anthropic")
    model: str = Field(description="模型名称")
    
    # 输入
    messages: List[Dict[str, Any]] = Field(description="消息列表")
    system_prompt: Optional[str] = Field(default=None)
    temperature: float = Field(default=0.7)
    max_tokens: Optional[int] = Field(default=None)
    
    # 输出
    response: Optional[str] = Field(default=None)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    finish_reason: Optional[str] = Field(default=None)
    
    # Token 使用
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    
    # 成本（美元）
    cost_usd: float = Field(default=0.0)
    
    # 性能
    latency_ms: int = Field(default=0)
    
    # 时间
    timestamp: datetime = Field(default_factory=datetime.now)
    
    # 状态
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)
    
    # 缓存
    cache_hit: bool = Field(default=False)


# ============================================================================
# 工具调用记录
# ============================================================================

class ToolCallRecord(BaseModel):
    """工具调用记录"""
    
    call_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    span_id: str = Field(description="所属跨度 ID")
    trace_id: str = Field(description="所属追踪 ID")
    
    # 工具信息
    tool_id: str = Field(description="工具 ID")
    tool_name: str = Field(description="工具名称")
    tool_category: str = Field(description="工具分类")
    
    # 输入输出
    input_params: Dict[str, Any] = Field(description="输入参数")
    output: Optional[Any] = Field(default=None, description="输出结果")
    output_truncated: bool = Field(default=False, description="输出是否被截断")
    
    # 性能
    latency_ms: int = Field(default=0)
    
    # 时间
    timestamp: datetime = Field(default_factory=datetime.now)
    
    # 状态
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)
    retry_count: int = Field(default=0)


# ============================================================================
# 检查点快照
# ============================================================================

class Checkpoint(BaseModel):
    """检查点快照 - 用于恢复执行"""
    
    checkpoint_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    trace_id: str = Field(description="所属追踪 ID")
    
    # 位置信息
    iteration: int = Field(description="迭代次数")
    phase: str = Field(description="执行阶段")
    node_id: Optional[str] = Field(default=None, description="工作流节点 ID")
    
    # 状态快照
    agent_state: Dict[str, Any] = Field(description="Agent 状态")
    workflow_state: Optional[Dict[str, Any]] = Field(default=None, description="工作流状态")
    
    # LangGraph 检查点（如果使用）
    langgraph_checkpoint: Optional[str] = Field(default=None, description="LangGraph 检查点 ID")
    
    # 时间
    timestamp: datetime = Field(default_factory=datetime.now)
    
    # 恢复信息
    recoverable: bool = Field(default=True)
    recovery_instructions: Optional[str] = Field(default=None)


# ============================================================================
# 验证记录
# ============================================================================

class VerificationRecord(BaseModel):
    """验证记录"""
    
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    span_id: str = Field(description="所属跨度 ID")
    trace_id: str = Field(description="所属追踪 ID")
    
    iteration: int = Field(description="迭代次数")
    
    # 验证结果
    passed: bool = Field(description="是否通过")
    score: float = Field(description="评分 0-1")
    feedback: str = Field(description="反馈信息")
    
    # 详细结果
    rule_results: List[Dict[str, Any]] = Field(default_factory=list)
    llm_judge_result: Optional[Dict[str, Any]] = Field(default=None)
    
    # 输入
    output_verified: Any = Field(description="被验证的输出")
    
    # 时间
    timestamp: datetime = Field(default_factory=datetime.now)


# ============================================================================
# 执行追踪（顶层）
# ============================================================================

class ExecutionTrace(BaseModel):
    """执行追踪 - 完整的执行记录"""
    
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    
    # 关联信息
    task_id: str = Field(description="任务 ID")
    agent_id: str = Field(description="Agent ID")
    workflow_id: Optional[str] = Field(default=None, description="工作流 ID")
    parent_trace_id: Optional[str] = Field(default=None, description="父追踪 ID（子 Agent）")
    
    # 输入
    input_data: Dict[str, Any] = Field(default_factory=dict)
    task_description: str = Field(default="")
    
    # 输出
    output_data: Optional[Dict[str, Any]] = Field(default=None)
    output_files: List[str] = Field(default_factory=list)
    
    # 状态
    status: ExecutionStatus = Field(default=ExecutionStatus.PENDING)
    
    # 时间
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    duration_ms: Optional[int] = Field(default=None)
    
    # 执行详情
    spans: List[Span] = Field(default_factory=list)
    llm_calls: List[LLMCallRecord] = Field(default_factory=list)
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    checkpoints: List[Checkpoint] = Field(default_factory=list)
    verifications: List[VerificationRecord] = Field(default_factory=list)
    
    # 汇总统计
    summary: Dict[str, Any] = Field(default_factory=dict)
    
    # 错误信息
    error: Optional[str] = Field(default=None)
    error_stack: Optional[str] = Field(default=None)
    
    # 元数据
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # 工作空间路径
    workspace_path: Optional[str] = Field(default=None)
    
    def start(self):
        """开始追踪"""
        self.started_at = datetime.now()
        self.status = ExecutionStatus.RUNNING
    
    def complete(self, output: Dict[str, Any] = None):
        """完成追踪"""
        self.completed_at = datetime.now()
        self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)
        self.status = ExecutionStatus.COMPLETED
        self.output_data = output
        self._calculate_summary()
    
    def fail(self, error: str, error_stack: str = None):
        """标记失败"""
        self.completed_at = datetime.now()
        self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)
        self.status = ExecutionStatus.FAILED
        self.error = error
        self.error_stack = error_stack
        self._calculate_summary()
    
    def _calculate_summary(self):
        """计算汇总统计"""
        self.summary = {
            "total_spans": len(self.spans),
            "total_llm_calls": len(self.llm_calls),
            "total_tool_calls": len(self.tool_calls),
            "total_checkpoints": len(self.checkpoints),
            "total_verifications": len(self.verifications),
            
            # Token 统计
            "total_prompt_tokens": sum(c.prompt_tokens for c in self.llm_calls),
            "total_completion_tokens": sum(c.completion_tokens for c in self.llm_calls),
            "total_tokens": sum(c.total_tokens for c in self.llm_calls),
            
            # 成本统计
            "total_cost_usd": sum(c.cost_usd for c in self.llm_calls),
            
            # 成功率
            "llm_success_rate": (
                sum(1 for c in self.llm_calls if c.success) / len(self.llm_calls)
                if self.llm_calls else 1.0
            ),
            "tool_success_rate": (
                sum(1 for c in self.tool_calls if c.success) / len(self.tool_calls)
                if self.tool_calls else 1.0
            ),
            
            # 验证统计
            "final_verification_score": (
                self.verifications[-1].score if self.verifications else None
            ),
            "iterations": len(self.verifications),
            
            # 延迟统计
            "avg_llm_latency_ms": (
                sum(c.latency_ms for c in self.llm_calls) / len(self.llm_calls)
                if self.llm_calls else 0
            ),
            "avg_tool_latency_ms": (
                sum(c.latency_ms for c in self.tool_calls) / len(self.tool_calls)
                if self.tool_calls else 0
            )
        }
```

---

## 2.3 Observability 与 Persistence 集成

运行时追踪（`observability/tracing.py`）和持久化存储（`persistence/`）通过 **SpanExporter** 机制连接：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       运行时追踪 → 持久化流程                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐   │
│   │  AgentTracer    │ ───▶ │  SpanExporter   │ ───▶ │  TraceStorage   │   │
│   │  (运行时采集)    │       │  (导出桥接)     │       │  (持久化存储)   │   │
│   └─────────────────┘       └─────────────────┘       └─────────────────┘   │
│                                                                              │
│   observability/            observability/             persistence/          │
│   tracing.py                exporters.py               trace_storage.py      │
│                                                                              │
│   • Span 创建与管理          • DatabaseSpanExporter    • FileTraceStorage    │
│   • 上下文传播               • FileSpanExporter        • DatabaseTraceStorage│
│   • 装饰器支持               • 数据模型转换             • OSS 集成            │
│   • OpenTelemetry 兼容       • 异步批量写入             • 查询与过滤          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**关键类型转换**：

```python
# observability/tracing.py 的 Span
@dataclass
class Span:
    name: str
    context: SpanContext  # trace_id, span_id, parent_span_id
    start_time: datetime
    end_time: Optional[datetime]
    status: str  # "ok", "error"
    attributes: Dict[str, Any]
    events: list

# persistence/models.py 的 SpanRecord (持久化版本)
class SpanRecord(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: Optional[str]
    name: str
    span_type: SpanType
    started_at: datetime
    ended_at: Optional[datetime]
    duration_ms: Optional[int]
    status: ExecutionStatus
    error: Optional[str]
    attributes: Dict[str, Any]
    events: List[Dict[str, Any]]
    
    @classmethod
    def from_observability_span(cls, span: "observability.tracing.Span") -> "SpanRecord":
        """从运行时 Span 转换为持久化 SpanRecord"""
        ...
```

**导出器实现**：

```python
# observability/exporters.py

class DatabaseSpanExporter(SpanExporter):
    """将 Span 导出到数据库"""
    
    def __init__(self, trace_storage: TraceStorage):
        self.trace_storage = trace_storage
    
    def export(self, spans: List[Span]) -> None:
        for span in spans:
            span_record = SpanRecord.from_observability_span(span)
            asyncio.create_task(self.trace_storage.save_span(span_record))
```

**使用方式**：

```python
from observability.tracing import AgentTracer
from observability.exporters import DatabaseSpanExporter
from persistence.trace_storage import DatabaseTraceStorage, TraceStorageFactory
from storage import AsyncDatabaseManager

# 初始化
db_manager = await AsyncDatabaseManager.get_instance()
trace_storage = TraceStorageFactory.create("database", db_manager=db_manager)

# 配置追踪器
tracer = AgentTracer.get_default()
tracer.add_exporter(DatabaseSpanExporter(trace_storage))
```

---

## 3. 追踪收集器

```python
# etf_common/agent_framework/persistence/trace_collector.py

from typing import Dict, Any, Optional, Callable
from contextlib import contextmanager
from contextvars import ContextVar
import asyncio
import functools

from .models import (
    ExecutionTrace, Span, SpanType, ExecutionStatus,
    LLMCallRecord, ToolCallRecord, Checkpoint, VerificationRecord
)


# 上下文变量：当前追踪
_current_trace: ContextVar[Optional[ExecutionTrace]] = ContextVar('current_trace', default=None)
_current_span: ContextVar[Optional[Span]] = ContextVar('current_span', default=None)


class TraceCollector:
    """
    追踪收集器
    
    负责收集执行过程中的所有数据，支持：
    - 自动追踪 Agent 执行
    - 手动添加 Span
    - LLM/Tool 调用自动记录
    - 检查点自动保存
    """
    
    def __init__(self, storage: "TraceStorage"):
        self.storage = storage
    
    # ========== 追踪管理 ==========
    
    def create_trace(
        self,
        task_id: str,
        agent_id: str,
        workflow_id: str = None,
        input_data: Dict[str, Any] = None,
        task_description: str = "",
        parent_trace_id: str = None,
        workspace_path: str = None,
        tags: list = None,
        metadata: dict = None
    ) -> ExecutionTrace:
        """创建新的执行追踪"""
        trace = ExecutionTrace(
            task_id=task_id,
            agent_id=agent_id,
            workflow_id=workflow_id,
            input_data=input_data or {},
            task_description=task_description,
            parent_trace_id=parent_trace_id,
            workspace_path=workspace_path,
            tags=tags or [],
            metadata=metadata or {}
        )
        
        # 设置当前追踪
        _current_trace.set(trace)
        
        return trace
    
    def get_current_trace(self) -> Optional[ExecutionTrace]:
        """获取当前追踪"""
        return _current_trace.get()
    
    async def finish_trace(
        self,
        trace: ExecutionTrace,
        output: Dict[str, Any] = None,
        success: bool = True,
        error: str = None
    ):
        """完成追踪并持久化"""
        if success:
            trace.complete(output)
        else:
            trace.fail(error)
        
        # 持久化
        await self.storage.save_trace(trace)
        
        # 清理上下文
        _current_trace.set(None)
        _current_span.set(None)
    
    # ========== Span 管理 ==========
    
    @contextmanager
    def span(
        self,
        name: str,
        span_type: SpanType = SpanType.CUSTOM,
        attributes: Dict[str, Any] = None
    ):
        """
        创建 Span 的上下文管理器
        
        Usage:
            with collector.span("gather_context", SpanType.PHASE):
                # 执行操作
                pass
        """
        trace = _current_trace.get()
        if trace is None:
            yield None
            return
        
        parent_span = _current_span.get()
        
        span = Span(
            trace_id=trace.trace_id,
            parent_span_id=parent_span.span_id if parent_span else None,
            name=name,
            span_type=span_type,
            attributes=attributes or {}
        )
        
        trace.spans.append(span)
        _current_span.set(span)
        
        try:
            yield span
            span.end(ExecutionStatus.COMPLETED)
        except Exception as e:
            span.end(ExecutionStatus.FAILED, str(e))
            raise
        finally:
            _current_span.set(parent_span)
    
    # ========== LLM 调用记录 ==========
    
    def record_llm_call(
        self,
        provider: str,
        model: str,
        messages: list,
        response: str = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        success: bool = True,
        error: str = None,
        **kwargs
    ) -> LLMCallRecord:
        """记录 LLM 调用"""
        trace = _current_trace.get()
        span = _current_span.get()
        
        if trace is None:
            return None
        
        record = LLMCallRecord(
            span_id=span.span_id if span else "",
            trace_id=trace.trace_id,
            provider=provider,
            model=model,
            messages=messages,
            response=response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            success=success,
            error=error,
            **kwargs
        )
        
        trace.llm_calls.append(record)
        return record
    
    # ========== 工具调用记录 ==========
    
    def record_tool_call(
        self,
        tool_id: str,
        tool_name: str,
        tool_category: str,
        input_params: Dict[str, Any],
        output: Any = None,
        latency_ms: int = 0,
        success: bool = True,
        error: str = None
    ) -> ToolCallRecord:
        """记录工具调用"""
        trace = _current_trace.get()
        span = _current_span.get()
        
        if trace is None:
            return None
        
        # 处理大输出
        output_truncated = False
        if output and len(str(output)) > 10000:
            output = str(output)[:10000] + "...[TRUNCATED]"
            output_truncated = True
        
        record = ToolCallRecord(
            span_id=span.span_id if span else "",
            trace_id=trace.trace_id,
            tool_id=tool_id,
            tool_name=tool_name,
            tool_category=tool_category,
            input_params=input_params,
            output=output,
            output_truncated=output_truncated,
            latency_ms=latency_ms,
            success=success,
            error=error
        )
        
        trace.tool_calls.append(record)
        return record
    
    # ========== 检查点 ==========
    
    def save_checkpoint(
        self,
        iteration: int,
        phase: str,
        agent_state: Dict[str, Any],
        workflow_state: Dict[str, Any] = None,
        node_id: str = None,
        langgraph_checkpoint: str = None
    ) -> Checkpoint:
        """保存检查点"""
        trace = _current_trace.get()
        
        if trace is None:
            return None
        
        checkpoint = Checkpoint(
            trace_id=trace.trace_id,
            iteration=iteration,
            phase=phase,
            node_id=node_id,
            agent_state=agent_state,
            workflow_state=workflow_state,
            langgraph_checkpoint=langgraph_checkpoint
        )
        
        trace.checkpoints.append(checkpoint)
        return checkpoint
    
    # ========== 验证记录 ==========
    
    def record_verification(
        self,
        iteration: int,
        passed: bool,
        score: float,
        feedback: str,
        output_verified: Any,
        rule_results: list = None,
        llm_judge_result: dict = None
    ) -> VerificationRecord:
        """记录验证结果"""
        trace = _current_trace.get()
        span = _current_span.get()
        
        if trace is None:
            return None
        
        record = VerificationRecord(
            span_id=span.span_id if span else "",
            trace_id=trace.trace_id,
            iteration=iteration,
            passed=passed,
            score=score,
            feedback=feedback,
            output_verified=output_verified,
            rule_results=rule_results or [],
            llm_judge_result=llm_judge_result
        )
        
        trace.verifications.append(record)
        return record


# ========== 装饰器 ==========

def trace_agent(collector: TraceCollector):
    """Agent 执行追踪装饰器"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            trace = collector.create_trace(
                task_id=self.workspace.config.task_id,
                agent_id=self.definition.agent_id,
                workspace_path=str(self.workspace.root)
            )
            trace.start()
            
            try:
                result = await func(self, *args, **kwargs)
                await collector.finish_trace(
                    trace,
                    output=result,
                    success=True
                )
                return result
            except Exception as e:
                await collector.finish_trace(
                    trace,
                    success=False,
                    error=str(e)
                )
                raise
        
        return wrapper
    return decorator


def trace_llm_call(collector: TraceCollector):
    """LLM 调用追踪装饰器"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            import time
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                latency_ms = int((time.time() - start_time) * 1000)
                
                # 提取 LLM 调用信息（需要根据实际 LLM 客户端调整）
                collector.record_llm_call(
                    provider=kwargs.get('provider', 'unknown'),
                    model=kwargs.get('model', 'unknown'),
                    messages=kwargs.get('messages', []),
                    response=str(result),
                    latency_ms=latency_ms,
                    success=True
                )
                
                return result
            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)
                collector.record_llm_call(
                    provider=kwargs.get('provider', 'unknown'),
                    model=kwargs.get('model', 'unknown'),
                    messages=kwargs.get('messages', []),
                    latency_ms=latency_ms,
                    success=False,
                    error=str(e)
                )
                raise
        
        return wrapper
    return decorator
```

---

## 4. 追踪存储

```python
# etf_common/agent_framework/persistence/trace_storage.py

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from pathlib import Path
import json
import asyncio

from .models import ExecutionTrace, ExecutionStatus


class TraceStorage(ABC):
    """追踪存储抽象基类"""
    
    @abstractmethod
    async def save_trace(self, trace: ExecutionTrace):
        """保存追踪"""
        pass
    
    @abstractmethod
    async def get_trace(self, trace_id: str) -> Optional[ExecutionTrace]:
        """获取追踪"""
        pass
    
    @abstractmethod
    async def list_traces(
        self,
        task_id: str = None,
        agent_id: str = None,
        status: ExecutionStatus = None,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ExecutionTrace]:
        """列出追踪"""
        pass
    
    @abstractmethod
    async def delete_trace(self, trace_id: str):
        """删除追踪"""
        pass


class FileTraceStorage(TraceStorage):
    """
    文件系统追踪存储
    
    目录结构：
    traces/
    ├── index.json              # 索引文件
    ├── 2024/
    │   ├── 01/
    │   │   ├── 01/
    │   │   │   ├── trace_xxx.json
    │   │   │   └── trace_yyy.json
    │   │   └── 02/
    │   └── 02/
    └── by_task/                # 按任务索引（软链接或引用）
        └── task_001/
            └── traces.json
    """
    
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._index_path = self.base_path / "index.json"
        self._ensure_index()
    
    def _ensure_index(self):
        """确保索引文件存在"""
        if not self._index_path.exists():
            self._save_index({"traces": {}, "updated_at": datetime.now().isoformat()})
    
    def _load_index(self) -> Dict[str, Any]:
        """加载索引"""
        with open(self._index_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _save_index(self, index: Dict[str, Any]):
        """保存索引"""
        with open(self._index_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
    
    def _get_trace_path(self, trace: ExecutionTrace) -> Path:
        """获取追踪文件路径"""
        date = trace.started_at or datetime.now()
        dir_path = self.base_path / str(date.year) / f"{date.month:02d}" / f"{date.day:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / f"trace_{trace.trace_id}.json"
    
    async def save_trace(self, trace: ExecutionTrace):
        """保存追踪"""
        # 保存追踪文件
        trace_path = self._get_trace_path(trace)
        trace_data = trace.model_dump()
        
        # 转换 datetime 为字符串
        trace_data = self._serialize_dates(trace_data)
        
        with open(trace_path, 'w', encoding='utf-8') as f:
            json.dump(trace_data, f, ensure_ascii=False, indent=2)
        
        # 更新索引
        index = self._load_index()
        index["traces"][trace.trace_id] = {
            "task_id": trace.task_id,
            "agent_id": trace.agent_id,
            "status": trace.status.value,
            "started_at": trace.started_at.isoformat() if trace.started_at else None,
            "path": str(trace_path.relative_to(self.base_path))
        }
        index["updated_at"] = datetime.now().isoformat()
        self._save_index(index)
        
        # 更新任务索引
        await self._update_task_index(trace)
    
    async def _update_task_index(self, trace: ExecutionTrace):
        """更新任务索引"""
        task_dir = self.base_path / "by_task" / trace.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        
        task_index_path = task_dir / "traces.json"
        
        if task_index_path.exists():
            with open(task_index_path, 'r', encoding='utf-8') as f:
                task_index = json.load(f)
        else:
            task_index = {"task_id": trace.task_id, "traces": []}
        
        # 添加或更新追踪
        trace_entry = {
            "trace_id": trace.trace_id,
            "agent_id": trace.agent_id,
            "status": trace.status.value,
            "started_at": trace.started_at.isoformat() if trace.started_at else None,
            "completed_at": trace.completed_at.isoformat() if trace.completed_at else None
        }
        
        # 检查是否已存在
        existing = [t for t in task_index["traces"] if t["trace_id"] == trace.trace_id]
        if existing:
            task_index["traces"].remove(existing[0])
        task_index["traces"].append(trace_entry)
        
        with open(task_index_path, 'w', encoding='utf-8') as f:
            json.dump(task_index, f, ensure_ascii=False, indent=2)
    
    async def get_trace(self, trace_id: str) -> Optional[ExecutionTrace]:
        """获取追踪"""
        index = self._load_index()
        
        if trace_id not in index["traces"]:
            return None
        
        trace_info = index["traces"][trace_id]
        trace_path = self.base_path / trace_info["path"]
        
        if not trace_path.exists():
            return None
        
        with open(trace_path, 'r', encoding='utf-8') as f:
            trace_data = json.load(f)
        
        return ExecutionTrace(**self._deserialize_dates(trace_data))
    
    async def list_traces(
        self,
        task_id: str = None,
        agent_id: str = None,
        status: ExecutionStatus = None,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ExecutionTrace]:
        """列出追踪"""
        index = self._load_index()
        
        # 过滤
        filtered = []
        for trace_id, info in index["traces"].items():
            if task_id and info.get("task_id") != task_id:
                continue
            if agent_id and info.get("agent_id") != agent_id:
                continue
            if status and info.get("status") != status.value:
                continue
            if start_time and info.get("started_at"):
                trace_time = datetime.fromisoformat(info["started_at"])
                if trace_time < start_time:
                    continue
            if end_time and info.get("started_at"):
                trace_time = datetime.fromisoformat(info["started_at"])
                if trace_time > end_time:
                    continue
            
            filtered.append(trace_id)
        
        # 排序（按时间倒序）
        filtered.sort(key=lambda x: index["traces"][x].get("started_at", ""), reverse=True)
        
        # 分页
        paginated = filtered[offset:offset + limit]
        
        # 加载完整追踪
        traces = []
        for trace_id in paginated:
            trace = await self.get_trace(trace_id)
            if trace:
                traces.append(trace)
        
        return traces
    
    async def delete_trace(self, trace_id: str):
        """删除追踪"""
        index = self._load_index()
        
        if trace_id not in index["traces"]:
            return
        
        trace_info = index["traces"][trace_id]
        trace_path = self.base_path / trace_info["path"]
        
        # 删除文件
        if trace_path.exists():
            trace_path.unlink()
        
        # 更新索引
        del index["traces"][trace_id]
        index["updated_at"] = datetime.now().isoformat()
        self._save_index(index)
    
    def _serialize_dates(self, data: Any) -> Any:
        """序列化日期"""
        if isinstance(data, datetime):
            return data.isoformat()
        elif isinstance(data, dict):
            return {k: self._serialize_dates(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._serialize_dates(v) for v in data]
        return data
    
    def _deserialize_dates(self, data: Any) -> Any:
        """反序列化日期"""
        if isinstance(data, str):
            try:
                return datetime.fromisoformat(data)
            except ValueError:
                return data
        elif isinstance(data, dict):
            return {k: self._deserialize_dates(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._deserialize_dates(v) for v in data]
        return data


class DatabaseTraceStorage(TraceStorage):
    """
    数据库追踪存储（PostgreSQL / SQLite）
    
    表结构：
    - execution_traces: 追踪主表
    - trace_spans: 跨度表
    - trace_llm_calls: LLM 调用表
    - trace_tool_calls: 工具调用表
    - trace_checkpoints: 检查点表
    - trace_verifications: 验证记录表
    """
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        # TODO: 实现数据库存储
        pass
    
    async def save_trace(self, trace: ExecutionTrace):
        """保存追踪到数据库"""
        # TODO: 实现
        pass
    
    async def get_trace(self, trace_id: str) -> Optional[ExecutionTrace]:
        """从数据库获取追踪"""
        # TODO: 实现
        pass
    
    async def list_traces(self, **kwargs) -> List[ExecutionTrace]:
        """从数据库列出追踪"""
        # TODO: 实现
        pass
    
    async def delete_trace(self, trace_id: str):
        """从数据库删除追踪"""
        # TODO: 实现
        pass
```

---

## 5. 与 LangGraph 集成

### 5.1 检查点存储架构

LangGraph 检查点存储已重构到 `storage/checkpointers/` 模块，提供统一的检查点管理：

```
storage/checkpointers/
├── __init__.py          # 导出接口
├── base.py              # BaseCheckpointSaver 基类
├── memory_saver.py      # 内存检查点（开发/测试）
├── redis_saver.py       # Redis 检查点（分布式）
├── postgres_saver.py    # PostgreSQL 检查点（持久化）
├── file_saver.py        # 文件系统检查点（本地）
└── factory.py           # 检查点工厂
```

### 5.2 检查点存储类型选择

| 类型 | 适用场景 | 特点 |
|------|----------|------|
| **Memory** | 单实例、开发测试 | 简单快速、不持久化 |
| **Redis** | 分布式、多实例共享 | 快速读写、可设置 TTL |
| **PostgreSQL** | 长期持久化、审计 | 持久化、可查询、合规 |
| **File** | 本地开发、调试 | 简单、可直接查看 |

### 5.3 检查点工厂

```python
# storage/checkpointers/factory.py

from storage.config import CheckpointerType, CheckpointStorageConfig
from storage.redis_client import RedisClient
from storage.database import AsyncDatabaseManager

class CheckpointerFactory:
    @staticmethod
    def create(
        config: CheckpointStorageConfig,
        redis_client: Optional[RedisClient] = None,
        db_manager: Optional[AsyncDatabaseManager] = None,
    ) -> BaseCheckpointSaver:
        """
        根据配置创建检查点存储
        
        Args:
            config: 检查点存储配置
            redis_client: Redis 客户端（Redis 类型必需）
            db_manager: 数据库管理器（PostgreSQL 类型必需）
        
        Returns:
            检查点存储实例
        """
        if config.type == CheckpointerType.MEMORY:
            return CheckpointerFactory._create_memory()
        
        elif config.type == CheckpointerType.REDIS:
            if redis_client is None:
                raise ValueError("RedisClient must be provided for Redis checkpointer.")
            return RedisCheckpointSaver(
                redis_client=redis_client,
                prefix=config.redis_prefix,
                ttl=config.redis_ttl,
            )
        
        elif config.type == CheckpointerType.POSTGRESQL:
            if db_manager is None:
                raise ValueError("AsyncDatabaseManager must be provided for PostgreSQL checkpointer.")
            return PostgresCheckpointSaver(
                db_manager=db_manager,
                table_name=config.postgres_table,
            )
        
        elif config.type == CheckpointerType.FILE:
            return FileCheckpointSaver(path=config.file_path)
        
        else:
            raise ValueError(f"不支持的检查点存储类型: {config.type}")
    
    @staticmethod
    def from_env(
        redis_client: Optional[RedisClient] = None,
        db_manager: Optional[AsyncDatabaseManager] = None,
    ) -> BaseCheckpointSaver:
        """从环境变量创建检查点存储"""
        from storage.config import StorageConfig
        config = StorageConfig.from_env().checkpoint
        return CheckpointerFactory.create(config, redis_client, db_manager)
```

### 5.4 Redis 检查点存储（使用统一 RedisClient）

```python
# storage/checkpointers/redis_saver.py

class RedisCheckpointSaver(BaseCheckpointSaver):
    """
    Redis 检查点存储
    
    使用注入的 RedisClient，支持同步和异步操作。
    LangGraph 需要同步接口，因此使用 RedisClient.sync_client。
    """
    
    def __init__(
        self,
        redis_client: RedisClient,  # 注入统一的 Redis 客户端
        prefix: str = "langgraph:checkpoint:",
        ttl: Optional[int] = None,
    ):
        self._client = redis_client
        self.prefix = prefix
        self.ttl = ttl
    
    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        checkpoint_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        
        # 使用同步客户端（LangGraph 要求同步接口）
        sync_client = self._client.sync_client
        pipe = sync_client.pipeline()
        # ... 保存逻辑 ...
        pipe.execute()
        
        return new_config
```

### 5.5 PostgreSQL 检查点存储（使用统一 AsyncDatabaseManager）

```python
# storage/checkpointers/postgres_saver.py

class PostgresCheckpointSaver(BaseCheckpointSaver):
    """
    PostgreSQL 检查点存储
    
    使用注入的 AsyncDatabaseManager，支持原生 asyncpg 查询。
    """
    
    def __init__(
        self,
        db_manager: AsyncDatabaseManager,  # 注入统一的数据库管理器
        table_name: str = "langgraph_checkpoints",
    ):
        self.db_manager = db_manager
        self.table_name = table_name
    
    async def setup(self):
        """创建检查点表"""
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            thread_id VARCHAR(256) NOT NULL,
            checkpoint_id VARCHAR(64) NOT NULL,
            checkpoint_data JSONB NOT NULL,
            metadata JSONB DEFAULT '{{}}',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            UNIQUE(thread_id, checkpoint_id)
        );
        """
        await self.db_manager.execute_raw(create_table_sql)
```

### 5.6 带追踪的检查点存储

```python
# persistence/langgraph_integration.py

class TracingCheckpointSaver(BaseCheckpointSaver):
    """
    带追踪功能的 LangGraph 检查点存储
    
    将 LangGraph 的检查点与追踪系统集成
    """
    
    def __init__(
        self,
        collector: TraceCollector,
        base_saver: BaseCheckpointSaver = None
    ):
        self.collector = collector
        self.base_saver = base_saver or MemorySaver()
    
    async def aput(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Dict[str, Any] = None
    ):
        """保存检查点并记录到追踪系统"""
        result = await self.base_saver.aput(config, checkpoint, metadata)
        
        # 记录到追踪系统
        thread_id = config.get("configurable", {}).get("thread_id", "")
        self.collector.save_checkpoint(
            iteration=metadata.get("step", 0) if metadata else 0,
            phase=metadata.get("phase", "unknown") if metadata else "unknown",
            agent_state=checkpoint.get("channel_values", {}),
            workflow_state=checkpoint.get("channel_versions", {}),
            langgraph_checkpoint=thread_id
        )
        
        return result
```

### 5.7 在 BaseAgent 中使用检查点

```python
# core/base_agent.py

from storage.checkpointers import CheckpointerFactory
from storage.config import CheckpointStorageConfig

class BaseAgent:
    def __init__(
        self,
        definition: AgentDefinition,
        workspace: AgentWorkspace,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        checkpointer_config: Optional[CheckpointStorageConfig] = None,
        # ...
    ):
        # 编译图时使用检查点
        self.graph = self.graph_builder.compile(
            checkpointer=checkpointer,
            checkpointer_config=checkpointer_config,
        )
    
    @classmethod
    def from_env(cls, ...) -> "BaseAgent":
        """从环境变量创建 Agent，自动配置检查点存储"""
        checkpointer = CheckpointerFactory.from_env()
        return cls(..., checkpointer=checkpointer)
```

---

## 6. 使用示例

```python
# 示例：带追踪的 Agent 执行

from etf_common.agent_framework import (
    BaseAgent,
    AgentDefinition,
    AgentWorkspace,
    WorkspaceConfig
)
from etf_common.agent_framework.persistence import (
    TraceCollector,
    FileTraceStorage,
    trace_agent
)


# 1. 初始化存储和收集器
storage = FileTraceStorage("./traces")
collector = TraceCollector(storage)


# 2. 创建 Agent（使用装饰器自动追踪）
class TracedFinancialAgent(BaseAgent):
    
    @trace_agent(collector)
    async def run(self, **kwargs):
        return await super().run(**kwargs)
    
    async def _gather_context(self):
        # 使用 span 追踪具体操作
        with collector.span("search_financial_data", SpanType.TOOL_CALL):
            # 执行搜索
            result = await self.tool_registry.execute(
                "financial_data",
                {"company": "贵州茅台"}
            )
            
            # 自动记录工具调用
            collector.record_tool_call(
                tool_id="financial_data",
                tool_name="财务数据查询",
                tool_category="financial",
                input_params={"company": "贵州茅台"},
                output=result,
                success=True
            )
        
        self.state.gathered_context = str(result)


# 3. 执行并查看追踪
async def main():
    workspace = AgentWorkspace(WorkspaceConfig(
        base_path="./workspaces",
        task_id="analysis_001"
    ))
    
    agent = TracedFinancialAgent(
        definition=AgentDefinition(...),
        workspace=workspace,
        # ...
    )
    
    result = await agent.run(
        task_description="分析贵州茅台",
        input_data={"company": "贵州茅台"}
    )
    
    # 查看追踪
    traces = await storage.list_traces(task_id="analysis_001")
    for trace in traces:
        print(f"Trace: {trace.trace_id}")
        print(f"  Status: {trace.status}")
        print(f"  Duration: {trace.duration_ms}ms")
        print(f"  LLM Calls: {len(trace.llm_calls)}")
        print(f"  Tool Calls: {len(trace.tool_calls)}")
        print(f"  Total Cost: ${trace.summary.get('total_cost_usd', 0):.4f}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## 7. 目录结构

```
src/
├── observability/                   # 运行时采集层
│   ├── __init__.py
│   ├── tracing.py                   # Span 采集、上下文传播
│   ├── metrics.py                   # 指标采集
│   └── exporters.py                 # 导出器（连接到 persistence）
│
├── persistence/                     # 存储 API 层
│   ├── __init__.py
│   ├── models.py                    # 持久化数据模型
│   ├── trace_collector.py           # 追踪收集器
│   ├── trace_storage.py             # 追踪存储接口 + 实现
│   └── langgraph_integration.py     # LangGraph 检查点追踪集成
│
└── storage/                         # 基础设施层
    ├── __init__.py
    ├── config.py                    # 统一配置管理
    ├── database.py                  # AsyncDatabaseManager
    ├── redis_client.py              # RedisClient (异步 + 同步)
    ├── oss_client.py                # OSS 客户端
    ├── checkpointers/               # LangGraph 检查点存储
    │   ├── __init__.py
    │   ├── base.py                  # 基类
    │   ├── memory_saver.py          # 内存检查点
    │   ├── redis_saver.py           # Redis 检查点
    │   ├── postgres_saver.py        # PostgreSQL 检查点
    │   ├── file_saver.py            # 文件系统检查点
    │   └── factory.py               # 检查点工厂
    ├── repositories/                # Repository 模式
    │   ├── __init__.py
    │   ├── base.py
    │   ├── agent_repository.py
    │   └── ...
    └── models/                      # ORM 模型
        ├── __init__.py
        └── db_models.py
```

---

## 8. 架构总结

### 8.1 三层职责划分

| 层级 | 模块 | 职责 | 关键组件 |
|------|------|------|----------|
| **运行时采集** | `observability/` | 实时数据采集、上下文传播 | `AgentTracer`, `Span`, `SpanExporter` |
| **存储 API** | `persistence/` | 存储抽象、数据模型 | `TraceStorage`, `TraceCollector`, `ExecutionTrace` |
| **基础设施** | `storage/` | 数据库/缓存/文件连接 | `AsyncDatabaseManager`, `RedisClient`, `CheckpointerFactory` |

### 8.2 设计原则

1. **依赖注入**：检查点存储器、数据库管理器通过注入而非内部创建，便于测试和配置
2. **统一客户端**：`RedisClient` 和 `AsyncDatabaseManager` 是唯一的客户端实现，避免重复
3. **模块化设计**：检查点存储位于 `storage/checkpointers/`，`core/` 模块重新导出以保持接口一致
4. **配置驱动**：通过 `StorageConfig` 和环境变量统一管理所有存储配置
5. **异步优先**：数据库操作使用异步，Redis 同时提供异步和同步接口（LangGraph 需要）

### 8.3 数据流示意

```
Agent 执行
    │
    ▼
AgentTracer.start_span()  ────────────────────────┐
    │                                              │
    │  运行时 Span                                 │
    │                                              ▼
    │                                    SpanExporter.export()
    │                                              │
    │                                              ▼
    │                            SpanRecord.from_observability_span()
    │                                              │
    │                                              ▼
    │                                    TraceStorage.save_span()
    │                                              │
    ▼                                              ▼
LangGraph 图执行                          PostgreSQL / File / OSS
    │
    ▼
CheckpointSaver.put()  ───────────────────┐
    │                                      │
    │  检查点数据                          ▼
    │                              Redis / PostgreSQL / File
    │
    ▼
Agent 输出
```


"""
持久化层

提供追踪数据的持久化存储能力。

包含：
- 数据模型 (SpanRecord, ExecutionTrace, etc.)
- 存储后端 (FileTraceStorage, DatabaseTraceStorage)
"""

from .models import (
    ExecutionStatus,
    SpanType,
    SpanRecord,
    LLMCallRecord,
    ToolCallRecord,
    ExecutionTrace,
    TraceFilters,
)
from .trace_storage import (
    TraceStorage,
    FileTraceStorage,
    DatabaseTraceStorage,
    TraceStorageFactory,
)

__all__ = [
    # 数据模型
    "ExecutionStatus",
    "SpanType",
    "SpanRecord",
    "LLMCallRecord",
    "ToolCallRecord",
    "ExecutionTrace",
    "TraceFilters",
    # 存储后端
    "TraceStorage",
    "FileTraceStorage",
    "DatabaseTraceStorage",
    "TraceStorageFactory",
]

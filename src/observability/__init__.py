"""
可观测性层

提供框架的可观测性能力，包括：
- 分布式追踪（Tracing）
- 指标收集（Metrics）
- 结构化日志（Logging）
"""

from .tracing import (
    AgentTracer,
    SpanContext,
    Span,
    SpanExporter,
    ConsoleSpanExporter,
    span,
    trace_agent_run,
    trace_tool_call,
    get_current_span,
    get_tracer,
    set_tracer,
    reset_tracer,
)
from .exporters import (
    DatabaseSpanExporter,
    FileSpanExporter,
    BatchSpanExporter,
    CompositeSpanExporter,
)
from .metrics import (
    MetricsCollector,
    Counter,
    Gauge,
    Histogram,
    MetricPoint,
    get_metrics_collector,
)
from .structured_logging import (
    StructuredLogger,
    LogContext,
    get_structured_logger,
)

__all__ = [
    # 追踪
    "AgentTracer",
    "SpanContext",
    "Span",
    "SpanExporter",
    "ConsoleSpanExporter",
    "span",
    "trace_agent_run",
    "trace_tool_call",
    "get_current_span",
    "get_tracer",
    "set_tracer",
    "reset_tracer",
    # 持久化导出器
    "DatabaseSpanExporter",
    "FileSpanExporter",
    "BatchSpanExporter",
    "CompositeSpanExporter",
    # 指标
    "MetricsCollector",
    "Counter",
    "Gauge",
    "Histogram",
    "MetricPoint",
    "get_metrics_collector",
    # 日志
    "StructuredLogger",
    "LogContext",
    "get_structured_logger",
]

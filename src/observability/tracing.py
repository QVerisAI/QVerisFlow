"""
分布式追踪

提供 Agent 执行的追踪能力，支持：
- Span 管理
- 上下文传播
- 与 OpenTelemetry 兼容
"""

from typing import Dict, Any, Optional, Callable, Generator
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager
from functools import wraps
import uuid
import threading

from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class SpanContext:
    """Span 上下文"""

    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    baggage: Dict[str, str] = field(default_factory=dict)


@dataclass
class Span:
    """追踪 Span"""

    name: str
    context: SpanContext
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "ok"  # ok, error
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: list = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return 0.0

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self.events.append(
            {
                "name": name,
                "timestamp": datetime.now().isoformat(),
                "attributes": attributes or {},
            }
        )

    def set_status(self, status: str, description: str = "") -> None:
        self.status = status
        if description:
            self.attributes["status_description"] = description

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.context.trace_id,
            "span_id": self.context.span_id,
            "parent_span_id": self.context.parent_span_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


class SpanExporter:
    """Span 导出器基类"""

    def export(self, spans: list) -> None:
        """导出 spans"""
        pass


class ConsoleSpanExporter(SpanExporter):
    """控制台导出器"""

    def export(self, spans: list) -> None:
        for span in spans:
            logger.info(
                f"[TRACE] {span.name} "
                f"trace_id={span.context.trace_id} "
                f"span_id={span.context.span_id} "
                f"duration={span.duration_ms:.2f}ms "
                f"status={span.status}"
            )


class AgentTracer:
    """
    Agent 追踪器

    提供分布式追踪能力，支持：
    - 自动 span 创建和结束
    - 上下文传播
    - 与 OpenTelemetry 兼容的 API
    """

    _default_tracer: Optional["AgentTracer"] = None
    _lock = threading.Lock()

    def __init__(self, service_name: str = "agent_framework"):
        self.service_name = service_name
        self._spans: Dict[str, Span] = {}
        self._exporters: list = [ConsoleSpanExporter()]
        self._local = threading.local()
        self._enabled = True  # 是否启用追踪

    @classmethod
    def get_default(cls, service_name: str = "agent_framework") -> "AgentTracer":
        """
        获取默认追踪器实例

        如果默认实例不存在，将创建一个新实例。

        Args:
            service_name: 服务名称（仅在创建新实例时使用）

        Returns:
            AgentTracer 实例
        """
        if cls._default_tracer is None:
            with cls._lock:
                if cls._default_tracer is None:
                    cls._default_tracer = cls(service_name)
        return cls._default_tracer

    @classmethod
    def set_default(cls, tracer: "AgentTracer") -> None:
        """
        设置默认追踪器实例

        用于测试或自定义追踪器配置。

        Args:
            tracer: 要设置为默认的追踪器实例
        """
        with cls._lock:
            cls._default_tracer = tracer

    @classmethod
    def reset_default(cls) -> None:
        """
        重置默认追踪器

        主要用于测试清理。
        """
        with cls._lock:
            cls._default_tracer = None

    # 保留旧的 get_instance 方法以保持兼容性
    @classmethod
    def get_instance(cls, service_name: str = "agent_framework") -> "AgentTracer":
        """获取实例（已废弃，请使用 get_default）"""
        return cls.get_default(service_name)

    def enable(self) -> None:
        """启用追踪"""
        self._enabled = True

    def disable(self) -> None:
        """禁用追踪"""
        self._enabled = False

    def add_exporter(self, exporter: SpanExporter) -> None:
        """添加导出器"""
        self._exporters.append(exporter)

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        parent: Optional[SpanContext] = None,
    ) -> Generator[Span, None, None]:
        """
        开始一个新的 span

        Args:
            name: span 名称
            attributes: 属性
            parent: 父 span 上下文

        Yields:
            Span 对象
        """
        # 如果追踪被禁用，返回一个空操作的 span
        if not self._enabled:
            # 创建一个 no-op span
            noop_span = Span(
                name=name,
                context=SpanContext(trace_id="noop", span_id="noop"),
                start_time=datetime.now(),
                attributes=attributes or {},
            )
            yield noop_span
            return

        # 获取或创建 trace_id
        current_span = getattr(self._local, "current_span", None)

        if parent:
            trace_id = parent.trace_id
            parent_span_id = parent.span_id
        elif current_span:
            trace_id = current_span.context.trace_id
            parent_span_id = current_span.context.span_id
        else:
            trace_id = uuid.uuid4().hex
            parent_span_id = None

        # 创建 span
        context = SpanContext(
            trace_id=trace_id,
            span_id=uuid.uuid4().hex[:16],
            parent_span_id=parent_span_id,
        )

        span = Span(
            name=name,
            context=context,
            start_time=datetime.now(),
            attributes=attributes or {},
        )

        # 设置 service name
        span.set_attribute("service.name", self.service_name)

        # 设置为当前 span
        old_span = getattr(self._local, "current_span", None)
        self._local.current_span = span
        self._spans[span.context.span_id] = span

        try:
            yield span
            if span.status == "ok":
                span.set_status("ok")
        except Exception as e:
            span.set_status("error", str(e))
            span.add_event("exception", {"message": str(e)})
            raise
        finally:
            span.end_time = datetime.now()
            self._local.current_span = old_span

            # 导出 span
            self._export_span(span)

    def _export_span(self, span: Span) -> None:
        """导出 span"""
        for exporter in self._exporters:
            try:
                exporter.export([span])
            except Exception as e:
                logger.warning(f"导出 span 失败: {e}")

    def get_current_span(self) -> Optional[Span]:
        """获取当前 span"""
        return getattr(self._local, "current_span", None)

    def inject_context(self, carrier: Dict[str, str]) -> None:
        """注入追踪上下文到载体"""
        current = self.get_current_span()
        if current:
            carrier["traceparent"] = (
                f"00-{current.context.trace_id}-" f"{current.context.span_id}-01"
            )

    def extract_context(self, carrier: Dict[str, str]) -> Optional[SpanContext]:
        """从载体提取追踪上下文"""
        traceparent = carrier.get("traceparent")
        if not traceparent:
            return None

        parts = traceparent.split("-")
        if len(parts) >= 3:
            return SpanContext(
                trace_id=parts[1],
                span_id=parts[2],
            )
        return None


# 全局追踪器（已废弃，请直接使用 AgentTracer.get_default()）
_tracer: Optional[AgentTracer] = None


def get_tracer(service_name: str = "agent_framework") -> AgentTracer:
    """
    获取全局追踪器

    这是一个便捷函数，等价于 AgentTracer.get_default(service_name)。

    Args:
        service_name: 服务名称

    Returns:
        AgentTracer 实例
    """
    return AgentTracer.get_default(service_name)


def set_tracer(tracer: AgentTracer) -> None:
    """
    设置全局追踪器

    Args:
        tracer: 要设置的追踪器实例
    """
    AgentTracer.set_default(tracer)


def reset_tracer() -> None:
    """重置全局追踪器"""
    AgentTracer.reset_default()


def get_current_span() -> Optional[Span]:
    """获取当前 span"""
    return get_tracer().get_current_span()


# 装饰器
def span(
    name: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
):
    """
    Span 装饰器

    用法:
    ```python
    @span("my_operation")
    async def my_function():
        ...
    ```
    """

    def decorator(func: Callable):
        span_name = name or func.__name__

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_span(span_name, attributes=attributes) as s:
                s.set_attribute("function", func.__name__)
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_span(span_name, attributes=attributes) as s:
                s.set_attribute("function", func.__name__)
                return func(*args, **kwargs)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_agent_run(agent_id: str, task_id: str):
    """
    Agent 运行追踪装饰器

    用法:
    ```python
    @trace_agent_run("my_agent", "task_123")
    async def run_agent():
        ...
    ```
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_span(
                "agent_run",
                attributes={
                    "agent.id": agent_id,
                    "task.id": task_id,
                },
            ) as s:
                result = await func(*args, **kwargs)
                if isinstance(result, dict):
                    s.set_attribute("result.success", result.get("success", False))
                return result

        return wrapper

    return decorator


def trace_tool_call(tool_id: str):
    """
    工具调用追踪装饰器
    """

    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_span("tool_call", attributes={"tool.id": tool_id}) as s:
                try:
                    result = await func(*args, **kwargs)
                    s.set_attribute("tool.success", True)
                    return result
                except Exception as e:
                    s.set_attribute("tool.success", False)
                    s.set_attribute("tool.error", str(e))
                    raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_span("tool_call", attributes={"tool.id": tool_id}) as s:
                try:
                    result = func(*args, **kwargs)
                    s.set_attribute("tool.success", True)
                    return result
                except Exception as e:
                    s.set_attribute("tool.success", False)
                    s.set_attribute("tool.error", str(e))
                    raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator

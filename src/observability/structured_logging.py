"""
结构化日志

提供框架的结构化日志能力，支持：
- JSON 格式输出
- 上下文自动注入
- 与追踪系统集成
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager
import json
import threading
import logging

from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class LogContext:
    """日志上下文"""

    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    workflow_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {}
        if self.trace_id:
            result["trace_id"] = self.trace_id
        if self.span_id:
            result["span_id"] = self.span_id
        if self.agent_id:
            result["agent_id"] = self.agent_id
        if self.task_id:
            result["task_id"] = self.task_id
        if self.workflow_id:
            result["workflow_id"] = self.workflow_id
        result.update(self.extra)
        return result

    def merge(self, other: "LogContext") -> "LogContext":
        """合并上下文"""
        return LogContext(
            trace_id=other.trace_id or self.trace_id,
            span_id=other.span_id or self.span_id,
            agent_id=other.agent_id or self.agent_id,
            task_id=other.task_id or self.task_id,
            workflow_id=other.workflow_id or self.workflow_id,
            extra={**self.extra, **other.extra},
        )


class StructuredLogger:
    """
    结构化日志记录器

    提供 JSON 格式的结构化日志，自动注入上下文信息
    """

    _context = threading.local()

    def __init__(
        self,
        name: str = "agent_framework",
        level: int = logging.INFO,
        output_json: bool = True,
    ):
        self.name = name
        self.level = level
        self.output_json = output_json
        self._handlers: List[logging.Handler] = []

    @property
    def context(self) -> LogContext:
        """获取当前上下文"""
        if not hasattr(self._context, "stack"):
            self._context.stack = [LogContext()]
        if not self._context.stack:
            self._context.stack = [LogContext()]
        return self._context.stack[-1]

    @contextmanager
    def with_context(self, context: LogContext):
        """
        设置日志上下文

        用法:
        ```python
        with logger.with_context(LogContext(agent_id="my_agent")):
            logger.info("Processing...")
        ```
        """
        if not hasattr(self._context, "stack"):
            self._context.stack = [LogContext()]

        merged = self.context.merge(context)
        self._context.stack.append(merged)

        try:
            yield
        finally:
            self._context.stack.pop()

    def _format_message(
        self,
        level: str,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """格式化日志消息"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "logger": self.name,
            "message": message,
        }

        # 添加上下文
        ctx = self.context.to_dict()
        if ctx:
            log_entry["context"] = ctx

        # 添加额外字段
        if extra:
            log_entry["extra"] = extra

        if self.output_json:
            return json.dumps(log_entry, ensure_ascii=False, default=str)
        else:
            ctx_str = " ".join(f"{k}={v}" for k, v in ctx.items()) if ctx else ""
            return f"[{level}] {message} {ctx_str}".strip()

    def debug(self, message: str, **kwargs) -> None:
        """记录 DEBUG 级别日志"""
        if self.level <= logging.DEBUG:
            formatted = self._format_message(
                "DEBUG", message, kwargs if kwargs else None
            )
            logger.debug(formatted)

    def info(self, message: str, **kwargs) -> None:
        """记录 INFO 级别日志"""
        if self.level <= logging.INFO:
            formatted = self._format_message(
                "INFO", message, kwargs if kwargs else None
            )
            logger.info(formatted)

    def warning(self, message: str, **kwargs) -> None:
        """记录 WARNING 级别日志"""
        if self.level <= logging.WARNING:
            formatted = self._format_message(
                "WARNING", message, kwargs if kwargs else None
            )
            logger.warning(formatted)

    def error(self, message: str, **kwargs) -> None:
        """记录 ERROR 级别日志"""
        if self.level <= logging.ERROR:
            formatted = self._format_message(
                "ERROR", message, kwargs if kwargs else None
            )
            logger.error(formatted)

    def critical(self, message: str, **kwargs) -> None:
        """记录 CRITICAL 级别日志"""
        formatted = self._format_message(
            "CRITICAL", message, kwargs if kwargs else None
        )
        logger.critical(formatted)

    def exception(self, message: str, exc_info: bool = True, **kwargs) -> None:
        """记录异常日志"""
        formatted = self._format_message("ERROR", message, kwargs if kwargs else None)
        logger.exception(formatted, exc_info=exc_info)

    # 便捷方法
    def agent_start(self, agent_id: str, task_id: str, **kwargs) -> None:
        """记录 Agent 启动"""
        self.info(
            f"Agent 开始执行",
            event="agent_start",
            agent_id=agent_id,
            task_id=task_id,
            **kwargs,
        )

    def agent_complete(
        self,
        agent_id: str,
        task_id: str,
        success: bool,
        duration_ms: float,
        **kwargs,
    ) -> None:
        """记录 Agent 完成"""
        self.info(
            f"Agent 执行完成: {'成功' if success else '失败'}",
            event="agent_complete",
            agent_id=agent_id,
            task_id=task_id,
            success=success,
            duration_ms=duration_ms,
            **kwargs,
        )

    def tool_call(
        self,
        tool_id: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> None:
        """记录工具调用"""
        self.debug(
            f"调用工具: {tool_id}",
            event="tool_call",
            tool_id=tool_id,
            params=params,
            **kwargs,
        )

    def tool_result(
        self,
        tool_id: str,
        success: bool,
        duration_ms: float,
        **kwargs,
    ) -> None:
        """记录工具结果"""
        level = "debug" if success else "warning"
        getattr(self, level)(
            f"工具执行{'成功' if success else '失败'}: {tool_id}",
            event="tool_result",
            tool_id=tool_id,
            success=success,
            duration_ms=duration_ms,
            **kwargs,
        )

    def llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
        **kwargs,
    ) -> None:
        """记录 LLM 调用"""
        self.debug(
            f"LLM 调用: {model}",
            event="llm_call",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            **kwargs,
        )


# 全局日志记录器
_structured_logger: Optional[StructuredLogger] = None


def get_structured_logger(
    name: str = "agent_framework",
    output_json: bool = True,
) -> StructuredLogger:
    """获取结构化日志记录器"""
    global _structured_logger
    if _structured_logger is None:
        _structured_logger = StructuredLogger(name=name, output_json=output_json)
    return _structured_logger

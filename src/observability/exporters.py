"""
Span 导出器

提供将追踪数据导出到不同存储后端的实现。
"""

import asyncio
from typing import List, Optional, TYPE_CHECKING

from .tracing import Span, SpanExporter
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from ..persistence.trace_storage import TraceStorage

logger = get_logger(__name__)


class DatabaseSpanExporter(SpanExporter):
    """
    数据库 Span 导出器

    将 Span 导出到数据库（通过 TraceStorage）。

    用法:
        ```python
        from observability.exporters import DatabaseSpanExporter
        from persistence.trace_storage import DatabaseTraceStorage
        from storage.database import AsyncDatabaseManager

        db = AsyncDatabaseManager(config)
        await db.connect()

        storage = DatabaseTraceStorage(db)
        exporter = DatabaseSpanExporter(storage)

        tracer = get_tracer()
        tracer.add_exporter(exporter)
        ```
    """

    def __init__(self, trace_storage: "TraceStorage"):
        """
        初始化数据库导出器

        Args:
            trace_storage: 追踪存储后端
        """
        self.trace_storage = trace_storage
        self._buffer: List[Span] = []
        self._buffer_size = 10
        self._flush_interval = 5.0  # 秒
        self._flush_task: Optional[asyncio.Task] = None

    def export(self, spans: List[Span]) -> None:
        """
        导出 Spans

        将 Span 添加到缓冲区，批量写入存储。
        """
        for span in spans:
            try:
                # 转换并添加到缓冲区
                self._buffer.append(span)

                # 达到缓冲区大小时刷新
                if len(self._buffer) >= self._buffer_size:
                    self._flush_buffer()

            except Exception as e:
                logger.warning(f"导出 Span 到数据库失败: {e}")

    def _flush_buffer(self) -> None:
        """刷新缓冲区"""
        if not self._buffer:
            return

        spans_to_flush = self._buffer.copy()
        self._buffer.clear()

        # 创建异步任务刷新
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_flush(spans_to_flush))
            else:
                loop.run_until_complete(self._async_flush(spans_to_flush))
        except RuntimeError:
            # 没有运行中的事件循环
            asyncio.run(self._async_flush(spans_to_flush))

    async def _async_flush(self, spans: List[Span]) -> None:
        """异步刷新 Spans 到存储"""
        from ..persistence.models import SpanRecord

        for span in spans:
            try:
                record = SpanRecord.from_observability_span(span)
                await self.trace_storage.save_span(record)
            except Exception as e:
                logger.warning(f"保存 Span 到数据库失败: {e}")

    def close(self) -> None:
        """关闭导出器，刷新剩余数据"""
        self._flush_buffer()


class FileSpanExporter(SpanExporter):
    """
    文件系统 Span 导出器

    将 Span 导出到文件系统（通过 TraceStorage）。

    用法:
        ```python
        from observability.exporters import FileSpanExporter
        from persistence.trace_storage import FileTraceStorage

        storage = FileTraceStorage("./traces")
        exporter = FileSpanExporter(storage)

        tracer = get_tracer()
        tracer.add_exporter(exporter)
        ```
    """

    def __init__(self, trace_storage: "TraceStorage"):
        """
        初始化文件导出器

        Args:
            trace_storage: 追踪存储后端
        """
        self.trace_storage = trace_storage

    def export(self, spans: List[Span]) -> None:
        """导出 Spans"""
        from ..persistence.models import SpanRecord

        for span in spans:
            try:
                record = SpanRecord.from_observability_span(span)

                # 创建异步任务保存
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.trace_storage.save_span(record))
                    else:
                        loop.run_until_complete(self.trace_storage.save_span(record))
                except RuntimeError:
                    asyncio.run(self.trace_storage.save_span(record))

            except Exception as e:
                logger.warning(f"导出 Span 到文件失败: {e}")


class BatchSpanExporter(SpanExporter):
    """
    批量 Span 导出器

    提供缓冲和批量导出能力。
    """

    def __init__(
        self,
        underlying_exporter: SpanExporter,
        batch_size: int = 100,
        flush_interval: float = 10.0,
    ):
        """
        初始化批量导出器

        Args:
            underlying_exporter: 底层导出器
            batch_size: 批量大小
            flush_interval: 刷新间隔（秒）
        """
        self.underlying = underlying_exporter
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._buffer: List[Span] = []

    def export(self, spans: List[Span]) -> None:
        """添加到缓冲区"""
        self._buffer.extend(spans)

        if len(self._buffer) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        """刷新缓冲区"""
        if self._buffer:
            self.underlying.export(self._buffer)
            self._buffer.clear()


class CompositeSpanExporter(SpanExporter):
    """
    组合 Span 导出器

    将 Spans 导出到多个目标。
    """

    def __init__(self, exporters: List[SpanExporter]):
        """
        初始化组合导出器

        Args:
            exporters: 导出器列表
        """
        self.exporters = exporters

    def export(self, spans: List[Span]) -> None:
        """导出到所有底层导出器"""
        for exporter in self.exporters:
            try:
                exporter.export(spans)
            except Exception as e:
                logger.warning(f"导出器 {type(exporter).__name__} 失败: {e}")


__all__ = [
    "DatabaseSpanExporter",
    "FileSpanExporter",
    "BatchSpanExporter",
    "CompositeSpanExporter",
]

"""
可观测性集成端到端测试

测试追踪、指标和日志的集成：
- Span 创建和导出
- 指标收集
- 追踪到存储管道
"""

import pytest
import time
from datetime import datetime
from pathlib import Path

from src.observability.metrics import (
    MetricsCollector,
    Counter,
    Gauge,
    Histogram,
    get_metrics_collector,
)
from src.persistence.models import (
    ExecutionTrace,
    SpanRecord,
    LLMCallRecord,
    ToolCallRecord,
    ExecutionStatus,
    TraceFilters,
)
from src.persistence.trace_storage import FileTraceStorage


class TestSpanCreation:
    """Span 创建测试"""

    def test_create_span_record(self):
        """测试创建 SpanRecord"""
        span = SpanRecord(
            span_id="span_123",
            trace_id="trace_456",
            parent_span_id=None,
            name="test_operation",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=100.5,
            status="ok",
            attributes={"key": "value"},
        )

        assert span.span_id == "span_123"
        assert span.trace_id == "trace_456"
        assert span.name == "test_operation"
        assert span.duration_ms == 100.5

    def test_span_to_dict(self):
        """测试 Span 转字典"""
        span = SpanRecord(
            span_id="span_1",
            trace_id="trace_1",
            parent_span_id="parent_1",
            name="operation",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=50.0,
            status="ok",
        )

        data = span.to_dict()

        assert data["span_id"] == "span_1"
        assert data["trace_id"] == "trace_1"
        assert data["parent_span_id"] == "parent_1"
        assert data["name"] == "operation"

    def test_span_from_dict(self):
        """测试从字典创建 Span"""
        data = {
            "span_id": "span_2",
            "trace_id": "trace_2",
            "parent_span_id": None,
            "name": "restored_operation",
            "start_time": datetime.now().isoformat(),
            "end_time": datetime.now().isoformat(),
            "duration_ms": 75.0,
            "status": "ok",
            "attributes": {"attr1": "value1"},
            "events": [],
        }

        span = SpanRecord.from_dict(data)

        assert span.span_id == "span_2"
        assert span.name == "restored_operation"
        assert span.attributes.get("attr1") == "value1"


class TestMetricsCollection:
    """指标收集测试"""

    @pytest.fixture
    def metrics_collector(self):
        """创建新的指标收集器"""
        return MetricsCollector()

    def test_counter_metrics(self, metrics_collector):
        """测试计数器指标"""
        # Create counter
        counter = metrics_collector.counter(
            "test_counter",
            description="Test counter",
            labels=["status"],
        )

        # Increment
        counter.inc(1.0, labels={"status": "success"})
        counter.inc(2.0, labels={"status": "success"})
        counter.inc(1.0, labels={"status": "error"})

        # Verify
        assert counter.get(labels={"status": "success"}) == 3.0
        assert counter.get(labels={"status": "error"}) == 1.0

    def test_gauge_metrics(self, metrics_collector):
        """测试仪表指标"""
        # Create gauge
        gauge = metrics_collector.gauge(
            "test_gauge",
            description="Test gauge",
        )

        # Set values
        gauge.set(100.0)
        assert gauge.get() == 100.0

        # Increment/decrement
        gauge.inc(10.0)
        assert gauge.get() == 110.0

        gauge.dec(5.0)
        assert gauge.get() == 105.0

    def test_histogram_metrics(self, metrics_collector):
        """测试直方图指标"""
        # Create histogram
        histogram = metrics_collector.histogram(
            "test_histogram",
            description="Test histogram",
            buckets=[0.1, 0.5, 1.0, 2.0],
        )

        # Observe values
        histogram.observe(0.05)
        histogram.observe(0.3)
        histogram.observe(0.8)
        histogram.observe(1.5)

        # Verify
        assert histogram.get_count() == 4
        assert histogram.get_sum() == pytest.approx(2.65, rel=0.01)
        assert histogram.get_average() == pytest.approx(0.6625, rel=0.01)

    def test_metrics_with_labels(self, metrics_collector):
        """测试带标签的指标"""
        counter = metrics_collector.counter(
            "labeled_counter",
            description="Counter with labels",
            labels=["agent_id", "status"],
        )

        # Increment with different label combinations
        counter.inc(1.0, labels={"agent_id": "agent_1", "status": "success"})
        counter.inc(2.0, labels={"agent_id": "agent_1", "status": "error"})
        counter.inc(3.0, labels={"agent_id": "agent_2", "status": "success"})

        # Verify each combination is tracked separately
        assert counter.get(labels={"agent_id": "agent_1", "status": "success"}) == 1.0
        assert counter.get(labels={"agent_id": "agent_1", "status": "error"}) == 2.0
        assert counter.get(labels={"agent_id": "agent_2", "status": "success"}) == 3.0

    def test_collect_all_metrics(self, metrics_collector):
        """测试收集所有指标"""
        # Create various metrics
        counter = metrics_collector.counter("collect_counter")
        gauge = metrics_collector.gauge("collect_gauge")
        histogram = metrics_collector.histogram("collect_histogram")

        counter.inc(5.0)
        gauge.set(50.0)
        histogram.observe(1.0)

        # Collect all
        all_metrics = metrics_collector.collect_all()

        assert "collect_counter" in all_metrics
        assert "collect_gauge" in all_metrics
        assert "collect_histogram" in all_metrics


class TestTraceToStoragePipeline:
    """追踪到存储管道测试"""

    @pytest.fixture
    def trace_storage(self, tmp_path):
        """创建临时追踪存储"""
        return FileTraceStorage(str(tmp_path / "traces"))

    @pytest.mark.asyncio
    async def test_span_export_to_storage(self, trace_storage):
        """测试 Span 导出到存储"""
        trace = ExecutionTrace(
            trace_id="e2e_span_export",
            task_id="export_task",
            agent_id="export_agent",
        )
        trace.start()

        # Create spans
        spans = [
            SpanRecord(
                span_id=f"span_{i}",
                trace_id="e2e_span_export",
                parent_span_id=None if i == 0 else "span_0",
                name=f"operation_{i}",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration_ms=float(10 * (i + 1)),
                status="ok",
            )
            for i in range(3)
        ]

        for span in spans:
            trace.spans.append(span)

        trace.complete()
        await trace_storage.save_trace(trace)

        # Verify
        retrieved = await trace_storage.get_trace("e2e_span_export")
        assert retrieved is not None
        assert len(retrieved.spans) == 3

    @pytest.mark.asyncio
    async def test_complete_trace_pipeline(self, trace_storage):
        """测试完整追踪管道"""
        # Create trace
        trace = ExecutionTrace(
            trace_id="e2e_complete_pipeline",
            task_id="pipeline_task",
            agent_id="pipeline_agent",
        )
        trace.start()

        # Add spans
        main_span = SpanRecord(
            span_id="main_span",
            trace_id="e2e_complete_pipeline",
            parent_span_id=None,
            name="main_operation",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=1000.0,
            status="ok",
            attributes={"phase": "main"},
        )
        trace.spans.append(main_span)

        # Add LLM call
        llm_call = LLMCallRecord(
            call_id="llm_1",
            trace_id="e2e_complete_pipeline",
            provider="openai",
            model="gpt-4",
            prompt_tokens=50,
            completion_tokens=25,
        )
        trace.llm_calls.append(llm_call)

        # Add tool call
        tool_call = ToolCallRecord(
            call_id="tool_1",
            trace_id="e2e_complete_pipeline",
            tool_id="search_tool",
            tool_name="search",
        )
        trace.tool_calls.append(tool_call)

        # Complete and save
        trace.complete(output={"result": "success"})
        await trace_storage.save_trace(trace)

        # Verify pipeline
        retrieved = await trace_storage.get_trace("e2e_complete_pipeline")
        assert retrieved is not None
        assert retrieved.status == ExecutionStatus.COMPLETED
        assert len(retrieved.spans) == 1
        assert retrieved.summary["total_llm_calls"] == 1
        assert retrieved.summary["total_tool_calls"] == 1


class TestDistributedTracingContext:
    """分布式追踪上下文测试"""

    def test_parent_trace_linking(self):
        """测试父追踪链接"""
        # Parent trace
        parent_trace = ExecutionTrace(
            trace_id="parent_trace",
            task_id="main_task",
            agent_id="main_agent",
        )

        # Child trace linked to parent
        child_trace = ExecutionTrace(
            trace_id="child_trace",
            task_id="sub_task",
            agent_id="sub_agent",
            parent_trace_id="parent_trace",
        )

        assert child_trace.parent_trace_id == "parent_trace"

    def test_span_parent_linking(self):
        """测试 Span 父链接"""
        parent_span = SpanRecord(
            span_id="parent_span",
            trace_id="trace_1",
            parent_span_id=None,
            name="parent_operation",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=100.0,
            status="ok",
        )

        child_span = SpanRecord(
            span_id="child_span",
            trace_id="trace_1",
            parent_span_id="parent_span",
            name="child_operation",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=50.0,
            status="ok",
        )

        assert child_span.parent_span_id == parent_span.span_id


class TestErrorSpanRecording:
    """错误 Span 记录测试"""

    @pytest.fixture
    def trace_storage(self, tmp_path):
        """创建临时追踪存储"""
        return FileTraceStorage(str(tmp_path / "traces"))

    @pytest.mark.asyncio
    async def test_error_span_attributes(self, trace_storage):
        """测试错误 Span 属性"""
        trace = ExecutionTrace(
            trace_id="e2e_error_span",
            task_id="error_task",
            agent_id="error_agent",
        )
        trace.start()

        # Add error span
        error_span = SpanRecord(
            span_id="error_span",
            trace_id="e2e_error_span",
            parent_span_id=None,
            name="failed_operation",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=50.0,
            status="error",
            attributes={
                "error.type": "ValueError",
                "error.message": "Invalid input",
                "error.stack": "Traceback...",
            },
        )
        trace.spans.append(error_span)
        trace.fail("ValueError: Invalid input")

        await trace_storage.save_trace(trace)

        # Verify
        retrieved = await trace_storage.get_trace("e2e_error_span")
        assert retrieved is not None
        assert retrieved.status == ExecutionStatus.FAILED
        assert len(retrieved.spans) == 1
        assert retrieved.spans[0].status == "error"

    @pytest.mark.asyncio
    async def test_partial_failure_tracing(self, trace_storage):
        """测试部分失败追踪"""
        trace = ExecutionTrace(
            trace_id="e2e_partial_fail",
            task_id="partial_task",
            agent_id="partial_agent",
        )
        trace.start()

        # Add successful span
        success_span = SpanRecord(
            span_id="success_span",
            trace_id="e2e_partial_fail",
            parent_span_id=None,
            name="successful_step",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=100.0,
            status="ok",
        )
        trace.spans.append(success_span)

        # Add failed span
        fail_span = SpanRecord(
            span_id="fail_span",
            trace_id="e2e_partial_fail",
            parent_span_id=None,
            name="failed_step",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=50.0,
            status="error",
            attributes={"error.message": "Step failed"},
        )
        trace.spans.append(fail_span)

        trace.fail("Partial failure")
        await trace_storage.save_trace(trace)

        # Verify
        retrieved = await trace_storage.get_trace("e2e_partial_fail")
        assert retrieved is not None
        assert len(retrieved.spans) == 2

        # Find the statuses
        statuses = [s.status for s in retrieved.spans]
        assert "ok" in statuses
        assert "error" in statuses


class TestGlobalMetricsCollector:
    """全局指标收集器测试"""

    def test_get_global_collector(self):
        """测试获取全局收集器"""
        collector = get_metrics_collector()
        assert collector is not None

        # Should return same instance
        collector2 = get_metrics_collector()
        assert collector is collector2

    def test_predefined_metrics_exist(self):
        """测试预定义指标存在"""
        collector = get_metrics_collector()

        # Check for predefined metric names
        metrics = collector.list_metrics()

        # These should be created by _setup_default_metrics
        assert "agent_runs_total" in metrics
        assert "tool_calls_total" in metrics
        assert "llm_tokens_total" in metrics

    def test_use_predefined_metrics(self):
        """测试使用预定义指标"""
        collector = get_metrics_collector()

        # Use the predefined agent runs counter
        counter = collector.counter("agent_runs_total")
        counter.inc(1.0, labels={"agent_id": "test_agent", "status": "success"})

        value = counter.get(labels={"agent_id": "test_agent", "status": "success"})
        assert value >= 1.0  # May have been incremented in other tests

"""
持久化数据模型测试

测试 SpanRecord, LLMCallRecord, ToolCallRecord, ExecutionTrace 等数据模型。
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from src.persistence.models import (
    ExecutionStatus,
    SpanType,
    SpanRecord,
    LLMCallRecord,
    ToolCallRecord,
    ExecutionTrace,
    TraceFilters,
)


class TestExecutionStatus:
    """ExecutionStatus 枚举测试"""

    def test_enum_values(self):
        """测试枚举值"""
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.RUNNING.value == "running"
        assert ExecutionStatus.COMPLETED.value == "completed"
        assert ExecutionStatus.FAILED.value == "failed"
        assert ExecutionStatus.CANCELLED.value == "cancelled"


class TestSpanType:
    """SpanType 枚举测试"""

    def test_enum_values(self):
        """测试枚举值"""
        assert SpanType.AGENT.value == "agent"
        assert SpanType.PHASE.value == "phase"
        assert SpanType.LLM_CALL.value == "llm_call"
        assert SpanType.TOOL_CALL.value == "tool_call"
        assert SpanType.CUSTOM.value == "custom"


class TestSpanRecord:
    """SpanRecord 测试"""

    @pytest.fixture
    def span_record(self):
        """创建测试 SpanRecord"""
        return SpanRecord(
            span_id="span_123",
            trace_id="trace_456",
            parent_span_id="span_000",
            name="test_operation",
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(seconds=2),
            duration_ms=2000.0,
            status="ok",
            attributes={"key": "value"},
            events=[{"name": "event1", "timestamp": datetime.now().isoformat()}],
        )

    def test_create_span_record(self, span_record):
        """测试创建 SpanRecord"""
        assert span_record.span_id == "span_123"
        assert span_record.trace_id == "trace_456"
        assert span_record.name == "test_operation"
        assert span_record.duration_ms == 2000.0

    def test_to_dict(self, span_record):
        """测试序列化"""
        d = span_record.to_dict()

        assert d["span_id"] == "span_123"
        assert d["trace_id"] == "trace_456"
        assert d["parent_span_id"] == "span_000"
        assert d["name"] == "test_operation"
        assert d["duration_ms"] == 2000.0
        assert d["status"] == "ok"
        assert "key" in d["attributes"]

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "span_id": "span_abc",
            "trace_id": "trace_xyz",
            "parent_span_id": None,
            "name": "from_dict_operation",
            "start_time": datetime.now().isoformat(),
            "end_time": datetime.now().isoformat(),
            "duration_ms": 500,
            "status": "error",
            "attributes": {"error": "timeout"},
            "events": [],
        }

        span = SpanRecord.from_dict(data)

        assert span.span_id == "span_abc"
        assert span.name == "from_dict_operation"
        assert span.status == "error"

    def test_from_observability_span(self):
        """测试从 observability Span 转换"""
        # 创建模拟的 observability Span
        mock_span = MagicMock()
        mock_span.context.span_id = "obs_span_1"
        mock_span.context.trace_id = "obs_trace_1"
        mock_span.context.parent_span_id = None
        mock_span.name = "obs_operation"
        mock_span.start_time = datetime.now()
        mock_span.end_time = datetime.now()
        mock_span.duration_ms = 100.0
        mock_span.status = "ok"
        mock_span.attributes = {"service": "test"}
        mock_span.events = []

        span_record = SpanRecord.from_observability_span(mock_span)

        assert span_record.span_id == "obs_span_1"
        assert span_record.trace_id == "obs_trace_1"
        assert span_record.name == "obs_operation"

    def test_to_dict_with_none_times(self):
        """测试带 None 时间的序列化"""
        span = SpanRecord(
            span_id="span_1",
            trace_id="trace_1",
            parent_span_id=None,
            name="incomplete",
            start_time=None,
            end_time=None,
            duration_ms=0,
            status="running",
        )

        d = span.to_dict()

        assert d["start_time"] is None
        assert d["end_time"] is None


class TestLLMCallRecord:
    """LLMCallRecord 测试"""

    def test_create_record(self):
        """测试创建 LLM 调用记录"""
        record = LLMCallRecord(
            span_id="span_1",
            trace_id="trace_1",
            provider="openai",
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello"}],
            response="Hi there!",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            cost_usd=0.001,
            latency_ms=500,
        )

        assert record.provider == "openai"
        assert record.model == "gpt-4"
        assert record.total_tokens == 15
        assert record.success is True

    def test_default_values(self):
        """测试默认值"""
        record = LLMCallRecord()

        assert record.call_id is not None
        assert record.temperature == 0.7
        assert record.success is True
        assert record.cache_hit is False

    def test_to_dict(self):
        """测试序列化"""
        record = LLMCallRecord(
            span_id="span_1",
            trace_id="trace_1",
            provider="anthropic",
            model="claude-3",
            messages=[],
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )

        d = record.to_dict()

        assert d["provider"] == "anthropic"
        assert d["model"] == "claude-3"
        assert d["prompt_tokens"] == 100
        assert "timestamp" in d

    def test_failed_call(self):
        """测试失败的调用记录"""
        record = LLMCallRecord(
            span_id="span_1",
            trace_id="trace_1",
            provider="openai",
            model="gpt-4",
            messages=[],
            success=False,
            error="Rate limit exceeded",
        )

        assert record.success is False
        assert record.error == "Rate limit exceeded"


class TestToolCallRecord:
    """ToolCallRecord 测试"""

    def test_create_record(self):
        """测试创建工具调用记录"""
        record = ToolCallRecord(
            span_id="span_1",
            trace_id="trace_1",
            tool_id="search_tool",
            tool_name="Web Search",
            tool_category="search",
            input_params={"query": "python"},
            output={"results": [1, 2, 3]},
            latency_ms=200,
        )

        assert record.tool_id == "search_tool"
        assert record.tool_name == "Web Search"
        assert record.success is True

    def test_default_values(self):
        """测试默认值"""
        record = ToolCallRecord()

        assert record.call_id is not None
        assert record.success is True
        assert record.retry_count == 0
        assert record.output_truncated is False

    def test_to_dict(self):
        """测试序列化"""
        record = ToolCallRecord(
            span_id="span_1",
            trace_id="trace_1",
            tool_id="calc",
            tool_name="Calculator",
            tool_category="math",
            input_params={"a": 1, "b": 2},
            output=3,
            latency_ms=50,
        )

        d = record.to_dict()

        assert d["tool_id"] == "calc"
        assert d["input_params"] == {"a": 1, "b": 2}
        assert d["output"] == 3

    def test_failed_call(self):
        """测试失败的工具调用"""
        record = ToolCallRecord(
            span_id="span_1",
            trace_id="trace_1",
            tool_id="api_call",
            tool_name="API",
            tool_category="network",
            input_params={},
            success=False,
            error="Connection timeout",
            retry_count=3,
        )

        assert record.success is False
        assert record.error == "Connection timeout"
        assert record.retry_count == 3


class TestExecutionTrace:
    """ExecutionTrace 测试"""

    @pytest.fixture
    def trace(self):
        """创建测试追踪"""
        return ExecutionTrace(
            task_id="task_001",
            agent_id="test_agent",
            input_data={"query": "test"},
            task_description="Test task",
        )

    def test_create_trace(self, trace):
        """测试创建追踪"""
        assert trace.trace_id is not None
        assert trace.task_id == "task_001"
        assert trace.agent_id == "test_agent"
        assert trace.status == ExecutionStatus.PENDING

    def test_start(self, trace):
        """测试开始追踪"""
        trace.start()

        assert trace.status == ExecutionStatus.RUNNING
        assert trace.started_at is not None

    def test_complete(self, trace):
        """测试完成追踪"""
        trace.start()
        trace.complete(output={"result": "success"})

        assert trace.status == ExecutionStatus.COMPLETED
        assert trace.completed_at is not None
        assert trace.duration_ms is not None
        assert trace.output_data == {"result": "success"}

    def test_fail(self, trace):
        """测试失败追踪"""
        trace.start()
        trace.fail(error="Something went wrong", error_stack="traceback...")

        assert trace.status == ExecutionStatus.FAILED
        assert trace.error == "Something went wrong"
        assert trace.error_stack == "traceback..."

    def test_calculate_summary(self, trace):
        """测试计算汇总统计"""
        trace.start()

        # 添加 LLM 调用
        trace.llm_calls = [
            LLMCallRecord(
                span_id="s1",
                trace_id=trace.trace_id,
                provider="openai",
                model="gpt-4",
                messages=[],
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.01,
                latency_ms=500,
                success=True,
            ),
            LLMCallRecord(
                span_id="s2",
                trace_id=trace.trace_id,
                provider="openai",
                model="gpt-4",
                messages=[],
                prompt_tokens=200,
                completion_tokens=100,
                total_tokens=300,
                cost_usd=0.02,
                latency_ms=800,
                success=True,
            ),
        ]

        # 添加工具调用
        trace.tool_calls = [
            ToolCallRecord(
                span_id="s1",
                trace_id=trace.trace_id,
                tool_id="t1",
                tool_name="Tool 1",
                tool_category="test",
                input_params={},
                latency_ms=100,
                success=True,
            ),
            ToolCallRecord(
                span_id="s2",
                trace_id=trace.trace_id,
                tool_id="t2",
                tool_name="Tool 2",
                tool_category="test",
                input_params={},
                latency_ms=200,
                success=False,
            ),
        ]

        trace.complete()

        assert trace.summary["total_llm_calls"] == 2
        assert trace.summary["total_tool_calls"] == 2
        assert trace.summary["total_prompt_tokens"] == 300
        assert trace.summary["total_completion_tokens"] == 150
        assert trace.summary["total_tokens"] == 450
        assert trace.summary["total_cost_usd"] == 0.03
        assert trace.summary["llm_success_rate"] == 1.0
        assert trace.summary["tool_success_rate"] == 0.5
        assert trace.summary["avg_llm_latency_ms"] == 650

    def test_to_dict(self, trace):
        """测试序列化"""
        trace.start()
        trace.tags = ["test", "unit"]
        trace.metadata = {"version": "1.0"}

        trace.spans = [
            SpanRecord(
                span_id="s1",
                trace_id=trace.trace_id,
                parent_span_id=None,
                name="root",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration_ms=100,
                status="ok",
            )
        ]

        trace.complete({"result": "done"})

        d = trace.to_dict()

        assert d["trace_id"] == trace.trace_id
        assert d["task_id"] == "task_001"
        assert d["agent_id"] == "test_agent"
        assert d["status"] == "completed"
        assert d["tags"] == ["test", "unit"]
        assert len(d["spans"]) == 1
        assert "summary" in d

    def test_empty_summary(self, trace):
        """测试空追踪的汇总"""
        trace.start()
        trace.complete()

        assert trace.summary["total_llm_calls"] == 0
        assert trace.summary["total_tool_calls"] == 0
        assert trace.summary["llm_success_rate"] == 1.0
        assert trace.summary["tool_success_rate"] == 1.0


class TestTraceFilters:
    """TraceFilters 测试"""

    def test_default_values(self):
        """测试默认值"""
        filters = TraceFilters()

        assert filters.task_id is None
        assert filters.agent_id is None
        assert filters.status is None
        assert filters.limit == 100
        assert filters.offset == 0

    def test_custom_filters(self):
        """测试自定义过滤器"""
        filters = TraceFilters(
            task_id="task_001",
            agent_id="agent_1",
            status=ExecutionStatus.COMPLETED,
            limit=50,
            offset=10,
            tags=["production"],
        )

        assert filters.task_id == "task_001"
        assert filters.agent_id == "agent_1"
        assert filters.status == ExecutionStatus.COMPLETED
        assert filters.limit == 50
        assert filters.offset == 10
        assert filters.tags == ["production"]

    def test_time_range_filter(self):
        """测试时间范围过滤"""
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        filters = TraceFilters(start_time=yesterday, end_time=now)

        assert filters.start_time == yesterday
        assert filters.end_time == now

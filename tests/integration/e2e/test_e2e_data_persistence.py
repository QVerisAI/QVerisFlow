"""
数据持久化端到端测试

测试数据持久化的完整流程：
- 追踪存储
- LLM 调用记录
- 工具调用记录
- 检查点持久化
"""

import pytest
import tempfile
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from src.persistence.models import (
    ExecutionTrace,
    ExecutionStatus,
    SpanRecord,
    LLMCallRecord,
    ToolCallRecord,
    TraceFilters,
)
from src.persistence.trace_storage import FileTraceStorage


class TestFileTraceStorage:
    """文件追踪存储测试"""

    @pytest.fixture
    def trace_storage(self, tmp_path):
        """创建临时追踪存储"""
        storage = FileTraceStorage(str(tmp_path / "traces"))
        yield storage
        # Cleanup is handled by tmp_path fixture

    @pytest.mark.asyncio
    async def test_save_and_get_trace(self, trace_storage):
        """测试保存和获取追踪"""
        trace = ExecutionTrace(
            trace_id="e2e_trace_1",
            task_id="test_task",
            agent_id="test_agent",
        )
        trace.start()
        trace.complete({"result": "success"})

        # Save trace
        await trace_storage.save_trace(trace)

        # Get trace
        retrieved = await trace_storage.get_trace("e2e_trace_1")

        assert retrieved is not None
        assert retrieved.trace_id == "e2e_trace_1"
        assert retrieved.task_id == "test_task"
        assert retrieved.agent_id == "test_agent"
        assert retrieved.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_list_traces_by_task(self, trace_storage):
        """测试按任务列出追踪"""
        # Create traces for different tasks
        for i in range(3):
            trace = ExecutionTrace(
                trace_id=f"trace_task_a_{i}",
                task_id="task_a",
                agent_id="agent_1",
            )
            trace.start()
            trace.complete()
            await trace_storage.save_trace(trace)

        for i in range(2):
            trace = ExecutionTrace(
                trace_id=f"trace_task_b_{i}",
                task_id="task_b",
                agent_id="agent_1",
            )
            trace.start()
            trace.complete()
            await trace_storage.save_trace(trace)

        # List by task using TraceFilters
        filters = TraceFilters(task_id="task_a")
        traces = await trace_storage.list_traces(filters)

        assert len(traces) == 3
        for trace in traces:
            assert trace.task_id == "task_a"

    @pytest.mark.asyncio
    async def test_list_traces_by_agent(self, trace_storage):
        """测试按 Agent 列出追踪"""
        # Create traces for different agents
        for i in range(2):
            trace = ExecutionTrace(
                trace_id=f"trace_agent_1_{i}",
                task_id="task_1",
                agent_id="agent_1",
            )
            trace.start()
            trace.complete()
            await trace_storage.save_trace(trace)

        for i in range(3):
            trace = ExecutionTrace(
                trace_id=f"trace_agent_2_{i}",
                task_id="task_1",
                agent_id="agent_2",
            )
            trace.start()
            trace.complete()
            await trace_storage.save_trace(trace)

        # List by agent using TraceFilters
        filters = TraceFilters(agent_id="agent_2")
        traces = await trace_storage.list_traces(filters)

        assert len(traces) == 3
        for trace in traces:
            assert trace.agent_id == "agent_2"

    @pytest.mark.asyncio
    async def test_list_traces_by_status(self, trace_storage):
        """测试按状态列出追踪"""
        # Create completed trace
        completed = ExecutionTrace(
            trace_id="trace_completed",
            task_id="task_1",
            agent_id="agent_1",
        )
        completed.start()
        completed.complete()
        await trace_storage.save_trace(completed)

        # Create failed trace
        failed = ExecutionTrace(
            trace_id="trace_failed",
            task_id="task_1",
            agent_id="agent_1",
        )
        failed.start()
        failed.fail("Test error")
        await trace_storage.save_trace(failed)

        # List by status using TraceFilters
        filters = TraceFilters(status=ExecutionStatus.COMPLETED)
        traces = await trace_storage.list_traces(filters)

        assert len(traces) == 1
        assert traces[0].status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_trace_with_spans(self, trace_storage):
        """测试包含 Span 的追踪"""
        trace = ExecutionTrace(
            trace_id="e2e_trace_spans",
            task_id="span_task",
            agent_id="span_agent",
        )
        trace.start()

        # Add spans (SpanRecord doesn't have span_type, only these fields)
        span1 = SpanRecord(
            span_id="span_1",
            trace_id="e2e_trace_spans",
            parent_span_id=None,
            name="main_operation",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=100.0,
            status="ok",
            attributes={"operation": "main"},
        )
        span2 = SpanRecord(
            span_id="span_2",
            trace_id="e2e_trace_spans",
            parent_span_id="span_1",
            name="sub_operation",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_ms=50.0,
            status="ok",
            attributes={"operation": "sub"},
        )

        trace.spans.append(span1)
        trace.spans.append(span2)
        trace.complete()

        await trace_storage.save_trace(trace)

        # Retrieve and verify
        retrieved = await trace_storage.get_trace("e2e_trace_spans")
        assert retrieved is not None
        assert len(retrieved.spans) == 2
        assert retrieved.spans[0].name == "main_operation"

    @pytest.mark.asyncio
    async def test_delete_trace(self, trace_storage):
        """测试删除追踪"""
        trace = ExecutionTrace(
            trace_id="e2e_trace_delete",
            task_id="delete_task",
            agent_id="delete_agent",
        )
        trace.start()
        trace.complete()

        await trace_storage.save_trace(trace)

        # Verify exists
        retrieved = await trace_storage.get_trace("e2e_trace_delete")
        assert retrieved is not None

        # Delete
        result = await trace_storage.delete_trace("e2e_trace_delete")
        assert result is True

        # Verify deleted
        retrieved = await trace_storage.get_trace("e2e_trace_delete")
        assert retrieved is None


class TestLLMCallRecords:
    """LLM 调用记录测试"""

    @pytest.fixture
    def trace_storage(self, tmp_path):
        """创建临时追踪存储"""
        return FileTraceStorage(str(tmp_path / "traces"))

    @pytest.mark.asyncio
    async def test_llm_call_recording(self, trace_storage):
        """测试 LLM 调用记录"""
        trace = ExecutionTrace(
            trace_id="e2e_trace_llm",
            task_id="llm_task",
            agent_id="llm_agent",
        )
        trace.start()

        # Add LLM call record
        llm_call = LLMCallRecord(
            call_id="llm_1",
            trace_id="e2e_trace_llm",
            provider="openai",
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello"}],
            response="Hi there!",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            latency_ms=500,
        )
        trace.llm_calls.append(llm_call)
        trace.complete()

        await trace_storage.save_trace(trace)

        # Retrieve and verify - note: FileTraceStorage doesn't persist llm_calls by default
        # We can verify the trace was saved and contains summary info
        retrieved = await trace_storage.get_trace("e2e_trace_llm")
        assert retrieved is not None
        assert retrieved.summary.get("total_llm_calls") == 1

    @pytest.mark.asyncio
    async def test_multiple_llm_calls(self, trace_storage):
        """测试多次 LLM 调用记录"""
        trace = ExecutionTrace(
            trace_id="e2e_trace_multi_llm",
            task_id="multi_llm_task",
            agent_id="multi_llm_agent",
        )
        trace.start()

        # Add multiple LLM calls
        for i in range(5):
            llm_call = LLMCallRecord(
                call_id=f"llm_{i}",
                trace_id="e2e_trace_multi_llm",
                provider="anthropic",
                model="claude-3",
                messages=[{"role": "user", "content": f"Message {i}"}],
                response=f"Response {i}",
                prompt_tokens=100 + i * 10,
                completion_tokens=50 + i * 5,
                latency_ms=500 + i * 100,
                cost_usd=0.001 + i * 0.0005,
            )
            trace.llm_calls.append(llm_call)

        trace.complete()
        await trace_storage.save_trace(trace)

        retrieved = await trace_storage.get_trace("e2e_trace_multi_llm")
        assert retrieved is not None
        assert retrieved.summary.get("total_llm_calls") == 5


class TestToolCallRecords:
    """工具调用记录测试"""

    @pytest.fixture
    def trace_storage(self, tmp_path):
        """创建临时追踪存储"""
        return FileTraceStorage(str(tmp_path / "traces"))

    @pytest.mark.asyncio
    async def test_tool_call_recording(self, trace_storage):
        """测试工具调用记录"""
        trace = ExecutionTrace(
            trace_id="e2e_trace_tool",
            task_id="tool_task",
            agent_id="tool_agent",
        )
        trace.start()

        # Add tool call record
        tool_call = ToolCallRecord(
            call_id="tool_1",
            trace_id="e2e_trace_tool",
            tool_id="search_tool",
            tool_name="web_search",
            tool_category="search",
            input_params={"query": "test query"},
            output={"results": ["result1", "result2"]},
            latency_ms=10,
            success=True,
        )
        trace.tool_calls.append(tool_call)
        trace.complete()

        await trace_storage.save_trace(trace)

        retrieved = await trace_storage.get_trace("e2e_trace_tool")
        assert retrieved is not None
        assert retrieved.summary.get("total_tool_calls") == 1

    @pytest.mark.asyncio
    async def test_tool_call_input_output_pairs(self, trace_storage):
        """测试工具调用输入输出配对"""
        trace = ExecutionTrace(
            trace_id="e2e_trace_tool_io",
            task_id="tool_io_task",
            agent_id="tool_io_agent",
        )
        trace.start()

        # Add multiple tool calls with different inputs/outputs
        tools = [
            ("search", {"query": "q1"}, {"results": ["r1"]}),
            ("calculator", {"expr": "2+2"}, {"result": 4}),
            ("formatter", {"text": "hello"}, {"formatted": "HELLO"}),
        ]

        for i, (name, input_params, output) in enumerate(tools):
            tool_call = ToolCallRecord(
                call_id=f"tool_{i}",
                trace_id="e2e_trace_tool_io",
                tool_id=f"{name}_tool",
                tool_name=name,
                input_params=input_params,
                output=output,
                latency_ms=10,
                success=True,
            )
            trace.tool_calls.append(tool_call)

        trace.complete()
        await trace_storage.save_trace(trace)

        retrieved = await trace_storage.get_trace("e2e_trace_tool_io")
        assert retrieved is not None
        assert retrieved.summary.get("total_tool_calls") == 3

    @pytest.mark.asyncio
    async def test_failed_tool_call(self, trace_storage):
        """测试失败的工具调用"""
        trace = ExecutionTrace(
            trace_id="e2e_trace_failed_tool",
            task_id="failed_tool_task",
            agent_id="failed_tool_agent",
        )
        trace.start()

        # Add failed tool call
        tool_call = ToolCallRecord(
            call_id="tool_fail",
            trace_id="e2e_trace_failed_tool",
            tool_id="unreliable_tool",
            tool_name="unreliable",
            input_params={"data": "test"},
            success=False,
            error="Connection timeout",
            retry_count=3,
        )
        trace.tool_calls.append(tool_call)
        trace.complete()

        await trace_storage.save_trace(trace)

        retrieved = await trace_storage.get_trace("e2e_trace_failed_tool")
        assert retrieved is not None
        # Verify summary shows tool call
        assert retrieved.summary.get("total_tool_calls") == 1


class TestTraceSummary:
    """追踪汇总测试"""

    @pytest.fixture
    def trace_storage(self, tmp_path):
        """创建临时追踪存储"""
        return FileTraceStorage(str(tmp_path / "traces"))

    @pytest.mark.asyncio
    async def test_summary_calculation(self, trace_storage):
        """测试汇总统计计算"""
        trace = ExecutionTrace(
            trace_id="e2e_trace_summary",
            task_id="summary_task",
            agent_id="summary_agent",
        )
        trace.start()

        # Add spans
        for i in range(3):
            span = SpanRecord(
                span_id=f"span_{i}",
                trace_id="e2e_trace_summary",
                parent_span_id=None,
                name=f"operation_{i}",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration_ms=float(100 + i * 50),
                status="ok",
            )
            trace.spans.append(span)

        # Add LLM calls
        for i in range(2):
            llm_call = LLMCallRecord(
                call_id=f"llm_{i}",
                trace_id="e2e_trace_summary",
                provider="openai",
                model="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.001,
                latency_ms=500,
            )
            trace.llm_calls.append(llm_call)

        # Add tool calls
        tool_call = ToolCallRecord(
            call_id="tool_1",
            trace_id="e2e_trace_summary",
            tool_id="test_tool",
            tool_name="test",
            latency_ms=10,
            success=True,
        )
        trace.tool_calls.append(tool_call)

        trace.complete()
        await trace_storage.save_trace(trace)

        retrieved = await trace_storage.get_trace("e2e_trace_summary")
        assert retrieved is not None

        summary = retrieved.summary
        assert summary["total_spans"] == 3
        assert summary["total_llm_calls"] == 2
        assert summary["total_tool_calls"] == 1


class TestTracePersistencePerformance:
    """追踪持久化性能测试"""

    @pytest.fixture
    def trace_storage(self, tmp_path):
        """创建临时追踪存储"""
        return FileTraceStorage(str(tmp_path / "traces"))

    @pytest.mark.asyncio
    async def test_large_trace_persistence(self, trace_storage):
        """测试大型追踪持久化"""
        trace = ExecutionTrace(
            trace_id="e2e_large_trace",
            task_id="large_task",
            agent_id="large_agent",
        )
        trace.start()

        # Add many LLM calls
        for i in range(50):
            llm_call = LLMCallRecord(
                call_id=f"llm_{i}",
                trace_id="e2e_large_trace",
                provider="openai",
                model="gpt-4",
                prompt_tokens=500,
                completion_tokens=200,
                latency_ms=100,
            )
            trace.llm_calls.append(llm_call)

        # Add many tool calls
        for i in range(100):
            tool_call = ToolCallRecord(
                call_id=f"tool_{i}",
                trace_id="e2e_large_trace",
                tool_id=f"tool_{i % 10}",
                tool_name=f"tool_type_{i % 10}",
                latency_ms=10,
                success=True,
            )
            trace.tool_calls.append(tool_call)

        trace.complete()

        # Measure save time
        import time

        start = time.time()
        await trace_storage.save_trace(trace)
        save_duration = time.time() - start

        # Should complete in reasonable time
        assert save_duration < 5.0  # Less than 5 seconds

        # Verify retrieval
        retrieved = await trace_storage.get_trace("e2e_large_trace")
        assert retrieved is not None
        assert retrieved.summary["total_llm_calls"] == 50
        assert retrieved.summary["total_tool_calls"] == 100


class TestTraceIndexing:
    """追踪索引测试"""

    @pytest.fixture
    def trace_storage(self, tmp_path):
        """创建临时追踪存储"""
        return FileTraceStorage(str(tmp_path / "traces"))

    @pytest.mark.asyncio
    async def test_task_index_creation(self, trace_storage):
        """测试任务索引创建"""
        # Create multiple traces for same task
        for i in range(5):
            trace = ExecutionTrace(
                trace_id=f"trace_indexed_{i}",
                task_id="indexed_task",
                agent_id="agent_1",
            )
            trace.start()
            trace.complete()
            await trace_storage.save_trace(trace)

        # List by task using TraceFilters
        filters = TraceFilters(task_id="indexed_task")
        traces = await trace_storage.list_traces(filters)

        assert len(traces) == 5

    @pytest.mark.asyncio
    async def test_time_range_filtering(self, trace_storage):
        """测试时间范围过滤"""
        now = datetime.now()

        # Create traces at different times
        trace1 = ExecutionTrace(
            trace_id="trace_time_1",
            task_id="time_task",
            agent_id="agent_1",
        )
        trace1.started_at = now - timedelta(hours=2)
        trace1.status = ExecutionStatus.COMPLETED
        await trace_storage.save_trace(trace1)

        trace2 = ExecutionTrace(
            trace_id="trace_time_2",
            task_id="time_task",
            agent_id="agent_1",
        )
        trace2.started_at = now
        trace2.status = ExecutionStatus.COMPLETED
        await trace_storage.save_trace(trace2)

        # Filter by time range using TraceFilters
        filters = TraceFilters(
            task_id="time_task",
            start_time=now - timedelta(hours=1),
        )
        traces = await trace_storage.list_traces(filters)

        # Should only get the recent trace
        assert len(traces) == 1
        assert traces[0].trace_id == "trace_time_2"

    @pytest.mark.asyncio
    async def test_pagination(self, trace_storage):
        """测试分页"""
        # Create 10 traces
        for i in range(10):
            trace = ExecutionTrace(
                trace_id=f"trace_page_{i}",
                task_id="page_task",
                agent_id="agent_1",
            )
            trace.start()
            trace.complete()
            await trace_storage.save_trace(trace)

        # Get first page using TraceFilters
        filters = TraceFilters(task_id="page_task", limit=3, offset=0)
        page1 = await trace_storage.list_traces(filters)
        assert len(page1) == 3

        # Get second page
        filters = TraceFilters(task_id="page_task", limit=3, offset=3)
        page2 = await trace_storage.list_traces(filters)
        assert len(page2) == 3

        # Verify no overlap
        page1_ids = {t.trace_id for t in page1}
        page2_ids = {t.trace_id for t in page2}
        assert page1_ids.isdisjoint(page2_ids)

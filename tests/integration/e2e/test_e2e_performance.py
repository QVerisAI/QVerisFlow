"""
性能端到端测试

测试框架在各种负载下的性能：
- 并发执行
- 大型上下文处理
- 高工具调用量
"""

import pytest
import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import List

from src.workspace.workspace import AgentWorkspace, WorkspaceConfig
from src.persistence.models import ExecutionTrace, LLMCallRecord, ToolCallRecord
from src.persistence.trace_storage import FileTraceStorage
from src.tools.retry import RetryExecutor, RetryPolicy


class TestConcurrentAgentExecution:
    """并发 Agent 执行测试"""

    @pytest.mark.asyncio
    async def test_concurrent_workspace_creation(self, tmp_path):
        """测试并发工作空间创建"""
        async def create_workspace(index: int):
            config = WorkspaceConfig(
                base_path=str(tmp_path),
                task_id=f"concurrent_task_{index}",
                auto_create=True,
            )
            workspace = AgentWorkspace(config)
            workspace.write_task(f"Task {index}", {"index": index})
            return workspace

        # Create 20 workspaces concurrently
        start_time = time.time()
        workspaces = await asyncio.gather(*[create_workspace(i) for i in range(20)])
        elapsed = time.time() - start_time

        assert len(workspaces) == 20
        # Should complete in reasonable time
        assert elapsed < 5.0

    @pytest.mark.asyncio
    async def test_concurrent_trace_storage(self, tmp_path):
        """测试并发追踪存储"""
        storage = FileTraceStorage(str(tmp_path / "traces"))

        async def save_trace(index: int):
            trace = ExecutionTrace(
                trace_id=f"concurrent_trace_{index}",
                task_id=f"task_{index}",
                agent_id="agent_1",
            )
            trace.start()
            trace.complete({"index": index})
            await storage.save_trace(trace)
            return trace.trace_id

        # Save 50 traces concurrently
        start_time = time.time()
        trace_ids = await asyncio.gather(*[save_trace(i) for i in range(50)])
        elapsed = time.time() - start_time

        assert len(trace_ids) == 50
        # Verify all were saved
        for trace_id in trace_ids:
            retrieved = await storage.get_trace(trace_id)
            assert retrieved is not None

        # Should complete in reasonable time
        assert elapsed < 10.0


class TestLargeContextHandling:
    """大型上下文处理测试"""

    @pytest.fixture
    def workspace(self, tmp_path):
        """创建工作空间"""
        config = WorkspaceConfig(
            base_path=str(tmp_path),
            task_id="large_context_task",
            auto_create=True,
        )
        return AgentWorkspace(config)

    def test_large_context_processing(self, workspace):
        """测试大型上下文处理"""
        # Create large context file (1 MB)
        large_content = "A" * (1024 * 1024)
        context_file = workspace.context_dir / "large_context.txt"
        context_file.write_text(large_content, encoding="utf-8")

        # Read back
        start_time = time.time()
        read_content = context_file.read_text(encoding="utf-8")
        read_time = time.time() - start_time

        assert len(read_content) == len(large_content)
        assert read_time < 1.0  # Should read in under 1 second

    def test_many_small_context_files(self, workspace):
        """测试多个小上下文文件"""
        # Create 100 small files
        for i in range(100):
            file_path = workspace.context_dir / f"context_{i}.txt"
            file_path.write_text(f"Context content {i}" * 100, encoding="utf-8")

        # List all files
        start_time = time.time()
        files = list(workspace.context_dir.glob("*.txt"))
        list_time = time.time() - start_time

        assert len(files) == 100
        assert list_time < 1.0


class TestHighToolCallVolume:
    """高工具调用量测试"""

    @pytest.mark.asyncio
    async def test_rapid_tool_execution(self):
        """测试快速工具执行"""
        policy = RetryPolicy(max_retries=0)
        executor = RetryExecutor(policy=policy)

        call_count = 0

        async def fast_tool():
            nonlocal call_count
            call_count += 1
            return {"result": call_count}

        # Execute 100 times rapidly
        start_time = time.time()
        results = []
        for _ in range(100):
            result = await executor.execute(fast_tool)
            results.append(result)
        elapsed = time.time() - start_time

        assert len(results) == 100
        assert all(r.success for r in results)
        assert elapsed < 2.0  # Should complete quickly

    @pytest.mark.asyncio
    async def test_parallel_tool_execution(self):
        """测试并行工具执行"""
        policy = RetryPolicy(max_retries=0)
        executor = RetryExecutor(policy=policy)

        async def slow_tool(index: int):
            await asyncio.sleep(0.05)  # 50ms each
            return {"index": index}

        # Execute 20 tools in parallel
        start_time = time.time()

        async def execute_tool(index: int):
            return await executor.execute(slow_tool, args=(index,))

        results = await asyncio.gather(*[execute_tool(i) for i in range(20)])
        elapsed = time.time() - start_time

        assert len(results) == 20
        # Parallel execution should be much faster than sequential
        # 20 * 50ms = 1s sequential, but parallel should be ~50-100ms
        assert elapsed < 0.5


class TestCheckpointPerformance:
    """检查点性能测试"""

    @pytest.mark.asyncio
    async def test_checkpoint_save_performance(self, tmp_path):
        """测试检查点保存性能"""
        from src.storage.checkpointers import FileCheckpointSaver

        saver = FileCheckpointSaver(str(tmp_path / "checkpoints"))

        # Create checkpoint data
        checkpoint = {
            "v": 1,
            "ts": datetime.now().isoformat(),
            "id": "perf_test",
            "channel_values": {
                "messages": [{"role": "user", "content": "Hello" * 1000}] * 10,
                "state": {"key": "value" * 100},
            },
            "channel_versions": {},
            "versions_seen": {},
            "pending_sends": [],
        }

        config = {"configurable": {"thread_id": "perf_thread"}}

        # Save multiple checkpoints (put is sync, takes 3 args)
        start_time = time.time()
        for i in range(20):
            checkpoint["id"] = f"perf_test_{i}"
            saver.put(config.copy(), checkpoint.copy(), {})
        elapsed = time.time() - start_time

        assert elapsed < 5.0  # Should complete in under 5 seconds

    @pytest.mark.asyncio
    async def test_checkpoint_load_performance(self, tmp_path):
        """测试检查点加载性能"""
        from src.storage.checkpointers import FileCheckpointSaver

        saver = FileCheckpointSaver(str(tmp_path / "checkpoints"))

        # Setup: Save checkpoints
        checkpoint = {
            "v": 1,
            "ts": datetime.now().isoformat(),
            "id": "load_test",
            "channel_values": {"data": "content" * 500},
            "channel_versions": {},
            "versions_seen": {},
            "pending_sends": [],
        }

        config = {"configurable": {"thread_id": "load_thread"}}

        for i in range(10):
            checkpoint["id"] = f"load_test_{i}"
            saver.put(config.copy(), checkpoint.copy(), {})

        # Test load performance (get is sync)
        start_time = time.time()
        for _ in range(10):
            result = saver.get(config)
            assert result is not None
        elapsed = time.time() - start_time

        assert elapsed < 2.0


class TestTracePersistencePerformance:
    """追踪持久化性能测试"""

    @pytest.mark.asyncio
    async def test_large_trace_with_many_records(self, tmp_path):
        """测试包含大量记录的追踪"""
        storage = FileTraceStorage(str(tmp_path / "traces"))

        trace = ExecutionTrace(
            trace_id="large_record_trace",
            task_id="perf_task",
            agent_id="perf_agent",
        )
        trace.start()

        # Add many LLM calls
        for i in range(100):
            trace.llm_calls.append(
                LLMCallRecord(
                    call_id=f"llm_{i}",
                    trace_id="large_record_trace",
                    provider="openai",
                    model="gpt-4",
                    prompt_tokens=100,
                    completion_tokens=50,
                )
            )

        # Add many tool calls
        for i in range(200):
            trace.tool_calls.append(
                ToolCallRecord(
                    call_id=f"tool_{i}",
                    trace_id="large_record_trace",
                    tool_id=f"tool_{i % 20}",
                    tool_name=f"tool_type_{i % 20}",
                )
            )

        trace.complete()

        # Measure save time
        start_time = time.time()
        await storage.save_trace(trace)
        save_time = time.time() - start_time

        # Measure load time
        start_time = time.time()
        retrieved = await storage.get_trace("large_record_trace")
        load_time = time.time() - start_time

        assert retrieved is not None
        assert save_time < 3.0
        assert load_time < 2.0


class TestMemoryEfficiency:
    """内存效率测试"""

    @pytest.mark.asyncio
    async def test_workspace_memory_cleanup(self, tmp_path):
        """测试工作空间内存清理"""
        import gc

        workspaces = []

        # Create many workspaces
        for i in range(50):
            config = WorkspaceConfig(
                base_path=str(tmp_path),
                task_id=f"memory_task_{i}",
                auto_create=True,
            )
            ws = AgentWorkspace(config)
            ws.write_task(f"Task {i}", {"data": "x" * 1000})
            workspaces.append(ws)

        # Clear references
        workspaces.clear()
        gc.collect()

        # Should be able to create more without memory issues
        for i in range(50, 100):
            config = WorkspaceConfig(
                base_path=str(tmp_path),
                task_id=f"memory_task_{i}",
                auto_create=True,
            )
            ws = AgentWorkspace(config)
            ws.write_task(f"Task {i}", {"data": "x" * 1000})

        # Test passes if no memory errors occur

"""
检查点恢复 E2E 测试

测试 Agent 的检查点保存和恢复功能：
- 内存检查点恢复
- 文件检查点恢复
- 中间迭代恢复
- 跨实例恢复
"""

import pytest
import asyncio
import json
import copy
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from .utils import (
    TestDataGenerator,
    AssertionHelpers,
    WaitHelpers,
    PerformanceTimer,
)


class TestMemoryCheckpointRecovery:
    """内存检查点恢复测试"""

    @pytest.mark.asyncio
    async def test_basic_save_and_get(self, memory_checkpointer):
        """测试基本的保存和获取"""
        thread_id = "recovery_test_basic"
        config = {"configurable": {"thread_id": thread_id}}

        checkpoint_data = {
            "channel_values": {
                "messages": ["message1", "message2"],
                "state": {"iteration": 1},
            },
            "channel_versions": {"messages": 2, "state": 1},
        }

        # 保存检查点
        result_config = memory_checkpointer.put(config, checkpoint_data)

        # 验证返回的配置包含 checkpoint_id
        assert "checkpoint_id" in result_config["configurable"]

        # 获取检查点
        retrieved = memory_checkpointer.get(config)

        assert retrieved is not None
        assert (
            retrieved["channel_values"]["messages"]
            == checkpoint_data["channel_values"]["messages"]
        )
        assert retrieved["channel_versions"] == checkpoint_data["channel_versions"]

    @pytest.mark.asyncio
    async def test_multiple_checkpoints_same_thread(self, memory_checkpointer):
        """测试同一线程多个检查点"""
        thread_id = "recovery_test_multiple"
        config = {"configurable": {"thread_id": thread_id}}

        # 保存多个版本
        for i in range(3):
            config_copy = copy.deepcopy(config)
            checkpoint_data = {
                "channel_values": {"iteration": i, "data": f"version_{i}"},
                "channel_versions": {"iteration": i},
            }
            memory_checkpointer.put(config_copy, checkpoint_data)

        # 获取最新版本
        latest = memory_checkpointer.get(config)

        assert latest is not None
        assert latest["channel_values"]["iteration"] == 2
        assert latest["channel_values"]["data"] == "version_2"

    @pytest.mark.asyncio
    async def test_list_checkpoints(self, memory_checkpointer):
        """测试列出检查点"""
        thread_id = "recovery_test_list"
        config = {"configurable": {"thread_id": thread_id}}

        # 保存多个检查点
        checkpoint_ids = []
        for i in range(5):
            config_copy = copy.deepcopy(config)
            result = memory_checkpointer.put(
                config_copy,
                {"channel_values": {"index": i}, "channel_versions": {}},
            )
            checkpoint_ids.append(result["configurable"]["checkpoint_id"])

        # 列出检查点
        checkpoints = list(memory_checkpointer.list(config))

        assert len(checkpoints) == 5

    @pytest.mark.asyncio
    async def test_get_specific_checkpoint(self, memory_checkpointer):
        """测试获取特定检查点"""
        thread_id = "recovery_test_specific"
        config = {"configurable": {"thread_id": thread_id}}

        # 保存两个版本
        config_copy1 = copy.deepcopy(config)
        result1 = memory_checkpointer.put(
            config_copy1,
            {"channel_values": {"version": "first"}, "channel_versions": {}},
        )
        first_checkpoint_id = result1["configurable"]["checkpoint_id"]

        config_copy2 = copy.deepcopy(config)
        memory_checkpointer.put(
            config_copy2,
            {"channel_values": {"version": "second"}, "channel_versions": {}},
        )

        # 获取第一个版本
        specific_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": first_checkpoint_id,
            }
        }
        retrieved = memory_checkpointer.get(specific_config)

        assert retrieved is not None
        assert retrieved["channel_values"]["version"] == "first"

    @pytest.mark.asyncio
    async def test_delete_checkpoint(self, memory_checkpointer):
        """测试删除检查点"""
        thread_id = "recovery_test_delete"
        config = {"configurable": {"thread_id": thread_id}}

        # 保存检查点
        config_copy = copy.deepcopy(config)
        memory_checkpointer.put(
            config_copy,
            {"channel_values": {"data": "to_delete"}, "channel_versions": {}},
        )

        # 验证存在
        assert memory_checkpointer.get(config) is not None

        # 删除
        result = memory_checkpointer.delete(config)
        assert result is True

        # 验证已删除
        assert memory_checkpointer.get(config) is None

    @pytest.mark.asyncio
    async def test_state_continuity(self, memory_checkpointer):
        """测试状态连续性"""
        thread_id = "recovery_test_continuity"
        config = {"configurable": {"thread_id": thread_id}}

        # 模拟多次迭代的状态
        states = []
        for i in range(3):
            state = TestDataGenerator.generate_agent_state(iteration=i + 1)
            states.append(state)

            config_copy = copy.deepcopy(config)
            memory_checkpointer.put(
                config_copy,
                {"channel_values": state, "channel_versions": {"iteration": i + 1}},
            )

        # 恢复最后状态
        recovered = memory_checkpointer.get(config)

        assert recovered is not None
        assert recovered["channel_values"]["iteration"] == 3


class TestFileCheckpointRecovery:
    """文件检查点恢复测试"""

    @pytest.mark.asyncio
    async def test_file_checkpoint_save(self, file_checkpointer):
        """测试文件检查点保存"""
        thread_id = "file_recovery_test"
        config = {"configurable": {"thread_id": thread_id}}

        checkpoint_data = {
            "channel_values": {
                "agent_id": "test_agent",
                "iteration": 1,
                "gathered_context": "Test context data",
            },
            "channel_versions": {"iteration": 1},
        }

        result = file_checkpointer.put(config, checkpoint_data)

        assert "checkpoint_id" in result["configurable"]

    @pytest.mark.asyncio
    async def test_file_checkpoint_persistence(self, file_checkpointer, tmp_path):
        """测试文件检查点持久化"""
        thread_id = "file_persistence_test"
        config = {"configurable": {"thread_id": thread_id}}

        checkpoint_data = {
            "channel_values": {"persistent": True, "data": "important"},
            "channel_versions": {},
        }

        file_checkpointer.put(config, checkpoint_data)

        # 验证文件已创建
        checkpoint_dir = tmp_path / "checkpoints" / thread_id
        assert checkpoint_dir.exists()

        # 获取并验证
        retrieved = file_checkpointer.get(config)
        assert retrieved is not None
        assert retrieved["channel_values"]["persistent"] is True

    @pytest.mark.asyncio
    async def test_file_checkpoint_recovery_after_restart(
        self, checkpointer_factory, tmp_path
    ):
        """测试重启后文件检查点恢复"""
        thread_id = "restart_recovery_test"
        config = {"configurable": {"thread_id": thread_id}}

        # 使用第一个检查点存储保存
        saver1 = checkpointer_factory("file")
        checkpoint_data = {
            "channel_values": {"recovered": True, "iteration": 5},
            "channel_versions": {},
        }
        saver1.put(config, checkpoint_data)

        # 创建新的检查点存储实例（模拟重启）
        saver2 = checkpointer_factory("file")

        # 从新实例恢复
        recovered = saver2.get(config)

        assert recovered is not None
        assert recovered["channel_values"]["recovered"] is True
        assert recovered["channel_values"]["iteration"] == 5

    @pytest.mark.asyncio
    async def test_file_checkpoint_list_versions(self, file_checkpointer):
        """测试文件检查点列出版本"""
        thread_id = "file_list_versions_test"
        config = {"configurable": {"thread_id": thread_id}}

        # 保存多个版本
        for i in range(3):
            config_copy = copy.deepcopy(config)
            file_checkpointer.put(
                config_copy,
                {"channel_values": {"version": i}, "channel_versions": {}},
            )

        # 列出所有版本
        versions = list(file_checkpointer.list(config))

        assert len(versions) >= 1

    @pytest.mark.asyncio
    async def test_file_checkpoint_delete_thread(self, file_checkpointer):
        """测试删除整个线程的检查点"""
        thread_id = "file_delete_thread_test"
        config = {"configurable": {"thread_id": thread_id}}

        # 保存多个检查点
        for i in range(3):
            config_copy = copy.deepcopy(config)
            file_checkpointer.put(
                config_copy,
                {"channel_values": {"index": i}, "channel_versions": {}},
            )

        # 删除整个线程
        delete_config = {"configurable": {"thread_id": thread_id}}
        file_checkpointer.delete(delete_config)

        # 验证已删除
        assert file_checkpointer.get(config) is None


class TestMidIterationRecovery:
    """中间迭代恢复测试"""

    @pytest.mark.asyncio
    async def test_save_checkpoint_at_each_phase(self, memory_checkpointer):
        """测试在每个阶段保存检查点"""
        thread_id = "phase_checkpoint_test"
        config = {"configurable": {"thread_id": thread_id}}

        phases = ["gather_context", "take_action", "verify_work"]

        for i, phase in enumerate(phases):
            config_copy = copy.deepcopy(config)
            state = {
                "channel_values": {
                    "phase": phase,
                    "iteration": 1,
                    "data": f"data_at_{phase}",
                },
                "channel_versions": {"phase": i},
            }
            memory_checkpointer.put(config_copy, state)

        # 验证最后阶段
        latest = memory_checkpointer.get(config)
        assert latest["channel_values"]["phase"] == "verify_work"

    @pytest.mark.asyncio
    async def test_recover_mid_iteration_context(self, memory_checkpointer):
        """测试恢复中间迭代上下文"""
        thread_id = "mid_iteration_test"
        config = {"configurable": {"thread_id": thread_id}}

        # 模拟中间迭代状态
        mid_state = {
            "channel_values": {
                "iteration": 2,
                "phase": "take_action",
                "gathered_context": "Context from iteration 2",
                "messages": [
                    {"role": "user", "content": "Task"},
                    {"role": "assistant", "content": "Working on it..."},
                ],
                "current_draft": "Partial draft",
            },
            "channel_versions": {"iteration": 2},
        }

        config_copy = copy.deepcopy(config)
        memory_checkpointer.put(config_copy, mid_state)

        # 恢复
        recovered = memory_checkpointer.get(config)

        assert recovered["channel_values"]["iteration"] == 2
        assert recovered["channel_values"]["phase"] == "take_action"
        assert len(recovered["channel_values"]["messages"]) == 2
        assert recovered["channel_values"]["current_draft"] == "Partial draft"

    @pytest.mark.asyncio
    async def test_no_duplicate_work_after_recovery(self, memory_checkpointer):
        """测试恢复后不重复工作"""
        thread_id = "no_duplicate_test"
        config = {"configurable": {"thread_id": thread_id}}

        # 保存迭代2的完成状态
        completed_state = {
            "channel_values": {
                "iteration": 2,
                "completed_iterations": [1, 2],
                "work_done": ["task1", "task2"],
            },
            "channel_versions": {},
        }
        config_copy = copy.deepcopy(config)
        memory_checkpointer.put(config_copy, completed_state)

        # 恢复
        recovered = memory_checkpointer.get(config)

        # 应该从迭代2继续，不重复1和2
        assert 1 in recovered["channel_values"]["completed_iterations"]
        assert 2 in recovered["channel_values"]["completed_iterations"]

    @pytest.mark.asyncio
    async def test_context_preserved_across_checkpoints(self, memory_checkpointer):
        """测试上下文在检查点间保留"""
        thread_id = "context_preserve_test"
        config = {"configurable": {"thread_id": thread_id}}

        # 累积上下文
        contexts = []
        for i in range(3):
            contexts.append(f"Context piece {i}")
            config_copy = copy.deepcopy(config)
            memory_checkpointer.put(
                config_copy,
                {
                    "channel_values": {
                        "iteration": i + 1,
                        "accumulated_context": "\n".join(contexts),
                    },
                    "channel_versions": {},
                },
            )

        # 恢复最终上下文
        recovered = memory_checkpointer.get(config)
        accumulated = recovered["channel_values"]["accumulated_context"]

        assert "Context piece 0" in accumulated
        assert "Context piece 1" in accumulated
        assert "Context piece 2" in accumulated


class TestCrossInstanceRecovery:
    """跨实例恢复测试"""

    @pytest.mark.asyncio
    async def test_thread_id_identifies_state(self, checkpointer_factory):
        """测试线程 ID 标识状态"""
        thread_id = "cross_instance_thread"
        config = {"configurable": {"thread_id": thread_id}}

        # 实例 1 保存状态
        saver1 = checkpointer_factory("memory")
        saver1.put(
            copy.deepcopy(config),
            {
                "channel_values": {"instance": 1, "data": "from_instance_1"},
                "channel_versions": {},
            },
        )

        # 使用相同内存存储的实例 2（实际上是同一个对象）
        # 在实际场景中，这会是不同进程/容器中的实例
        saver2 = saver1  # 共享状态以模拟分布式存储

        # 实例 2 恢复状态
        recovered = saver2.get(config)

        assert recovered is not None
        assert recovered["channel_values"]["instance"] == 1

    @pytest.mark.asyncio
    async def test_different_threads_independent(self, memory_checkpointer):
        """测试不同线程独立"""
        thread1_config = {"configurable": {"thread_id": "thread_1"}}
        thread2_config = {"configurable": {"thread_id": "thread_2"}}

        # 为不同线程保存不同状态
        memory_checkpointer.put(
            copy.deepcopy(thread1_config),
            {
                "channel_values": {"thread": 1, "data": "thread1_data"},
                "channel_versions": {},
            },
        )
        memory_checkpointer.put(
            copy.deepcopy(thread2_config),
            {
                "channel_values": {"thread": 2, "data": "thread2_data"},
                "channel_versions": {},
            },
        )

        # 验证独立性
        thread1_state = memory_checkpointer.get(thread1_config)
        thread2_state = memory_checkpointer.get(thread2_config)

        assert thread1_state["channel_values"]["thread"] == 1
        assert thread2_state["channel_values"]["thread"] == 2
        assert (
            thread1_state["channel_values"]["data"]
            != thread2_state["channel_values"]["data"]
        )

    @pytest.mark.asyncio
    async def test_resume_with_same_thread_id(self, memory_checkpointer):
        """测试使用相同线程 ID 恢复"""
        thread_id = "resume_same_thread"

        # 第一次执行
        config1 = {"configurable": {"thread_id": thread_id}}
        memory_checkpointer.put(
            config1,
            {
                "channel_values": {
                    "execution": 1,
                    "progress": "50%",
                    "partial_result": "partial",
                },
                "channel_versions": {},
            },
        )

        # 模拟中断和恢复
        config2 = {"configurable": {"thread_id": thread_id}}
        recovered = memory_checkpointer.get(config2)

        assert recovered["channel_values"]["progress"] == "50%"

        # 继续执行
        memory_checkpointer.put(
            copy.deepcopy(config2),
            {
                "channel_values": {
                    "execution": 1,
                    "progress": "100%",
                    "partial_result": "partial",
                    "final_result": "complete",
                },
                "channel_versions": {},
            },
        )

        # 验证最终状态
        final = memory_checkpointer.get(config2)
        assert final["channel_values"]["progress"] == "100%"
        assert "final_result" in final["channel_values"]


class TestCheckpointPerformance:
    """检查点性能测试"""

    @pytest.mark.asyncio
    async def test_checkpoint_write_latency(self, memory_checkpointer):
        """测试检查点写入延迟"""
        thread_id = "perf_write_test"
        config = {"configurable": {"thread_id": thread_id}}

        state = TestDataGenerator.generate_agent_state(iteration=1)

        with PerformanceTimer("checkpoint_write") as timer:
            for i in range(10):
                config_copy = copy.deepcopy(config)
                state["iteration"] = i
                memory_checkpointer.put(
                    config_copy,
                    {"channel_values": state, "channel_versions": {"i": i}},
                )

        avg_latency = timer.elapsed_ms / 10
        assert avg_latency < 100, f"Average write latency {avg_latency}ms exceeds 100ms"

    @pytest.mark.asyncio
    async def test_checkpoint_read_latency(self, memory_checkpointer):
        """测试检查点读取延迟"""
        thread_id = "perf_read_test"
        config = {"configurable": {"thread_id": thread_id}}

        # 预先保存检查点
        memory_checkpointer.put(
            copy.deepcopy(config),
            {
                "channel_values": TestDataGenerator.generate_agent_state(1),
                "channel_versions": {},
            },
        )

        with PerformanceTimer("checkpoint_read") as timer:
            for _ in range(10):
                memory_checkpointer.get(config)

        avg_latency = timer.elapsed_ms / 10
        assert avg_latency < 50, f"Average read latency {avg_latency}ms exceeds 50ms"

    @pytest.mark.asyncio
    async def test_file_checkpoint_latency(self, file_checkpointer):
        """测试文件检查点延迟"""
        thread_id = "file_perf_test"
        config = {"configurable": {"thread_id": thread_id}}

        state = TestDataGenerator.generate_agent_state(iteration=1)

        # 写入延迟
        with PerformanceTimer("file_write") as write_timer:
            config_copy = copy.deepcopy(config)
            file_checkpointer.put(
                config_copy,
                {"channel_values": state, "channel_versions": {}},
            )

        # 读取延迟
        with PerformanceTimer("file_read") as read_timer:
            file_checkpointer.get(config)

        # 文件操作应该在合理范围内
        assert write_timer.elapsed_ms < 500
        assert read_timer.elapsed_ms < 100


class TestCheckpointEdgeCases:
    """检查点边界情况测试"""

    @pytest.mark.asyncio
    async def test_empty_checkpoint(self, memory_checkpointer):
        """测试空检查点"""
        thread_id = "empty_checkpoint_test"
        config = {"configurable": {"thread_id": thread_id}}

        memory_checkpointer.put(
            config,
            {"channel_values": {}, "channel_versions": {}},
        )

        retrieved = memory_checkpointer.get(config)
        assert retrieved is not None
        assert retrieved["channel_values"] == {}

    @pytest.mark.asyncio
    async def test_large_checkpoint(self, memory_checkpointer):
        """测试大型检查点"""
        thread_id = "large_checkpoint_test"
        config = {"configurable": {"thread_id": thread_id}}

        # 创建大型状态
        large_state = {
            "channel_values": {
                "large_context": TestDataGenerator.generate_large_context(size_kb=50),
                "messages": [
                    {"role": "user", "content": f"msg_{i}"} for i in range(100)
                ],
                "data": {"key_" + str(i): "value_" * 100 for i in range(50)},
            },
            "channel_versions": {},
        }

        memory_checkpointer.put(copy.deepcopy(config), large_state)

        retrieved = memory_checkpointer.get(config)
        assert retrieved is not None
        assert len(retrieved["channel_values"]["messages"]) == 100

    @pytest.mark.asyncio
    async def test_special_characters_in_state(self, memory_checkpointer):
        """测试状态中的特殊字符"""
        thread_id = "special_chars_test"
        config = {"configurable": {"thread_id": thread_id}}

        special_state = {
            "channel_values": {
                "unicode": "你好世界 🌍 مرحبا",
                "escape": "Line1\nLine2\tTabbed",
                "quotes": 'He said "Hello"',
                "json_string": '{"nested": "json"}',
            },
            "channel_versions": {},
        }

        memory_checkpointer.put(copy.deepcopy(config), special_state)

        retrieved = memory_checkpointer.get(config)
        assert retrieved["channel_values"]["unicode"] == "你好世界 🌍 مرحبا"
        assert retrieved["channel_values"]["escape"] == "Line1\nLine2\tTabbed"

    @pytest.mark.asyncio
    async def test_nonexistent_checkpoint(self, memory_checkpointer):
        """测试不存在的检查点"""
        config = {"configurable": {"thread_id": "nonexistent_thread"}}

        result = memory_checkpointer.get(config)
        assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_checkpoint_access(self, memory_checkpointer):
        """测试并发检查点访问"""
        thread_id = "concurrent_access_test"
        config = {"configurable": {"thread_id": thread_id}}

        # 并发写入
        async def write_checkpoint(index):
            config_copy = copy.deepcopy(config)
            memory_checkpointer.put(
                config_copy,
                {"channel_values": {"index": index}, "channel_versions": {}},
            )
            return index

        # 并发执行多个写入
        results = await asyncio.gather(*[write_checkpoint(i) for i in range(5)])

        assert len(results) == 5

        # 验证最终状态存在
        final = memory_checkpointer.get(config)
        assert final is not None

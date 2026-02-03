"""
多 Agent 工作流端到端测试

测试多 Agent 协作场景：
- 并行执行
- 顺序执行
- 工作空间隔离
- 上下文传递
"""

import pytest
import asyncio
from pathlib import Path
from typing import List, Dict, Any

from src.workspace.workspace import AgentWorkspace, WorkspaceConfig
from src.workspace.isolation import (
    IsolationLevel,
    ResourceLimits,
    IsolationManager,
    IsolatedWorkspaceBuilder,
)


class TestSubWorkspaceCreation:
    """子工作空间创建测试"""

    @pytest.fixture
    def parent_workspace(self, tmp_path):
        """创建父工作空间"""
        config = WorkspaceConfig(
            base_path=str(tmp_path),
            task_id="parent_task",
            auto_create=True,
        )
        return AgentWorkspace(config)

    def test_create_sub_workspace(self, parent_workspace):
        """测试创建子工作空间"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)
        sub_workspace, manager = builder.build(
            sub_task_id="sub_task_1",
            isolation_level=IsolationLevel.SOFT,
        )

        assert sub_workspace is not None
        assert sub_workspace.root.exists()
        assert manager is not None
        assert manager.level == IsolationLevel.SOFT

    def test_create_multiple_sub_workspaces(self, parent_workspace):
        """测试创建多个子工作空间"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        sub_workspaces = []
        for i in range(3):
            sub_ws, manager = builder.build(
                sub_task_id=f"sub_task_{i}",
                isolation_level=IsolationLevel.SOFT,
            )
            sub_workspaces.append((sub_ws, manager))

        assert len(sub_workspaces) == 3
        # Each sub-workspace should be unique
        paths = [ws.root for ws, _ in sub_workspaces]
        assert len(set(paths)) == 3


class TestParallelSubAgents:
    """并行子 Agent 测试"""

    @pytest.fixture
    def parent_workspace(self, tmp_path):
        """创建父工作空间"""
        config = WorkspaceConfig(
            base_path=str(tmp_path),
            task_id="parallel_parent",
            auto_create=True,
        )
        return AgentWorkspace(config)

    @pytest.mark.asyncio
    async def test_parallel_sub_agent_execution(self, parent_workspace):
        """测试并行子 Agent 执行"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        results: Dict[str, Any] = {}

        async def sub_agent_task(name: str, delay: float):
            """模拟子 Agent 任务"""
            sub_ws, _ = builder.build(
                sub_task_id=f"parallel_{name}",
                isolation_level=IsolationLevel.STRICT,
            )

            # Simulate work
            await asyncio.sleep(delay)

            # Write result
            result = {"agent": name, "status": "completed"}
            sub_ws.write_result(result)
            results[name] = result

            return result

        # Run sub-agents in parallel
        start_time = asyncio.get_event_loop().time()
        await asyncio.gather(
            sub_agent_task("agent_a", 0.1),
            sub_agent_task("agent_b", 0.1),
            sub_agent_task("agent_c", 0.1),
        )
        elapsed = asyncio.get_event_loop().time() - start_time

        # All should complete
        assert len(results) == 3
        # Parallel execution should be faster than sequential
        assert elapsed < 0.25  # Less than 3 * 0.1

    @pytest.mark.asyncio
    async def test_parallel_result_aggregation(self, parent_workspace):
        """测试并行结果聚合"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        async def compute_partial(index: int):
            sub_ws, _ = builder.build(
                sub_task_id=f"compute_{index}",
                isolation_level=IsolationLevel.STRICT,
            )

            # Each computes a partial result
            partial = {"index": index, "value": index * 10}
            sub_ws.write_result(partial)
            return partial

        # Compute in parallel
        partials = await asyncio.gather(*[compute_partial(i) for i in range(5)])

        # Aggregate results
        total = sum(p["value"] for p in partials)
        assert total == 0 + 10 + 20 + 30 + 40  # 100


class TestSequentialSubAgents:
    """顺序子 Agent 测试"""

    @pytest.fixture
    def parent_workspace(self, tmp_path):
        """创建父工作空间"""
        config = WorkspaceConfig(
            base_path=str(tmp_path),
            task_id="sequential_parent",
            auto_create=True,
        )
        return AgentWorkspace(config)

    @pytest.mark.asyncio
    async def test_sequential_pipeline(self, parent_workspace):
        """测试顺序流水线"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        # Stage 1: Extract
        extract_ws, _ = builder.build(
            sub_task_id="stage_extract",
            isolation_level=IsolationLevel.SOFT,
        )
        extract_result = {"data": [1, 2, 3, 4, 5]}
        extract_ws.write_result(extract_result)

        # Stage 2: Transform
        transform_ws, _ = builder.build(
            sub_task_id="stage_transform",
            isolation_level=IsolationLevel.SOFT,
        )
        # Read from previous stage
        transformed = [x * 2 for x in extract_result["data"]]
        transform_result = {"data": transformed}
        transform_ws.write_result(transform_result)

        # Stage 3: Load
        load_ws, _ = builder.build(
            sub_task_id="stage_load",
            isolation_level=IsolationLevel.SOFT,
        )
        load_result = {
            "loaded": len(transform_result["data"]),
            "total": sum(transform_result["data"]),
        }
        load_ws.write_result(load_result)

        # Verify final result
        final = load_ws.read_result()
        assert final["loaded"] == 5
        assert final["total"] == 30  # 2+4+6+8+10

    @pytest.mark.asyncio
    async def test_data_passing_between_stages(self, parent_workspace):
        """测试阶段间数据传递"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        # Create context file in parent
        context_content = "Initial context data"
        context_file = parent_workspace.context_dir / "shared_context.txt"
        context_file.write_text(context_content, encoding="utf-8")

        # Stage 1: Read and append to context
        stage1_ws, manager1 = builder.build(
            sub_task_id="stage_1",
            isolation_level=IsolationLevel.SOFT,
            shared_context=["context/shared_context.txt"],
        )

        # Read shared context
        shared_file = stage1_ws.root / "context" / "shared_context.txt"
        assert shared_file.exists()
        content = shared_file.read_text(encoding="utf-8")
        assert content == context_content


class TestSubAgentFailureHandling:
    """子 Agent 失败处理测试"""

    @pytest.fixture
    def parent_workspace(self, tmp_path):
        """创建父工作空间"""
        config = WorkspaceConfig(
            base_path=str(tmp_path),
            task_id="failure_parent",
            auto_create=True,
        )
        return AgentWorkspace(config)

    @pytest.mark.asyncio
    async def test_single_sub_agent_failure(self, parent_workspace):
        """测试单个子 Agent 失败"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        async def failing_task():
            sub_ws, _ = builder.build(
                sub_task_id="failing_agent",
                isolation_level=IsolationLevel.STRICT,
            )
            raise ValueError("Simulated failure")

        with pytest.raises(ValueError, match="Simulated failure"):
            await failing_task()

    @pytest.mark.asyncio
    async def test_partial_failure_in_parallel(self, parent_workspace):
        """测试并行执行中的部分失败"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        results = {}
        errors = {}

        async def sub_task(name: str, should_fail: bool):
            sub_ws, _ = builder.build(
                sub_task_id=f"partial_{name}",
                isolation_level=IsolationLevel.STRICT,
            )

            if should_fail:
                raise ValueError(f"{name} failed")

            result = {"agent": name, "status": "success"}
            sub_ws.write_result(result)
            return result

        # Run with one failing task
        tasks = [
            ("agent_a", False),
            ("agent_b", True),  # Will fail
            ("agent_c", False),
        ]

        for name, should_fail in tasks:
            try:
                result = await sub_task(name, should_fail)
                results[name] = result
            except ValueError as e:
                errors[name] = str(e)

        assert len(results) == 2
        assert len(errors) == 1
        assert "agent_b" in errors


class TestWorkspaceIsolation:
    """工作空间隔离测试"""

    @pytest.fixture
    def parent_workspace(self, tmp_path):
        """创建父工作空间"""
        config = WorkspaceConfig(
            base_path=str(tmp_path),
            task_id="isolation_parent",
            auto_create=True,
        )
        ws = AgentWorkspace(config)
        # Add some files to parent
        (ws.context_dir / "parent_file.txt").write_text("Parent data", encoding="utf-8")
        return ws

    def test_strict_isolation(self, parent_workspace):
        """测试严格隔离"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        sub_ws, manager = builder.build(
            sub_task_id="strict_sub",
            isolation_level=IsolationLevel.STRICT,
        )

        # Strict isolation should not allow reading parent
        assert manager.can_read_parent("context/parent_file.txt") is False

    def test_soft_isolation(self, parent_workspace):
        """测试软隔离"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        sub_ws, manager = builder.build(
            sub_task_id="soft_sub",
            isolation_level=IsolationLevel.SOFT,
        )

        # Soft isolation allows reading parent
        assert manager.can_read_parent("context/parent_file.txt") is True
        # But not writing
        assert manager.can_write_parent("context/parent_file.txt") is False

    def test_no_isolation(self, parent_workspace):
        """测试无隔离"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        sub_ws, manager = builder.build(
            sub_task_id="no_iso_sub",
            isolation_level=IsolationLevel.NONE,
        )

        # No isolation allows both read and write
        assert manager.can_read_parent("context/parent_file.txt") is True
        assert manager.can_write_parent("context/parent_file.txt") is True

    def test_resource_limits_per_sub_workspace(self, parent_workspace):
        """测试每个子工作空间的资源限制"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        # Create with resource limits - use correct parameter name
        limits = ResourceLimits(
            max_files=10,
            max_total_size=1024 * 1024,  # 1 MB (not max_total_size_bytes)
        )

        sub_ws, manager = builder.build(
            sub_task_id="limited_sub",
            isolation_level=IsolationLevel.SOFT,
            resource_limits=limits,
        )

        assert manager.limits.max_files == 10
        assert manager.limits.max_total_size == 1024 * 1024


class TestParentContextInheritance:
    """父工作空间上下文继承测试"""

    @pytest.fixture
    def parent_workspace(self, tmp_path):
        """创建带上下文的父工作空间"""
        config = WorkspaceConfig(
            base_path=str(tmp_path),
            task_id="inherit_parent",
            auto_create=True,
        )
        ws = AgentWorkspace(config)

        # Add context files
        (ws.context_dir / "config.json").write_text(
            '{"setting": "value"}', encoding="utf-8"
        )
        (ws.context_dir / "data.txt").write_text("Important data", encoding="utf-8")

        return ws

    def test_inherit_specific_context(self, parent_workspace):
        """测试继承特定上下文"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        sub_ws, manager = builder.build(
            sub_task_id="inherit_specific",
            isolation_level=IsolationLevel.SOFT,
            shared_context=["context/config.json"],
        )

        # Should have copied the config file
        copied_file = sub_ws.root / "context" / "config.json"
        assert copied_file.exists()

        content = copied_file.read_text(encoding="utf-8")
        assert "setting" in content

    def test_inherit_multiple_context_files(self, parent_workspace):
        """测试继承多个上下文文件"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        sub_ws, manager = builder.build(
            sub_task_id="inherit_multiple",
            isolation_level=IsolationLevel.SOFT,
            shared_context=[
                "context/config.json",
                "context/data.txt",
            ],
        )

        # Both files should be copied
        assert (sub_ws.root / "context" / "config.json").exists()
        assert (sub_ws.root / "context" / "data.txt").exists()


class TestSubWorkspaceCleanup:
    """子工作空间清理测试"""

    @pytest.fixture
    def parent_workspace(self, tmp_path):
        """创建父工作空间"""
        config = WorkspaceConfig(
            base_path=str(tmp_path),
            task_id="cleanup_parent",
            auto_create=True,
        )
        return AgentWorkspace(config)

    def test_sub_workspace_artifacts(self, parent_workspace):
        """测试子工作空间产出物"""
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        sub_ws, _ = builder.build(
            sub_task_id="artifact_sub",
            isolation_level=IsolationLevel.STRICT,
        )

        # Create some artifacts
        sub_ws.write_result({"status": "done"})
        (sub_ws.output_dir / "output.txt").write_text("Output data", encoding="utf-8")

        # Verify artifacts exist
        assert sub_ws.read_result() is not None
        assert (sub_ws.output_dir / "output.txt").exists()

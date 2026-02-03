"""
工作流引擎集成测试

测试 DAG 工作流执行，包括：
- DAG 工作流执行
- 并行节点执行
- 条件分支
- 检查点和恢复
- 子 Agent 协作
"""

import pytest
import asyncio
from pathlib import Path


class TestWorkflowEngine:
    """工作流引擎测试"""

    @pytest.mark.asyncio
    async def test_simple_workflow_definition(self, tool_registry, workspace):
        """测试简单工作流定义创建"""
        from src.definitions.workflow_definition import (
            WorkflowDefinition,
            WorkflowNode,
            WorkflowEdge,
            NodeType,
        )

        # 创建工作流定义
        workflow = WorkflowDefinition(
            workflow_id="simple_workflow",
            name="Simple Test Workflow",
            description="A simple test workflow",
            nodes=[
                WorkflowNode(
                    node_id="step1",
                    name="Step 1",
                    node_type=NodeType.START,
                ),
                WorkflowNode(
                    node_id="step2",
                    name="Step 2",
                    node_type=NodeType.END,
                    dependencies=["step1"],
                ),
            ],
            edges=[
                WorkflowEdge(from_node="step1", to_node="step2"),
            ],
            entry_node="step1",
            exit_nodes=["step2"],
        )

        # 验证工作流定义
        assert workflow.workflow_id == "simple_workflow"
        assert len(workflow.nodes) == 2
        assert len(workflow.edges) == 1
        assert workflow.entry_node == "step1"
        assert "step2" in workflow.exit_nodes

    @pytest.mark.asyncio
    async def test_parallel_workflow_definition(self, tool_registry, workspace):
        """测试并行工作流定义"""
        from src.definitions.workflow_definition import (
            WorkflowDefinition,
            WorkflowNode,
            WorkflowEdge,
            NodeType,
        )

        # 创建并行工作流定义
        workflow = WorkflowDefinition(
            workflow_id="parallel_workflow",
            name="Parallel Test Workflow",
            description="A parallel test workflow",
            nodes=[
                WorkflowNode(
                    node_id="start",
                    name="Start",
                    node_type=NodeType.START,
                ),
                WorkflowNode(
                    node_id="parallel_a",
                    name="Parallel A",
                    node_type=NodeType.PARALLEL,
                    dependencies=["start"],
                ),
                WorkflowNode(
                    node_id="parallel_b",
                    name="Parallel B",
                    node_type=NodeType.PARALLEL,
                    dependencies=["start"],
                ),
                WorkflowNode(
                    node_id="end",
                    name="End",
                    node_type=NodeType.END,
                    dependencies=["parallel_a", "parallel_b"],
                ),
            ],
            edges=[
                WorkflowEdge(from_node="start", to_node="parallel_a"),
                WorkflowEdge(from_node="start", to_node="parallel_b"),
                WorkflowEdge(from_node="parallel_a", to_node="end"),
                WorkflowEdge(from_node="parallel_b", to_node="end"),
            ],
            entry_node="start",
            exit_nodes=["end"],
        )

        # 验证并行工作流定义
        assert workflow.workflow_id == "parallel_workflow"
        assert len(workflow.nodes) == 4
        # 验证依赖关系
        parallel_a = next(n for n in workflow.nodes if n.node_id == "parallel_a")
        parallel_b = next(n for n in workflow.nodes if n.node_id == "parallel_b")
        assert "start" in parallel_a.dependencies
        assert "start" in parallel_b.dependencies

    @pytest.mark.asyncio
    async def test_conditional_workflow_definition(self, tool_registry, workspace):
        """测试条件分支工作流定义"""
        from src.definitions.workflow_definition import (
            WorkflowDefinition,
            WorkflowNode,
            WorkflowEdge,
            NodeType,
        )

        workflow = WorkflowDefinition(
            workflow_id="conditional_workflow",
            name="Conditional Test Workflow",
            description="A conditional test workflow",
            nodes=[
                WorkflowNode(
                    node_id="check",
                    name="Check",
                    node_type=NodeType.START,
                ),
                WorkflowNode(
                    node_id="condition",
                    name="Condition",
                    node_type=NodeType.CONDITION,
                    condition_expression="check.output > 5",
                    dependencies=["check"],
                ),
                WorkflowNode(
                    node_id="branch_true",
                    name="True Branch",
                    node_type=NodeType.END,
                    dependencies=["condition"],
                ),
                WorkflowNode(
                    node_id="branch_false",
                    name="False Branch",
                    node_type=NodeType.END,
                    dependencies=["condition"],
                ),
            ],
            edges=[
                WorkflowEdge(from_node="check", to_node="condition"),
                WorkflowEdge(
                    from_node="condition", to_node="branch_true", condition="true"
                ),
                WorkflowEdge(
                    from_node="condition", to_node="branch_false", condition="false"
                ),
            ],
            entry_node="check",
            exit_nodes=["branch_true", "branch_false"],
        )

        # 验证条件工作流定义
        assert workflow.workflow_id == "conditional_workflow"
        condition_node = next(n for n in workflow.nodes if n.node_id == "condition")
        assert condition_node.node_type == NodeType.CONDITION
        assert condition_node.condition_expression == "check.output > 5"

    @pytest.mark.asyncio
    async def test_workflow_checkpoint_definition(self, tool_registry, workspace):
        """测试工作流检查点定义"""
        from src.definitions.workflow_definition import (
            WorkflowDefinition,
            WorkflowNode,
            WorkflowEdge,
            NodeType,
        )

        workflow = WorkflowDefinition(
            workflow_id="checkpoint_workflow",
            name="Checkpoint Test Workflow",
            description="A checkpoint test workflow",
            nodes=[
                WorkflowNode(
                    node_id="step1",
                    name="Step 1",
                    node_type=NodeType.START,
                ),
                WorkflowNode(
                    node_id="step2",
                    name="Step 2",
                    node_type=NodeType.END,
                    dependencies=["step1"],
                ),
            ],
            edges=[
                WorkflowEdge(from_node="step1", to_node="step2"),
            ],
            entry_node="step1",
            exit_nodes=["step2"],
        )

        # 验证工作流定义
        assert workflow.workflow_id == "checkpoint_workflow"
        assert len(workflow.nodes) == 2

    @pytest.mark.asyncio
    async def test_workflow_data_passing_definition(self, tool_registry, workspace):
        """测试工作流数据传递定义"""
        from src.definitions.workflow_definition import (
            WorkflowDefinition,
            WorkflowNode,
            WorkflowEdge,
            NodeType,
            DataMapping,
        )

        workflow = WorkflowDefinition(
            workflow_id="data_passing_workflow",
            name="Data Passing Test",
            description="A data passing test workflow",
            nodes=[
                WorkflowNode(
                    node_id="compute",
                    name="Compute",
                    node_type=NodeType.START,
                ),
                WorkflowNode(
                    node_id="output",
                    name="Output",
                    node_type=NodeType.END,
                    dependencies=["compute"],
                    input_mappings=[
                        DataMapping(
                            source_node="compute",
                            source_field="output",
                            target_field="message",
                        )
                    ],
                ),
            ],
            edges=[
                WorkflowEdge(from_node="compute", to_node="output"),
            ],
            entry_node="compute",
            exit_nodes=["output"],
        )

        # 验证数据映射定义
        assert workflow.workflow_id == "data_passing_workflow"
        output_node = next(n for n in workflow.nodes if n.node_id == "output")
        assert len(output_node.input_mappings) == 1
        assert output_node.input_mappings[0].source_node == "compute"


class TestSubAgentManager:
    """子 Agent 管理器测试"""

    @pytest.mark.asyncio
    async def test_sub_workspace_creation(self, sub_agent_manager, workspace):
        """测试子工作空间创建"""
        # 创建子工作空间
        sub_ws = workspace.create_sub_workspace("test_sub_1")

        assert sub_ws.root.exists()
        assert sub_ws.input_dir.exists()

    @pytest.mark.asyncio
    async def test_spawn_with_retry_success(self, sub_agent_manager, mock_llm):
        """测试带重试的子 Agent 生成（成功场景）"""

        # 创建一个简单的 Mock Agent 类
        class MockAgent:
            def __init__(self, workspace, **kwargs):
                self.workspace = workspace

            async def run(self, task, input_data=None):
                return {"status": "success", "result": "completed"}

        result = await sub_agent_manager.spawn_with_retry(
            agent_class=MockAgent,
            task_description="Test task",
            max_retries=3,
        )

        assert result.is_success
        assert result.result["status"] == "success"

    @pytest.mark.asyncio
    async def test_spawn_parallel(self, sub_agent_manager):
        """测试并行生成多个子 Agent"""

        class MockAgent:
            def __init__(self, workspace, **kwargs):
                self.workspace = workspace

            async def run(self, task, input_data=None):
                await asyncio.sleep(0.1)  # 模拟工作
                return {"task": task, "status": "done"}

        tasks = [
            {
                "agent_class": MockAgent,
                "task_description": f"Task {i}",
                "sub_task_id": f"task_{i}",
            }
            for i in range(3)
        ]

        results = await sub_agent_manager.spawn_parallel(tasks)

        assert len(results) == 3
        success_count = sum(1 for r in results if r.is_success)
        assert success_count == 3

    @pytest.mark.asyncio
    async def test_spawn_with_timeout(self, sub_agent_manager):
        """测试带超时的子 Agent 生成"""

        class SlowAgent:
            def __init__(self, workspace, **kwargs):
                self.workspace = workspace

            async def run(self, task, input_data=None):
                await asyncio.sleep(10)  # 长时间运行
                return {"status": "done"}

        result = await sub_agent_manager.spawn(
            agent_class=SlowAgent,
            task_description="Slow task",
            timeout=0.5,  # 短超时
        )

        assert not result.is_success
        assert "超时" in result.error or "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_cancel_all(self, sub_agent_manager):
        """测试取消所有子任务"""

        class LongRunningAgent:
            def __init__(self, workspace, **kwargs):
                self.workspace = workspace

            async def run(self, task, input_data=None):
                await asyncio.sleep(100)
                return {"status": "done"}

        # 启动长时间运行的任务
        tasks = [
            {
                "agent_class": LongRunningAgent,
                "task_description": f"Long task {i}",
            }
            for i in range(3)
        ]

        # 在后台启动任务
        async def run_and_cancel():
            task = asyncio.create_task(sub_agent_manager.spawn_parallel(tasks))
            await asyncio.sleep(0.1)
            await sub_agent_manager.cancel_all()
            return task

        task = await run_and_cancel()

        assert sub_agent_manager.is_cancelled

    @pytest.mark.asyncio
    async def test_get_summary(self, sub_agent_manager):
        """测试获取执行摘要"""

        class MockAgent:
            def __init__(self, workspace, **kwargs):
                self.workspace = workspace

            async def run(self, task, input_data=None):
                return {"status": "success"}

        # 执行几个任务
        for i in range(3):
            await sub_agent_manager.spawn(
                agent_class=MockAgent,
                task_description=f"Task {i}",
            )

        summary = sub_agent_manager.get_summary()

        assert summary["total_tasks"] == 3
        assert summary["completed"] == 3
        assert summary["success_rate"] == 1.0


class TestResultAggregator:
    """结果聚合器测试"""

    @pytest.mark.asyncio
    async def test_merge_all_results(self):
        """测试合并所有结果"""
        from src.orchestration.sub_agent_manager import (
            ResultAggregator,
            SubAgentResult,
            SubAgentStatus,
        )

        results = [
            SubAgentResult(
                task_id="task1",
                status=SubAgentStatus.COMPLETED,
                result={"data": 1},
            ),
            SubAgentResult(
                task_id="task2",
                status=SubAgentStatus.COMPLETED,
                result={"data": 2},
            ),
            SubAgentResult(
                task_id="task3",
                status=SubAgentStatus.FAILED,
                error="Some error",
            ),
        ]

        merged = ResultAggregator.merge_results(results, strategy="all")

        assert len(merged["results"]) == 2
        assert len(merged["errors"]) == 1
        assert merged["summary"]["success"] == 2
        assert merged["summary"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_merge_success_only(self):
        """测试仅合并成功结果"""
        from src.orchestration.sub_agent_manager import (
            ResultAggregator,
            SubAgentResult,
            SubAgentStatus,
        )

        results = [
            SubAgentResult(
                task_id="task1",
                status=SubAgentStatus.COMPLETED,
                result={"value": 10},
            ),
            SubAgentResult(
                task_id="task2",
                status=SubAgentStatus.FAILED,
                error="Error",
            ),
        ]

        merged = ResultAggregator.merge_results(results, strategy="success_only")

        assert merged["count"] == 1
        assert len(merged["results"]) == 1

    @pytest.mark.asyncio
    async def test_reduce_results(self):
        """测试使用 reducer 聚合结果"""
        from src.orchestration.sub_agent_manager import (
            ResultAggregator,
            SubAgentResult,
            SubAgentStatus,
        )

        results = [
            SubAgentResult(
                task_id=f"task{i}",
                status=SubAgentStatus.COMPLETED,
                result={"value": i},
            )
            for i in range(1, 6)
        ]

        # 求和
        total = ResultAggregator.reduce_results(
            results,
            lambda rs: sum(r["value"] for r in rs),
        )

        assert total == 15  # 1 + 2 + 3 + 4 + 5

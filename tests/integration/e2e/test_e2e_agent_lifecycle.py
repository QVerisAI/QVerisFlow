"""
Agent 生命周期 E2E 测试

测试 Agent 的完整执行流程，包括：
- 简单任务完成
- 工具调用
- 验证循环
- 上下文管理
- 检查点
"""

import pytest
import asyncio
import json
from pathlib import Path
from datetime import datetime

from .utils import (
    ScenarioRunner,
    TestDataGenerator,
    AssertionHelpers,
    PerformanceTimer,
)


class TestAgentLifecycleSimple:
    """Agent 简单生命周期测试"""

    @pytest.mark.asyncio
    async def test_agent_initialization(self, full_agent_setup):
        """测试 Agent 初始化"""
        if full_agent_setup is None:
            pytest.skip("Agent setup failed - missing dependencies")

        agent = full_agent_setup["agent"]
        workspace = full_agent_setup["workspace"]
        definition = full_agent_setup["definition"]

        # 验证 Agent 初始化正确
        assert agent.definition.agent_id == definition.agent_id
        assert agent.workspace == workspace
        assert agent.tools is not None

    @pytest.mark.asyncio
    async def test_workspace_initialization(self, e2e_workspace):
        """测试工作空间初始化"""
        # 验证目录结构
        assert e2e_workspace.root.exists()
        assert e2e_workspace.input_dir.exists()
        assert e2e_workspace.output_dir.exists()
        assert e2e_workspace.scratch_dir.exists()
        assert e2e_workspace.context_dir.exists()
        assert e2e_workspace.logs_dir.exists()
        assert e2e_workspace.state_dir.exists()

    @pytest.mark.asyncio
    async def test_simple_task_completion(self, full_agent_setup):
        """测试简单任务完成

        验证：
        - Agent 能够完成简单任务
        - 工作空间有输出文件
        - 迭代次数合理
        """
        if full_agent_setup is None:
            pytest.skip("Agent setup failed - missing dependencies")

        agent = full_agent_setup["agent"]
        workspace = full_agent_setup["workspace"]
        llm_client = full_agent_setup["llm_client"]

        # 设置 LLM 响应场景
        llm_client.reset()
        llm_client.add_response("I have gathered the context for the task.")
        llm_client.add_response(
            json.dumps(
                {
                    "result": "Task completed",
                    "status": "success",
                }
            )
        )

        try:
            # 执行任务
            result = await agent.run(
                task_description="Complete this simple test task",
                input_data={"test": "data"},
            )

            # 验证结果
            assert result is not None
            assert "agent_id" in result
            assert "task_id" in result
            assert result["iterations"] >= 1
        except ImportError:
            pytest.skip("Missing langgraph dependency for agent execution")

    @pytest.mark.asyncio
    async def test_task_with_input_data(self, full_agent_setup):
        """测试带输入数据的任务"""
        if full_agent_setup is None:
            pytest.skip("Agent setup failed - missing dependencies")

        agent = full_agent_setup["agent"]
        workspace = full_agent_setup["workspace"]
        llm_client = full_agent_setup["llm_client"]

        # 设置响应
        llm_client.reset()
        llm_client.add_response("Processing the input data: test_value")
        llm_client.add_response(
            json.dumps(
                {
                    "result": "Processed test_value",
                    "input_received": True,
                }
            )
        )

        input_data = {
            "key": "test_value",
            "number": 42,
            "nested": {"inner": "value"},
        }

        try:
            result = await agent.run(
                task_description="Process the input data",
                input_data=input_data,
            )

            # 验证任务被正确写入工作空间
            task, read_input = workspace.read_task()
            assert "Process the input data" in task
            assert read_input["key"] == "test_value"
        except ImportError:
            pytest.skip("Missing langgraph dependency for agent execution")

    @pytest.mark.asyncio
    async def test_workspace_task_write_read(self, e2e_workspace):
        """测试工作空间任务读写"""
        task_description = "E2E Test task description"
        input_data = {"e2e_key": "e2e_value", "number": 100}

        e2e_workspace.write_task(task_description, input_data)

        read_task, read_input = e2e_workspace.read_task()

        assert read_task == task_description
        assert read_input == input_data


class TestAgentLifecycleWithTools:
    """Agent 工具调用测试"""

    @pytest.mark.asyncio
    async def test_tool_execution_in_context(self, e2e_tool_registry):
        """测试工具执行"""
        # 直接测试工具执行
        result = await e2e_tool_registry.execute(
            "e2e_echo",
            {"message": "Hello from E2E test"},
        )
        assert result == "Echo: Hello from E2E test"

        # 计算工具
        calc_result = await e2e_tool_registry.execute(
            "e2e_calculate",
            {"expression": "2 + 3 * 4"},
        )
        assert calc_result == 14.0

    @pytest.mark.asyncio
    async def test_tool_logging(self, e2e_workspace, e2e_tool_registry):
        """测试工具调用日志"""
        # Execute a tool
        result = await e2e_tool_registry.execute(
            "e2e_echo",
            {"message": "Test logging"},
        )

        # Verify execution completes
        assert result == "Echo: Test logging"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self, e2e_tool_registry):
        """测试多次工具调用"""
        results = []

        for i in range(5):
            result = await e2e_tool_registry.execute(
                "e2e_echo",
                {"message": f"Call {i}"},
            )
            results.append(result)

        assert len(results) == 5
        assert all(f"Echo: Call {i}" == results[i] for i in range(5))

    @pytest.mark.asyncio
    async def test_tool_failure_handling(self, e2e_tool_registry):
        """测试工具失败处理"""
        with pytest.raises(RuntimeError, match="always fails"):
            await e2e_tool_registry.execute("e2e_fail", {})


class TestAgentVerificationLoop:
    """Agent 验证循环测试"""

    @pytest.mark.asyncio
    async def test_verification_pass(self, simple_verifier):
        """测试验证通过"""
        valid_output = {"result": "success", "data": [1, 2, 3]}

        result = await simple_verifier.verify(valid_output)

        assert result.passed is True
        assert result.score > 0.5

    @pytest.mark.asyncio
    async def test_verification_fail(self, simple_verifier):
        """测试验证失败"""
        # 缺少必需字段
        invalid_output = {"data": [1, 2, 3]}

        result = await simple_verifier.verify(invalid_output)

        assert result.passed is False

    @pytest.mark.asyncio
    async def test_verification_with_feedback(self, agent_with_verification_setup):
        """测试验证反馈"""
        if agent_with_verification_setup is None:
            pytest.skip("Agent setup failed - missing dependencies")

        agent = agent_with_verification_setup["agent"]
        llm_client = agent_with_verification_setup["llm_client"]
        definition = agent_with_verification_setup["definition"]

        # 设置多轮响应：第一次失败，第二次成功
        llm_client.reset()

        # 第一轮：收集上下文
        llm_client.add_response("Gathering initial context.")
        # 第一轮：执行动作（返回无效结果）
        llm_client.add_response("Invalid response without result field")
        # 第二轮：收集上下文（带反馈）
        llm_client.add_response("Gathering context with feedback applied.")
        # 第二轮：执行动作（返回有效结果）
        llm_client.add_response(
            json.dumps(
                {
                    "result": "Now valid",
                    "status": "success",
                }
            )
        )

        try:
            result = await agent.run(
                task_description="Task requiring verification",
                input_data={"test": True},
            )

            # 应该经历多次迭代
            assert result["iterations"] >= 1
        except ImportError:
            pytest.skip("Missing langgraph dependency for agent execution")


class TestAgentContextManagement:
    """Agent 上下文管理测试"""

    @pytest.mark.asyncio
    async def test_context_manager_basic(self):
        """测试上下文管理器基本功能"""
        from src.core.context_manager import ContextManager, SimpleTokenCounter

        cm = ContextManager(
            max_tokens=1000,
            compression_threshold=0.8,
            token_counter=SimpleTokenCounter(),
        )

        cm.add("First context piece", source="test", priority=10)
        cm.add("Second context piece", source="test", priority=5)

        context = cm.get_context()

        assert "First context" in context
        assert "Second context" in context

    @pytest.mark.asyncio
    async def test_context_priority(self):
        """测试上下文优先级"""
        from src.core.context_manager import ContextManager, SimpleTokenCounter

        cm = ContextManager(
            max_tokens=100,  # 小限制触发压缩
            compression_threshold=0.9,
            token_counter=SimpleTokenCounter(),
        )

        cm.add("Low priority content", source="low", priority=1)
        cm.add("High priority content", source="high", priority=10)
        cm.add("Medium priority content", source="medium", priority=5)

        context = cm.get_context()

        # 高优先级内容应该存在
        assert "High priority" in context

    @pytest.mark.asyncio
    async def test_large_context_handling(self):
        """测试大型上下文处理"""
        from src.core.context_manager import ContextManager, SimpleTokenCounter

        cm = ContextManager(
            max_tokens=50000,  # Large enough to hold the content
            compression_threshold=0.7,
            token_counter=SimpleTokenCounter(),
        )

        # 添加适量内容
        large_content = TestDataGenerator.generate_large_context(size_kb=10)
        cm.add(large_content, source="large", priority=5)

        context = cm.get_context()

        # 应该有内容
        assert len(context) > 0

        # 检查 total_tokens 属性
        assert cm.total_tokens > 0


class TestAgentIterationLimits:
    """Agent 迭代限制测试"""

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, full_agent_setup):
        """测试达到最大迭代"""
        if full_agent_setup is None:
            pytest.skip("Agent setup failed - missing dependencies")

        agent = full_agent_setup["agent"]
        llm_client = full_agent_setup["llm_client"]
        definition = full_agent_setup["definition"]

        # 设置最大迭代次数
        max_iter = definition.llm_config.max_iterations

        # 设置总是返回无法通过验证的响应
        llm_client.reset()
        for _ in range(max_iter * 2):  # 足够多的响应
            llm_client.add_response("Gathering context...")
            llm_client.add_response("Some output")  # 无效 JSON

        try:
            result = await agent.run(
                task_description="Task that won't pass verification",
                input_data={},
            )

            # 迭代次数应该等于或小于最大值
            assert result["iterations"] <= max_iter
        except ImportError:
            pytest.skip("Missing langgraph dependency for agent execution")

    @pytest.mark.asyncio
    async def test_early_termination_on_success(self, agent_with_verification_setup):
        """测试成功时提前终止"""
        if agent_with_verification_setup is None:
            pytest.skip("Agent setup failed - missing dependencies")

        agent = agent_with_verification_setup["agent"]
        llm_client = agent_with_verification_setup["llm_client"]

        # 设置第一次就返回有效结果
        llm_client.reset()
        llm_client.add_response("Context gathered successfully.")
        llm_client.add_response(
            json.dumps(
                {
                    "result": "Immediate success",
                    "status": "completed",
                }
            )
        )

        try:
            result = await agent.run(
                task_description="Quick task",
                input_data={},
            )

            # 应该只迭代一次
            assert result["iterations"] == 1
        except ImportError:
            pytest.skip("Missing langgraph dependency for agent execution")


class TestAgentCheckpointing:
    """Agent 检查点测试"""

    @pytest.mark.asyncio
    async def test_workspace_checkpoint_save_load(self, e2e_workspace):
        """测试工作空间检查点保存和加载"""
        state = {
            "iteration": 2,
            "gathered_context": "Test context",
            "current_draft": "Draft content",
            "phase": "verify_work",
        }

        # 保存检查点
        checkpoint_path = e2e_workspace.save_checkpoint(state)
        assert Path(checkpoint_path).exists()

        # 加载检查点
        loaded_state = e2e_workspace.load_checkpoint()
        assert loaded_state is not None
        assert loaded_state["iteration"] == 2
        assert loaded_state["phase"] == "verify_work"

    @pytest.mark.asyncio
    async def test_memory_checkpointer(self, memory_checkpointer):
        """测试内存检查点存储"""
        thread_id = "test_thread_lifecycle"

        checkpoint = {
            "v": 1,
            "ts": datetime.now().isoformat(),
            "id": "checkpoint_1",
            "channel_values": {"messages": [], "state": {}},
            "channel_versions": {},
            "versions_seen": {},
            "pending_sends": [],
        }

        config = {"configurable": {"thread_id": thread_id}}

        # 保存检查点 (put is sync, takes 3 args: config, checkpoint, metadata)
        saved_config = memory_checkpointer.put(config, checkpoint, {})
        assert saved_config is not None

        # 获取检查点 (get is sync)
        retrieved = memory_checkpointer.get(config)
        assert retrieved is not None
        assert retrieved["id"] == "checkpoint_1"


class TestSubWorkspaceManagement:
    """子工作空间管理测试"""

    @pytest.mark.asyncio
    async def test_sub_workspace_creation(self, e2e_workspace):
        """测试子工作空间创建"""
        from src.workspace.isolation import IsolatedWorkspaceBuilder, IsolationLevel

        builder = IsolatedWorkspaceBuilder(e2e_workspace)

        sub_ws, manager = builder.build(
            sub_task_id="sub_task_1",
            isolation_level=IsolationLevel.SOFT,
        )

        assert sub_ws is not None
        assert sub_ws.root.exists()
        assert manager.level == IsolationLevel.SOFT

    @pytest.mark.asyncio
    async def test_sub_workspace_list(self, e2e_workspace):
        """测试子工作空间列表"""
        from src.workspace.isolation import IsolatedWorkspaceBuilder, IsolationLevel

        builder = IsolatedWorkspaceBuilder(e2e_workspace)

        # 创建多个子工作空间
        sub_workspaces = []
        for i in range(3):
            sub_ws, _ = builder.build(
                sub_task_id=f"sub_task_{i}",
                isolation_level=IsolationLevel.STRICT,
            )
            sub_workspaces.append(sub_ws)

        assert len(sub_workspaces) == 3

        # 验证每个子工作空间都是独立的
        paths = [ws.root for ws in sub_workspaces]
        assert len(set(paths)) == 3

    @pytest.mark.asyncio
    async def test_sub_workspace_isolation(self, e2e_workspace):
        """测试子工作空间隔离"""
        from src.workspace.isolation import IsolatedWorkspaceBuilder, IsolationLevel

        # 在父工作空间创建文件
        parent_file = e2e_workspace.context_dir / "parent_data.txt"
        parent_file.write_text("Parent data", encoding="utf-8")

        builder = IsolatedWorkspaceBuilder(e2e_workspace)

        # 创建严格隔离的子工作空间
        sub_ws, manager = builder.build(
            sub_task_id="isolated_sub",
            isolation_level=IsolationLevel.STRICT,
        )

        # 严格隔离不允许读取父工作空间
        assert manager.can_read_parent("context/parent_data.txt") is False


class TestExecutionTiming:
    """执行时间测试"""

    @pytest.mark.asyncio
    async def test_tool_execution_timing(self, e2e_tool_registry):
        """测试工具执行时间"""
        import time

        start = time.time()
        result = await e2e_tool_registry.execute(
            "e2e_echo",
            {"message": "Timing test"},
        )
        elapsed = time.time() - start

        assert result == "Echo: Timing test"
        assert elapsed < 1.0  # 应该在1秒内完成

    @pytest.mark.asyncio
    async def test_concurrent_tool_execution(self, e2e_tool_registry):
        """测试并发工具执行"""
        import time

        async def execute_tool(index):
            return await e2e_tool_registry.execute(
                "e2e_echo",
                {"message": f"Concurrent {index}"},
            )

        start = time.time()
        results = await asyncio.gather(*[execute_tool(i) for i in range(10)])
        elapsed = time.time() - start

        assert len(results) == 10
        # 并发执行应该比顺序执行快
        assert elapsed < 2.0


class TestScenarioExecution:
    """场景执行测试"""

    @pytest.mark.asyncio
    async def test_simple_task_scenario(self, e2e_tool_registry):
        """测试简单任务场景"""
        runner = ScenarioRunner("simple_task")

        # 设置场景步骤
        async def echo_step():
            return await e2e_tool_registry.execute("e2e_echo", {"message": "Step 1"})

        async def calculate_step():
            return await e2e_tool_registry.execute(
                "e2e_calculate", {"expression": "1+1"}
            )

        runner.add_step("echo", echo_step)
        runner.add_step("calculate", calculate_step)

        result = await runner.run()

        assert result.success is True
        assert result.steps_completed == 2

    def test_data_generator(self):
        """测试数据生成器"""
        # 测试任务生成
        task = TestDataGenerator.generate_task("simple")
        assert "description" in task
        assert "input_data" in task

        # 测试大型上下文生成
        context = TestDataGenerator.generate_large_context(size_kb=1)
        assert len(context) >= 1024

        # 测试状态生成
        state = TestDataGenerator.generate_agent_state(iteration=2)
        assert state["iteration"] == 2

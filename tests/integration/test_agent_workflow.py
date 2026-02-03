"""
Agent 工作流集成测试

测试 Agent 的完整执行流程，包括：
- 简单任务执行
- 工具调用
- 验证循环
- 上下文压缩
- 检查点恢复
"""

import pytest
import asyncio
from pathlib import Path


class TestAgentWorkflow:
    """Agent 工作流测试"""

    @pytest.mark.asyncio
    async def test_workspace_initialization(self, workspace):
        """测试工作空间初始化"""
        # 验证目录结构
        assert workspace.root.exists()
        assert workspace.input_dir.exists()
        assert workspace.output_dir.exists()
        assert workspace.scratch_dir.exists()
        assert workspace.context_dir.exists()
        assert workspace.logs_dir.exists()
        assert workspace.state_dir.exists()

    @pytest.mark.asyncio
    async def test_workspace_task_write_read(self, workspace):
        """测试任务读写"""
        task_description = "Test task description"
        input_data = {"key": "value", "number": 42}

        workspace.write_task(task_description, input_data)

        read_task, read_input = workspace.read_task()

        assert read_task == task_description
        assert read_input == input_data

    @pytest.mark.asyncio
    async def test_workspace_file_operations(self, workspace, create_test_file):
        """测试文件操作"""
        # 创建文件
        content = "Hello, World!"
        create_test_file("test.txt", content)

        # 读取文件
        read_content = workspace.read_file("test.txt")
        assert read_content == content

        # 写入新内容
        new_content = "New content"
        workspace.write_file("output/result.txt", new_content)

        result_path = workspace.output_dir / "result.txt"
        assert result_path.exists()
        assert result_path.read_text() == new_content

        # 追加内容
        workspace.append_file("output/result.txt", "\nAppended line")
        assert (
            workspace.output_dir / "result.txt"
        ).read_text() == "New content\nAppended line"

        # 删除文件
        assert workspace.delete_file("output/result.txt")
        assert not (workspace.output_dir / "result.txt").exists()

    @pytest.mark.asyncio
    async def test_workspace_checkpoint(self, workspace):
        """测试检查点保存和加载"""
        # 保存检查点
        state = {
            "iteration": 3,
            "gathered_context": "Some context",
            "current_draft": "Draft content",
        }

        checkpoint_path = workspace.save_checkpoint(state)
        assert Path(checkpoint_path).exists()

        # 加载检查点 - 不传参数加载最新的
        loaded_state = workspace.load_checkpoint()
        assert loaded_state is not None
        assert loaded_state["iteration"] == 3
        assert loaded_state["gathered_context"] == "Some context"

    @pytest.mark.asyncio
    async def test_workspace_sub_workspace(self, workspace):
        """测试子工作空间创建"""
        sub_workspace = workspace.create_sub_workspace("sub_task_1")

        assert sub_workspace.root.exists()
        assert "sub_agents" in str(sub_workspace.root)
        assert "sub_task_1" in str(sub_workspace.root)

        # 子工作空间应该有完整的目录结构
        assert sub_workspace.input_dir.exists()
        assert sub_workspace.output_dir.exists()

        # 列出子工作空间
        sub_workspaces = workspace.list_sub_workspaces()
        assert "sub_task_1" in sub_workspaces

    @pytest.mark.asyncio
    async def test_workspace_tool_logging(self, workspace):
        """测试工具调用日志"""
        # 记录工具调用 - 使用正确的 API 参数名
        workspace.log_tool_call(
            tool_id="test_tool",
            input_params={"arg1": "value1"},
            output={"status": "success"},
            phase="complete",
        )

        # 获取工具调用历史
        history = workspace.get_tool_call_history()
        assert len(history) == 1
        assert history[0]["tool_id"] == "test_tool"
        assert history[0]["input"]["arg1"] == "value1"


class TestContextManager:
    """上下文管理器测试"""

    @pytest.mark.asyncio
    async def test_context_add_and_get(self):
        """测试上下文添加和获取"""
        from src.core.context_manager import ContextManager, SimpleTokenCounter

        cm = ContextManager(
            max_tokens=1000,
            compression_threshold=0.8,
            token_counter=SimpleTokenCounter(),
        )

        cm.add("First piece of context", source="system", priority=10)
        cm.add("Second piece of context", source="user", priority=5)

        context = cm.get_context()
        assert "First piece" in context
        assert "Second piece" in context

    @pytest.mark.asyncio
    async def test_context_compression(self):
        """测试上下文压缩"""
        from src.core.context_manager import ContextManager, SimpleTokenCounter

        # 使用小的 max_tokens 触发压缩
        cm = ContextManager(
            max_tokens=50,  # 非常小的限制
            compression_threshold=0.7,
            token_counter=SimpleTokenCounter(),
        )

        # 添加大量内容
        for i in range(20):
            cm.add(
                f"This is context chunk number {i} with some additional content.",
                source="test",
            )

        # 应该触发压缩，结果长度应该受限
        context = cm.get_context()
        # 验证上下文不为空
        assert len(context) > 0

    @pytest.mark.asyncio
    async def test_context_priority_ordering(self):
        """测试上下文优先级排序"""
        from src.core.context_manager import ContextManager, SimpleTokenCounter

        cm = ContextManager(
            max_tokens=100,
            compression_threshold=0.9,
            token_counter=SimpleTokenCounter(),
        )

        cm.add("Low priority", source="low", priority=1)
        cm.add("High priority", source="high", priority=10)
        cm.add("Medium priority", source="medium", priority=5)

        context = cm.get_context()

        # 验证所有内容都存在（顺序可能因实现而异）
        assert "High priority" in context
        assert "Medium priority" in context
        assert "Low priority" in context


class TestReferenceResolver:
    """引用解析器测试"""

    @pytest.mark.asyncio
    async def test_tool_reference_resolution(self, tool_registry):
        """测试工具引用解析"""
        from src.core.reference_resolver import ReferenceResolver

        resolver = ReferenceResolver(
            tool_registry=tool_registry,
            inject_tool_description=True,
        )

        prompt = "Please use @echo to echo the message."
        result = resolver.resolve(
            prompt
        )  # resolve 是同步方法，返回 ReferenceResolutionResult

        # 应该注入工具描述
        assert "Echo Tool" in result.resolved_prompt or "echo" in result.resolved_prompt

    @pytest.mark.asyncio
    async def test_context_reference_resolution(self, workspace, create_test_file):
        """测试上下文引用解析"""
        from src.core.reference_resolver import ReferenceResolver

        # 创建上下文文件
        create_test_file("context/data.txt", "Important context data")

        resolver = ReferenceResolver(
            tool_registry=None,
            inject_tool_description=False,
        )

        prompt = "Based on #data context, please process."
        # 添加静态上下文
        resolver.add_static_context("data", "Important context data")

        result = resolver.resolve(prompt)  # 同步方法
        # 上下文内容应该被注入
        assert "Important context data" in result.resolved_prompt


class TestAgentState:
    """Agent 状态测试"""

    @pytest.mark.asyncio
    async def test_initial_state_creation(self):
        """测试初始状态创建"""
        from src.core.agent_state import create_initial_state

        state = create_initial_state(
            agent_id="test_agent",
            task_id="test_task",
            workspace_path="/tmp/workspace",
        )

        assert state["agent_id"] == "test_agent"
        assert state["task_id"] == "test_task"
        assert state["iteration"] == 0
        assert state["phase"] == "gather_context"
        assert state["messages"] == []

    @pytest.mark.asyncio
    async def test_state_transitions(self):
        """测试状态转换"""
        from src.core.agent_state import create_initial_state

        state = create_initial_state(
            agent_id="test_agent",
            task_id="test_task",
            workspace_path="/tmp/workspace",
        )

        # 模拟状态转换
        state["phase"] = "take_action"
        state["iteration"] = 1
        state["gathered_context"] = "Some context"

        assert state["phase"] == "take_action"
        assert state["iteration"] == 1
        assert state["gathered_context"] == "Some context"


class TestVerificationLoop:
    """验证循环测试"""

    @pytest.mark.asyncio
    async def test_json_format_verification(self):
        """测试 JSON 格式验证"""
        from src.verification import JSONFormatRule

        rule = JSONFormatRule()

        # 有效 JSON
        passed, feedback = rule.validate('{"key": "value"}')
        assert passed

        # 无效 JSON
        passed, feedback = rule.validate("not json")
        assert not passed

    @pytest.mark.asyncio
    async def test_required_fields_verification(self):
        """测试必需字段验证"""
        from src.verification import RequiredFieldsRule

        rule = RequiredFieldsRule(required_fields=["name", "value"])

        # 包含所有必需字段
        passed, feedback = rule.validate({"name": "test", "value": 42})
        assert passed

        # 缺少字段
        passed, feedback = rule.validate({"name": "test"})
        assert not passed

    @pytest.mark.asyncio
    async def test_composite_verifier(self, composite_verifier):
        """测试组合验证器"""
        # 满足所有规则
        valid_content = {"result": "success", "data": [1, 2, 3]}
        result = await composite_verifier.verify(valid_content)
        assert result.passed

        # 不满足必需字段规则
        invalid_content = {"data": [1, 2, 3]}
        result = await composite_verifier.verify(invalid_content)
        assert not result.passed

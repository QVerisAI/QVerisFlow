"""
集成测试 fixtures

提供集成测试所需的完整环境和 Mock 组件。
"""

import sys
import os
import pytest
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import tempfile
import shutil

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


# ==================== 异步支持 ====================


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ==================== 临时目录 ====================


@pytest.fixture
def temp_dir(tmp_path):
    """创建临时目录"""
    yield tmp_path
    # 清理
    if tmp_path.exists():
        shutil.rmtree(tmp_path, ignore_errors=True)


# ==================== Mock LLM 客户端 ====================


class MockLLMClient:
    """
    Mock LLM 客户端

    用于测试的可配置 LLM 响应模拟器。
    """

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.responses: List[Any] = []
        self.default_response = "This is a mock response."
        self.tool_calls: List[Dict[str, Any]] = []
        self._response_index = 0

    def set_response(self, response: Any):
        """设置下一个响应"""
        self.responses.append(response)

    def set_responses(self, responses: List[Any]):
        """设置多个响应"""
        self.responses.extend(responses)

    def reset(self):
        """重置所有记录"""
        self.calls.clear()
        self.responses.clear()
        self.tool_calls.clear()
        self._response_index = 0

    async def generate(self, prompt: str, **kwargs) -> str:
        """模拟生成文本"""
        self.calls.append({"type": "generate", "prompt": prompt, **kwargs})
        if self.responses:
            return self.responses.pop(0)
        return self.default_response

    async def call(
        self, messages: List[Dict], tools: List[Dict] = None, **kwargs
    ) -> Dict:
        """模拟完整的 LLM 调用"""
        self.calls.append(
            {"type": "call", "messages": messages, "tools": tools, **kwargs}
        )

        if self.responses:
            return self.responses.pop(0)

        # 默认响应
        return {
            "content": self.default_response,
            "tool_calls": [],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }

    def add_tool_call_response(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        content: Optional[str] = None,
    ):
        """添加一个包含工具调用的响应"""
        self.responses.append(
            {
                "content": content or "",
                "tool_calls": [
                    {
                        "id": f"call_{len(self.tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args),
                        },
                    }
                ],
            }
        )
        self.tool_calls.append({"name": tool_name, "args": tool_args})


@pytest.fixture
def mock_llm():
    """创建 Mock LLM 客户端"""
    return MockLLMClient()


# ==================== 工作空间 Fixtures ====================


@pytest.fixture
def workspace(temp_dir):
    """创建测试用工作空间"""
    from src.workspace.workspace import AgentWorkspace, WorkspaceConfig

    config = WorkspaceConfig(
        task_id="integration_test",
        base_path=str(temp_dir),
    )
    ws = AgentWorkspace(config)
    yield ws


# ==================== 工具注册表 Fixtures ====================


@pytest.fixture
def tool_registry():
    """创建独立的 ToolRegistry 实例"""
    from src.tools.registry import ToolRegistry
    from src.definitions import ToolDefinition, ToolCategory

    registry = ToolRegistry(validate_params=True)

    # 定义并注册测试工具

    # Echo 工具
    echo_def = ToolDefinition(
        tool_id="test_echo",
        name="Echo Tool",
        alias="echo",
        description="Returns the input as output",
        category=ToolCategory.SYSTEM,
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"}
            },
            "required": ["message"],
        },
        output_schema={"type": "string"},
    )

    async def echo_impl(message: str, **kwargs) -> str:
        return f"Echo: {message}"

    registry.register(echo_def, echo_impl)

    # Add 工具
    add_def = ToolDefinition(
        tool_id="test_add",
        name="Add Numbers",
        alias="add",
        description="Adds two numbers",
        category=ToolCategory.SYSTEM,
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
        output_schema={"type": "number"},
    )

    async def add_impl(a: float, b: float, **kwargs) -> float:
        return a + b

    registry.register(add_def, add_impl)

    # Fail 工具
    fail_def = ToolDefinition(
        tool_id="test_fail",
        name="Fail Tool",
        alias="fail",
        description="Always fails",
        category=ToolCategory.SYSTEM,
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "string"},
    )

    async def fail_impl(**kwargs) -> str:
        raise ValueError("This tool always fails!")

    registry.register(fail_def, fail_impl)

    yield registry
    registry.reset()


# ==================== Agent Definition Fixtures ====================


@pytest.fixture
def simple_agent_definition():
    """创建简单的 Agent 定义"""
    return {
        "id": "test_agent",
        "name": "Test Agent",
        "description": "A simple test agent",
        "prompts": {
            "background": "You are a helpful test agent.",
            "output": "Respond concisely.",
            "user": "Help the user with: {task}",
        },
        "tools": ["test_echo", "test_add"],
        "config": {
            "max_iterations": 3,
            "verification_enabled": False,
        },
    }


# ==================== Workflow Definition Fixtures ====================


@pytest.fixture
def simple_workflow_definition():
    """创建简单的工作流定义"""
    return {
        "id": "test_workflow",
        "name": "Test Workflow",
        "description": "A simple test workflow",
        "nodes": [
            {
                "id": "node_1",
                "type": "agent",
                "agent_id": "test_agent",
                "config": {},
            },
            {
                "id": "node_2",
                "type": "tool",
                "tool_id": "test_echo",
                "inputs": {"message": "${node_1.output}"},
            },
        ],
        "edges": [
            {"from_node": "node_1", "to_node": "node_2"},
        ],
        "start_node": "node_1",
        "end_nodes": ["node_2"],
    }


@pytest.fixture
def parallel_workflow_definition():
    """创建并行执行的工作流定义"""
    return {
        "id": "parallel_workflow",
        "name": "Parallel Workflow",
        "description": "A workflow with parallel execution",
        "nodes": [
            {
                "id": "start",
                "type": "tool",
                "tool_id": "test_echo",
                "inputs": {"message": "start"},
            },
            {
                "id": "parallel_1",
                "type": "tool",
                "tool_id": "test_add",
                "inputs": {"a": 1, "b": 2},
            },
            {
                "id": "parallel_2",
                "type": "tool",
                "tool_id": "test_add",
                "inputs": {"a": 3, "b": 4},
            },
            {
                "id": "end",
                "type": "tool",
                "tool_id": "test_echo",
                "inputs": {
                    "message": "sum: ${parallel_1.output} + ${parallel_2.output}"
                },
            },
        ],
        "edges": [
            {"from_node": "start", "to_node": "parallel_1"},
            {"from_node": "start", "to_node": "parallel_2"},
            {"from_node": "parallel_1", "to_node": "end"},
            {"from_node": "parallel_2", "to_node": "end"},
        ],
        "start_node": "start",
        "end_nodes": ["end"],
    }


# ==================== Verifier Fixtures ====================


@pytest.fixture
def composite_verifier():
    """创建组合验证器"""
    from src.verification import (
        CompositeVerifier,
        RuleBasedVerifier,
        JSONFormatRule,
        RequiredFieldsRule,
    )

    # 创建基于规则的验证器
    rule_verifier = RuleBasedVerifier(
        [
            JSONFormatRule(),
            RequiredFieldsRule(required_fields=["result"]),
        ]
    )

    # 组合验证器需要接收 BaseVerifier 列表
    return CompositeVerifier(verifiers=[rule_verifier])


# ==================== Evolution Fixtures ====================


@pytest.fixture
def prompt_optimizer(mock_llm, temp_dir):
    """创建 PromptOptimizer 实例"""
    from src.evolution.prompt_optimizer import PromptOptimizer

    return PromptOptimizer(
        llm_client=mock_llm,
        optimization_interval=10,
        storage_path=str(temp_dir / "prompt_optimizer"),
    )


@pytest.fixture
def version_control(temp_dir):
    """创建 VersionControl 实例"""
    from src.evolution.version_control import VersionControl

    return VersionControl(storage_path=str(temp_dir / "versions"))


@pytest.fixture
def ab_testing(temp_dir):
    """创建 ABTestingFramework 实例"""
    from src.evolution.ab_testing import ABTestingFramework

    return ABTestingFramework(storage_path=str(temp_dir / "experiments"))


# ==================== SubAgentManager Fixtures ====================


@pytest.fixture
def sub_agent_manager(workspace):
    """创建 SubAgentManager 实例"""
    from src.orchestration.sub_agent_manager import SubAgentManager

    return SubAgentManager(
        parent_workspace=workspace,
        max_parallel=3,
        default_timeout=30.0,
    )


# ==================== 辅助函数 ====================


@pytest.fixture
def create_test_file(workspace):
    """创建测试文件的辅助函数"""

    def _create(filename: str, content: str) -> Path:
        file_path = workspace.root / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return file_path

    return _create

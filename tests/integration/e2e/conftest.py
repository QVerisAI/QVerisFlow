"""
E2E 测试 fixtures

提供端到端集成测试所需的完整环境和 Mock 组件。
"""

import sys
import os
import pytest
import asyncio
import json
import tempfile
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from dataclasses import dataclass, field

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


# ==================== 异步支持 ====================


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ==================== Mock LLM 客户端 ====================


@dataclass
class LLMResponse:
    """LLM 响应数据"""

    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, int] = field(
        default_factory=lambda: {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
    )


class MockLLMWithScenarios:
    """
    支持多轮对话场景的 Mock LLM 客户端

    可以配置一系列响应，模拟真实的 LLM 交互流程。
    """

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.responses: List[LLMResponse] = []
        self.tool_responses: Dict[str, Any] = {}
        self._response_index = 0
        self.default_response = LLMResponse(content="Default mock response")

    def reset(self):
        """重置状态"""
        self.calls.clear()
        self.responses.clear()
        self.tool_responses.clear()
        self._response_index = 0

    def add_response(self, content: str, tool_calls: List[Dict] = None):
        """添加一个响应"""
        self.responses.append(LLMResponse(content=content, tool_calls=tool_calls or []))

    def add_tool_call_response(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        followed_by_content: str = "",
    ):
        """添加一个工具调用响应"""
        tool_call = {
            "id": f"call_{len(self.responses)}",
            "name": tool_name,
            "args": tool_args,
        }
        self.responses.append(
            LLMResponse(content=followed_by_content, tool_calls=[tool_call])
        )

    def set_scenario(self, scenario: List[Dict[str, Any]]):
        """
        设置完整的对话场景

        scenario: [
            {"type": "response", "content": "..."},
            {"type": "tool_call", "tool": "...", "args": {...}},
            {"type": "response", "content": "final answer"},
        ]
        """
        self.responses.clear()
        for step in scenario:
            if step["type"] == "response":
                self.add_response(step["content"])
            elif step["type"] == "tool_call":
                self.add_tool_call_response(
                    step["tool"],
                    step.get("args", {}),
                    step.get("content", ""),
                )

    def _get_next_response(self) -> LLMResponse:
        """获取下一个响应"""
        if self._response_index < len(self.responses):
            resp = self.responses[self._response_index]
            self._response_index += 1
            return resp
        return self.default_response

    async def ainvoke(self, messages: Any, **kwargs) -> Any:
        """异步调用（LangChain 兼容）"""
        self.calls.append(
            {
                "type": "ainvoke",
                "messages": messages,
                "kwargs": kwargs,
                "timestamp": datetime.now().isoformat(),
            }
        )

        resp = self._get_next_response()

        # 返回 LangChain 兼容的响应格式
        class MockAIMessage:
            def __init__(self, content, tool_calls):
                self.content = content
                self.tool_calls = tool_calls

        return MockAIMessage(resp.content, resp.tool_calls)

    async def agenerate(self, prompts: List[str], **kwargs) -> Dict:
        """异步生成"""
        self.calls.append(
            {
                "type": "agenerate",
                "prompts": prompts,
                "kwargs": kwargs,
            }
        )
        resp = self._get_next_response()
        return {"generations": [[{"text": resp.content}]]}

    def bind_tools(self, tools: List[Any]) -> "MockLLMWithScenarios":
        """绑定工具（返回自身以支持链式调用）"""
        return self

    def get_langchain_client(self) -> "MockLLMWithScenarios":
        """获取 LangChain 客户端（返回自身）"""
        return self


@pytest.fixture
def mock_llm():
    """创建 Mock LLM 客户端"""
    return MockLLMWithScenarios()


@pytest.fixture
def configured_llm_client(mock_llm):
    """
    配置好的 LLM 客户端

    预设了一些常用的响应场景
    """
    # 设置一个简单的成功场景
    mock_llm.add_response(
        content="I have gathered the context. The task requires analysis."
    )
    mock_llm.add_response(
        content=json.dumps(
            {
                "result": "Task completed successfully",
                "analysis": "Based on the context, I have completed the task.",
            }
        )
    )
    return mock_llm


# ==================== 工作空间 Fixtures ====================


@pytest.fixture
def e2e_workspace(tmp_path):
    """创建 E2E 测试用工作空间"""
    from src.workspace.workspace import AgentWorkspace, WorkspaceConfig

    config = WorkspaceConfig(
        task_id=f"e2e_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        base_path=str(tmp_path / "workspace"),
    )
    workspace = AgentWorkspace(config)
    yield workspace

    # 清理
    if workspace.root.exists():
        shutil.rmtree(workspace.root, ignore_errors=True)


# ==================== 工具注册表 Fixtures ====================


@pytest.fixture
def e2e_tool_registry():
    """创建 E2E 测试用工具注册表"""
    from src.tools.registry import ToolRegistry
    from src.definitions import ToolDefinition, ToolCategory

    registry = ToolRegistry(validate_params=True)

    # Echo 工具
    echo_def = ToolDefinition(
        tool_id="e2e_echo",
        name="Echo Tool",
        alias="echo",
        description="Returns the input message",
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

    # 计算工具
    calc_def = ToolDefinition(
        tool_id="e2e_calculate",
        name="Calculator",
        alias="calc",
        description="Performs arithmetic calculations",
        category=ToolCategory.SYSTEM,
        input_schema={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression"}
            },
            "required": ["expression"],
        },
        output_schema={"type": "number"},
    )

    async def calc_impl(expression: str, **kwargs) -> float:
        # 简单的安全计算
        allowed_chars = set("0123456789+-*/.()")
        if not all(c in allowed_chars or c.isspace() for c in expression):
            raise ValueError("Invalid expression")
        return eval(expression)  # 仅用于测试

    registry.register(calc_def, calc_impl)

    # 搜索工具（模拟）
    search_def = ToolDefinition(
        tool_id="e2e_search",
        name="Search Tool",
        alias="search",
        description="Searches for information",
        category=ToolCategory.WEB_SEARCH,
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
        output_schema={"type": "object"},
    )

    async def search_impl(query: str, **kwargs) -> Dict[str, Any]:
        return {
            "query": query,
            "results": [
                {"title": f"Result for {query}", "snippet": "Mock search result"},
            ],
            "total": 1,
        }

    registry.register(search_def, search_impl)

    # 失败工具（用于测试错误处理）
    fail_def = ToolDefinition(
        tool_id="e2e_fail",
        name="Failing Tool",
        alias="fail",
        description="Always fails for testing",
        category=ToolCategory.SYSTEM,
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "string"},
    )

    async def fail_impl(**kwargs) -> str:
        raise RuntimeError("This tool always fails!")

    registry.register(fail_def, fail_impl)

    # 可重试工具（有时失败）
    retry_state = {"attempts": 0}

    retry_def = ToolDefinition(
        tool_id="e2e_retry_tool",
        name="Retry Test Tool",
        alias="retry",
        description="Fails first N times then succeeds",
        category=ToolCategory.SYSTEM,
        input_schema={
            "type": "object",
            "properties": {"fail_times": {"type": "integer", "default": 2}},
        },
        output_schema={"type": "string"},
    )

    async def retry_impl(fail_times: int = 2, **kwargs) -> str:
        retry_state["attempts"] += 1
        if retry_state["attempts"] <= fail_times:
            raise RuntimeError(
                f"Transient failure {retry_state['attempts']}/{fail_times}"
            )
        result = f"Success after {retry_state['attempts']} attempts"
        retry_state["attempts"] = 0  # Reset for next test
        return result

    registry.register(retry_def, retry_impl)

    yield registry
    registry.reset()


# ==================== Agent Definition Fixtures ====================


@pytest.fixture
def simple_agent_definition():
    """创建简单的 Agent 定义"""
    from src.definitions import (
        AgentDefinition,
        BackgroundInstruction,
        OutputInstruction,
        UserInstruction,
        ModelConfig,
        ToolReference,
        ToolReferenceType,
    )

    return AgentDefinition(
        agent_id="e2e_test_agent",
        name="E2E Test Agent",
        description="An agent for E2E testing",
        background_instruction=BackgroundInstruction(
            role_description="You are a helpful test agent.",
            core_capability="You can perform various tasks for testing.",
            task_context="You are being tested for correct behavior.",
        ),
        output_instruction=OutputInstruction(
            format_type="json",
            format_requirements=["Output valid JSON"],
        ),
        user_instruction=UserInstruction(
            task_description="Complete the assigned task: {task}",
        ),
        llm_config=ModelConfig(
            model_name="mock-model",
            temperature=0.0,
            max_tokens=1000,
            max_iterations=3,
        ),
        tool_references=[
            ToolReference(
                tool_id="e2e_echo",
                alias="echo",
                tool_type=ToolReferenceType.BUILTIN,
                enabled=True,
            ),
            ToolReference(
                tool_id="e2e_calculate",
                alias="calc",
                tool_type=ToolReferenceType.BUILTIN,
                enabled=True,
            ),
            ToolReference(
                tool_id="e2e_search",
                alias="search",
                tool_type=ToolReferenceType.BUILTIN,
                enabled=True,
            ),
        ],
    )


@pytest.fixture
def agent_with_verification(simple_agent_definition):
    """带验证器的 Agent 定义"""
    simple_agent_definition.llm_config.max_iterations = 5
    return simple_agent_definition


# ==================== 检查点存储 Fixtures ====================


@pytest.fixture
def memory_checkpointer():
    """简单内存检查点存储 - 我们的自定义实现，用于独立 checkpoint 测试"""
    from src.storage.checkpointers import SimpleMemoryCheckpointSaver

    return SimpleMemoryCheckpointSaver()


@pytest.fixture
def langgraph_checkpointer():
    """LangGraph 兼容的检查点存储 - 用于 Agent 测试"""
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


@pytest.fixture
def file_checkpointer(tmp_path):
    """文件系统检查点存储"""
    from src.storage.checkpointers import FileCheckpointSaver

    checkpoint_path = tmp_path / "checkpoints"
    saver = FileCheckpointSaver(path=str(checkpoint_path))
    yield saver


@pytest.fixture
def checkpointer_factory(tmp_path):
    """检查点存储工厂"""
    from src.storage.checkpointers import (
        SimpleMemoryCheckpointSaver,
        FileCheckpointSaver,
    )

    def create(checkpointer_type: str = "memory"):
        if checkpointer_type == "memory":
            return SimpleMemoryCheckpointSaver()
        elif checkpointer_type == "file":
            return FileCheckpointSaver(path=str(tmp_path / "checkpoints"))
        else:
            raise ValueError(f"Unknown checkpointer type: {checkpointer_type}")

    return create


# ==================== 追踪存储 Fixtures ====================


@pytest.fixture
def file_trace_storage(tmp_path):
    """文件追踪存储"""
    from src.persistence.trace_storage import FileTraceStorage

    storage = FileTraceStorage(base_path=str(tmp_path / "traces"))
    yield storage


@pytest.fixture
def trace_storage_with_cleanup(tmp_path):
    """带自动清理的追踪存储"""
    from src.persistence.trace_storage import FileTraceStorage

    trace_path = tmp_path / "traces"
    storage = FileTraceStorage(base_path=str(trace_path))
    yield storage

    # 清理
    if trace_path.exists():
        shutil.rmtree(trace_path, ignore_errors=True)


# ==================== 验证器 Fixtures ====================


@pytest.fixture
def simple_verifier():
    """简单规则验证器"""
    from src.verification import RuleBasedVerifier, JSONFormatRule, RequiredFieldsRule

    return RuleBasedVerifier(
        [
            JSONFormatRule(),
            RequiredFieldsRule(required_fields=["result"]),
        ]
    )


@pytest.fixture
def composite_verifier():
    """组合验证器"""
    from src.verification import (
        CompositeVerifier,
        RuleBasedVerifier,
        JSONFormatRule,
        RequiredFieldsRule,
    )

    rule_verifier = RuleBasedVerifier(
        [
            JSONFormatRule(),
            RequiredFieldsRule(required_fields=["result"]),
        ]
    )

    return CompositeVerifier(verifiers=[rule_verifier])


# ==================== 完整 Agent 设置 ====================


@pytest.fixture
def full_agent_setup(
    e2e_workspace,
    e2e_tool_registry,
    configured_llm_client,
    simple_agent_definition,
    langgraph_checkpointer,
):
    """
    完整的 Agent 设置

    包含工作空间、工具注册表、LLM 客户端、检查点存储。
    使用 LangGraph 的 MemorySaver 以保证兼容性。
    """
    from src.core.base_agent import BaseAgent

    agent = BaseAgent(
        definition=simple_agent_definition,
        workspace=e2e_workspace,
        tool_registry=e2e_tool_registry,
        llm_client=configured_llm_client,
        checkpointer=langgraph_checkpointer,
    )

    return {
        "agent": agent,
        "workspace": e2e_workspace,
        "tool_registry": e2e_tool_registry,
        "llm_client": configured_llm_client,
        "checkpointer": langgraph_checkpointer,
        "definition": simple_agent_definition,
    }


@pytest.fixture
def agent_with_verification_setup(
    e2e_workspace,
    e2e_tool_registry,
    configured_llm_client,
    agent_with_verification,
    langgraph_checkpointer,
    simple_verifier,
):
    """带验证器的完整 Agent 设置，使用 LangGraph 的 MemorySaver"""
    from src.core.base_agent import BaseAgent

    agent = BaseAgent(
        definition=agent_with_verification,
        workspace=e2e_workspace,
        tool_registry=e2e_tool_registry,
        llm_client=configured_llm_client,
        verifier=simple_verifier,
        checkpointer=langgraph_checkpointer,
    )

    return {
        "agent": agent,
        "workspace": e2e_workspace,
        "tool_registry": e2e_tool_registry,
        "llm_client": configured_llm_client,
        "verifier": simple_verifier,
        "checkpointer": langgraph_checkpointer,
        "definition": agent_with_verification,
    }


# ==================== 性能监控 Fixtures ====================


@pytest.fixture
def performance_monitor():
    """性能监控器"""
    from src.evolution.performance_monitor import AgentPerformanceMonitor

    return AgentPerformanceMonitor()


# ==================== 追踪器 Fixtures ====================


@pytest.fixture
def tracer():
    """Agent 追踪器"""
    from src.observability.tracing import AgentTracer

    tracer = AgentTracer(service_name="e2e_test")
    yield tracer
    AgentTracer.reset_default()


@pytest.fixture
def metrics_collector():
    """指标收集器"""
    from src.observability.metrics import MetricsCollector

    return MetricsCollector()


# ==================== 辅助函数 ====================


@pytest.fixture
def create_test_file(e2e_workspace):
    """创建测试文件的辅助函数"""

    def _create(filename: str, content: str) -> Path:
        file_path = e2e_workspace.root / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return file_path

    return _create


@pytest.fixture
def wait_for_condition():
    """等待条件满足的辅助函数"""

    async def _wait(condition_fn, timeout: float = 5.0, interval: float = 0.1):
        import time

        start = time.time()
        while time.time() - start < timeout:
            if condition_fn():
                return True
            await asyncio.sleep(interval)
        return False

    return _wait

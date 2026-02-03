"""
pytest 配置和 fixtures

提供测试所需的共享 fixtures。
"""

import sys
import os
import pytest
import asyncio
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(project_root / "src") not in sys.path:
    sys.path.insert(0, str(project_root / "src"))


# ==================== 异步支持 ====================


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ==================== 工具系统 Fixtures ====================


@pytest.fixture
def tool_registry():
    """创建独立的 ToolRegistry 实例"""
    from src.tools.registry import ToolRegistry

    registry = ToolRegistry(validate_params=True)
    yield registry
    registry.reset()


@pytest.fixture
def tool_validator():
    """创建 ToolParameterValidator 实例"""
    from src.tools.validation import ToolParameterValidator

    return ToolParameterValidator(strict_mode=True, coerce_types=True)


# ==================== 上下文管理 Fixtures ====================


@pytest.fixture
def context_manager():
    """创建 ContextManager 实例"""
    from src.core.context_manager import ContextManager, SimpleTokenCounter

    return ContextManager(
        max_tokens=10000,
        compression_threshold=0.8,
        token_counter=SimpleTokenCounter(),
    )


# ==================== 引用解析 Fixtures ====================


@pytest.fixture
def reference_resolver(tool_registry):
    """创建 ReferenceResolver 实例"""
    from src.core.reference_resolver import ReferenceResolver

    return ReferenceResolver(
        tool_registry=tool_registry,
        inject_tool_description=True,
        inject_tool_schema=True,
    )


# ==================== 工作空间 Fixtures ====================


@pytest.fixture
def temp_workspace(tmp_path):
    """创建临时工作空间"""
    from src.workspace.workspace import AgentWorkspace, WorkspaceConfig

    config = WorkspaceConfig(
        task_id="test_task",
        base_path=str(tmp_path),
    )
    workspace = AgentWorkspace(config)
    workspace.initialize()
    yield workspace


# ==================== Mock LLM Fixtures ====================


@pytest.fixture
def mock_llm_client():
    """创建 Mock LLM 客户端"""

    class MockLLMClient:
        def __init__(self):
            self.calls = []
            self.responses = []
            self.default_response = "This is a mock response."

        def set_response(self, response):
            self.responses.append(response)

        async def generate(self, prompt, **kwargs):
            self.calls.append({"prompt": prompt, **kwargs})
            if self.responses:
                return self.responses.pop(0)
            return {"content": self.default_response}

        async def call(self, messages, **kwargs):
            self.calls.append({"messages": messages, **kwargs})
            if self.responses:
                return self.responses.pop(0)
            return {"content": self.default_response}

    return MockLLMClient()


# ==================== 验证器 Fixtures ====================


@pytest.fixture
def schema_verifier():
    """创建 SchemaVerifier 实例"""
    from src.verification.schema_verifier import SchemaVerifier

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "age": {"type": "integer", "minimum": 0},
            "email": {"type": "string"},
        },
        "required": ["name"],
    }

    return SchemaVerifier(schema, strict_mode=True)

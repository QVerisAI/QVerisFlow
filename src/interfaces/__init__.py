"""
核心接口定义

提供框架的核心抽象接口，支持：
- 依赖注入
- Mock 测试
- 扩展实现

接口列表：
- IToolRegistry: 工具注册表接口
- ITool: 工具接口
- IAgentExecutor: Agent 执行器接口
- IAgentState: Agent 状态接口
- IVerifier: 验证器接口
- IWorkspace: 工作空间接口
- IWorkflowEngine: 工作流引擎接口
"""

from .agent import IAgentExecutor, IAgentState
from .tool import IToolRegistry, ITool
from .verification import IVerifier, IVerificationResult
from .workspace import IWorkspace
from .workflow import IWorkflowEngine, IWorkflowNode

__all__ = [
    # Agent 接口
    "IAgentExecutor",
    "IAgentState",
    # 工具接口
    "IToolRegistry",
    "ITool",
    # 验证接口
    "IVerifier",
    "IVerificationResult",
    # 工作空间接口
    "IWorkspace",
    # 工作流接口
    "IWorkflowEngine",
    "IWorkflowNode",
]

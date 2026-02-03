"""编排层 - 工作流引擎、智能路由与子 Agent 管理"""

from .smart_router import SmartRouter, RoutingStrategy
from .workflow_engine import WorkflowEngine, WorkflowResult, NodeExecutionResult
from .hooks import HooksManager, HookEvent, HookAction, CommonHooks
from .sub_agent_manager import (
    SubAgentManager,
    SubAgentResult,
    SubAgentTask,
    SubAgentStatus,
    ResultAggregator,
)

__all__ = [
    # 智能路由
    "SmartRouter",
    "RoutingStrategy",
    # 工作流引擎
    "WorkflowEngine",
    "WorkflowResult",
    "NodeExecutionResult",
    # Hooks
    "HooksManager",
    "HookEvent",
    "HookAction",
    "CommonHooks",
    # 子 Agent 管理
    "SubAgentManager",
    "SubAgentResult",
    "SubAgentTask",
    "SubAgentStatus",
    "ResultAggregator",
]

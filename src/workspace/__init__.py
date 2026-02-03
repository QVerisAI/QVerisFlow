"""工作空间 - 文件系统交互与状态持久化"""

from .workspace import AgentWorkspace, WorkspaceConfig
from .isolation import (
    IsolationLevel,
    ResourceLimits,
    ResourceUsage,
    IsolationError,
    ResourceLimitExceededError,
    PathTraversalError,
    IsolationManager,
    IsolatedWorkspaceBuilder,
)

__all__ = [
    # 工作空间
    "AgentWorkspace",
    "WorkspaceConfig",
    # 隔离机制
    "IsolationLevel",
    "ResourceLimits",
    "ResourceUsage",
    "IsolationError",
    "ResourceLimitExceededError",
    "PathTraversalError",
    "IsolationManager",
    "IsolatedWorkspaceBuilder",
]

"""核心模块 - Agent 核心循环与状态管理"""

from .agent_state import AgentState, create_initial_state
from .agent_graph import AgentGraphBuilder
from .base_agent import BaseAgent
from .context_manager import (
    ContextManager,
    ContextChunk,
    TokenCounter,
    SimpleTokenCounter,
    TiktokenCounter,
)
from .reference_resolver import (
    ReferenceResolver,
    ReferenceResolutionResult,
    ResolvedReference,
    ContextProvider,
    WorkspaceContextProvider,
    DynamicContextProvider,
    get_default_resolver,
    set_default_resolver,
    resolve_references,
)
from ..storage.checkpointers import (
    BaseCheckpointSaver,
    RedisCheckpointSaver,
    PostgresCheckpointSaver,
    SimpleMemoryCheckpointSaver,
    FileCheckpointSaver,
    CheckpointerFactory,
)
from ..storage.config import (
    CheckpointerType,
    CheckpointStorageConfig as CheckpointerConfig,
)

__all__ = [
    # Agent 状态
    "AgentState",
    "create_initial_state",
    # Agent 图
    "AgentGraphBuilder",
    # Agent 基类
    "BaseAgent",
    # 上下文管理
    "ContextManager",
    "ContextChunk",
    "TokenCounter",
    "SimpleTokenCounter",
    "TiktokenCounter",
    # 引用解析
    "ReferenceResolver",
    "ReferenceResolutionResult",
    "ResolvedReference",
    "ContextProvider",
    "WorkspaceContextProvider",
    "DynamicContextProvider",
    "get_default_resolver",
    "set_default_resolver",
    "resolve_references",
    # 检查点存储
    "CheckpointerType",
    "CheckpointerConfig",
    "BaseCheckpointSaver",
    "RedisCheckpointSaver",
    "PostgresCheckpointSaver",
    "SimpleMemoryCheckpointSaver",
    "FileCheckpointSaver",
    "CheckpointerFactory",
]

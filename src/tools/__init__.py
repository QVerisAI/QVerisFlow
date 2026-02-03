"""工具系统 - 工具注册、引用解析与 LangChain 适配"""

from .registry import ToolRegistry, tool
from .adapters import LangChainToolAdapter, EnhancedToolRegistry
from .validation import (
    ToolParameterValidator,
    ToolValidationError,
    validate_tool_params,
    get_default_validator,
)

# 重试机制和熔断器
from .retry import (
    RetryPolicy,
    RetryExecutor,
    RetryResult,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
    RetryableError,
    NonRetryableError,
    CircuitBreakerOpenError,
    with_retry,
)

# 内置工具（导入即注册）
from .builtin import (
    file_ls,
    file_read,
    file_write,
    file_edit,
    file_append,
    bash_execute,
    bash_execute_safe,
    register_builtin_tools,
)

# QVeris 远程工具集成
from .qveris_client import (
    QVerisClient,
    QVerisSearchResult,
    QVerisExecuteResult,
    QVerisToolInfo,
    QVerisAPIError,
)
from .qveris_adapter import (
    QVerisToolAdapter,
    create_qveris_adapter,
)

__all__ = [
    # 注册表
    "ToolRegistry",
    "tool",
    "LangChainToolAdapter",
    "EnhancedToolRegistry",
    # 参数验证
    "ToolParameterValidator",
    "ToolValidationError",
    "validate_tool_params",
    "get_default_validator",
    # 重试和熔断器
    "RetryPolicy",
    "RetryExecutor",
    "RetryResult",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerRegistry",
    "CircuitState",
    "RetryableError",
    "NonRetryableError",
    "CircuitBreakerOpenError",
    "with_retry",
    # 内置工具
    "file_ls",
    "file_read",
    "file_write",
    "file_edit",
    "file_append",
    "bash_execute",
    "bash_execute_safe",
    "register_builtin_tools",
    # QVeris 远程工具
    "QVerisClient",
    "QVerisSearchResult",
    "QVerisExecuteResult",
    "QVerisToolInfo",
    "QVerisAPIError",
    "QVerisToolAdapter",
    "create_qveris_adapter",
]

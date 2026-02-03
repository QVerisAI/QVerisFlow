"""
共享工具模块
提供通用的工具函数
"""

from .logger import get_logger
from .timestamp import utc_now_naive
from .safe_eval import (
    safe_eval_condition,
    safe_eval_expression,
    validate_expression,
    SafeEvalError,
)
from .resilience import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    RateLimiter,
    SlidingWindowRateLimiter,
    RateLimitExceededError,
    retry,
    ResiliencePolicy,
)


# 延迟导入的模块（有外部依赖）
def get_claude_client():
    """获取 Claude SDK 客户端（延迟导入）"""
    from .claude_client import ClaudeSDKClient

    return ClaudeSDKClient


def get_unified_llm_client():
    """获取统一 LLM 客户端（延迟导入）"""
    from .llm_client import UnifiedLLMClient

    return UnifiedLLMClient


def get_token_tracker():
    """获取 Token 使用追踪器（延迟导入）"""
    from .token_usage_tracker import TokenUsageTracker, ModelCallMetrics

    return TokenUsageTracker, ModelCallMetrics


__all__ = [
    "get_logger",
    "utc_now_naive",
    # Safe evaluation
    "safe_eval_condition",
    "safe_eval_expression",
    "validate_expression",
    "SafeEvalError",
    # Resilience
    "CircuitBreaker",
    "CircuitState",
    "CircuitOpenError",
    "RateLimiter",
    "SlidingWindowRateLimiter",
    "RateLimitExceededError",
    "retry",
    "ResiliencePolicy",
    # Lazy imports
    "get_claude_client",
    "get_unified_llm_client",
    "get_token_tracker",
]

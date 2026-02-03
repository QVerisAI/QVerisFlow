"""
工具执行重试机制

提供完善的重试策略、熔断器和错误分类，确保工具执行的可靠性。

特性：
- 指数退避重试
- 熔断器模式
- 可配置的重试策略
- 错误分类和处理
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, TypeVar, Union
from functools import wraps

from src.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class RetryableError(Exception):
    """可重试的错误"""

    pass


class NonRetryableError(Exception):
    """不可重试的错误"""

    pass


class CircuitBreakerOpenError(Exception):
    """熔断器开启错误"""

    pass


class CircuitState(str, Enum):
    """熔断器状态"""

    CLOSED = "closed"  # 正常状态，允许请求
    OPEN = "open"  # 熔断状态，拒绝请求
    HALF_OPEN = "half_open"  # 半开状态，允许部分请求测试


@dataclass
class RetryPolicy:
    """
    重试策略配置

    定义重试行为的各项参数。

    用法:
        ```python
        policy = RetryPolicy(
            max_retries=5,
            base_delay=1.0,
            max_delay=30.0,
            exponential_base=2.0,
            jitter=True,
        )
        ```
    """

    # 基本配置
    max_retries: int = 3
    base_delay: float = 1.0  # 秒
    max_delay: float = 60.0  # 秒
    exponential_base: float = 2.0

    # 抖动配置（防止惊群效应）
    jitter: bool = True
    jitter_factor: float = 0.1  # 0-1 之间

    # 可重试的异常类型
    retryable_exceptions: Tuple[Type[Exception], ...] = (
        TimeoutError,
        ConnectionError,
        RetryableError,
    )

    # 不可重试的异常类型（优先级高于 retryable_exceptions）
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (
        NonRetryableError,
        ValueError,
        TypeError,
    )

    # 根据 HTTP 状态码判断是否重试
    retryable_status_codes: Set[int] = field(
        default_factory=lambda: {408, 429, 500, 502, 503, 504}
    )

    # 超时配置
    timeout_per_attempt: Optional[float] = None  # 每次尝试的超时时间

    def calculate_delay(self, attempt: int) -> float:
        """
        计算第 N 次重试的延迟时间

        使用指数退避算法，可选抖动。

        Args:
            attempt: 当前尝试次数（从 0 开始）

        Returns:
            延迟时间（秒）
        """
        delay = min(self.base_delay * (self.exponential_base**attempt), self.max_delay)

        if self.jitter:
            import random

            jitter_range = delay * self.jitter_factor
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0, delay)

    def should_retry(self, exception: Exception, attempt: int) -> bool:
        """
        判断是否应该重试

        Args:
            exception: 捕获的异常
            attempt: 当前尝试次数

        Returns:
            是否应该重试
        """
        # 检查重试次数
        if attempt >= self.max_retries:
            return False

        # 检查不可重试异常
        if isinstance(exception, self.non_retryable_exceptions):
            return False

        # 检查可重试异常
        if isinstance(exception, self.retryable_exceptions):
            return True

        # 检查 HTTP 状态码
        if hasattr(exception, "status_code"):
            return exception.status_code in self.retryable_status_codes

        # 默认不重试未知异常
        return False


@dataclass
class CircuitBreakerConfig:
    """
    熔断器配置

    定义熔断器的行为参数。
    """

    # 触发熔断的失败阈值
    failure_threshold: int = 5

    # 熔断恢复时间（秒）
    recovery_timeout: float = 30.0

    # 半开状态允许的测试请求数
    half_open_max_calls: int = 3

    # 成功率阈值（半开状态恢复到关闭状态）
    success_threshold: float = 0.5

    # 滑动窗口大小（用于计算失败率）
    window_size: int = 10


class CircuitBreaker:
    """
    熔断器

    实现熔断器模式，在连续失败时暂时阻止请求，
    防止雪崩效应。

    状态转换：
    - CLOSED -> OPEN: 失败次数达到阈值
    - OPEN -> HALF_OPEN: 恢复时间到达
    - HALF_OPEN -> CLOSED: 测试请求成功率达标
    - HALF_OPEN -> OPEN: 测试请求失败

    用法:
        ```python
        breaker = CircuitBreaker(name="my_tool")

        if breaker.can_execute():
            try:
                result = await execute_tool()
                breaker.record_success()
            except Exception as e:
                breaker.record_failure()
                raise
        else:
            raise CircuitBreakerOpenError("Circuit breaker is open")
        ```
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        """
        初始化熔断器

        Args:
            name: 熔断器名称（通常是工具 ID）
            config: 熔断器配置
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._half_open_calls = 0

        # 滑动窗口记录
        self._recent_results: List[bool] = []

    @property
    def state(self) -> CircuitState:
        """获取当前状态"""
        self._check_state_transition()
        return self._state

    @property
    def is_open(self) -> bool:
        """熔断器是否开启"""
        return self.state == CircuitState.OPEN

    def can_execute(self) -> bool:
        """
        检查是否可以执行

        Returns:
            是否允许执行
        """
        state = self.state

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.HALF_OPEN:
            # 半开状态下限制请求数
            return self._half_open_calls < self.config.half_open_max_calls

        # OPEN 状态不允许执行
        return False

    def record_success(self) -> None:
        """记录成功"""
        self._recent_results.append(True)
        self._trim_window()

        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            self._half_open_calls += 1

            # 检查是否可以恢复到 CLOSED
            if self._half_open_calls >= self.config.half_open_max_calls:
                success_rate = self._success_count / self._half_open_calls
                if success_rate >= self.config.success_threshold:
                    self._transition_to_closed()
                else:
                    self._transition_to_open()
        else:
            self._failure_count = 0

    def record_failure(self) -> None:
        """记录失败"""
        self._recent_results.append(False)
        self._trim_window()
        self._last_failure_time = datetime.now()

        if self._state == CircuitState.HALF_OPEN:
            # 半开状态下失败直接熔断
            self._transition_to_open()
        else:
            self._failure_count += 1

            # 检查是否需要熔断
            if self._failure_count >= self.config.failure_threshold:
                self._transition_to_open()

    def reset(self) -> None:
        """重置熔断器"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._half_open_calls = 0
        self._recent_results = []
        logger.info(f"熔断器 {self.name} 已重置")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        success_count = sum(1 for r in self._recent_results if r)
        failure_count = len(self._recent_results) - success_count

        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "recent_success": success_count,
            "recent_failure": failure_count,
            "last_failure_time": (
                self._last_failure_time.isoformat() if self._last_failure_time else None
            ),
        }

    def _check_state_transition(self) -> None:
        """检查状态转换"""
        if self._state == CircuitState.OPEN and self._last_failure_time:
            elapsed = (datetime.now() - self._last_failure_time).total_seconds()
            if elapsed >= self.config.recovery_timeout:
                self._transition_to_half_open()

    def _transition_to_open(self) -> None:
        """转换到 OPEN 状态"""
        self._state = CircuitState.OPEN
        self._last_failure_time = datetime.now()
        logger.warning(f"熔断器 {self.name} 开启")

    def _transition_to_half_open(self) -> None:
        """转换到 HALF_OPEN 状态"""
        self._state = CircuitState.HALF_OPEN
        self._half_open_calls = 0
        self._success_count = 0
        logger.info(f"熔断器 {self.name} 进入半开状态")

    def _transition_to_closed(self) -> None:
        """转换到 CLOSED 状态"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        logger.info(f"熔断器 {self.name} 关闭（恢复正常）")

    def _trim_window(self) -> None:
        """修剪滑动窗口"""
        while len(self._recent_results) > self.config.window_size:
            self._recent_results.pop(0)


class CircuitBreakerRegistry:
    """
    熔断器注册表

    管理多个工具的熔断器实例。
    """

    _instance: Optional["CircuitBreakerRegistry"] = None

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._default_config = CircuitBreakerConfig()

    @classmethod
    def get_default(cls) -> "CircuitBreakerRegistry":
        """获取默认实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_default(cls) -> None:
        """重置默认实例"""
        cls._instance = None

    def get_breaker(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        """
        获取或创建熔断器

        Args:
            name: 熔断器名称
            config: 熔断器配置（仅在创建时使用）

        Returns:
            熔断器实例
        """
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                config=config or self._default_config,
            )
        return self._breakers[name]

    def set_default_config(self, config: CircuitBreakerConfig) -> None:
        """设置默认配置"""
        self._default_config = config

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有熔断器的统计信息"""
        return {name: breaker.get_stats() for name, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        """重置所有熔断器"""
        for breaker in self._breakers.values():
            breaker.reset()


@dataclass
class RetryResult:
    """重试执行结果"""

    success: bool
    result: Any = None
    exception: Optional[Exception] = None
    attempts: int = 0
    total_delay: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "attempts": self.attempts,
            "total_delay": self.total_delay,
            "error": str(self.exception) if self.exception else None,
        }


class RetryExecutor:
    """
    重试执行器

    封装重试逻辑和熔断器，提供统一的工具执行接口。

    用法:
        ```python
        executor = RetryExecutor(
            policy=RetryPolicy(max_retries=3),
            circuit_breaker=CircuitBreaker("my_tool"),
        )

        result = await executor.execute(
            func=my_async_function,
            args=(arg1, arg2),
            kwargs={"key": "value"},
        )

        if result.success:
            print(result.result)
        else:
            print(f"Failed after {result.attempts} attempts: {result.exception}")
        ```
    """

    def __init__(
        self,
        policy: Optional[RetryPolicy] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        on_retry: Optional[Callable[[int, Exception, float], None]] = None,
    ):
        """
        初始化重试执行器

        Args:
            policy: 重试策略
            circuit_breaker: 熔断器
            on_retry: 重试回调函数 (attempt, exception, delay)
        """
        self.policy = policy or RetryPolicy()
        self.circuit_breaker = circuit_breaker
        self.on_retry = on_retry

    async def execute(
        self,
        func: Callable[..., Any],
        args: Tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> RetryResult:
        """
        执行函数（带重试和熔断）

        Args:
            func: 要执行的函数（同步或异步）
            args: 位置参数
            kwargs: 关键字参数

        Returns:
            执行结果
        """
        kwargs = kwargs or {}

        # 检查熔断器
        if self.circuit_breaker and not self.circuit_breaker.can_execute():
            return RetryResult(
                success=False,
                exception=CircuitBreakerOpenError(
                    f"Circuit breaker '{self.circuit_breaker.name}' is open"
                ),
                attempts=0,
            )

        attempt = 0
        total_delay = 0.0
        last_exception: Optional[Exception] = None

        while attempt <= self.policy.max_retries:
            try:
                # 执行函数
                if asyncio.iscoroutinefunction(func):
                    if self.policy.timeout_per_attempt:
                        result = await asyncio.wait_for(
                            func(*args, **kwargs),
                            timeout=self.policy.timeout_per_attempt,
                        )
                    else:
                        result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                # 成功
                if self.circuit_breaker:
                    self.circuit_breaker.record_success()

                return RetryResult(
                    success=True,
                    result=result,
                    attempts=attempt + 1,
                    total_delay=total_delay,
                )

            except Exception as e:
                last_exception = e

                # 记录熔断器失败
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure()

                # 检查是否应该重试
                if not self.policy.should_retry(e, attempt):
                    logger.warning(f"不再重试: attempt={attempt + 1}, error={e}")
                    break

                # 计算延迟
                delay = self.policy.calculate_delay(attempt)
                total_delay += delay

                # 回调
                if self.on_retry:
                    self.on_retry(attempt, e, delay)

                logger.info(
                    f"重试 {attempt + 1}/{self.policy.max_retries}: "
                    f"delay={delay:.2f}s, error={e}"
                )

                # 等待
                await asyncio.sleep(delay)
                attempt += 1

        return RetryResult(
            success=False,
            exception=last_exception,
            attempts=attempt + 1,
            total_delay=total_delay,
        )

    def execute_sync(
        self,
        func: Callable[..., T],
        args: Tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> RetryResult:
        """
        同步执行函数（带重试和熔断）

        Args:
            func: 要执行的同步函数
            args: 位置参数
            kwargs: 关键字参数

        Returns:
            执行结果
        """
        kwargs = kwargs or {}

        # 检查熔断器
        if self.circuit_breaker and not self.circuit_breaker.can_execute():
            return RetryResult(
                success=False,
                exception=CircuitBreakerOpenError(
                    f"Circuit breaker '{self.circuit_breaker.name}' is open"
                ),
                attempts=0,
            )

        attempt = 0
        total_delay = 0.0
        last_exception: Optional[Exception] = None

        while attempt <= self.policy.max_retries:
            try:
                result = func(*args, **kwargs)

                # 成功
                if self.circuit_breaker:
                    self.circuit_breaker.record_success()

                return RetryResult(
                    success=True,
                    result=result,
                    attempts=attempt + 1,
                    total_delay=total_delay,
                )

            except Exception as e:
                last_exception = e

                if self.circuit_breaker:
                    self.circuit_breaker.record_failure()

                if not self.policy.should_retry(e, attempt):
                    break

                delay = self.policy.calculate_delay(attempt)
                total_delay += delay

                if self.on_retry:
                    self.on_retry(attempt, e, delay)

                time.sleep(delay)
                attempt += 1

        return RetryResult(
            success=False,
            exception=last_exception,
            attempts=attempt + 1,
            total_delay=total_delay,
        )


def with_retry(
    policy: Optional[RetryPolicy] = None,
    circuit_breaker_name: Optional[str] = None,
):
    """
    重试装饰器

    用法:
        ```python
        @with_retry(policy=RetryPolicy(max_retries=3))
        async def fetch_data():
            ...

        @with_retry(circuit_breaker_name="api_client")
        async def call_api():
            ...
        ```
    """

    def decorator(func: Callable):
        executor_policy = policy or RetryPolicy()

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 获取熔断器
            breaker = None
            if circuit_breaker_name:
                registry = CircuitBreakerRegistry.get_default()
                breaker = registry.get_breaker(circuit_breaker_name)

            executor = RetryExecutor(
                policy=executor_policy,
                circuit_breaker=breaker,
            )

            result = await executor.execute(func, args, kwargs)

            if result.success:
                return result.result
            else:
                raise result.exception

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            breaker = None
            if circuit_breaker_name:
                registry = CircuitBreakerRegistry.get_default()
                breaker = registry.get_breaker(circuit_breaker_name)

            executor = RetryExecutor(
                policy=executor_policy,
                circuit_breaker=breaker,
            )

            result = executor.execute_sync(func, args, kwargs)

            if result.success:
                return result.result
            else:
                raise result.exception

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# 导出
__all__ = [
    # 异常
    "RetryableError",
    "NonRetryableError",
    "CircuitBreakerOpenError",
    # 枚举
    "CircuitState",
    # 配置
    "RetryPolicy",
    "CircuitBreakerConfig",
    # 核心类
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "RetryExecutor",
    "RetryResult",
    # 装饰器
    "with_retry",
]

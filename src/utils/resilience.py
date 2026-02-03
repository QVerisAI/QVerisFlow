"""
弹性工具模块

提供断路器（Circuit Breaker）和限流器（Rate Limiter）等弹性设计模式实现，
用于提高系统的容错能力和稳定性。
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic
from functools import wraps
from collections import deque

from src.utils.logger import get_logger

logger = get_logger()

T = TypeVar("T")


# ==================== 断路器 ====================


class CircuitState(str, Enum):
    """断路器状态"""

    CLOSED = "closed"  # 闭合状态，正常运行
    OPEN = "open"  # 打开状态，快速失败
    HALF_OPEN = "half_open"  # 半开状态，尝试恢复


@dataclass
class CircuitBreakerState:
    """断路器状态数据"""

    failures: int = 0  # 连续失败次数
    successes: int = 0  # 半开状态下的连续成功次数
    last_failure_time: Optional[datetime] = None  # 最后失败时间
    state: CircuitState = CircuitState.CLOSED  # 当前状态
    total_calls: int = 0  # 总调用次数
    total_failures: int = 0  # 总失败次数


class CircuitBreaker:
    """
    断路器

    实现断路器模式，当服务连续失败达到阈值时，快速失败而不是继续尝试。
    这可以防止级联失败，并给失败的服务恢复时间。

    状态转换:
    - CLOSED -> OPEN: 连续失败达到阈值
    - OPEN -> HALF_OPEN: 恢复超时后
    - HALF_OPEN -> CLOSED: 测试调用成功达到阈值
    - HALF_OPEN -> OPEN: 测试调用失败

    用法:
        # 作为装饰器
        @CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        async def call_external_api():
            ...

        # 作为上下文管理器
        async with circuit_breaker:
            result = await call_external_api()
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        success_threshold: int = 3,
        name: str = "default",
        on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None,
    ):
        """
        初始化断路器

        Args:
            failure_threshold: 触发断路器打开的连续失败次数
            recovery_timeout: 断路器打开后的恢复超时时间（秒）
            success_threshold: 半开状态下恢复到闭合状态所需的连续成功次数
            name: 断路器名称（用于日志和监控）
            on_state_change: 状态变化回调函数
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.name = name
        self.on_state_change = on_state_change

        self._state = CircuitBreakerState()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """获取当前状态"""
        return self._state.state

    @property
    def is_closed(self) -> bool:
        return self._state.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self._state.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        return self._state.state == CircuitState.HALF_OPEN

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "name": self.name,
            "state": self._state.state.value,
            "failures": self._state.failures,
            "total_calls": self._state.total_calls,
            "total_failures": self._state.total_failures,
            "failure_rate": (
                self._state.total_failures / self._state.total_calls
                if self._state.total_calls > 0
                else 0
            ),
            "last_failure_time": (
                self._state.last_failure_time.isoformat()
                if self._state.last_failure_time
                else None
            ),
        }

    async def _check_state(self) -> bool:
        """
        检查当前状态并决定是否允许调用

        Returns:
            是否允许调用
        """
        async with self._lock:
            if self._state.state == CircuitState.CLOSED:
                return True

            if self._state.state == CircuitState.OPEN:
                # 检查是否应该转换到半开状态
                if self._state.last_failure_time:
                    elapsed = datetime.now() - self._state.last_failure_time
                    if elapsed.total_seconds() >= self.recovery_timeout:
                        self._transition_to(CircuitState.HALF_OPEN)
                        return True
                return False

            # HALF_OPEN 状态允许尝试
            return True

    def _transition_to(self, new_state: CircuitState):
        """状态转换"""
        old_state = self._state.state
        if old_state == new_state:
            return

        self._state.state = new_state

        if new_state == CircuitState.CLOSED:
            self._state.failures = 0
            self._state.successes = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._state.successes = 0

        logger.info(
            f"断路器 [{self.name}] 状态转换: {old_state.value} -> {new_state.value}"
        )

        if self.on_state_change:
            try:
                self.on_state_change(old_state, new_state)
            except Exception as e:
                logger.warning(f"断路器状态变化回调失败: {e}")

    async def _on_success(self):
        """调用成功时的处理"""
        async with self._lock:
            self._state.total_calls += 1

            if self._state.state == CircuitState.HALF_OPEN:
                self._state.successes += 1
                if self._state.successes >= self.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
            else:
                self._state.failures = 0

    async def _on_failure(self, error: Exception):
        """调用失败时的处理"""
        async with self._lock:
            self._state.total_calls += 1
            self._state.total_failures += 1
            self._state.failures += 1
            self._state.last_failure_time = datetime.now()

            if self._state.state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)
            elif self._state.failures >= self.failure_threshold:
                self._transition_to(CircuitState.OPEN)

    async def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """
        通过断路器调用函数

        Args:
            func: 要调用的函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数返回值

        Raises:
            CircuitOpenError: 断路器打开时
            原始异常: 函数调用失败时
        """
        if not await self._check_state():
            raise CircuitOpenError(f"断路器 [{self.name}] 处于打开状态，拒绝调用")

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            await self._on_success()
            return result

        except Exception as e:
            await self._on_failure(e)
            raise

    def __call__(self, func: Callable) -> Callable:
        """装饰器模式"""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.call(func, *args, **kwargs)

        return wrapper

    async def __aenter__(self):
        """异步上下文管理器入口"""
        if not await self._check_state():
            raise CircuitOpenError(f"断路器 [{self.name}] 处于打开状态")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if exc_type is None:
            await self._on_success()
        else:
            await self._on_failure(exc_val)
        return False  # 不抑制异常

    def reset(self):
        """重置断路器状态"""
        self._state = CircuitBreakerState()
        logger.info(f"断路器 [{self.name}] 已重置")


class CircuitOpenError(Exception):
    """断路器打开异常"""

    pass


# ==================== 限流器 ====================


class RateLimiter:
    """
    限流器

    实现令牌桶算法，控制调用频率。

    用法:
        # 作为装饰器
        @RateLimiter(max_calls=10, period=60)
        async def call_api():
            ...

        # 显式获取令牌
        limiter = RateLimiter(max_calls=10, period=60)
        await limiter.acquire()
        await call_api()
    """

    def __init__(
        self,
        max_calls: int,
        period: float = 60.0,
        name: str = "default",
    ):
        """
        初始化限流器

        Args:
            max_calls: 时间窗口内的最大调用次数
            period: 时间窗口大小（秒）
            name: 限流器名称
        """
        self.max_calls = max_calls
        self.period = period
        self.name = name

        self._tokens = max_calls
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

        # 统计信息
        self._total_calls = 0
        self._rejected_calls = 0

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "name": self.name,
            "max_calls": self.max_calls,
            "period": self.period,
            "available_tokens": self._tokens,
            "total_calls": self._total_calls,
            "rejected_calls": self._rejected_calls,
            "rejection_rate": (
                self._rejected_calls / self._total_calls if self._total_calls > 0 else 0
            ),
        }

    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        获取令牌（等待直到可用或超时）

        Args:
            timeout: 最大等待时间（秒），None 表示无限等待

        Returns:
            是否成功获取令牌
        """
        start_time = time.monotonic()

        while True:
            async with self._lock:
                self._refill_tokens()

                if self._tokens >= 1:
                    self._tokens -= 1
                    self._total_calls += 1
                    return True

            # 检查超时
            if timeout is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    self._rejected_calls += 1
                    return False

            # 计算下一个令牌到达时间
            wait_time = self.period / self.max_calls
            if timeout is not None:
                remaining = timeout - (time.monotonic() - start_time)
                wait_time = min(wait_time, remaining)

            await asyncio.sleep(wait_time)

    async def try_acquire(self) -> bool:
        """
        尝试获取令牌（立即返回）

        Returns:
            是否成功获取令牌
        """
        async with self._lock:
            self._refill_tokens()

            if self._tokens >= 1:
                self._tokens -= 1
                self._total_calls += 1
                return True

            self._rejected_calls += 1
            return False

    def _refill_tokens(self):
        """补充令牌"""
        now = time.monotonic()
        elapsed = now - self._last_update

        # 计算应该补充的令牌数
        tokens_to_add = elapsed * (self.max_calls / self.period)
        self._tokens = min(self.max_calls, self._tokens + tokens_to_add)
        self._last_update = now

    def __call__(self, func: Callable) -> Callable:
        """装饰器模式"""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            acquired = await self.acquire()
            if not acquired:
                raise RateLimitExceededError(
                    f"限流器 [{self.name}] 拒绝调用: 达到速率限制"
                )

            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)

        return wrapper

    async def __aenter__(self):
        """异步上下文管理器"""
        acquired = await self.acquire()
        if not acquired:
            raise RateLimitExceededError(f"限流器 [{self.name}] 拒绝调用")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


class RateLimitExceededError(Exception):
    """速率限制异常"""

    pass


# ==================== 滑动窗口限流器 ====================


class SlidingWindowRateLimiter:
    """
    滑动窗口限流器

    使用滑动窗口算法，提供更精确的限流控制。
    """

    def __init__(
        self,
        max_calls: int,
        window_size: float = 60.0,
        name: str = "default",
    ):
        """
        初始化滑动窗口限流器

        Args:
            max_calls: 窗口内的最大调用次数
            window_size: 窗口大小（秒）
            name: 限流器名称
        """
        self.max_calls = max_calls
        self.window_size = window_size
        self.name = name

        self._timestamps: deque = deque()
        self._lock = asyncio.Lock()

        # 统计
        self._total_calls = 0
        self._rejected_calls = 0

    async def acquire(self) -> bool:
        """获取令牌"""
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_size

            # 移除过期的时间戳
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

            if len(self._timestamps) < self.max_calls:
                self._timestamps.append(now)
                self._total_calls += 1
                return True

            self._rejected_calls += 1
            return False

    async def wait_and_acquire(self, timeout: Optional[float] = None) -> bool:
        """等待并获取令牌"""
        start = time.monotonic()

        while True:
            if await self.acquire():
                return True

            if timeout is not None:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    return False

            await asyncio.sleep(0.1)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "max_calls": self.max_calls,
            "window_size": self.window_size,
            "current_calls": len(self._timestamps),
            "total_calls": self._total_calls,
            "rejected_calls": self._rejected_calls,
        }


# ==================== 重试装饰器 ====================


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
):
    """
    重试装饰器

    使用指数退避策略进行重试。

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间（秒）
        max_delay: 最大延迟时间（秒）
        exponential_base: 指数退避的基数
        exceptions: 需要重试的异常类型
        on_retry: 重试时的回调函数

    用法:
        @retry(max_retries=3, base_delay=1.0)
        async def call_api():
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    if asyncio.iscoroutinefunction(func):
                        return await func(*args, **kwargs)
                    else:
                        return func(*args, **kwargs)

                except exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        # 计算延迟时间
                        delay = min(base_delay * (exponential_base**attempt), max_delay)

                        logger.warning(
                            f"调用失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}, "
                            f"{delay:.1f}秒后重试"
                        )

                        if on_retry:
                            try:
                                on_retry(attempt, e)
                            except Exception:
                                pass

                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"调用失败，已达最大重试次数: {e}")

            raise last_exception

        return wrapper

    return decorator


# ==================== 组合使用 ====================


class ResiliencePolicy:
    """
    弹性策略组合

    组合断路器、限流器和重试策略。
    """

    def __init__(
        self,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        name: str = "default",
    ):
        """
        初始化弹性策略

        Args:
            circuit_breaker: 断路器实例
            rate_limiter: 限流器实例
            max_retries: 最大重试次数
            base_delay: 基础重试延迟
            name: 策略名称
        """
        self.name = name
        self.circuit_breaker = circuit_breaker
        self.rate_limiter = rate_limiter
        self.max_retries = max_retries
        self.base_delay = base_delay

    async def execute(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        通过弹性策略执行函数

        Args:
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数返回值
        """
        # 限流检查
        if self.rate_limiter:
            acquired = await self.rate_limiter.try_acquire()
            if not acquired:
                raise RateLimitExceededError(f"策略 [{self.name}] 限流: 请求被拒绝")

        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                # 断路器检查
                if self.circuit_breaker:
                    return await self.circuit_breaker.call(func, *args, **kwargs)
                else:
                    if asyncio.iscoroutinefunction(func):
                        return await func(*args, **kwargs)
                    else:
                        return func(*args, **kwargs)

            except CircuitOpenError:
                raise

            except Exception as e:
                last_exception = e

                if attempt < self.max_retries:
                    delay = self.base_delay * (2**attempt)
                    logger.warning(
                        f"策略 [{self.name}] 调用失败 ({attempt + 1}/{self.max_retries + 1}): "
                        f"{e}, {delay:.1f}秒后重试"
                    )
                    await asyncio.sleep(delay)

        raise last_exception

    def __call__(self, func: Callable) -> Callable:
        """装饰器模式"""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.execute(func, *args, **kwargs)

        return wrapper

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {"name": self.name}

        if self.circuit_breaker:
            stats["circuit_breaker"] = self.circuit_breaker.get_stats()

        if self.rate_limiter:
            stats["rate_limiter"] = self.rate_limiter.get_stats()

        return stats


# 导出
__all__ = [
    # 断路器
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerState",
    "CircuitOpenError",
    # 限流器
    "RateLimiter",
    "SlidingWindowRateLimiter",
    "RateLimitExceededError",
    # 重试
    "retry",
    # 组合策略
    "ResiliencePolicy",
]

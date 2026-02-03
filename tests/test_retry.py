"""
工具执行重试机制测试

测试 RetryPolicy, CircuitBreaker, RetryExecutor 的各项功能。
"""

import asyncio
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock

from src.tools.retry import (
    RetryPolicy,
    RetryableError,
    NonRetryableError,
    CircuitState,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    RetryExecutor,
    RetryResult,
    with_retry,
)


class TestRetryPolicy:
    """RetryPolicy 测试"""

    def test_default_values(self):
        """测试默认值"""
        policy = RetryPolicy()

        assert policy.max_retries == 3
        assert policy.base_delay == 1.0
        assert policy.max_delay == 60.0
        assert policy.exponential_base == 2.0
        assert policy.jitter is True

    def test_calculate_delay_exponential(self):
        """测试指数退避延迟计算"""
        policy = RetryPolicy(
            base_delay=1.0, exponential_base=2.0, max_delay=60.0, jitter=False
        )

        assert policy.calculate_delay(0) == 1.0  # 1 * 2^0 = 1
        assert policy.calculate_delay(1) == 2.0  # 1 * 2^1 = 2
        assert policy.calculate_delay(2) == 4.0  # 1 * 2^2 = 4
        assert policy.calculate_delay(3) == 8.0  # 1 * 2^3 = 8

    def test_calculate_delay_max_cap(self):
        """测试延迟上限"""
        policy = RetryPolicy(
            base_delay=10.0, exponential_base=2.0, max_delay=30.0, jitter=False
        )

        assert policy.calculate_delay(0) == 10.0
        assert policy.calculate_delay(1) == 20.0
        assert policy.calculate_delay(2) == 30.0  # capped at max_delay
        assert policy.calculate_delay(3) == 30.0  # capped at max_delay

    def test_calculate_delay_with_jitter(self):
        """测试带抖动的延迟"""
        policy = RetryPolicy(base_delay=10.0, jitter=True, jitter_factor=0.1)

        delay = policy.calculate_delay(0)
        # 延迟应该在 9.0 到 11.0 之间 (10 ± 10%)
        assert 9.0 <= delay <= 11.0

    def test_should_retry_max_retries(self):
        """测试最大重试次数"""
        policy = RetryPolicy(max_retries=3)

        assert policy.should_retry(RetryableError(), 0) is True
        assert policy.should_retry(RetryableError(), 1) is True
        assert policy.should_retry(RetryableError(), 2) is True
        assert policy.should_retry(RetryableError(), 3) is False  # 达到上限

    def test_should_retry_retryable_exception(self):
        """测试可重试异常"""
        policy = RetryPolicy()

        assert policy.should_retry(RetryableError(), 0) is True
        assert policy.should_retry(TimeoutError(), 0) is True
        assert policy.should_retry(ConnectionError(), 0) is True

    def test_should_retry_non_retryable_exception(self):
        """测试不可重试异常"""
        policy = RetryPolicy()

        assert policy.should_retry(NonRetryableError(), 0) is False
        assert policy.should_retry(ValueError(), 0) is False
        assert policy.should_retry(TypeError(), 0) is False

    def test_should_retry_unknown_exception(self):
        """测试未知异常（默认不重试）"""
        policy = RetryPolicy()

        assert policy.should_retry(RuntimeError(), 0) is False


class TestCircuitBreaker:
    """CircuitBreaker 测试"""

    def test_initial_state(self):
        """测试初始状态"""
        breaker = CircuitBreaker("test")

        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_open is False
        assert breaker.can_execute() is True

    def test_record_success(self):
        """测试记录成功"""
        breaker = CircuitBreaker("test")
        breaker.record_success()

        assert breaker.state == CircuitState.CLOSED

    def test_record_failure_threshold(self):
        """测试失败阈值触发熔断"""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("test", config)

        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        breaker.record_failure()  # 达到阈值
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open is True
        assert breaker.can_execute() is False

    def test_recovery_timeout(self):
        """测试恢复超时"""
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1)
        breaker = CircuitBreaker("test", config)

        # 触发熔断
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # 等待恢复超时
        time.sleep(0.15)

        # 应该转换到半开状态
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.can_execute() is True

    def test_half_open_success(self):
        """测试半开状态成功恢复"""
        config = CircuitBreakerConfig(
            failure_threshold=1, recovery_timeout=0.1, half_open_max_calls=1
        )
        breaker = CircuitBreaker("test", config)

        # 触发熔断
        breaker.record_failure()
        time.sleep(0.15)

        # 进入半开状态
        assert breaker.state == CircuitState.HALF_OPEN

        # 成功后恢复
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_failure(self):
        """测试半开状态失败重新熔断"""
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1)
        breaker = CircuitBreaker("test", config)

        # 触发熔断
        breaker.record_failure()
        time.sleep(0.15)

        # 进入半开状态
        assert breaker.state == CircuitState.HALF_OPEN

        # 失败后重新熔断
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_reset(self):
        """测试重置熔断器"""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker("test", config)

        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        breaker.reset()
        assert breaker.state == CircuitState.CLOSED

    def test_get_stats(self):
        """测试获取统计信息"""
        breaker = CircuitBreaker("test_breaker")
        breaker.record_success()
        breaker.record_failure()

        stats = breaker.get_stats()

        assert stats["name"] == "test_breaker"
        assert "state" in stats
        assert "failure_count" in stats


class TestCircuitBreakerRegistry:
    """CircuitBreakerRegistry 测试"""

    def setup_method(self):
        """测试前重置"""
        CircuitBreakerRegistry.reset_default()

    def test_get_default(self):
        """测试获取默认实例"""
        registry = CircuitBreakerRegistry.get_default()
        assert registry is not None

        # 多次调用返回同一实例
        registry2 = CircuitBreakerRegistry.get_default()
        assert registry is registry2

    def test_get_breaker(self):
        """测试获取熔断器"""
        registry = CircuitBreakerRegistry.get_default()

        breaker1 = registry.get_breaker("tool1")
        breaker2 = registry.get_breaker("tool1")

        # 同名熔断器返回同一实例
        assert breaker1 is breaker2

        # 不同名返回不同实例
        breaker3 = registry.get_breaker("tool2")
        assert breaker1 is not breaker3

    def test_get_all_stats(self):
        """测试获取所有统计"""
        registry = CircuitBreakerRegistry.get_default()
        registry.get_breaker("tool1")
        registry.get_breaker("tool2")

        stats = registry.get_all_stats()

        assert "tool1" in stats
        assert "tool2" in stats


class TestRetryExecutor:
    """RetryExecutor 测试"""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """测试成功执行"""
        executor = RetryExecutor()

        async def success_func():
            return "success"

        result = await executor.execute(success_func)

        assert result.success is True
        assert result.result == "success"
        assert result.attempts == 1
        assert result.exception is None

    @pytest.mark.asyncio
    async def test_execute_with_retry(self):
        """测试带重试的执行"""
        policy = RetryPolicy(max_retries=3, base_delay=0.01, jitter=False)
        executor = RetryExecutor(policy=policy)

        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError("temporary failure")
            return "success"

        result = await executor.execute(flaky_func)

        assert result.success is True
        assert result.result == "success"
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_execute_all_retries_fail(self):
        """测试所有重试都失败"""
        policy = RetryPolicy(max_retries=2, base_delay=0.01, jitter=False)
        executor = RetryExecutor(policy=policy)

        async def always_fail():
            raise RetryableError("always fails")

        result = await executor.execute(always_fail)

        assert result.success is False
        assert result.exception is not None
        assert result.attempts == 3  # 1 初始 + 2 重试

    @pytest.mark.asyncio
    async def test_execute_non_retryable_error(self):
        """测试不可重试错误"""
        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        executor = RetryExecutor(policy=policy)

        async def non_retryable():
            raise NonRetryableError("cannot retry")

        result = await executor.execute(non_retryable)

        assert result.success is False
        assert result.attempts == 1  # 不重试

    @pytest.mark.asyncio
    async def test_execute_with_circuit_breaker(self):
        """测试带熔断器的执行"""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker("test", config)
        executor = RetryExecutor(
            policy=RetryPolicy(max_retries=0), circuit_breaker=breaker
        )

        async def fail_func():
            raise RetryableError("fail")

        # 第一次失败
        await executor.execute(fail_func)
        assert breaker.state == CircuitState.CLOSED

        # 第二次失败，触发熔断
        await executor.execute(fail_func)
        assert breaker.state == CircuitState.OPEN

        # 熔断后立即返回
        result = await executor.execute(fail_func)
        assert result.success is False
        assert isinstance(result.exception, CircuitBreakerOpenError)
        assert result.attempts == 0

    @pytest.mark.asyncio
    async def test_execute_sync_function(self):
        """测试执行同步函数"""
        executor = RetryExecutor()

        def sync_func():
            return "sync_result"

        result = await executor.execute(sync_func)

        assert result.success is True
        assert result.result == "sync_result"

    @pytest.mark.asyncio
    async def test_execute_with_args_kwargs(self):
        """测试带参数执行"""
        executor = RetryExecutor()

        async def func_with_args(a, b, c=None):
            return {"a": a, "b": b, "c": c}

        result = await executor.execute(func_with_args, args=(1, 2), kwargs={"c": 3})

        assert result.success is True
        assert result.result == {"a": 1, "b": 2, "c": 3}

    @pytest.mark.asyncio
    async def test_execute_with_callback(self):
        """测试重试回调"""
        policy = RetryPolicy(max_retries=2, base_delay=0.01, jitter=False)
        callback_calls = []

        def on_retry(attempt, exception, delay):
            callback_calls.append({"attempt": attempt, "delay": delay})

        executor = RetryExecutor(policy=policy, on_retry=on_retry)

        async def flaky():
            raise RetryableError("fail")

        await executor.execute(flaky)

        assert len(callback_calls) == 2  # 2 次重试回调

    def test_execute_sync(self):
        """测试同步执行方法"""
        policy = RetryPolicy(max_retries=2, base_delay=0.01, jitter=False)
        executor = RetryExecutor(policy=policy)

        call_count = 0

        def sync_flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RetryableError("fail")
            return "success"

        result = executor.execute_sync(sync_flaky)

        assert result.success is True
        assert result.result == "success"
        assert result.attempts == 2


class TestRetryResult:
    """RetryResult 测试"""

    def test_to_dict_success(self):
        """测试成功结果序列化"""
        result = RetryResult(
            success=True, result={"data": "test"}, attempts=1, total_delay=0.0
        )

        d = result.to_dict()

        assert d["success"] is True
        assert d["attempts"] == 1
        assert d["error"] is None

    def test_to_dict_failure(self):
        """测试失败结果序列化"""
        result = RetryResult(
            success=False,
            exception=ValueError("test error"),
            attempts=3,
            total_delay=2.5,
        )

        d = result.to_dict()

        assert d["success"] is False
        assert d["attempts"] == 3
        assert d["total_delay"] == 2.5
        assert "test error" in d["error"]


class TestWithRetryDecorator:
    """@with_retry 装饰器测试"""

    def setup_method(self):
        """重置熔断器注册表"""
        CircuitBreakerRegistry.reset_default()

    @pytest.mark.asyncio
    async def test_decorator_success(self):
        """测试装饰器成功执行"""

        @with_retry(policy=RetryPolicy(max_retries=3))
        async def my_func():
            return "decorated_result"

        result = await my_func()
        assert result == "decorated_result"

    @pytest.mark.asyncio
    async def test_decorator_with_retry(self):
        """测试装饰器重试"""
        call_count = 0

        @with_retry(policy=RetryPolicy(max_retries=3, base_delay=0.01, jitter=False))
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RetryableError("fail")
            return "success"

        result = await flaky_func()

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_decorator_with_circuit_breaker(self):
        """测试装饰器带熔断器"""

        @with_retry(circuit_breaker_name="my_breaker")
        async def my_func():
            return "result"

        result = await my_func()
        assert result == "result"

        # 检查熔断器已创建
        registry = CircuitBreakerRegistry.get_default()
        breaker = registry.get_breaker("my_breaker")
        assert breaker is not None

    def test_decorator_sync_function(self):
        """测试装饰器同步函数"""

        @with_retry(policy=RetryPolicy(max_retries=2))
        def sync_func():
            return "sync_result"

        result = sync_func()
        assert result == "sync_result"

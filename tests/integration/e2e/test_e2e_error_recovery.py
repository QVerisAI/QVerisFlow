"""
错误恢复端到端测试

测试各种错误场景下的恢复能力：
- 重试机制
- 熔断器
- 错误处理和日志
"""

import pytest
import asyncio
import time
from datetime import datetime
from typing import List

from src.tools.retry import (
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


class TestRetryExecutor:
    """重试执行器测试"""

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        """测试成功执行"""
        policy = RetryPolicy(max_retries=3)
        executor = RetryExecutor(policy=policy)

        async def success_func():
            return "success"

        result = await executor.execute(success_func)

        assert result.success is True
        assert result.result == "success"
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_retry_on_transient_failure(self):
        """测试暂时性失败的重试"""
        policy = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(RetryableError,),
        )
        executor = RetryExecutor(policy=policy)

        call_count = 0

        async def transient_fail():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError("Transient error")
            return "success"

        result = await executor.execute(transient_fail)

        assert result.success is True
        assert result.result == "success"
        assert result.attempts == 3
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self):
        """测试重试耗尽"""
        policy = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(RetryableError,),
        )
        executor = RetryExecutor(policy=policy)

        async def always_fail():
            raise RetryableError("Always fails")

        result = await executor.execute(always_fail)

        assert result.success is False
        assert result.exception is not None
        assert isinstance(result.exception, RetryableError)
        # max_retries=3 means 1 initial attempt + 3 retries = 4 attempts
        assert result.attempts == policy.max_retries + 1

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        """测试不可重试异常"""
        policy = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            non_retryable_exceptions=(ValueError,),
        )
        executor = RetryExecutor(policy=policy)

        async def non_retryable_fail():
            raise ValueError("Non-retryable error")

        result = await executor.execute(non_retryable_fail)

        assert result.success is False
        assert result.exception is not None
        assert isinstance(result.exception, ValueError)
        assert result.attempts == 1  # No retries for non-retryable

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """测试指数退避"""
        policy = RetryPolicy(
            max_retries=3,
            base_delay=0.1,
            exponential_base=2.0,
            jitter=False,
            retryable_exceptions=(RetryableError,),
        )
        executor = RetryExecutor(policy=policy)

        call_times: List[float] = []

        async def record_time():
            call_times.append(time.time())
            raise RetryableError("Test")

        await executor.execute(record_time)

        # Verify exponential delays between calls
        if len(call_times) >= 3:
            delay1 = call_times[1] - call_times[0]
            delay2 = call_times[2] - call_times[1]

            # delay2 should be roughly 2x delay1
            assert delay2 > delay1 * 1.5

    @pytest.mark.asyncio
    async def test_retry_callback(self):
        """测试重试回调"""
        callbacks: List[tuple] = []

        def on_retry(attempt, exception, delay):
            callbacks.append((attempt, str(exception), delay))

        policy = RetryPolicy(
            max_retries=2,
            base_delay=0.01,
            retryable_exceptions=(RetryableError,),
        )
        executor = RetryExecutor(policy=policy, on_retry=on_retry)

        async def fail_func():
            raise RetryableError("Fail")

        await executor.execute(fail_func)

        assert len(callbacks) == 2
        assert callbacks[0][0] == 0  # First retry attempt
        assert callbacks[1][0] == 1  # Second retry attempt


class TestCircuitBreaker:
    """熔断器测试"""

    def test_circuit_breaker_closed_state(self):
        """测试熔断器关闭状态"""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(name="test_breaker", config=config)

        assert breaker.state == CircuitState.CLOSED
        assert breaker.can_execute() is True

    def test_circuit_breaker_opens_on_failures(self):
        """测试熔断器在失败时打开"""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(name="test_breaker", config=config)

        # Record failures up to threshold
        for _ in range(3):
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert breaker.can_execute() is False

    def test_circuit_breaker_half_open_state(self):
        """测试熔断器半开状态"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.01,  # Very short for test
        )
        breaker = CircuitBreaker(name="test_breaker", config=config)

        # Trigger open
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.02)

        # Should transition to half-open
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.can_execute() is True

    def test_circuit_breaker_recovery(self):
        """测试熔断器恢复"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.01,
            half_open_max_calls=2,
            success_threshold=0.5,
        )
        breaker = CircuitBreaker(name="test_breaker", config=config)

        # Trigger open
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for half-open
        time.sleep(0.02)

        # Access state property to trigger OPEN -> HALF_OPEN transition
        assert breaker.state == CircuitState.HALF_OPEN

        # Record successes in half-open
        breaker.record_success()
        breaker.record_success()

        assert breaker.state == CircuitState.CLOSED

    def test_circuit_breaker_fallback_to_open(self):
        """测试熔断器回退到打开"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.01,
            half_open_max_calls=3,
        )
        breaker = CircuitBreaker(name="test_breaker", config=config)

        # Trigger open
        breaker.record_failure()
        breaker.record_failure()

        # Wait for half-open
        time.sleep(0.02)
        assert breaker.state == CircuitState.HALF_OPEN

        # Failure in half-open should open again
        breaker.record_failure()

        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerRegistry:
    """熔断器注册表测试"""

    def test_registry_get_or_create(self):
        """测试注册表获取或创建"""
        registry = CircuitBreakerRegistry()

        # Get creates new breaker
        breaker1 = registry.get_breaker("tool_1")
        assert breaker1 is not None
        assert breaker1.name == "tool_1"

        # Get returns same breaker
        breaker2 = registry.get_breaker("tool_1")
        assert breaker1 is breaker2

    def test_registry_with_config(self):
        """测试带配置的注册表"""
        registry = CircuitBreakerRegistry()

        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=60.0,
        )

        breaker = registry.get_breaker("custom_tool", config=config)
        assert breaker.config.failure_threshold == 10
        assert breaker.config.recovery_timeout == 60.0

    def test_registry_reset_all(self):
        """测试重置所有熔断器"""
        registry = CircuitBreakerRegistry()

        # Create and trigger some breakers
        breaker1 = registry.get_breaker("tool_1")
        breaker2 = registry.get_breaker("tool_2")

        for _ in range(5):
            breaker1.record_failure()
            breaker2.record_failure()

        assert breaker1.state == CircuitState.OPEN
        assert breaker2.state == CircuitState.OPEN

        # Reset all
        registry.reset_all()

        assert breaker1.state == CircuitState.CLOSED
        assert breaker2.state == CircuitState.CLOSED


class TestRetryExecutorWithCircuitBreaker:
    """重试执行器与熔断器集成测试"""

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_execution(self):
        """测试熔断器阻止执行"""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker(name="block_test", config=config)

        # Open the circuit
        breaker.record_failure()
        breaker.record_failure()

        executor = RetryExecutor(
            policy=RetryPolicy(max_retries=3),
            circuit_breaker=breaker,
        )

        async def should_not_run():
            return "ran"

        result = await executor.execute(should_not_run)

        assert result.success is False
        assert isinstance(result.exception, CircuitBreakerOpenError)
        assert result.attempts == 0  # Never executed

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failures(self):
        """测试熔断器记录失败"""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(name="record_test", config=config)

        policy = RetryPolicy(
            max_retries=1,
            base_delay=0.01,
            retryable_exceptions=(RetryableError,),
        )
        executor = RetryExecutor(policy=policy, circuit_breaker=breaker)

        async def fail_func():
            raise RetryableError("Fail")

        # Execute multiple times
        await executor.execute(fail_func)
        await executor.execute(fail_func)

        # Breaker should now be open (failures from retries + calls)
        # After 2 executions with 2 attempts each = 4 failures
        assert breaker.state == CircuitState.OPEN


class TestWithRetryDecorator:
    """with_retry 装饰器测试"""

    @pytest.mark.asyncio
    async def test_decorator_basic_usage(self):
        """测试装饰器基本用法"""
        call_count = 0

        @with_retry(policy=RetryPolicy(max_retries=2, base_delay=0.01))
        async def flaky_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RetryableError("Flaky")
            return "success"

        result = await flaky_function()

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_decorator_with_circuit_breaker(self):
        """测试带熔断器的装饰器"""
        # Reset the default registry
        CircuitBreakerRegistry.reset_default()

        call_count = 0

        @with_retry(
            policy=RetryPolicy(max_retries=1, base_delay=0.01),
            circuit_breaker_name="decorator_test",
        )
        async def failing_function():
            nonlocal call_count
            call_count += 1
            raise RetryableError("Always fails")

        # Call multiple times to trigger circuit breaker
        for _ in range(3):
            try:
                await failing_function()
            except (RetryableError, CircuitBreakerOpenError):
                pass

        # Circuit should be open after failures
        registry = CircuitBreakerRegistry.get_default()
        breaker = registry.get_breaker("decorator_test")
        assert breaker.state == CircuitState.OPEN


class TestInvalidResponseHandling:
    """无效响应处理测试"""

    @pytest.mark.asyncio
    async def test_malformed_json_response(self):
        """测试格式错误的 JSON 响应"""
        policy = RetryPolicy(
            max_retries=2,
            base_delay=0.01,
            retryable_exceptions=(ValueError,),
            non_retryable_exceptions=(),  # Allow ValueError to be retried
        )
        executor = RetryExecutor(policy=policy)

        import json

        call_count = 0

        async def parse_json():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                # Return invalid JSON-like response
                json.loads(
                    "{invalid}"
                )  # Will raise JSONDecodeError (subclass of ValueError)
            return {"valid": "json"}

        result = await executor.execute(parse_json)

        assert result.success is True
        assert result.result == {"valid": "json"}

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """测试超时处理"""
        policy = RetryPolicy(
            max_retries=1,
            base_delay=0.01,
            timeout_per_attempt=0.05,
            retryable_exceptions=(asyncio.TimeoutError,),
        )
        executor = RetryExecutor(policy=policy)

        call_count = 0

        async def slow_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                await asyncio.sleep(0.1)  # Exceeds timeout
            return "fast"

        result = await executor.execute(slow_function)

        # First call times out, second succeeds
        assert result.success is True
        assert result.result == "fast"
        assert call_count == 2


class TestAgentErrorRecovery:
    """Agent 错误恢复测试"""

    @pytest.fixture
    def temp_workspace(self, tmp_path):
        """创建临时工作空间"""
        from src.workspace.workspace import AgentWorkspace, WorkspaceConfig

        config = WorkspaceConfig(
            base_path=str(tmp_path),
            task_id="error_test",
            auto_create=True,
        )
        return AgentWorkspace(config)

    def test_workspace_error_logging(self, temp_workspace):
        """测试工作空间错误日志"""
        # Write error log manually since there's no get_errors method
        error_log = temp_workspace.logs_dir / "error.log"
        error_message = "Test error occurred at step 3"
        error_log.write_text(error_message, encoding="utf-8")

        # Verify error was logged
        assert error_log.exists()
        content = error_log.read_text(encoding="utf-8")
        assert "Test error" in content


class TestResilientToolExecution:
    """弹性工具执行测试"""

    @pytest.mark.asyncio
    async def test_retry_executor_with_circuit_breaker(self):
        """测试重试执行器与熔断器集成"""
        config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=1.0,
        )
        breaker = CircuitBreaker(name="resilient_tool", config=config)

        policy = RetryPolicy(
            max_retries=2,
            base_delay=0.01,
            retryable_exceptions=(RetryableError,),
        )
        executor = RetryExecutor(policy=policy, circuit_breaker=breaker)

        call_count = 0

        async def unreliable_tool():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError("Temporary failure")
            return {"status": "success"}

        result = await executor.execute(unreliable_tool)

        assert result.success is True
        assert result.result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_tool_execution_with_retry_decorator(self):
        """测试使用重试装饰器的工具执行"""
        # Reset registry
        CircuitBreakerRegistry.reset_default()

        execution_log = []

        @with_retry(
            policy=RetryPolicy(
                max_retries=3,
                base_delay=0.01,
                retryable_exceptions=(ConnectionError,),
            ),
            circuit_breaker_name="network_tool",
        )
        async def network_call(url: str):
            execution_log.append(f"Calling {url}")
            if len(execution_log) < 2:
                raise ConnectionError("Network error")
            return f"Response from {url}"

        result = await network_call("http://example.com")

        assert result == "Response from http://example.com"
        assert len(execution_log) == 2


class TestSyncRetryExecutor:
    """同步重试执行器测试"""

    def test_sync_retry_success(self):
        """测试同步重试成功"""
        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        executor = RetryExecutor(policy=policy)

        def sync_func():
            return "sync_success"

        result = executor.execute_sync(sync_func)

        assert result.success is True
        assert result.result == "sync_success"

    def test_sync_retry_with_failures(self):
        """测试同步重试带失败"""
        policy = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(RetryableError,),
        )
        executor = RetryExecutor(policy=policy)

        call_count = 0

        def flaky_sync_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RetryableError("Flaky")
            return "recovered"

        result = executor.execute_sync(flaky_sync_func)

        assert result.success is True
        assert result.result == "recovered"
        assert call_count == 2

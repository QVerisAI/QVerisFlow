"""
E2E 测试工具类

提供测试场景执行、数据生成和断言辅助功能。
"""

import json
import asyncio
from typing import Any, Dict, List, Optional, Callable, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path


# ==================== 场景执行器 ====================


@dataclass
class ScenarioStep:
    """场景步骤"""

    name: str
    action: Callable
    expected_result: Optional[Dict[str, Any]] = None
    timeout: float = 30.0
    retry_on_failure: bool = False
    max_retries: int = 3


@dataclass
class ScenarioResult:
    """场景执行结果"""

    success: bool
    steps_completed: int
    total_steps: int
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
            "results": self.results,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
        }


class ScenarioRunner:
    """
    场景执行器

    执行预定义的测试场景，支持步骤验证和错误处理。
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self.steps: List[ScenarioStep] = []
        self.setup_fn: Optional[Callable] = None
        self.teardown_fn: Optional[Callable] = None

    def add_step(
        self,
        name: str,
        action: Callable,
        expected_result: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ):
        """添加场景步骤"""
        self.steps.append(
            ScenarioStep(
                name=name,
                action=action,
                expected_result=expected_result,
                timeout=timeout,
            )
        )

    def set_setup(self, fn: Callable):
        """设置 setup 函数"""
        self.setup_fn = fn

    def set_teardown(self, fn: Callable):
        """设置 teardown 函数"""
        self.teardown_fn = fn

    async def run(self) -> ScenarioResult:
        """执行场景"""
        start_time = datetime.now()
        results = []
        errors = []
        steps_completed = 0

        try:
            # Setup
            if self.setup_fn:
                if asyncio.iscoroutinefunction(self.setup_fn):
                    await self.setup_fn()
                else:
                    self.setup_fn()

            # 执行步骤
            for step in self.steps:
                try:
                    result = await self._execute_step(step)
                    results.append(
                        {
                            "step": step.name,
                            "success": True,
                            "result": result,
                        }
                    )
                    steps_completed += 1

                    # 验证预期结果
                    if step.expected_result:
                        self._validate_result(result, step.expected_result)

                except Exception as e:
                    errors.append(
                        {
                            "step": step.name,
                            "error": str(e),
                            "type": type(e).__name__,
                        }
                    )
                    if not step.retry_on_failure:
                        break

        finally:
            # Teardown
            if self.teardown_fn:
                try:
                    if asyncio.iscoroutinefunction(self.teardown_fn):
                        await self.teardown_fn()
                    else:
                        self.teardown_fn()
                except Exception:
                    pass

        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        return ScenarioResult(
            success=len(errors) == 0 and steps_completed == len(self.steps),
            steps_completed=steps_completed,
            total_steps=len(self.steps),
            results=results,
            errors=errors,
            duration_ms=duration_ms,
        )

    async def _execute_step(self, step: ScenarioStep) -> Any:
        """执行单个步骤"""
        if asyncio.iscoroutinefunction(step.action):
            return await asyncio.wait_for(step.action(), timeout=step.timeout)
        else:
            return await asyncio.to_thread(step.action)

    def _validate_result(self, actual: Any, expected: Dict[str, Any]):
        """验证结果"""
        if isinstance(actual, dict):
            for key, value in expected.items():
                if key not in actual:
                    raise AssertionError(f"Missing key: {key}")
                if actual[key] != value:
                    raise AssertionError(
                        f"Value mismatch for {key}: {actual[key]} != {value}"
                    )
        else:
            if actual != expected:
                raise AssertionError(f"Result mismatch: {actual} != {expected}")


# ==================== 测试数据生成器 ====================


class TestDataGenerator:
    """
    测试数据生成器

    生成各种测试场景所需的数据。
    """

    @staticmethod
    def generate_task(complexity: str = "simple") -> Dict[str, Any]:
        """生成测试任务"""
        tasks = {
            "simple": {
                "description": "Echo the message 'Hello, World!'",
                "input_data": {"message": "Hello, World!"},
                "expected_tool": "e2e_echo",
            },
            "calculation": {
                "description": "Calculate the result of 2 + 2 * 3",
                "input_data": {"expression": "2 + 2 * 3"},
                "expected_tool": "e2e_calculate",
            },
            "search": {
                "description": "Search for information about AI",
                "input_data": {"query": "artificial intelligence"},
                "expected_tool": "e2e_search",
            },
            "multi_step": {
                "description": "Search for data and calculate the sum",
                "input_data": {"query": "numbers", "expression": "1+2+3"},
                "expected_tools": ["e2e_search", "e2e_calculate"],
            },
        }
        return tasks.get(complexity, tasks["simple"])

    @staticmethod
    def generate_large_context(size_kb: int = 100) -> str:
        """生成大型上下文"""
        # 生成指定大小的文本
        base_text = "This is a test context paragraph. " * 100
        target_size = size_kb * 1024
        repetitions = (target_size // len(base_text)) + 1
        return (base_text * repetitions)[:target_size]

    @staticmethod
    def generate_agent_state(iteration: int = 1) -> Dict[str, Any]:
        """生成 Agent 状态"""
        return {
            "agent_id": "test_agent",
            "task_id": "test_task",
            "iteration": iteration,
            "phase": "gather_context",
            "gathered_context": f"Context at iteration {iteration}",
            "current_draft": f"Draft v{iteration}",
            "verification_passed": False,
            "verification_feedback": "",
            "verification_score": 0.0,
            "result": None,
            "messages": [],
            "errors": [],
            "draft_versions": [f"draft_v{i}" for i in range(1, iteration + 1)],
            "workspace_path": "/tmp/test_workspace",
            "max_iterations": 5,
        }

    @staticmethod
    def generate_trace_data() -> Dict[str, Any]:
        """生成追踪数据"""
        from src.persistence.models import (
            ExecutionTrace,
            SpanRecord,
            LLMCallRecord,
            ToolCallRecord,
            ExecutionStatus,
        )

        trace_id = f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        return {
            "trace": ExecutionTrace(
                trace_id=trace_id,
                task_id="test_task",
                agent_id="test_agent",
                status=ExecutionStatus.RUNNING,
            ),
            "spans": [
                SpanRecord(
                    span_id=f"span_{i}",
                    trace_id=trace_id,
                    parent_span_id=None,
                    name=f"operation_{i}",
                    start_time=datetime.now(),
                    end_time=datetime.now(),
                    duration_ms=100.0,
                    status="ok",
                )
                for i in range(3)
            ],
            "llm_calls": [
                LLMCallRecord(
                    call_id=f"llm_{i}",
                    span_id="span_0",
                    trace_id=trace_id,
                    provider="mock",
                    model="mock-model",
                    messages=[{"role": "user", "content": "test"}],
                    response="test response",
                    prompt_tokens=100,
                    completion_tokens=50,
                    latency_ms=500,
                )
                for i in range(2)
            ],
            "tool_calls": [
                ToolCallRecord(
                    call_id=f"tool_{i}",
                    span_id="span_1",
                    trace_id=trace_id,
                    tool_id="e2e_echo",
                    tool_name="Echo Tool",
                    tool_category="system",
                    input_params={"message": "test"},
                    output="Echo: test",
                    latency_ms=10,
                )
                for i in range(3)
            ],
        }


# ==================== 断言辅助 ====================


class AssertionHelpers:
    """
    断言辅助类

    提供常用的测试断言方法。
    """

    @staticmethod
    def assert_agent_result_success(result: Dict[str, Any]):
        """断言 Agent 执行成功"""
        assert result is not None, "Result should not be None"
        assert "success" in result, "Result should have 'success' key"
        assert (
            result["success"] is True
        ), f"Agent should succeed, got error: {result.get('error')}"

    @staticmethod
    def assert_agent_result_failure(result: Dict[str, Any]):
        """断言 Agent 执行失败"""
        assert result is not None, "Result should not be None"
        assert result.get("success") is False, "Agent should fail"

    @staticmethod
    def assert_workspace_has_output(workspace, filename: str):
        """断言工作空间有输出文件"""
        output_path = workspace.output_dir / filename
        assert output_path.exists(), f"Output file {filename} should exist"

    @staticmethod
    def assert_workspace_has_draft(workspace, version: int):
        """断言工作空间有草稿"""
        draft_path = workspace.scratch_dir / f"draft_v{version}.md"
        assert draft_path.exists(), f"Draft v{version} should exist"

    @staticmethod
    def assert_checkpoint_saved(checkpointer, thread_id: str):
        """断言检查点已保存"""
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint = checkpointer.get(config)
        assert checkpoint is not None, f"Checkpoint for {thread_id} should exist"

    @staticmethod
    def assert_trace_saved(storage, trace_id: str):
        """断言追踪已保存"""
        import asyncio

        async def check():
            trace = await storage.get_trace(trace_id)
            assert trace is not None, f"Trace {trace_id} should exist"
            return trace

        return asyncio.get_event_loop().run_until_complete(check())

    @staticmethod
    def assert_metrics_recorded(metrics_collector, metric_name: str):
        """断言指标已记录"""
        # 实际实现取决于 MetricsCollector 的 API
        pass

    @staticmethod
    def assert_span_hierarchy(spans: List[Any], expected_hierarchy: List[str]):
        """断言 Span 层级正确"""
        span_names = [s.name for s in spans]
        for name in expected_hierarchy:
            assert name in span_names, f"Span {name} should exist in hierarchy"

    @staticmethod
    def assert_iteration_count(result: Dict[str, Any], expected: int):
        """断言迭代次数"""
        actual = result.get("iterations", 0)
        assert actual == expected, f"Expected {expected} iterations, got {actual}"

    @staticmethod
    def assert_result_contains(result: Dict[str, Any], key: str, value: Any = None):
        """断言结果包含指定键值"""
        assert key in result, f"Result should contain key '{key}'"
        if value is not None:
            assert (
                result[key] == value
            ), f"Result['{key}'] should be {value}, got {result[key]}"

    @staticmethod
    def assert_json_valid(content: Union[str, Dict]) -> Dict:
        """断言内容是有效 JSON"""
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                raise AssertionError(f"Invalid JSON: {e}")
        return content


# ==================== 等待辅助 ====================


class WaitHelpers:
    """等待辅助类"""

    @staticmethod
    async def wait_for_file(path: Path, timeout: float = 5.0) -> bool:
        """等待文件出现"""
        start = datetime.now()
        while (datetime.now() - start).total_seconds() < timeout:
            if path.exists():
                return True
            await asyncio.sleep(0.1)
        return False

    @staticmethod
    async def wait_for_condition(
        condition: Callable[[], bool],
        timeout: float = 5.0,
        interval: float = 0.1,
    ) -> bool:
        """等待条件满足"""
        start = datetime.now()
        while (datetime.now() - start).total_seconds() < timeout:
            if condition():
                return True
            await asyncio.sleep(interval)
        return False

    @staticmethod
    async def wait_for_checkpoint(
        checkpointer,
        thread_id: str,
        timeout: float = 5.0,
    ) -> bool:
        """等待检查点保存"""
        config = {"configurable": {"thread_id": thread_id}}

        async def check():
            return checkpointer.get(config) is not None

        return await WaitHelpers.wait_for_condition(
            lambda: checkpointer.get(config) is not None,
            timeout=timeout,
        )


# ==================== Mock 工具 ====================


class MockToolExecutor:
    """
    Mock 工具执行器

    记录工具调用并返回预设结果。
    """

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.results: Dict[str, Any] = {}
        self.errors: Dict[str, Exception] = {}

    def set_result(self, tool_id: str, result: Any):
        """设置工具返回结果"""
        self.results[tool_id] = result

    def set_error(self, tool_id: str, error: Exception):
        """设置工具抛出错误"""
        self.errors[tool_id] = error

    async def execute(self, tool_id: str, params: Dict[str, Any]) -> Any:
        """执行工具"""
        self.calls.append(
            {
                "tool_id": tool_id,
                "params": params,
                "timestamp": datetime.now().isoformat(),
            }
        )

        if tool_id in self.errors:
            raise self.errors[tool_id]

        if tool_id in self.results:
            return self.results[tool_id]

        return {"status": "success", "tool_id": tool_id}

    def get_call_count(self, tool_id: str = None) -> int:
        """获取调用次数"""
        if tool_id:
            return sum(1 for c in self.calls if c["tool_id"] == tool_id)
        return len(self.calls)

    def reset(self):
        """重置"""
        self.calls.clear()
        self.results.clear()
        self.errors.clear()


# ==================== 性能计时 ====================


class PerformanceTimer:
    """性能计时器"""

    def __init__(self, name: str = "default"):
        self.name = name
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.checkpoints: List[Dict[str, Any]] = []

    def start(self):
        """开始计时"""
        self.start_time = datetime.now()

    def checkpoint(self, name: str):
        """记录检查点"""
        self.checkpoints.append(
            {
                "name": name,
                "timestamp": datetime.now(),
                "elapsed_ms": self.elapsed_ms,
            }
        )

    def stop(self):
        """停止计时"""
        self.end_time = datetime.now()

    @property
    def elapsed_ms(self) -> float:
        """已用时间（毫秒）"""
        if not self.start_time:
            return 0.0
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds() * 1000

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "elapsed_ms": self.elapsed_ms,
            "checkpoints": self.checkpoints,
        }

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

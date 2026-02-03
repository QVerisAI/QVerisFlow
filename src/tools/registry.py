"""
工具注册表

负责工具的注册、查找和 @引用解析。

重构：消除单例模式，改用工厂函数获取默认实例，支持依赖注入。
增强：集成重试机制和熔断器模式。
"""

from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from src.utils.logger import get_logger
import re

from ..definitions import ToolDefinition, ToolReference, ToolCategory
from ..interfaces.tool import IToolRegistry
from ..observability import get_tracer, get_metrics_collector
from .validation import ToolParameterValidator, ToolValidationError
from .retry import (
    RetryPolicy,
    RetryExecutor,
    CircuitBreakerRegistry,
    CircuitBreakerConfig,
    RetryResult,
)

logger = get_logger()

# 默认实例（延迟初始化）
_default_registry: Optional["ToolRegistry"] = None


class ToolRegistry(IToolRegistry):
    """
    工具注册表

    支持工具注册、查找和 @引用 解析。

    重构：
    - 消除单例模式，支持创建多个独立实例
    - 使用 get_default() 获取全局默认实例
    - 支持依赖注入和测试
    """

    def __init__(
        self,
        validate_params: bool = True,
        enable_retry: bool = True,
        default_retry_policy: Optional[RetryPolicy] = None,
        enable_circuit_breaker: bool = True,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
    ):
        """
        初始化工具注册表

        Args:
            validate_params: 是否在执行工具前验证参数（默认 True）
            enable_retry: 是否启用重试机制（默认 True）
            default_retry_policy: 默认重试策略
            enable_circuit_breaker: 是否启用熔断器（默认 True）
            circuit_breaker_config: 熔断器配置
        """
        self._tools: Dict[str, ToolDefinition] = {}
        self._tool_impls: Dict[str, Callable] = {}
        self._alias_map: Dict[str, str] = {}  # alias -> tool_id
        self._validate_params = validate_params
        self._validator = ToolParameterValidator(strict_mode=True, coerce_types=True)

        # 重试和熔断器配置
        self._enable_retry = enable_retry
        self._default_retry_policy = default_retry_policy or RetryPolicy()
        self._enable_circuit_breaker = enable_circuit_breaker
        self._circuit_breaker_registry = CircuitBreakerRegistry()
        if circuit_breaker_config:
            self._circuit_breaker_registry.set_default_config(circuit_breaker_config)

        # 工具级别的重试策略覆盖
        self._tool_retry_policies: Dict[str, RetryPolicy] = {}

    @classmethod
    def get_default(cls) -> "ToolRegistry":
        """
        获取默认的全局注册表实例

        Returns:
            默认的 ToolRegistry 实例
        """
        global _default_registry
        if _default_registry is None:
            _default_registry = cls()
        return _default_registry

    @classmethod
    def set_default(cls, registry: "ToolRegistry") -> None:
        """
        设置默认的全局注册表实例（用于测试或自定义）

        Args:
            registry: 新的默认注册表
        """
        global _default_registry
        _default_registry = registry

    @classmethod
    def reset_default(cls) -> None:
        """重置默认注册表（主要用于测试）"""
        global _default_registry
        _default_registry = None

    def register(
        self,
        definition: ToolDefinition,
        implementation: Callable,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        """
        注册工具

        Args:
            definition: 工具定义
            implementation: 工具实现函数
            retry_policy: 该工具的重试策略（可选，覆盖默认策略）
        """
        self._tools[definition.tool_id] = definition
        self._tool_impls[definition.tool_id] = implementation
        self._alias_map[definition.alias] = definition.tool_id

        # 注册工具级别的重试策略
        if retry_policy:
            self._tool_retry_policies[definition.tool_id] = retry_policy

        logger.info(f"✅ 注册工具: {definition.name} (@{definition.alias})")

    def set_tool_retry_policy(self, tool_id: str, policy: RetryPolicy) -> None:
        """
        设置工具的重试策略

        Args:
            tool_id: 工具 ID
            policy: 重试策略
        """
        self._tool_retry_policies[tool_id] = policy
        logger.debug(f"设置工具 {tool_id} 的重试策略")

    def get_circuit_breaker_stats(self) -> Dict[str, Any]:
        """
        获取所有熔断器的统计信息

        Returns:
            熔断器统计信息字典
        """
        return self._circuit_breaker_registry.get_all_stats()

    def reset_circuit_breaker(self, tool_id: str) -> None:
        """
        重置指定工具的熔断器

        Args:
            tool_id: 工具 ID
        """
        breaker = self._circuit_breaker_registry.get_breaker(tool_id)
        breaker.reset()

    def get(self, tool_id: str) -> Optional[ToolDefinition]:
        """
        获取工具定义

        Args:
            tool_id: 工具 ID

        Returns:
            工具定义，如果不存在则返回 None
        """
        return self._tools.get(tool_id)

    def get_by_alias(self, alias: str) -> Optional[ToolDefinition]:
        """
        通过别名获取工具定义

        Args:
            alias: 工具别名

        Returns:
            工具定义，如果不存在则返回 None
        """
        tool_id = self._alias_map.get(alias)
        return self._tools.get(tool_id) if tool_id else None

    def resolve_tool_references(
        self, prompt: str, tool_refs: List[ToolReference]
    ) -> tuple[str, List[ToolDefinition]]:
        """
        解析 prompt 中的 @工具名 引用

        Args:
            prompt: 原始 prompt
            tool_refs: 允许使用的工具引用列表

        Returns:
            (解析后的 prompt, 实际使用的工具列表)
        """
        used_tools = []
        allowed_aliases = {ref.alias for ref in tool_refs if ref.enabled}

        # 查找所有 @xxx 引用
        pattern = r"@(\S+)"
        matches = re.findall(pattern, prompt)

        for alias in matches:
            if alias in allowed_aliases:
                tool_def = self.get_by_alias(alias)
                if tool_def:
                    used_tools.append(tool_def)
                    # 可选：替换为工具描述
                    # prompt = prompt.replace(f"@{alias}", f"【工具：{tool_def.name}】")

        return prompt, used_tools

    def get_by_category(self, category: ToolCategory) -> List[ToolDefinition]:
        """
        按分类获取工具

        Args:
            category: 工具分类

        Returns:
            工具定义列表
        """
        return [tool for tool in self._tools.values() if tool.category == category]

    async def execute(
        self,
        tool_id: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        skip_validation: bool = False,
        use_retry: Optional[bool] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> Any:
        """
        执行工具（带参数验证、追踪、指标、重试和熔断器）

        Args:
            tool_id: 工具 ID
            params: 参数字典
            context: 执行上下文（包含 workspace 用于日志记录）
            skip_validation: 是否跳过参数验证（默认 False）
            use_retry: 是否使用重试（默认使用注册表配置）
            retry_policy: 本次执行的重试策略（覆盖默认）

        Returns:
            工具执行结果

        Raises:
            ValueError: 工具未注册
            ToolValidationError: 参数验证失败
        """
        # 决定是否使用重试
        should_retry = use_retry if use_retry is not None else self._enable_retry

        if should_retry:
            return await self._execute_with_retry(
                tool_id=tool_id,
                params=params,
                context=context,
                skip_validation=skip_validation,
                retry_policy=retry_policy,
            )
        else:
            return await self._execute_once(
                tool_id=tool_id,
                params=params,
                context=context,
                skip_validation=skip_validation,
            )

    async def _execute_with_retry(
        self,
        tool_id: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        skip_validation: bool = False,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> Any:
        """
        带重试和熔断器的工具执行
        """
        # 获取重试策略（优先级：参数 > 工具级别 > 默认）
        policy = (
            retry_policy
            or self._tool_retry_policies.get(tool_id)
            or self._default_retry_policy
        )

        # 获取熔断器
        circuit_breaker = None
        if self._enable_circuit_breaker:
            circuit_breaker = self._circuit_breaker_registry.get_breaker(tool_id)

        # 创建重试执行器
        executor = RetryExecutor(
            policy=policy,
            circuit_breaker=circuit_breaker,
            on_retry=lambda attempt, exc, delay: logger.warning(
                f"工具 {tool_id} 重试 {attempt + 1}: {exc}, 延迟 {delay:.2f}s"
            ),
        )

        # 执行
        result = await executor.execute(
            func=self._execute_once,
            kwargs={
                "tool_id": tool_id,
                "params": params,
                "context": context,
                "skip_validation": skip_validation,
            },
        )

        if result.success:
            return result.result
        else:
            # 记录重试失败
            logger.error(
                f"工具 {tool_id} 执行失败（尝试 {result.attempts} 次）: {result.exception}"
            )
            raise result.exception

    async def _execute_once(
        self,
        tool_id: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        skip_validation: bool = False,
    ) -> Any:
        """
        执行工具一次（不带重试）
        """
        if tool_id not in self._tool_impls:
            raise ValueError(f"工具 {tool_id} 未注册")

        impl = self._tool_impls[tool_id]
        definition = self._tools[tool_id]

        # 获取追踪器和指标收集器
        tracer = get_tracer()
        metrics = get_metrics_collector()
        start_time = datetime.now()

        # 获取 workspace 用于日志记录（文件系统交互总线）
        workspace = context.get("workspace") if context else None

        # 参数验证
        validated_params = params
        if self._validate_params and not skip_validation and definition.input_schema:
            try:
                validated_params = self._validator.validate_and_raise(
                    params=params,
                    schema=definition.input_schema,
                    tool_id=tool_id,
                )
                logger.debug(f"工具 {tool_id} 参数验证通过")
            except ToolValidationError as e:
                # 记录验证失败指标
                metrics.counter("tool.validation.errors").inc(
                    labels={"tool_id": tool_id}
                )
                logger.warning(f"工具 {tool_id} 参数验证失败: {e}")
                raise

        # 安全获取参数摘要（避免在 span 中存储过大数据）
        params_summary = str(validated_params)[:500] if validated_params else ""

        # 记录工具调用开始
        if workspace and hasattr(workspace, "log_tool_call"):
            workspace.log_tool_call(
                tool_id=tool_id, input_params=validated_params, phase="start"
            )

        import asyncio
        import inspect

        # 使用追踪器
        with tracer.start_span(
            "tool_call",
            attributes={
                "tool.id": tool_id,
                "tool.name": definition.name,
                "tool.category": (
                    definition.category.value if definition.category else "unknown"
                ),
                "tool.is_async": definition.is_async,
                "tool.params_summary": params_summary,
            },
        ) as span:
            try:
                # 注入上下文到参数（如果工具需要）
                exec_params = validated_params.copy()
                if context:
                    exec_params["_context"] = context

                # 执行工具
                span.add_event("execution_started")

                if definition.is_async:
                    if inspect.iscoroutinefunction(impl):
                        result = await impl(**exec_params)
                    else:
                        # 同步函数包装为异步
                        result = await asyncio.to_thread(impl, **exec_params)
                else:
                    if inspect.iscoroutinefunction(impl):
                        result = await impl(**exec_params)
                    else:
                        result = impl(**exec_params)

                span.add_event("execution_completed")

                # 记录成功指标
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                metrics.counter("tool.calls.total").inc(
                    labels={"tool_id": tool_id, "status": "success"}
                )
                metrics.histogram("tool.call.duration_ms").observe(
                    duration_ms, labels={"tool_id": tool_id}
                )

                # 设置 span 属性
                span.set_attribute("tool.success", True)
                span.set_attribute("tool.duration_ms", duration_ms)

                # 结果摘要（避免存储过大数据）
                result_summary = str(result)[:500] if result is not None else "None"
                span.set_attribute("tool.result_summary", result_summary)

                # 记录工具调用成功
                if workspace and hasattr(workspace, "log_tool_call"):
                    workspace.log_tool_call(
                        tool_id=tool_id,
                        input_params=params,
                        output=result,
                        phase="success",
                    )

                logger.debug(f"工具 {tool_id} 执行成功, 耗时 {duration_ms:.2f}ms")
                return result

            except Exception as e:
                # 记录失败指标
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                metrics.counter("tool.calls.total").inc(
                    labels={"tool_id": tool_id, "status": "failed"}
                )
                metrics.counter("tool.calls.errors").inc(
                    labels={"tool_id": tool_id, "error_type": type(e).__name__}
                )

                # 设置 span 错误状态
                span.set_status("error", str(e))
                span.set_attribute("tool.success", False)
                span.add_event(
                    "exception", {"message": str(e), "type": type(e).__name__}
                )

                # 记录工具调用失败
                if workspace and hasattr(workspace, "log_tool_call"):
                    workspace.log_tool_call(
                        tool_id=tool_id,
                        input_params=params,
                        error=str(e),
                        phase="error",
                    )

                logger.error(f"工具 {tool_id} 执行失败: {e}")
                raise

    def list_all(self) -> List[Dict[str, Any]]:
        """
        列出所有工具

        Returns:
            工具摘要列表
        """
        return [
            {
                "tool_id": d.tool_id,
                "name": d.name,
                "alias": d.alias,
                "category": d.category.value,
                "is_active": d.is_active,
            }
            for d in self._tools.values()
        ]

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        列出所有工具（list_all 的别名）

        Returns:
            工具摘要列表
        """
        return self.list_all()

    def unregister(self, tool_id: str) -> bool:
        """
        取消注册工具

        Args:
            tool_id: 要取消注册的工具 ID

        Returns:
            是否成功取消注册
        """
        if tool_id not in self._tools:
            return False

        definition = self._tools[tool_id]

        # 移除别名映射
        if definition.alias in self._alias_map:
            del self._alias_map[definition.alias]

        # 移除工具定义和实现
        del self._tools[tool_id]
        if tool_id in self._tool_impls:
            del self._tool_impls[tool_id]

        logger.info(f"已取消注册工具: {tool_id}")
        return True

    def reset(self):
        """重置此注册表实例"""
        self._tools = {}
        self._tool_impls = {}
        self._alias_map = {}
        self._tool_retry_policies = {}
        self._circuit_breaker_registry.reset_all()

    def copy(self) -> "ToolRegistry":
        """
        创建此注册表的副本

        Returns:
            新的 ToolRegistry 实例，包含相同的工具
        """
        new_registry = ToolRegistry(
            validate_params=self._validate_params,
            enable_retry=self._enable_retry,
            default_retry_policy=self._default_retry_policy,
            enable_circuit_breaker=self._enable_circuit_breaker,
        )
        new_registry._tools = self._tools.copy()
        new_registry._tool_impls = self._tool_impls.copy()
        new_registry._alias_map = self._alias_map.copy()
        new_registry._tool_retry_policies = self._tool_retry_policies.copy()
        return new_registry

    def merge(self, other: "ToolRegistry", overwrite: bool = False) -> None:
        """
        合并另一个注册表的工具

        Args:
            other: 要合并的注册表
            overwrite: 是否覆盖已存在的工具
        """
        for tool_id, definition in other._tools.items():
            if overwrite or tool_id not in self._tools:
                self._tools[tool_id] = definition
                self._tool_impls[tool_id] = other._tool_impls[tool_id]
                self._alias_map[definition.alias] = tool_id


# 装饰器语法糖
def tool(
    tool_id: str,
    name: str,
    alias: str,
    description: str,
    category: ToolCategory,
    input_schema: Dict[str, Any],
    output_schema: Dict[str, Any] = None,
    registry: "ToolRegistry" = None,
    **kwargs,
):
    """
    工具注册装饰器

    用法：
    ```python
    @tool(
        tool_id="stock_price",
        name="股票价格查询",
        alias="股票价格",
        description="查询股票实时价格",
        category=ToolCategory.STOCK_DATA,
        input_schema={"type": "object", ...},
        output_schema={"type": "object", ...}
    )
    async def get_stock_price(ticker: str) -> dict:
        ...
    ```

    Args:
        tool_id: 工具唯一标识
        name: 工具名称
        alias: 工具别名（用于 @引用）
        description: 工具描述
        category: 工具分类
        input_schema: 输入 JSON Schema
        output_schema: 输出 JSON Schema（可选）
        registry: 要注册到的注册表（可选，默认使用全局默认注册表）
        **kwargs: 其他工具定义参数
    """

    def decorator(func: Callable):
        definition = ToolDefinition(
            tool_id=tool_id,
            name=name,
            alias=alias,
            description=description,
            category=category,
            input_schema=input_schema,
            output_schema=output_schema or {"type": "object"},
            **kwargs,
        )

        # 使用指定的注册表或默认注册表
        target_registry = registry or ToolRegistry.get_default()
        target_registry.register(definition, func)

        # 保存定义到函数上，便于后续访问
        func._tool_definition = definition

        return func

    return decorator

"""
QVeris 工具适配器

将 QVeris 远程工具集成到 Agent Framework 的工具系统中。

功能：
- 提供 qveris_search_tools 元工具用于搜索远程工具
- 提供 qveris_execute_tool 元工具用于执行远程工具
- 支持将发现的工具动态注册为本地代理工具
- 集成追踪和指标
"""

from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
import json

from src.utils.logger import get_logger
from ..definitions.tool_definition import (
    ToolDefinition,
    ToolCategory,
    ToolReferenceType,
)
from .registry import ToolRegistry, tool
from .qveris_client import (
    QVerisClient,
    QVerisSearchResult,
    QVerisExecuteResult,
    QVerisToolInfo,
    QVerisAPIError,
)

logger = get_logger()

# 尝试导入可观测性模块
try:
    from observability import get_tracer, get_metrics_collector
except ImportError:
    get_tracer = None
    get_metrics_collector = None


class QVerisToolAdapter:
    """
    QVeris 工具适配器

    将 QVeris 的工具搜索和执行能力集成到 ToolRegistry 中。

    使用方式：
    1. 实例化适配器并传入 ToolRegistry
    2. 调用 register_meta_tools() 注册元工具
    3. Agent 可通过 qveris_search_tools 搜索工具
    4. Agent 可通过 qveris_execute_tool 执行找到的工具

    示例：
    ```python
    registry = ToolRegistry.get_default()
    adapter = QVerisToolAdapter(registry, api_key="your-api-key")
    adapter.register_meta_tools()

    # Agent 使用
    # 1. 搜索工具
    result = await registry.execute("qveris_search_tools", {"query": "weather API"})
    # 2. 执行工具
    exec_result = await registry.execute("qveris_execute_tool", {
        "tool_id": "openweathermap_current",
        "search_id": result["search_id"],
        "params": {"city": "London"}
    })
    ```
    """

    # 推荐的系统提示词（参考 https://qveris.ai/docs）
    RECOMMENDED_SYSTEM_PROMPT = """You are a helpful assistant that can dynamically search and execute tools to help the user.
First think about what kind of tools might be useful to accomplish the user's task.
Then use the qveris_search_tools tool with query describing the capability of the tool, not what params you want to pass to the tool later.
Then call suitable searched tool(s) using the qveris_execute_tool tool, passing parameters to the searched tool through params.
If tool has weighted_success_rate and avg_execution_time (in seconds), consider them when selecting which tool to call.
You could reference the examples given if any for each tool. You could call make multiple tool calls in a single response."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        cache_ttl: int = 3600,
        auto_register_discovered: bool = False,
        session_id: Optional[str] = None,
    ):
        """
        初始化 QVeris 工具适配器

        Args:
            tool_registry: 工具注册表实例
            api_key: QVeris API Key（可从环境变量读取）
            base_url: QVeris API 基础 URL
            cache_ttl: 搜索结果缓存时间（秒）
            auto_register_discovered: 是否自动将发现的工具注册为代理工具
                注意：建议保持为 False，让 Agent 按照 QVeris 设计模式工作：
                1. 使用 qveris_search_tools 搜索工具
                2. 使用 qveris_execute_tool 执行选定的工具
                自动注册可能导致工具名称过长（超过 LLM 的 64 字符限制）
            session_id: 会话 ID（用于追踪）
        """
        self.tool_registry = tool_registry
        self.auto_register_discovered = auto_register_discovered

        # 创建 QVeris 客户端
        self.client = QVerisClient(
            api_key=api_key,
            base_url=base_url,
            cache_ttl=cache_ttl,
            session_id=session_id,
        )

        # 存储最近的搜索结果（用于快速查找工具信息）
        self._recent_searches: Dict[str, QVerisSearchResult] = {}

        # 已注册的动态工具
        self._registered_dynamic_tools: Dict[str, ToolDefinition] = {}

        logger.info("QVeris 工具适配器已初始化")

    async def close(self):
        """关闭适配器，释放资源"""
        await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def register_meta_tools(self) -> None:
        """
        注册 QVeris 元工具到 ToolRegistry

        注册以下工具：
        - qveris_search_tools: 搜索远程工具
        - qveris_execute_tool: 执行远程工具
        - qveris_get_tool_info: 获取工具详细信息
        """
        # 注册搜索工具
        self._register_search_tool()

        # 注册执行工具
        self._register_execute_tool()

        # 注册获取工具信息
        self._register_get_tool_info()

        logger.info("QVeris 元工具已注册到 ToolRegistry")

    def _register_search_tool(self) -> None:
        """注册 qveris_search_tools 元工具"""
        search_definition = ToolDefinition(
            tool_id="qveris_search_tools",
            name="QVeris 工具搜索",
            alias="搜索远程工具",
            description=(
                "Search for available remote tools on the QVeris platform. "
                "IMPORTANT: Use English queries describing the general capability you need, NOT specific parameters. "
                "Good examples: 'stock price API', 'financial data', 'company earnings', 'weather forecast'. "
                "Bad examples: '09992.HK股票', '贵州茅台财报' (too specific, use Chinese). "
                "Returns a list of matching tools with tool_id, name, description, input_schema, success_rate, and execution_time."
            ),
            category=ToolCategory.QVERIS,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query in ENGLISH describing the tool capability needed. "
                            "Examples: 'stock price API', 'financial statements', 'company earnings data', "
                            "'weather forecast', 'exchange rate'. Do NOT include specific stock codes or company names."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回的最大工具数量（1-100）",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["query"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "search_id": {
                        "type": "string",
                        "description": "搜索 ID，执行工具时需要",
                    },
                    "query": {"type": "string", "description": "原始查询"},
                    "total_count": {"type": "integer", "description": "找到的工具数量"},
                    "tools": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool_id": {"type": "string"},
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "input_schema": {"type": "object"},
                                "weighted_success_rate": {"type": "number"},
                                "avg_execution_time": {"type": "number"},
                            },
                        },
                    },
                },
            },
            is_async=True,
            timeout=60,
            is_remote=True,
            provider="QVeris",
        )

        # 注册到 ToolRegistry
        self.tool_registry.register(search_definition, self._search_tools_impl)

    async def _search_tools_impl(
        self,
        query: str,
        limit: int = 20,
        _context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """搜索工具的实际实现"""
        tracer = get_tracer() if get_tracer else None
        metrics = get_metrics_collector() if get_metrics_collector else None

        start_time = datetime.now()

        try:
            # 调用 QVeris API
            result = await self.client.search_tools(query=query, limit=limit)

            # 缓存搜索结果
            self._recent_searches[result.search_id] = result

            # 自动注册发现的工具
            if self.auto_register_discovered:
                for tool_info in result.tools:
                    self._register_discovered_tool_as_proxy(tool_info, result.search_id)

            # 记录指标
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            if metrics:
                metrics.counter("qveris.search.total").inc(
                    labels={"status": "success"}
                )
                metrics.histogram("qveris.search.duration_ms").observe(duration_ms)
                metrics.gauge("qveris.search.tools_found").set(result.total_count)

            logger.info(f"QVeris 搜索完成: '{query}' -> {result.total_count} 个工具")

            return result.to_dict()

        except QVerisAPIError as e:
            if metrics:
                metrics.counter("qveris.search.total").inc(
                    labels={"status": "error"}
                )
            logger.error(f"QVeris 搜索失败: {e}")
            raise
        except Exception as e:
            if metrics:
                metrics.counter("qveris.search.total").inc(
                    labels={"status": "error"}
                )
            logger.error(f"QVeris 搜索异常: {e}")
            raise

    def _register_execute_tool(self) -> None:
        """注册 qveris_execute_tool 元工具"""
        execute_definition = ToolDefinition(
            tool_id="qveris_execute_tool",
            name="QVeris 工具执行",
            alias="执行远程工具",
            description=(
                "执行通过 qveris_search_tools 搜索到的远程工具。"
                "需要提供工具 ID、搜索 ID 和工具参数。"
                "参数应该以 JSON 字符串或字典形式提供。"
            ),
            category=ToolCategory.QVERIS,
            input_schema={
                "type": "object",
                "properties": {
                    "tool_id": {
                        "type": "string",
                        "description": "要执行的工具 ID（来自搜索结果）",
                    },
                    "search_id": {
                        "type": "string",
                        "description": "搜索 ID（来自 qveris_search_tools 的结果）",
                    },
                    "params": {
                        "oneOf": [{"type": "object"}, {"type": "string"}],
                        "description": "工具参数，可以是字典或 JSON 字符串",
                    },
                    "max_response_size": {
                        "type": "integer",
                        "description": "最大响应大小（字节），默认 20KB",
                        "default": 20480,
                    },
                },
                "required": ["tool_id", "search_id", "params"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "tool_id": {"type": "string"},
                    "success": {"type": "boolean"},
                    "content": {"description": "执行结果"},
                    "truncated": {"type": "boolean"},
                    "full_content_url": {"type": "string"},
                    "execution_time_ms": {"type": "number"},
                    "error": {"type": "string"},
                },
            },
            is_async=True,
            timeout=120,
            is_remote=True,
            provider="QVeris",
        )

        self.tool_registry.register(execute_definition, self._execute_tool_impl)

    async def _execute_tool_impl(
        self,
        tool_id: str,
        search_id: str,
        params: Any,
        max_response_size: int = 20480,
        _context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """执行工具的实际实现"""
        tracer = get_tracer() if get_tracer else None
        metrics = get_metrics_collector() if get_metrics_collector else None

        start_time = datetime.now()

        try:
            # 处理参数
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except json.JSONDecodeError:
                    # 如果不是有效 JSON，尝试作为简单值传递
                    params = {"value": params}

            # 调用 QVeris API
            result = await self.client.execute_tool(
                tool_id=tool_id,
                search_id=search_id,
                params=params,
                max_response_size=max_response_size,
            )

            # 记录指标
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            status = "success" if result.success else "error"

            if metrics:
                metrics.counter("qveris.execute.total").inc(
                    labels={"tool_id": tool_id, "status": status}
                )
                metrics.histogram("qveris.execute.duration_ms").observe(
                    duration_ms, labels={"tool_id": tool_id}
                )

            if result.success:
                logger.info(
                    f"QVeris 工具执行成功: {tool_id}, 耗时 {result.execution_time_ms:.2f}ms"
                )
            else:
                logger.warning(f"QVeris 工具执行失败: {tool_id}, 错误: {result.error}")

            return result.to_dict()

        except Exception as e:
            if metrics:
                metrics.counter("qveris.execute.total").inc(
                    labels={"tool_id": tool_id, "status": "exception"}
                )
            logger.error(f"QVeris 工具执行异常: {tool_id}, {e}")
            raise

    def _register_get_tool_info(self) -> None:
        """注册 qveris_get_tool_info 元工具"""
        info_definition = ToolDefinition(
            tool_id="qveris_get_tool_info",
            name="QVeris 获取工具信息",
            alias="获取远程工具信息",
            description=(
                "获取指定工具的详细信息，包括输入参数 schema、使用示例等。"
                "可用于在执行工具前了解其详细用法。"
            ),
            category=ToolCategory.QVERIS,
            input_schema={
                "type": "object",
                "properties": {
                    "tool_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要查询的工具 ID 列表",
                    },
                    "search_id": {
                        "type": "string",
                        "description": "关联的搜索 ID（可选）",
                    },
                },
                "required": ["tool_ids"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "tools": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool_id": {"type": "string"},
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "input_schema": {"type": "object"},
                                "examples": {"type": "array"},
                            },
                        },
                    }
                },
            },
            is_async=True,
            timeout=30,
            is_remote=True,
            provider="QVeris",
        )

        self.tool_registry.register(info_definition, self._get_tool_info_impl)

    async def _get_tool_info_impl(
        self,
        tool_ids: List[str],
        search_id: Optional[str] = None,
        _context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """获取工具信息的实际实现"""
        try:
            tools = await self.client.get_tools_by_ids(
                tool_ids=tool_ids,
                search_id=search_id,
            )

            return {"tools": [t.to_dict() for t in tools]}

        except Exception as e:
            logger.error(f"获取工具信息失败: {e}")
            raise

    def _register_discovered_tool_as_proxy(
        self,
        tool_info: QVerisToolInfo,
        search_id: str,
    ) -> Optional[ToolDefinition]:
        """
        将发现的工具注册为代理工具

        这允许 Agent 直接通过工具 ID 调用远程工具，
        而不需要显式使用 qveris_execute_tool。

        Args:
            tool_info: 工具信息
            search_id: 搜索 ID

        Returns:
            注册的 ToolDefinition，如果已存在则返回 None
        """
        proxy_tool_id = f"qveris_{tool_info.tool_id}"

        # 检查是否已注册
        if proxy_tool_id in self._registered_dynamic_tools:
            return None

        # 创建代理工具定义
        proxy_definition = ToolDefinition(
            tool_id=proxy_tool_id,
            name=f"[QVeris] {tool_info.name}",
            alias=tool_info.name,
            description=f"[远程工具] {tool_info.description}",
            category=ToolCategory.QVERIS,
            input_schema=tool_info.input_schema,
            output_schema={"type": "object", "description": "工具执行结果"},
            is_async=True,
            timeout=120,
            is_remote=True,
            provider=tool_info.provider or "QVeris",
            qveris_tool_id=tool_info.tool_id,
            qveris_search_id=search_id,
            weighted_success_rate=tool_info.weighted_success_rate,
            avg_execution_time=tool_info.avg_execution_time,
            tags=tool_info.tags + ["qveris", "remote", "dynamic"],
        )

        # 创建代理执行函数
        async def proxy_execute(**kwargs) -> Dict[str, Any]:
            # 移除 _context
            context = kwargs.pop("_context", None)
            params = kwargs

            result = await self._execute_tool_impl(
                tool_id=tool_info.tool_id,
                search_id=search_id,
                params=params,
                _context=context,
            )

            # 如果成功，直接返回内容
            if result.get("success"):
                return result.get("content", result)
            else:
                raise RuntimeError(f"工具执行失败: {result.get('error', '未知错误')}")

        # 注册到 ToolRegistry
        try:
            self.tool_registry.register(proxy_definition, proxy_execute)
            self._registered_dynamic_tools[proxy_tool_id] = proxy_definition
            logger.debug(f"已注册动态代理工具: {proxy_tool_id}")
            return proxy_definition
        except Exception as e:
            logger.warning(f"注册动态代理工具失败: {proxy_tool_id}, {e}")
            return None

    def get_discovered_tools(self) -> List[ToolDefinition]:
        """获取所有已发现并注册的动态工具"""
        return list(self._registered_dynamic_tools.values())

    def clear_discovered_tools(self) -> int:
        """清除所有动态注册的工具"""
        count = 0
        for tool_id in list(self._registered_dynamic_tools.keys()):
            try:
                self.tool_registry.unregister(tool_id)
                del self._registered_dynamic_tools[tool_id]
                count += 1
            except Exception as e:
                logger.warning(f"清除动态工具失败: {tool_id}, {e}")
        return count

    def get_search_result(self, search_id: str) -> Optional[QVerisSearchResult]:
        """获取缓存的搜索结果"""
        return self._recent_searches.get(search_id)

    @classmethod
    def get_recommended_system_prompt(cls) -> str:
        """获取推荐的系统提示词"""
        return cls.RECOMMENDED_SYSTEM_PROMPT


# 便捷函数
def create_qveris_adapter(
    tool_registry: Optional[ToolRegistry] = None,
    api_key: Optional[str] = None,
    auto_register: bool = True,
) -> QVerisToolAdapter:
    """
    创建并配置 QVeris 工具适配器

    Args:
        tool_registry: 工具注册表（默认使用全局实例）
        api_key: QVeris API Key
        auto_register: 是否自动注册元工具

    Returns:
        配置好的 QVerisToolAdapter 实例
    """
    registry = tool_registry or ToolRegistry.get_default()
    adapter = QVerisToolAdapter(
        tool_registry=registry,
        api_key=api_key,
    )

    if auto_register:
        adapter.register_meta_tools()

    return adapter


# 导出
__all__ = [
    "QVerisToolAdapter",
    "create_qveris_adapter",
]

"""
QVeris API 客户端

提供与 QVeris 工具搜索和执行服务的集成。
基于 QVeris REST API: https://qveris.ai/docs

功能：
- 工具搜索：通过自然语言查询发现远程工具
- 工具执行：执行发现的工具并获取结果
- 响应缓存：减少重复 API 调用
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio
import hashlib
import json
import os

from src.utils.logger import get_logger

logger = get_logger()

# 尝试导入 httpx，如果不存在则提示安装
try:
    import httpx
except ImportError:
    httpx = None
    logger.warning("httpx 未安装，QVeris 功能不可用。请运行: pip install httpx")


@dataclass
class QVerisToolInfo:
    """QVeris 工具信息"""

    tool_id: str
    name: str
    description: str
    input_schema: Dict[str, Any]
    examples: List[Dict[str, Any]] = field(default_factory=list)
    weighted_success_rate: Optional[float] = None
    avg_execution_time: Optional[float] = None  # 秒
    provider: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "examples": self.examples,
            "weighted_success_rate": self.weighted_success_rate,
            "avg_execution_time": self.avg_execution_time,
            "provider": self.provider,
            "tags": self.tags,
        }


@dataclass
class QVerisSearchResult:
    """QVeris 搜索结果"""

    search_id: str
    query: str
    tools: List[QVerisToolInfo]
    total_count: int
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "search_id": self.search_id,
            "query": self.query,
            "tools": [t.to_dict() for t in self.tools],
            "total_count": self.total_count,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class QVerisExecuteResult:
    """QVeris 执行结果"""

    tool_id: str
    success: bool
    content: Any
    truncated: bool = False
    full_content_url: Optional[str] = None
    execution_time_ms: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "success": self.success,
            "content": self.content,
            "truncated": self.truncated,
            "full_content_url": self.full_content_url,
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
        }


class QVerisClient:
    """
    QVeris API 客户端

    提供工具搜索和执行功能，支持：
    - 自然语言工具搜索
    - 远程工具执行
    - 响应缓存
    - 错误重试

    使用示例:
    ```python
    client = QVerisClient(api_key="your-api-key")

    # 搜索工具
    result = await client.search_tools("weather forecast API")
    for tool in result.tools:
        print(f"Tool: {tool.name} - {tool.description}")

    # 执行工具
    exec_result = await client.execute_tool(
        tool_id="openweathermap_current_weather",
        search_id=result.search_id,
        params={"city": "London", "units": "metric"}
    )
    print(exec_result.content)
    ```
    """

    DEFAULT_BASE_URL = "https://qveris.ai/api/v1"
    DEFAULT_TIMEOUT = 60  # 秒
    DEFAULT_MAX_RETRIES = 3

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        cache_ttl: int = 3600,  # 缓存时间（秒）
        session_id: Optional[str] = None,
    ):
        """
        初始化 QVeris 客户端

        Args:
            api_key: QVeris API 密钥（可从环境变量 QVERIS_API_KEY 读取）
            base_url: API 基础 URL
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            cache_ttl: 搜索结果缓存时间（秒）
            session_id: 会话 ID（用于追踪）
        """
        if httpx is None:
            raise ImportError("httpx 未安装。请运行: pip install httpx")

        self.api_key = api_key or os.environ.get("QVERIS_API_KEY", "")
        self.base_url = (
            base_url or os.environ.get("QVERIS_BASE_URL", self.DEFAULT_BASE_URL)
        ).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.cache_ttl = cache_ttl
        self.session_id = session_id

        # 搜索结果缓存
        self._search_cache: Dict[str, tuple[QVerisSearchResult, datetime]] = {}

        # HTTP 客户端（延迟初始化）
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            logger.warning(
                "QVeris API Key 未设置。请设置 QVERIS_API_KEY 环境变量或传入 api_key 参数。"
            )

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            # 只有当 API Key 非空时才添加 Authorization 头
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    def _check_api_key(self) -> None:
        """检查 API Key 是否已配置，未配置则抛出异常"""
        if not self.api_key:
            raise QVerisAPIError(
                "QVeris API Key 未配置。请设置 QVERIS_API_KEY 环境变量或在 config/app_config.yaml 中配置。"
            )

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _cache_key(self, query: str, limit: int) -> str:
        """生成缓存键"""
        return hashlib.md5(f"{query}:{limit}".encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> Optional[QVerisSearchResult]:
        """获取缓存的搜索结果"""
        if cache_key in self._search_cache:
            result, timestamp = self._search_cache[cache_key]
            if datetime.now() - timestamp < timedelta(seconds=self.cache_ttl):
                return result
            else:
                # 缓存过期
                del self._search_cache[cache_key]
        return None

    def _cache_result(self, cache_key: str, result: QVerisSearchResult):
        """缓存搜索结果"""
        self._search_cache[cache_key] = (result, datetime.now())

    def _params_to_json_schema(self, params: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        将 QVeris 的 params 列表转换为 JSON Schema 格式

        QVeris params 格式:
        [{"name": "q", "type": "string", "required": false, "description": {...}, "enum": [...]}]

        转换为 JSON Schema:
        {"type": "object", "properties": {...}, "required": [...]}
        """
        if not params:
            return {"type": "object", "properties": {}}

        properties = {}
        required = []

        for param in params:
            name = param.get("name", "")
            if not name:
                continue

            # 获取描述（可能是字符串或 dict）
            desc = param.get("description", "")
            if isinstance(desc, dict):
                desc = desc.get("en", desc.get("zh", str(desc)))

            prop = {
                "type": param.get("type", "string"),
                "description": desc,
            }

            # 添加 enum 如果存在
            if "enum" in param:
                prop["enum"] = param["enum"]

            properties[name] = prop

            # 添加到 required 列表
            if param.get("required", False):
                required.append(name)

        schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return schema

    async def search_tools(
        self,
        query: str,
        limit: int = 20,
        use_cache: bool = True,
    ) -> QVerisSearchResult:
        """
        搜索工具

        使用自然语言查询在 QVeris 平台上搜索可用工具。

        Args:
            query: 搜索查询（描述所需工具的能力）
            limit: 返回的最大工具数量（1-100）
            use_cache: 是否使用缓存

        Returns:
            QVerisSearchResult: 包含 search_id 和工具列表

        Raises:
            QVerisAPIError: API 调用失败时
        """
        # 检查 API Key
        self._check_api_key()

        # 检查缓存
        cache_key = self._cache_key(query, limit)
        if use_cache:
            cached = self._get_cached_result(cache_key)
            if cached:
                logger.debug(f"使用缓存的搜索结果: {query}")
                return cached

        client = await self._get_client()

        payload = {
            "query": query,
            "limit": min(max(1, limit), 100),
        }
        if self.session_id:
            payload["session_id"] = self.session_id

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await client.post("/search", json=payload)
                response.raise_for_status()
                data = response.json()

                # 调试：打印原始响应以便诊断
                logger.debug(f"QVeris 搜索原始响应: {data}")

                # 解析响应 - 支持多种响应格式
                tools = []
                # QVeris API 返回 "results" 而不是 "tools"
                tools_data = data.get(
                    "results", data.get("tools", data.get("data", []))
                )
                if isinstance(tools_data, dict):
                    tools_data = tools_data.get("results", tools_data.get("tools", []))

                for tool_data in tools_data:
                    # 将 params 列表转换为 JSON Schema 格式
                    params = tool_data.get("params", [])
                    input_schema = self._params_to_json_schema(params)

                    # 解析 examples
                    examples = tool_data.get("examples", {})
                    if isinstance(examples, dict):
                        examples = [examples] if examples else []

                    tools.append(
                        QVerisToolInfo(
                            tool_id=tool_data.get("tool_id", ""),
                            name=tool_data.get("name", tool_data.get("tool_id", "")),
                            description=tool_data.get("description", ""),
                            input_schema=input_schema,
                            examples=examples,
                            weighted_success_rate=tool_data.get(
                                "weighted_success_rate"
                            ),
                            avg_execution_time=tool_data.get("avg_execution_time"),
                            provider=tool_data.get(
                                "provider", tool_data.get("provider_description", "")
                            ),
                            tags=tool_data.get("tags", []),
                        )
                    )

                result = QVerisSearchResult(
                    search_id=data.get("search_id", ""),
                    query=query,
                    tools=tools,
                    total_count=len(tools),
                )

                # 缓存结果
                if use_cache:
                    self._cache_result(cache_key, result)

                logger.info(f"QVeris 搜索完成: '{query}' -> {len(tools)} 个工具")
                return result

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(
                    f"QVeris 搜索请求失败 (尝试 {attempt + 1}/{self.max_retries}): {e}"
                )
                if e.response.status_code == 429:
                    # 速率限制，等待后重试
                    await asyncio.sleep(2**attempt)
                elif e.response.status_code >= 500:
                    # 服务器错误，等待后重试
                    await asyncio.sleep(1)
                else:
                    # 客户端错误，不重试
                    raise QVerisAPIError(
                        f"搜索工具失败: {e.response.status_code}",
                        status_code=e.response.status_code,
                        response_body=e.response.text,
                    )
            except httpx.RequestError as e:
                last_error = e
                logger.warning(
                    f"QVeris 请求错误 (尝试 {attempt + 1}/{self.max_retries}): {e}"
                )
                await asyncio.sleep(1)

        raise QVerisAPIError(
            f"搜索工具失败，已重试 {self.max_retries} 次", cause=last_error
        )

    async def execute_tool(
        self,
        tool_id: str,
        search_id: str,
        params: Dict[str, Any],
        max_response_size: int = 20480,
    ) -> QVerisExecuteResult:
        """
        执行工具

        执行通过搜索发现的工具。

        Args:
            tool_id: 工具 ID（来自搜索结果）
            search_id: 搜索 ID（来自搜索结果）
            params: 工具参数
            max_response_size: 最大响应大小（字节），超出时会截断并提供下载链接

        Returns:
            QVerisExecuteResult: 执行结果

        Raises:
            QVerisAPIError: API 调用失败时
        """
        # 检查 API Key
        self._check_api_key()

        client = await self._get_client()

        payload = {
            "search_id": search_id,
            "parameters": params,
            "max_response_size": max_response_size,
        }
        if self.session_id:
            payload["session_id"] = self.session_id

        start_time = datetime.now()
        last_error = None

        for attempt in range(self.max_retries):
            try:
                response = await client.post(
                    f"/tools/execute?tool_id={tool_id}",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                execution_time = (datetime.now() - start_time).total_seconds() * 1000

                # 检查是否截断
                truncated = data.get("truncated", False)
                content = data.get("content", data.get("truncated_content", data))
                full_url = data.get("full_content_file_url")

                result = QVerisExecuteResult(
                    tool_id=tool_id,
                    success=True,
                    content=content,
                    truncated=truncated,
                    full_content_url=full_url,
                    execution_time_ms=execution_time,
                )

                logger.info(
                    f"QVeris 工具执行完成: {tool_id}, 耗时 {execution_time:.2f}ms"
                )
                return result

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(
                    f"QVeris 执行请求失败 (尝试 {attempt + 1}/{self.max_retries}): {e}"
                )
                if e.response.status_code == 429:
                    await asyncio.sleep(2**attempt)
                elif e.response.status_code >= 500:
                    await asyncio.sleep(1)
                else:
                    return QVerisExecuteResult(
                        tool_id=tool_id,
                        success=False,
                        content=None,
                        error=f"HTTP {e.response.status_code}: {e.response.text[:500]}",
                        execution_time_ms=(datetime.now() - start_time).total_seconds()
                        * 1000,
                    )
            except httpx.RequestError as e:
                last_error = e
                logger.warning(
                    f"QVeris 请求错误 (尝试 {attempt + 1}/{self.max_retries}): {e}"
                )
                await asyncio.sleep(1)

        return QVerisExecuteResult(
            tool_id=tool_id,
            success=False,
            content=None,
            error=f"执行失败，已重试 {self.max_retries} 次: {last_error}",
            execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
        )

    async def get_tools_by_ids(
        self,
        tool_ids: List[str],
        search_id: Optional[str] = None,
    ) -> List[QVerisToolInfo]:
        """
        通过工具 ID 获取工具信息

        Args:
            tool_ids: 工具 ID 列表
            search_id: 关联的搜索 ID

        Returns:
            工具信息列表
        """
        # 检查 API Key
        self._check_api_key()

        client = await self._get_client()

        payload = {
            "tool_ids": tool_ids,
        }
        if search_id:
            payload["search_id"] = search_id
        if self.session_id:
            payload["session_id"] = self.session_id

        try:
            response = await client.post("/tools/by-ids", json=payload)
            response.raise_for_status()
            data = response.json()

            tools = []
            for tool_data in data.get("tools", []):
                tools.append(
                    QVerisToolInfo(
                        tool_id=tool_data.get("tool_id", ""),
                        name=tool_data.get("name", ""),
                        description=tool_data.get("description", ""),
                        input_schema=tool_data.get("input_schema", {}),
                        examples=tool_data.get("examples", []),
                        weighted_success_rate=tool_data.get("weighted_success_rate"),
                        avg_execution_time=tool_data.get("avg_execution_time"),
                        provider=tool_data.get("provider"),
                        tags=tool_data.get("tags", []),
                    )
                )

            return tools

        except httpx.HTTPError as e:
            logger.error(f"获取工具信息失败: {e}")
            return []

    def clear_cache(self):
        """清除搜索缓存"""
        self._search_cache.clear()
        logger.debug("QVeris 搜索缓存已清除")


class QVerisAPIError(Exception):
    """QVeris API 错误"""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        self.cause = cause

    def __str__(self):
        parts = [self.message]
        if self.status_code:
            parts.append(f"(HTTP {self.status_code})")
        if self.cause:
            parts.append(f"Caused by: {self.cause}")
        return " ".join(parts)


# 导出
__all__ = [
    "QVerisClient",
    "QVerisSearchResult",
    "QVerisExecuteResult",
    "QVerisToolInfo",
    "QVerisAPIError",
]

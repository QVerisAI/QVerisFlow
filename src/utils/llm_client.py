"""
统一 LLM 客户端 - 纯基础层实现

设计原则:
1. **单一职责**: 只处理 LLM 调用的通用功能，不包含业务逻辑
2. **参数简单**: 只接受核心参数（provider, base_url, api_key, model_name）
3. **功能完整**: 重试机制、JSON 优化、Token 追踪、客户端缓存

核心功能:
- 统一的参数管理
- 完善的重试机制（指数退避）
- JSON 响应优化（6 种策略）
- Token 使用量追踪（可选）
- 客户端缓存（性能优化）
- 多客户端类型支持（AsyncOpenAI, LangChain, Litellm）
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Type, Union

import httpx
from langchain_openai import ChatOpenAI
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from pydantic import BaseModel

from src.utils.logger import get_logger
from src.utils.token_usage_tracker import (
    ModelCallMetrics,
    get_global_tracker,
)

logger = get_logger()


def _get_proxy_config() -> Optional[Dict[str, str]]:
    """获取代理配置（如果可用）"""
    try:
        from src.utils.proxy_utils import get_proxy_config

        return get_proxy_config()
    except ImportError:
        return None


class ClientFactory:
    """
    客户端工厂 - 创建不同类型的客户端

    支持:
    - AsyncOpenAI (直接调用，性能最优)
    - LangChain ChatOpenAI (兼容 LangChain 生态)
    - LitellmModel (兼容 Agents SDK)

    特性:
    - HTTP 客户端缓存（连接复用，避免资源泄漏）
    - ChatOpenAI 实例不缓存（避免状态累积）
    - 代理支持
    """

    _client_cache: Dict[str, Any] = {}
    _http_client_cache: Dict[str, Any] = {}  # 单独缓存 HTTP 客户端

    @classmethod
    def _create_http_client(
        cls,
        async_client: bool = True,
        timeout_config: Optional[Dict[str, float]] = None,
        proxy_config: Optional[Dict[str, str]] = None,
    ) -> Union[httpx.AsyncClient, httpx.Client]:
        """创建 HTTP 客户端"""
        timeout_config = timeout_config or {}

        kwargs = {
            "timeout": httpx.Timeout(
                connect=timeout_config.get("connect", 30.0),
                read=timeout_config.get("read", 300.0),
                write=timeout_config.get("write", 30.0),
                pool=timeout_config.get("pool", 30.0),
            ),
            "limits": httpx.Limits(
                max_keepalive_connections=timeout_config.get(
                    "max_keepalive_connections", 20
                ),
                max_connections=timeout_config.get("max_connections", 100),
                keepalive_expiry=timeout_config.get("keepalive_expiry", 30.0),
            ),
        }

        if proxy_config:
            if async_client:
                from httpx import AsyncHTTPTransport

                mounts = {}
                if "http://" in proxy_config:
                    mounts["http://"] = AsyncHTTPTransport(
                        proxy=proxy_config["http://"]
                    )
                if "https://" in proxy_config:
                    mounts["https://"] = AsyncHTTPTransport(
                        proxy=proxy_config["https://"]
                    )
                kwargs["mounts"] = mounts
            else:
                from httpx import HTTPTransport

                mounts = {}
                if "http://" in proxy_config:
                    mounts["http://"] = HTTPTransport(proxy=proxy_config["http://"])
                if "https://" in proxy_config:
                    mounts["https://"] = HTTPTransport(proxy=proxy_config["https://"])
                kwargs["mounts"] = mounts
            logger.info("✅ HTTP 客户端已启用代理")

        if async_client:
            return httpx.AsyncClient(**kwargs)
        else:
            return httpx.Client(**kwargs)

    @classmethod
    def create_async_openai_client(
        cls,
        base_url: str,
        api_key: str,
        timeout: Optional[float] = None,
        http_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncOpenAI:
        """创建 AsyncOpenAI 客户端"""
        cache_key = f"async_openai_{base_url}"

        if cache_key in cls._client_cache:
            logger.debug(f"使用缓存的 AsyncOpenAI 客户端: {base_url}")
            return cls._client_cache[cache_key]

        proxy_config = _get_proxy_config()
        http_client = cls._create_http_client(
            async_client=True, timeout_config=http_config, proxy_config=proxy_config
        )

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout or 300.0,
            max_retries=0,  # 重试由 UnifiedLLMClient 处理
            http_client=http_client,
        )

        cls._client_cache[cache_key] = client
        logger.info(f"✅ 创建 AsyncOpenAI 客户端: {base_url}")
        return client

    @classmethod
    def _get_or_create_http_clients(
        cls,
        base_url: str,
        http_config: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """
        获取或创建 HTTP 客户端（缓存复用，避免连接泄漏）

        HTTP 客户端是无状态的，可以安全地复用。
        """
        cache_key = f"http_{base_url}"

        if cache_key in cls._http_client_cache:
            return cls._http_client_cache[cache_key]

        proxy_config = _get_proxy_config()
        http_client = cls._create_http_client(
            async_client=False, timeout_config=http_config, proxy_config=proxy_config
        )
        async_http_client = cls._create_http_client(
            async_client=True, timeout_config=http_config, proxy_config=proxy_config
        )

        cls._http_client_cache[cache_key] = (http_client, async_http_client)
        logger.debug(f"✅ 创建并缓存 HTTP 客户端: {base_url}")

        return http_client, async_http_client

    @classmethod
    def create_langchain_client(
        cls,
        base_url: str,
        api_key: str,
        model_name: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        timeout: Optional[float] = None,
        max_retries: int = 3,
        use_cache: bool = False,  # 默认禁用 ChatOpenAI 缓存，避免状态累积问题
    ) -> ChatOpenAI:
        """
        创建 LangChain ChatOpenAI 客户端

        策略（彻底隔离模式）：
        - 每次创建全新的 ChatOpenAI 实例
        - 不传入 HTTP 客户端，让 ChatOpenAI 自己管理连接
        - 完全避免任何可能的状态累积
        """
        # ChatOpenAI 实例缓存（仅在明确启用时使用）
        chat_cache_key = f"langchain_{base_url}_{model_name}_{temperature}_{max_tokens}"
        if use_cache and chat_cache_key in cls._client_cache:
            logger.debug(f"使用缓存的 LangChain 客户端: {model_name}")
            return cls._client_cache[chat_cache_key]

        # 彻底隔离模式：不传入任何 HTTP 客户端，让 ChatOpenAI 自己创建和管理
        # 这样可以完全避免 HTTP 客户端状态累积的问题
        logger.debug(
            f"🔄 创建全新的 LangChain 客户端（无共享 HTTP 客户端）: {model_name}"
        )

        # 准备额外的模型参数
        model_kwargs = {}

        # 检查是否为 Kimi/Moonshot 模型，如果是，禁用 thinking 模式
        # Kimi 的 thinking 模式会导致 tool calling 场景下的消息格式问题
        # 错误: 'thinking is enabled but reasoning_content is missing in assistant tool call message'
        # 根据 Moonshot API 官方文档，正确的禁用方式是：
        # "thinking": {"type": "disabled"}
        # 参考: https://platform.moonshot.ai/docs/guide/kimi-k2-5-quickstart#disable-thinking-capability-example
        #
        # 重要：kimi-k2.5 模型的 temperature 限制：
        # - thinking 模式启用时：temperature 必须为 1.0
        # - thinking 模式禁用时：temperature 必须为 0.6
        # 任何其他值都会导致 400 错误
        model_lower = model_name.lower() if model_name else ""
        is_kimi = "kimi" in model_lower or "moonshot" in model_lower

        if is_kimi:
            # 通过 extra_body 禁用 thinking 模式
            # kimi-k2.5 模型默认启用 thinking，需要显式禁用
            model_kwargs["extra_body"] = {
                "thinking": {"type": "disabled"},  # 正确的禁用 thinking 模式参数
            }
            # 禁用 thinking 模式时，temperature 必须为 0.6
            temperature = 0.6
            logger.debug(
                f"🔄 Kimi/Moonshot 模型检测到，已禁用 thinking 模式，temperature 设为 0.6"
            )

        # 构建 ChatOpenAI 参数
        chat_kwargs = {
            "model": model_name,
            "base_url": base_url,
            "openai_api_key": api_key,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout or 300.0,
            "max_retries": max_retries,
            # 不传入 http_client 和 http_async_client，让 ChatOpenAI 自己创建
            # 这样每个 ChatOpenAI 实例都有自己独立的 HTTP 客户端
        }

        # 只有当 model_kwargs 非空时才传入，避免传入空字典或 None 导致错误
        if model_kwargs:
            chat_kwargs["model_kwargs"] = model_kwargs

        client = ChatOpenAI(**chat_kwargs)

        # 只有明确启用缓存时才缓存 ChatOpenAI 实例
        if use_cache:
            cls._client_cache[chat_cache_key] = client
            logger.info(f"✅ 创建并缓存 LangChain 客户端: {model_name}")
        else:
            logger.debug(f"✅ 创建 LangChain 客户端（独立 HTTP 连接）: {model_name}")
        return client

    @classmethod
    def create_litellm_model(
        cls,
        provider: str,
        base_url: str,
        api_key: str,
        model_name: str,
    ) -> Any:
        """创建 Litellm 模型"""
        cache_key = f"litellm_{provider}_{model_name}"

        if cache_key in cls._client_cache:
            logger.debug(f"使用缓存的 Litellm 模型: {model_name}")
            return cls._client_cache[cache_key]

        try:
            from agents.extensions.models.litellm_model import LitellmModel  # type: ignore
        except ImportError as e:
            raise ImportError(
                "缺少 agents.models.LitellmModel，请确认依赖已安装"
            ) from e

        # 根据 provider 添加前缀
        model_with_prefix = f"{provider}/{model_name}"

        litellm_model = LitellmModel(
            model=model_with_prefix,
            api_key=api_key,
            base_url=base_url,
        )

        cls._client_cache[cache_key] = litellm_model
        logger.info(f"✅ 创建 Litellm 模型: {model_with_prefix}")
        return litellm_model

    @classmethod
    def clear_cache(cls, close_http_clients: bool = False):
        """
        清空客户端缓存

        Args:
            close_http_clients: 是否关闭 HTTP 客户端（默认 False，保持连接复用）
        """
        cls._client_cache.clear()
        logger.info("✅ ChatOpenAI 客户端缓存已清空")

        if close_http_clients:
            # 关闭所有 HTTP 客户端
            for cache_key, (
                http_client,
                async_http_client,
            ) in cls._http_client_cache.items():
                try:
                    http_client.close()
                    # 注意：AsyncClient 需要在异步上下文中关闭
                    # 这里只是同步清理，异步客户端会在垃圾回收时自动关闭
                except Exception as e:
                    logger.warning(f"关闭 HTTP 客户端失败: {e}")
            cls._http_client_cache.clear()
            logger.info("✅ HTTP 客户端缓存已清空并关闭连接")


class UnifiedLLMClient:
    """
    统一 LLM 客户端 - 纯基础层实现

    核心功能:
    - 统一的参数管理
    - 完善的重试机制（指数退避）
    - JSON 响应优化（6 种策略）
    - Token 使用量追踪（可选）
    - 客户端缓存（性能优化）
    - 多客户端类型支持（AsyncOpenAI, LangChain, Litellm）

    设计原则:
    - 单一职责：只处理 LLM 调用的通用功能
    - 无业务逻辑：不包含 fast_model, smart_model 等业务概念
    - 参数简单：只接受核心参数

    LiteLLM 支持策略:
    - ✅ JSON 响应优化（处理格式问题）
    - ✅ Token 使用量追踪（统一统计）
    - ⚠️ 重试机制（作为 LiteLLM 内置重试的额外保障）
    - 注意：LiteLLM 已有自己的重试和错误处理，本客户端的重试作为兜底
    """

    def __init__(
        self,
        # ==== 核心参数（必需） ====
        provider: str,  # 提供商标识（如 "dashscope", "openrouter"）
        base_url: str,  # API 基础 URL
        api_key: str,  # API 密钥
        model_name: str,  # 模型名称
        # ==== 客户端类型（必需） ====
        client_type: Literal["async_openai", "langchain", "litellm"] = "langchain",
        # ==== 可选参数 ====
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout: float = 300,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        enable_token_tracking: bool = True,
        # ==== HTTP 客户端配置（可选） ====
        http_config: Optional[Dict[str, Any]] = None,
        # ==== 其他参数 ====
        **kwargs,
    ):
        """
        初始化统一客户端

        Args:
            provider: 提供商标识（用于日志和缓存 key）
            base_url: API 基础 URL
            api_key: API 密钥
            model_name: 模型名称
            client_type: 客户端类型
                - "async_openai": AsyncOpenAI（性能最优）
                - "langchain": LangChain ChatOpenAI（兼容生态）
                - "litellm": LitellmModel（兼容 Agents SDK）
            temperature: 温度参数
            max_tokens: 最大 token 数
            timeout: 超时时间（秒）
            max_retries: 最大重试次数
            retry_base_delay: 重试基础延迟（秒）
            enable_token_tracking: 是否启用 token 追踪
            http_config: HTTP 客户端配置（超时、连接池等）
            **kwargs: 其他参数（传递给底层客户端）
        """
        # 核心参数
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.client_type = client_type

        # 可选参数
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.enable_token_tracking = enable_token_tracking
        self.http_config = http_config or {}
        self.kwargs = kwargs

        # Token 追踪器
        self.token_tracker = get_global_tracker() if enable_token_tracking else None

        # 创建底层客户端
        self._create_client()

        logger.info(
            f"✅ 统一客户端初始化: provider={self.provider}, model={self.model_name}, "
            f"type={self.client_type}, tracking={self.enable_token_tracking}"
        )

    def _create_client(self):
        """创建底层客户端"""
        if self.client_type == "async_openai":
            self._async_openai_client = ClientFactory.create_async_openai_client(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
                http_config=self.http_config,
            )
            self._langchain_client = None
            self._litellm_model = None

        elif self.client_type == "langchain":
            self._async_openai_client = None
            self._langchain_client = ClientFactory.create_langchain_client(
                base_url=self.base_url,
                api_key=self.api_key,
                model_name=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
            self._litellm_model = None

        elif self.client_type == "litellm":
            self._async_openai_client = None
            self._langchain_client = None
            self._litellm_model = ClientFactory.create_litellm_model(
                provider=self.provider,
                base_url=self.base_url,
                api_key=self.api_key,
                model_name=self.model_name,
            )

        else:
            raise ValueError(f"不支持的客户端类型: {self.client_type}")

    def _is_json_response_expected(self, response_format: Any) -> bool:
        """判断是否期望 JSON 格式响应"""
        if (
            isinstance(response_format, dict)
            and response_format.get("type") == "json_object"
        ):
            return True

        # 检查是否是 Pydantic 模型
        if hasattr(response_format, "__bases__") and hasattr(
            response_format, "model_fields"
        ):
            return True

        return False

    def _optimize_json_response(self, content: str) -> Optional[str]:
        """
        优化 JSON 响应，尝试修复常见的 JSON 格式问题

        实现了 7 种优化策略:
        1. 移除前缀和后缀（```json、解释文字等）
        2. 提取 JSON 对象边界
        3. 修复引号问题
        4. 截断到最后一个完整对象
        5. 修复截断的字符串值
        6. 修复截断的数组内容
        7. 移除 JSON 前后的解释文字
        """
        if not content:
            return None

        # 策略 1: 移除可能的前缀和后缀
        optimized = content.strip()

        # 移除常见的 markdown 代码块标记
        if optimized.startswith("```json"):
            optimized = optimized[7:]
        elif optimized.startswith("```"):
            optimized = optimized[3:]

        if optimized.endswith("```"):
            optimized = optimized[:-3]

        optimized = optimized.strip()

        # 移除可能的解释文字（在 JSON 之前）
        # 查找第一个 { 之前是否有文字
        first_brace = optimized.find("{")
        if first_brace > 0:
            # 检查前面是否有解释文字（如 "Here is the JSON:", "以下是分析结果：" 等）
            prefix = optimized[:first_brace].strip()
            if prefix and len(prefix) < 200:  # 合理的前缀长度
                # 如果前缀看起来像解释文字，移除它
                if any(
                    keyword in prefix.lower()
                    for keyword in [
                        "json",
                        "结果",
                        "输出",
                        "分析",
                        "here",
                        "following",
                        "below",
                    ]
                ):
                    optimized = optimized[first_brace:]

        # 移除可能的解释文字（在 JSON 之后）
        last_brace = optimized.rfind("}")
        if last_brace > 0 and last_brace < len(optimized) - 1:
            # 检查后面是否有解释文字
            suffix = optimized[last_brace + 1 :].strip()
            if suffix and len(suffix) < 200:  # 合理的后缀长度
                # 如果后缀看起来像解释文字，移除它
                if any(
                    keyword in suffix.lower()
                    for keyword in [
                        "希望",
                        "以上",
                        "注意",
                        "说明",
                        "hope",
                        "above",
                        "note",
                    ]
                ):
                    optimized = optimized[: last_brace + 1]

        optimized = optimized.strip()

        # 尝试解析
        try:
            json.loads(optimized)
            logger.debug("✅ JSON 优化成功：移除前缀/后缀")
            return optimized
        except json.JSONDecodeError:
            pass

        # 策略 2: 尝试找到 JSON 对象边界
        json_start = optimized.find("{")
        json_end = optimized.rfind("}")

        if json_start != -1 and json_end != -1 and json_end > json_start:
            json_content = optimized[json_start : json_end + 1]
            try:
                json.loads(json_content)
                logger.debug("✅ JSON 优化成功：提取 JSON 对象")
                return json_content
            except json.JSONDecodeError:
                pass

        # 策略 3: 尝试修复常见的 JSON 格式问题
        try:
            fixed_content = optimized
            # 修复键名
            fixed_content = re.sub(
                r"([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', fixed_content
            )
            # 修复值
            fixed_content = re.sub(
                r":\s*([a-zA-Z_][a-zA-Z0-9_]*)(?=\s*[,}])", r': "\1"', fixed_content
            )

            json.loads(fixed_content)
            logger.debug("✅ JSON 优化成功：修复引号问题")
            return fixed_content
        except json.JSONDecodeError:
            pass

        # 策略 4: 尝试截断到最后一个完整的 JSON 对象
        try:
            # 从后往前找到最后一个完整的 JSON 对象
            brace_count = 0
            last_complete_pos = -1

            for i in range(len(optimized) - 1, -1, -1):
                if optimized[i] == "}":
                    brace_count += 1
                elif optimized[i] == "{":
                    brace_count -= 1
                    if brace_count == 0:
                        last_complete_pos = i
                        break

            if last_complete_pos != -1:
                truncated = optimized[last_complete_pos:]
                json.loads(truncated)
                logger.debug("✅ JSON 优化成功：截断到完整对象")
                return truncated
        except json.JSONDecodeError:
            pass

        # 策略 5: 尝试修复截断的字符串值（在数组或对象中）
        try:
            # 如果响应被截断，尝试关闭未完成的字符串、数组或对象
            fixed_content = optimized

            # 检查是否在字符串中（未闭合的引号）
            in_string = False
            escape_next = False
            last_quote_pos = -1

            for i, char in enumerate(fixed_content):
                if escape_next:
                    escape_next = False
                    continue
                if char == "\\":
                    escape_next = True
                    continue
                if char == '"':
                    if not in_string:
                        in_string = True
                        last_quote_pos = i
                    else:
                        in_string = False
                        last_quote_pos = -1

            # 如果字符串未闭合，尝试闭合它
            if in_string and last_quote_pos != -1:
                # 找到字符串开始的位置
                string_start = last_quote_pos
                # 尝试找到这个字符串应该结束的位置（在下一个逗号、冒号、}或]之前）
                for i in range(string_start + 1, len(fixed_content)):
                    if fixed_content[i] in [",", ":", "}", "]", "\n"]:
                        fixed_content = fixed_content[:i] + '"' + fixed_content[i:]
                        break
                else:
                    # 如果没找到，在末尾添加引号
                    fixed_content = fixed_content + '"'

            # 尝试关闭未完成的数组或对象
            open_braces = fixed_content.count("{") - fixed_content.count("}")
            open_brackets = fixed_content.count("[") - fixed_content.count("]")

            # 如果对象未闭合，尝试闭合
            if open_braces > 0:
                # 移除末尾可能的未完成内容（如未完成的键值对）
                # 找到最后一个完整的键值对
                last_comma = fixed_content.rfind(",")
                last_colon = fixed_content.rfind(":")

                if last_colon > last_comma:
                    # 有未完成的键值对，尝试修复
                    # 找到最后一个冒号后的内容
                    after_colon = fixed_content[last_colon + 1 :].strip()
                    if after_colon and not after_colon.endswith(
                        ('"', "}", "]", "true", "false", "null")
                    ):
                        # 可能是未完成的字符串或值，尝试截断到最后一个逗号
                        if last_comma != -1:
                            fixed_content = fixed_content[:last_comma] + "}"
                        else:
                            fixed_content = fixed_content[:last_colon] + ": null}"
                    else:
                        fixed_content = fixed_content + "}" * open_braces
                else:
                    fixed_content = fixed_content + "}" * open_braces

            # 如果数组未闭合，尝试闭合
            if open_brackets > 0:
                fixed_content = fixed_content + "]" * open_brackets

            # 尝试解析修复后的内容
            json.loads(fixed_content)
            logger.debug("✅ JSON 优化成功：修复截断的字符串/对象")
            return fixed_content
        except (json.JSONDecodeError, IndexError, ValueError):
            pass

        # 策略 6: 尝试提取并修复数组内容
        try:
            # 查找常见的数组字段（如 "items", "results", "data" 等）
            array_patterns = [
                r'"items"\s*:\s*\[',
                r'"results"\s*:\s*\[',
                r'"data"\s*:\s*\[',
                r'"list"\s*:\s*\[',
            ]

            for pattern in array_patterns:
                array_match = re.search(pattern, optimized)
                if array_match:
                    array_start = array_match.end() - 1  # 包括 '['
                    # 找到数组的结束位置（可能不完整）
                    bracket_count = 0
                    array_end = -1

                    for i in range(array_start, len(optimized)):
                        if optimized[i] == "[":
                            bracket_count += 1
                        elif optimized[i] == "]":
                            bracket_count -= 1
                            if bracket_count == 0:
                                array_end = i
                                break

                    if array_end == -1:
                        # 数组未闭合，尝试找到最后一个完整的对象并闭合数组
                        # 从后往前找最后一个完整的对象
                        brace_count = 0
                        last_obj_end = -1
                        for i in range(len(optimized) - 1, array_start, -1):
                            if optimized[i] == "}":
                                brace_count += 1
                            elif optimized[i] == "{":
                                brace_count -= 1
                                if brace_count == 0:
                                    last_obj_end = i
                                    break

                        if last_obj_end != -1:
                            # 构建完整的JSON
                            before_array = optimized[:array_start]
                            array_content = optimized[array_start : last_obj_end + 1]
                            fixed_content = before_array + array_content + "]}"
                            try:
                                json.loads(fixed_content)
                                logger.debug("✅ JSON 优化成功：修复截断的数组")
                                return fixed_content
                            except json.JSONDecodeError:
                                continue
        except (json.JSONDecodeError, IndexError, ValueError):
            pass

        # 记录失败信息以便调试
        content_preview = content[:500] if len(content) > 500 else content
        logger.warning(f"⚠️ JSON 优化失败：无法修复 JSON 格式")
        logger.debug(f"响应内容预览（前500字符）: {content_preview}")
        if len(content) > 500:
            logger.debug(f"响应内容预览（后500字符）: {content[-500:]}")
        return None

    def _adjust_params_for_model(
        self,
        temperature: float,
        max_tokens: int,
    ) -> tuple[float, int]:
        """
        根据模型特性调整参数

        某些模型对参数有特殊限制：
        - moonshot (kimi): 某些模型只支持 temperature=1
        - 其他模型可能有类似限制

        Args:
            temperature: 原始温度参数
            max_tokens: 原始 max_tokens

        Returns:
            调整后的 (temperature, max_tokens)
        """
        model_lower = self.model_name.lower() if self.model_name else ""

        # moonshot/kimi 模型限制
        # https://platform.moonshot.cn/docs/api-reference
        if "moonshot" in model_lower or "kimi" in model_lower:
            # moonshot 某些模型只接受 temperature=1
            # 其他模型接受 0.0-1.0，但某些高级模型有限制
            if temperature != 1.0:
                logger.debug(
                    f"模型 {self.model_name} 可能要求 temperature=1，"
                    f"原始值 {temperature} 将被调整"
                )
                # 如果不是 0（确定性），则使用 1
                temperature = 1.0

        return temperature, max_tokens

    async def call(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Any:
        """
        统一的调用接口

        特性:
        - 自动重试（指数退避）
        - JSON 响应优化
        - Token 追踪
        - 详细日志
        - 模型特定参数调整（如 moonshot 的 temperature 限制）

        Args:
            messages: 消息列表
            temperature: 温度参数（可选，覆盖实例配置）
            max_tokens: 最大 token 数（可选，覆盖实例配置）
            response_format: 响应格式（JSON 或 Pydantic 模型）
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            响应对象（类型取决于 client_type）
        """
        # 使用传入参数或实例默认值
        temp = temperature if temperature is not None else self.temperature
        max_tok = max_tokens if max_tokens is not None else self.max_tokens

        # 根据模型调整参数
        temp, max_tok = self._adjust_params_for_model(temp, max_tok)

        # 检查是否期望 JSON 响应
        expect_json = self._is_json_response_expected(response_format)

        # 重试循环
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"🔄 LLM 调用尝试 {attempt + 1}/{self.max_retries}")

                # 根据客户端类型调用
                if self.client_type == "async_openai":
                    response = await self._call_async_openai(
                        messages=messages,
                        temperature=temp,
                        max_tokens=max_tok,
                        response_format=response_format,
                        stream=stream,
                        **kwargs,
                    )

                elif self.client_type == "langchain":
                    response = await self._call_langchain(
                        messages=messages,
                        temperature=temp,
                        max_tokens=max_tok,
                        **kwargs,
                    )

                elif self.client_type == "litellm":
                    response = await self._call_litellm(
                        messages=messages,
                        temperature=temp,
                        max_tokens=max_tok,
                        **kwargs,
                    )

                # 如果期望 JSON 响应，尝试优化
                if expect_json:
                    content = None
                    # 提取内容（支持多种响应格式）
                    if hasattr(response, "content"):
                        # LangChain 风格：response.content
                        content = response.content
                        content_path = "content"
                    elif hasattr(response, "choices") and response.choices:
                        # OpenAI/LiteLLM 风格：response.choices[0].message.content
                        content = response.choices[0].message.content
                        content_path = "choices[0].message.content"

                    if content:
                        optimized_content = self._optimize_json_response(content)
                        if optimized_content and optimized_content != content:
                            logger.info(f"🔧 JSON 响应已优化 (from {content_path})")
                            # 更新内容
                            if content_path == "content":
                                response.content = optimized_content
                            else:  # choices[0].message.content
                                response.choices[0].message.content = optimized_content

                # 记录 token 使用量
                if self.enable_token_tracking and hasattr(response, "usage"):
                    self._record_token_usage(response.usage)

                return response

            except (APIConnectionError, APITimeoutError, RateLimitError) as e:
                if attempt < self.max_retries - 1:
                    delay = self.retry_base_delay * (2**attempt)
                    logger.warning(
                        f"⚠️ LLM 调用失败 (尝试 {attempt + 1}/{self.max_retries}): {e}"
                    )
                    logger.info(f"⏳ 等待 {delay:.1f} 秒后重试...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"❌ LLM 调用最终失败: {e}")
                    raise

            except Exception as e:
                # JSON 解析错误可以重试
                if expect_json and "JSON" in str(e) and attempt < self.max_retries - 1:
                    logger.warning(
                        f"⚠️ JSON 解析失败，尝试重新调用 LLM (尝试 {attempt + 1}/{self.max_retries}): {e}"
                    )
                    delay = self.retry_base_delay * (2**attempt)
                    logger.info(f"⏳ 等待 {delay:.1f} 秒后重试...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"❌ LLM 调用出现未知错误: {e}")
                    raise

    async def call_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tool_choice: str = "auto",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        带工具调用支持的 LLM 调用接口

        使用 OpenAI 原生 Function Calling API 实现可靠的工具调用。

        Args:
            messages: 消息列表
            tools: 工具定义列表（OpenAI function 格式）
            temperature: 温度参数（可选）
            max_tokens: 最大 token 数（可选）
            tool_choice: 工具选择策略 ("auto", "none", "required", 或具体工具名)
            **kwargs: 其他参数

        Returns:
            包含 content 和 tool_calls 的字典
        """
        # 使用传入参数或实例默认值
        temp = temperature if temperature is not None else self.temperature
        max_tok = max_tokens if max_tokens is not None else self.max_tokens

        # 根据模型调整参数
        temp, max_tok = self._adjust_params_for_model(temp, max_tok)

        # 重试循环
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"🔧 LLM 工具调用尝试 {attempt + 1}/{self.max_retries}")

                if self.client_type == "async_openai":
                    response = await self._call_async_openai_with_tools(
                        messages=messages,
                        tools=tools,
                        temperature=temp,
                        max_tokens=max_tok,
                        tool_choice=tool_choice,
                        **kwargs,
                    )
                elif self.client_type == "langchain":
                    # LangChain 也支持工具调用
                    response = await self._call_langchain_with_tools(
                        messages=messages,
                        tools=tools,
                        temperature=temp,
                        max_tokens=max_tok,
                        **kwargs,
                    )
                else:
                    # 对于不支持原生工具调用的客户端，回退到嵌入式提示
                    logger.warning(
                        f"客户端类型 {self.client_type} 不支持原生工具调用，使用提示词方式"
                    )
                    return await self._call_with_embedded_tools(
                        messages=messages,
                        tools=tools,
                        temperature=temp,
                        max_tokens=max_tok,
                        **kwargs,
                    )

                # 解析响应
                result = self._parse_tool_response(response)

                # 记录 token 使用量
                if self.enable_token_tracking and hasattr(response, "usage"):
                    self._record_token_usage(response.usage)

                return result

            except (APIConnectionError, APITimeoutError, RateLimitError) as e:
                if attempt < self.max_retries - 1:
                    delay = self.retry_base_delay * (2**attempt)
                    logger.warning(
                        f"⚠️ 工具调用失败 (尝试 {attempt + 1}/{self.max_retries}): {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"❌ 工具调用最终失败: {e}")
                    raise
            except Exception as e:
                logger.error(f"❌ 工具调用出现错误: {e}")
                raise

    async def _call_async_openai_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tool_choice: str = "auto",
        **kwargs,
    ) -> Any:
        """使用 AsyncOpenAI 进行工具调用"""
        call_kwargs = {
            "model": self.model_name,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        return await self._async_openai_client.chat.completions.create(**call_kwargs)

    async def _call_langchain_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> Any:
        """使用 LangChain 进行工具调用"""
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

        # 转换消息格式
        langchain_messages = []
        for msg in messages:
            if msg["role"] == "system":
                langchain_messages.append(SystemMessage(content=msg["content"]))
            elif msg["role"] == "user":
                langchain_messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                langchain_messages.append(AIMessage(content=msg["content"]))

        # 绑定工具到模型
        model_with_tools = self._langchain_client.bind_tools(tools)

        return await model_with_tools.ainvoke(
            langchain_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    async def _call_with_embedded_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> Dict[str, Any]:
        """使用嵌入式提示词进行工具调用（回退方案）"""
        # 构建工具提示
        tool_descriptions = []
        for tool in tools:
            func = tool.get("function", tool)
            name = func.get("name", "unknown")
            desc = func.get("description", "")
            params = func.get("parameters", {}).get("properties", {})
            param_desc = ", ".join(
                [f"{k}: {v.get('description', '')}" for k, v in params.items()]
            )
            tool_descriptions.append(f"- {name}: {desc}\n  参数: {param_desc or '无'}")

        tool_prompt = f"""## 可用工具
当需要执行操作时，使用以下 JSON 格式调用工具：
<tool_call>
{{"name": "工具名称", "arguments": {{"参数名": "参数值"}}}}
</tool_call>

可用工具：
{chr(10).join(tool_descriptions)}
"""

        # 增强系统消息
        enhanced_messages = messages.copy()
        if enhanced_messages and enhanced_messages[0]["role"] == "system":
            enhanced_messages[0] = {
                "role": "system",
                "content": enhanced_messages[0]["content"] + "\n\n" + tool_prompt,
            }
        else:
            enhanced_messages.insert(0, {"role": "system", "content": tool_prompt})

        # 调用 LLM
        response = await self.call(
            messages=enhanced_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        # 解析响应中的工具调用
        content = ""
        if hasattr(response, "content"):
            content = response.content
        elif hasattr(response, "choices") and response.choices:
            content = response.choices[0].message.content

        # 解析 <tool_call> 标签
        tool_calls = self._parse_embedded_tool_calls(content)

        return {
            "content": content,
            "tool_calls": tool_calls if tool_calls else None,
        }

    def _parse_embedded_tool_calls(self, content: str) -> List[Dict]:
        """解析嵌入式工具调用"""
        import re

        tool_calls = []

        # 匹配 <tool_call>...</tool_call> 标签
        pattern = r"<tool_call>\s*(\{.*?\})\s*</tool_call>"
        matches = re.findall(pattern, content, re.DOTALL)

        for i, match in enumerate(matches):
            try:
                data = json.loads(match)
                if "name" in data:
                    tool_calls.append(
                        {
                            "id": f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": data["name"],
                                "arguments": json.dumps(
                                    data.get("arguments", {}), ensure_ascii=False
                                ),
                            },
                        }
                    )
            except json.JSONDecodeError:
                logger.warning(f"无法解析嵌入式工具调用: {match[:100]}...")

        return tool_calls

    def _parse_tool_response(self, response: Any) -> Dict[str, Any]:
        """解析工具调用响应"""
        content = ""
        tool_calls = None

        # AsyncOpenAI 响应格式
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            content = message.content or ""

            if hasattr(message, "tool_calls") and message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append(
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                    )

        # LangChain 响应格式
        elif hasattr(response, "content"):
            content = response.content or ""

            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_calls = []
                for tc in response.tool_calls:
                    tool_calls.append(
                        {
                            "id": tc.get("id", f"call_{len(tool_calls)}"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": json.dumps(
                                    tc.get("args", {}), ensure_ascii=False
                                ),
                            },
                        }
                    )

        return {
            "content": content,
            "tool_calls": tool_calls,
        }

    async def _call_async_openai(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Any:
        """调用 AsyncOpenAI 客户端"""
        call_kwargs = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            **kwargs,
        }

        if response_format:
            # 检查是否是 Pydantic 模型
            if hasattr(response_format, "__bases__") and hasattr(
                response_format, "model_fields"
            ):
                # 使用 parse 方法
                call_kwargs["response_format"] = response_format
                return await self._async_openai_client.chat.completions.parse(
                    **call_kwargs
                )
            else:
                # 使用普通的 response_format
                call_kwargs["response_format"] = response_format

        return await self._async_openai_client.chat.completions.create(**call_kwargs)

    async def _call_langchain(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> Any:
        """调用 LangChain 客户端"""
        # LangChain 使用不同的消息格式
        from langchain_core.messages import HumanMessage, SystemMessage

        langchain_messages = []
        for msg in messages:
            if msg["role"] == "system":
                langchain_messages.append(SystemMessage(content=msg["content"]))
            elif msg["role"] == "user":
                langchain_messages.append(HumanMessage(content=msg["content"]))

        return await self._langchain_client.ainvoke(
            langchain_messages, temperature=temperature, max_tokens=max_tokens, **kwargs
        )

    async def _call_litellm(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> Any:
        """调用 LiteLLM 客户端

        注意：
        - LiteLLM 已有自己的重试机制，UnifiedLLMClient 的重试作为额外保障
        - 支持 JSON 优化（LiteLLM 的响应也可能需要修复）
        - 支持 token 追踪
        - Agents SDK 的 LitellmModel 使用 get_response 方法
        """
        # Agents SDK 的 LitellmModel 使用 get_response 方法
        try:
            # 检查是否是 Agents SDK 的 LitellmModel
            if hasattr(self._litellm_model, "get_response"):
                # Agents SDK 格式
                import asyncio

                loop = asyncio.get_event_loop()

                # get_response 是同步方法，需要包装为异步
                response = await loop.run_in_executor(
                    None,
                    lambda: self._litellm_model.get_response(
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs,
                    ),
                )
            elif hasattr(self._litellm_model, "acompletion"):
                # 标准 LiteLLM 异步接口
                response = await self._litellm_model.acompletion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            elif hasattr(self._litellm_model, "completion"):
                # 标准 LiteLLM 同步接口
                import asyncio

                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self._litellm_model.completion(
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs,
                    ),
                )
            else:
                raise NotImplementedError(
                    "LiteLLM 模型不支持 get_response, acompletion 或 completion 方法"
                )

            return response
        except Exception as e:
            logger.error(f"❌ LiteLLM 调用失败: {e}")
            raise

    def _record_token_usage(self, usage: Any):
        """记录 token 使用量"""
        if not self.token_tracker:
            return

        # 兼容不同的 usage 格式
        if hasattr(usage, "prompt_tokens"):
            input_tokens = usage.prompt_tokens
            output_tokens = usage.completion_tokens
            total_tokens = usage.total_tokens
        elif hasattr(usage, "input_tokens"):
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            total_tokens = getattr(usage, "total_tokens", input_tokens + output_tokens)
        elif isinstance(usage, dict):
            input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens", 0)
            output_tokens = usage.get("completion_tokens") or usage.get(
                "output_tokens", 0
            )
            total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
        else:
            logger.warning(f"无法识别的 usage 格式: {type(usage)}")
            return

        metrics = ModelCallMetrics(
            model_name=self.model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

        self.token_tracker.record_call(metrics)
        logger.debug(
            f"📊 Token 使用量: input={input_tokens}, output={output_tokens}, total={total_tokens}"
        )

    # ===== 向后兼容接口 =====

    def get_langchain_client(self, fresh: bool = True) -> ChatOpenAI:
        """
        获取 LangChain 客户端

        Args:
            fresh: 是否创建新的客户端实例（默认 True，避免状态累积问题）

        Returns:
            ChatOpenAI 客户端实例
        """
        # 根据模型调整参数（处理 moonshot 等特殊模型的限制）
        adjusted_temp, adjusted_max_tokens = self._adjust_params_for_model(
            self.temperature, self.max_tokens
        )

        # 默认每次创建新的客户端，避免状态累积导致的 token 爆炸问题
        if fresh:
            logger.debug(f"🔄 创建新的 LangChain 客户端（完全隔离）: {self.model_name}")
            return ClientFactory.create_langchain_client(
                base_url=self.base_url,
                api_key=self.api_key,
                model_name=self.model_name,
                temperature=adjusted_temp,
                max_tokens=adjusted_max_tokens,
                timeout=self.timeout,
                max_retries=self.max_retries,
                use_cache=False,  # 禁用 ChatOpenAI 缓存
            )

        # 向后兼容：返回缓存的客户端（不推荐）
        if self._langchain_client:
            return self._langchain_client

        # 如果不是 LangChain 类型，动态创建一个
        return ClientFactory.create_langchain_client(
            base_url=self.base_url,
            api_key=self.api_key,
            model_name=self.model_name,
            temperature=adjusted_temp,
            max_tokens=adjusted_max_tokens,
            timeout=self.timeout,
            max_retries=self.max_retries,
            use_cache=False,
        )

    def get_async_openai_client(self) -> AsyncOpenAI:
        """获取 AsyncOpenAI 客户端（向后兼容）"""
        if self._async_openai_client:
            return self._async_openai_client

        # 如果不是 AsyncOpenAI 类型，动态创建一个
        return ClientFactory.create_async_openai_client(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
            http_config=self.http_config,
        )

    def get_litellm_model(self) -> Any:
        """获取 Litellm 模型（向后兼容）"""
        if self._litellm_model:
            return self._litellm_model

        # 如果不是 Litellm 类型，动态创建一个
        return ClientFactory.create_litellm_model(
            provider=self.provider,
            base_url=self.base_url,
            api_key=self.api_key,
            model_name=self.model_name,
        )

    def get_token_usage(self) -> Dict[str, Any]:
        """获取 token 使用量统计"""
        if not self.token_tracker:
            return {
                "message": "Token tracking is disabled",
                "total": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "call_count": 0,
                },
            }

        return self.token_tracker.get_summary()

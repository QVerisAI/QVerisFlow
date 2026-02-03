"""
Claude Agent SDK 客户端适配器

将 Claude Agent SDK 适配为统一的 LLM 客户端接口，
与现有的 UnifiedLLMClient 兼容。

设计原则：
1. 实现与 UnifiedLLMClient 相同的接口
2. 充分利用 Claude SDK 的原生能力（MCP、Hooks）
3. 保持简洁，只处理 Claude 特定的功能
"""

from typing import Any, Dict, List, Optional, Union, AsyncIterator
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ClaudeSDKClient:
    """
    Claude SDK 客户端适配器

    作为 UnifiedLLMClient 的替代实现，专为 Claude 优化。

    特性：
    - 原生 MCP 工具支持
    - Hooks 机制
    - 子代理和会话管理
    - 流式响应

    用法：
    ```python
    from src.utils import ClaudeSDKClient

    client = ClaudeSDKClient(
        model_name="claude-sonnet-4-20250514",
        mcp_servers={"tools": mcp_server},
        hooks={"PreToolUse": [...]}
    )

    # 与 UnifiedLLMClient 兼容的接口
    response = await client.ainvoke(messages)

    # 流式响应
    async for chunk in client.astream(messages):
        print(chunk)
    ```
    """

    def __init__(
        self,
        model_name: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
        mcp_servers: Optional[Dict[str, Any]] = None,
        hooks: Optional[Dict[str, List[Any]]] = None,
        allowed_tools: Optional[List[str]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        timeout: float = 300.0,
        **kwargs,
    ):
        """
        初始化 Claude SDK 客户端

        Args:
            model_name: Claude 模型名称
            api_key: Anthropic API Key（可选，从环境变量读取）
            mcp_servers: MCP 服务器配置
            hooks: Hooks 配置
            allowed_tools: 允许使用的工具列表
            temperature: 温度参数
            max_tokens: 最大 tokens
            timeout: 超时时间
            **kwargs: 其他参数
        """
        self.model_name = model_name
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        # Claude SDK 配置
        self.mcp_servers = mcp_servers or {}
        self.hooks = hooks or {}
        self.allowed_tools = allowed_tools or []

        # 延迟初始化 Claude SDK（避免导入错误）
        self._sdk_client = None
        self._options = None

        logger.info(f"✅ Claude SDK 客户端初始化: {model_name}")

    def _ensure_sdk_client(self):
        """确保 SDK 客户端已初始化"""
        if self._sdk_client is not None:
            return

        try:
            from claude_agent_sdk import ClaudeSDKClient as SDKClient
            from claude_agent_sdk import ClaudeAgentOptions
        except ImportError:
            raise ImportError("需要安装 claude-agent-sdk: pip install claude-agent-sdk")

        # 构建选项
        self._options = ClaudeAgentOptions(
            model_name=self.model_name,
            api_key=self.api_key,
            mcp_servers=self.mcp_servers,
            hooks=self.hooks,
            allowed_tools=self.allowed_tools,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        # 创建客户端（注意：需要在异步上下文中使用）
        self._sdk_client = SDKClient(options=self._options)

    async def ainvoke(
        self, messages: Union[List[Dict[str, str]], str], **kwargs
    ) -> str:
        """
        异步调用（兼容 UnifiedLLMClient 接口）

        Args:
            messages: 消息列表或单个字符串
            **kwargs: 其他参数

        Returns:
            模型响应文本
        """
        self._ensure_sdk_client()

        # 转换消息格式
        if isinstance(messages, str):
            prompt = messages
        else:
            prompt = self._convert_messages_to_prompt(messages)

        # 使用 Claude SDK
        response_parts = []
        async with self._sdk_client as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        for block in content:
                            if block.get("type") == "text":
                                response_parts.append(block.get("text", ""))
                    elif isinstance(content, str):
                        response_parts.append(content)
                elif isinstance(msg, str):
                    response_parts.append(msg)

        return "".join(response_parts)

    async def astream(
        self, messages: Union[List[Dict[str, str]], str], **kwargs
    ) -> AsyncIterator[str]:
        """
        流式调用（兼容 UnifiedLLMClient 接口）

        Args:
            messages: 消息列表或单个字符串
            **kwargs: 其他参数

        Yields:
            响应块
        """
        self._ensure_sdk_client()

        # 转换消息格式
        if isinstance(messages, str):
            prompt = messages
        else:
            prompt = self._convert_messages_to_prompt(messages)

        # 使用 Claude SDK 流式响应
        async with self._sdk_client as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        for block in content:
                            if block.get("type") == "text":
                                yield block.get("text", "")
                    elif isinstance(content, str):
                        yield content
                elif isinstance(msg, str):
                    yield msg

    def get_langchain_client(self) -> Any:
        """
        获取 LangChain 兼容的客户端

        注意：Claude SDK 本身不直接提供 LangChain 客户端，
        这里返回一个包装器以保持接口兼容性。

        Returns:
            LangChain 兼容的客户端
        """
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=self.model_name,
            api_key=self.api_key,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    def _convert_messages_to_prompt(self, messages: List[Dict[str, str]]) -> str:
        """
        将消息列表转换为单个 prompt

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]

        Returns:
            合并后的 prompt
        """
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                parts.append(f"System: {content}")
            elif role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")

        return "\n\n".join(parts)

    # ========== Claude SDK 特有功能 ==========

    def add_mcp_server(self, name: str, server_config: Dict[str, Any]):
        """
        动态添加 MCP 服务器

        Args:
            name: 服务器名称
            server_config: 服务器配置
        """
        self.mcp_servers[name] = server_config
        logger.info(f"✅ 添加 MCP 服务器: {name}")

    def add_hook(self, event: str, hook_matcher):
        """
        动态添加 Hook

        Args:
            event: 事件名称（如 "PreToolUse", "PostToolUse"）
            hook_matcher: Hook 匹配器
        """
        if event not in self.hooks:
            self.hooks[event] = []
        self.hooks[event].append(hook_matcher)
        logger.info(f"✅ 添加 Hook: {event}")

    async def create_subagent(
        self, task: str, inherit_tools: bool = True
    ) -> "ClaudeSDKClient":
        """
        创建子代理（利用 Claude SDK 的子代理功能）

        Args:
            task: 子任务描述
            inherit_tools: 是否继承父代理的工具

        Returns:
            新的 ClaudeSDKClient 实例
        """
        subagent_options = {
            "model_name": self.model_name,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if inherit_tools:
            subagent_options["mcp_servers"] = self.mcp_servers
            subagent_options["allowed_tools"] = self.allowed_tools

        return ClaudeSDKClient(**subagent_options)


class ClaudeLLMFactory:
    """
    Claude 客户端工厂

    根据配置决定使用 Claude SDK 还是标准 Anthropic API
    """

    @staticmethod
    def create_client(
        provider: str = "anthropic", use_sdk: bool = True, **kwargs
    ) -> Union[ClaudeSDKClient, Any]:
        """
        创建 Claude 客户端

        Args:
            provider: 提供商名称
            use_sdk: 是否使用 Claude SDK
            **kwargs: 其他参数

        Returns:
            客户端实例
        """
        if provider.lower() in ["anthropic", "claude"] and use_sdk:
            return ClaudeSDKClient(**kwargs)
        else:
            # 回退到标准 UnifiedLLMClient
            from .llm_client import UnifiedLLMClient

            return UnifiedLLMClient(provider=provider, **kwargs)

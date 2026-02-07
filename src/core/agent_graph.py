"""
Agent 图构建器

使用 LangGraph 构建标准的 Agent 核心循环：
gather_context → take_action → verify_work → (repeat or complete)
"""

import json
import asyncio
from typing import Dict, Any, Optional, Callable, Literal, List
from concurrent.futures import ThreadPoolExecutor
from src.utils.logger import get_logger
from src.utils.json_utils import extract_structured_output

from .agent_state import AgentState
from .context_manager import ContextManager, TiktokenCounter, SimpleTokenCounter
from .reference_resolver import ReferenceResolver
from .context_provider import RuntimeContextProvider, get_current_time_context

logger = get_logger()

# CPU 密集型操作使用的线程池
_cpu_executor = ThreadPoolExecutor(max_workers=4)


# ---------------------------------------------------------------------------
# Helper: convert a JSON output_schema into Markdown section guidance
# ---------------------------------------------------------------------------


def schema_to_markdown_guide(schema: Dict[str, Any]) -> str:
    """Convert a JSON Schema into Markdown section guidance for the LLM.

    When ``data_format`` is ``"markdown"``, the LLM should produce a
    Markdown string instead of a JSON object.  If the agent also has an
    ``output_schema`` that describes the expected JSON structure, this
    helper translates the schema *keys* into section headings so the LLM
    knows which topics to cover.

    Example input::

        {"type": "object", "properties": {
            "financial_analysis": {"description": "财务分析"},
            "risk_analysis": {"description": "风险评估"}
        }}

    Example output::

        ## Markdown data 章节指引
        请在 data 字段中包含以下章节：
        - ## 财务分析
        - ## 风险评估

    Args:
        schema: JSON Schema dict (typically from ``AgentDefinition.output_schema``).

    Returns:
        A prompt snippet (may be empty if the schema has no usable properties).
    """
    properties = schema.get("properties", {})
    if not properties:
        return ""

    sections: list[str] = []
    for key, prop in properties.items():
        # Prefer the Chinese ``description``; fall back to the key itself.
        label = prop.get("description", key) if isinstance(prop, dict) else key
        sections.append(f"- ## {label}")

    if not sections:
        return ""

    lines = [
        "## Markdown data 章节指引",
        "请在 data 字段中包含以下章节（使用 Markdown 二级标题）：",
        *sections,
    ]
    return "\n".join(lines)


def _normalize_tool_calls_args(response: Any) -> Any:
    """
    规范化 AI 响应中的 tool_calls.args 字段

    某些 LLM 提供商（如 deepseek、kimi）可能返回 args 为 JSON 字符串而非字典，
    这会导致 langchain 的 AIMessage Pydantic 验证失败。
    此函数将字符串形式的 args 解析为字典。

    Args:
        response: LLM 的响应对象

    Returns:
        处理后的响应对象（如果需要修改则返回新的 AIMessage）
    """
    if not hasattr(response, "tool_calls") or not response.tool_calls:
        return response

    needs_normalization = False
    normalized_tool_calls = []

    for tool_call in response.tool_calls:
        args = tool_call.get("args", {})

        # 如果 args 是字符串，尝试解析为字典
        if isinstance(args, str):
            needs_normalization = True
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                logger.warning(f"无法解析 tool_call args 字符串: {args[:100]}...")
                args = {"raw_args": args}

        normalized_tool_calls.append(
            {
                "id": tool_call.get("id", ""),
                "name": tool_call.get("name", ""),
                "args": args,
            }
        )

    if needs_normalization:
        # 创建新的 AIMessage，确保 tool_calls.args 是字典
        from langchain_core.messages import AIMessage

        return AIMessage(
            content=response.content if hasattr(response, "content") else "",
            tool_calls=normalized_tool_calls,
            additional_kwargs=getattr(response, "additional_kwargs", {}),
        )

    return response


def _sanitize_message_for_kimi(message: Any, model_name: str = "") -> Any:
    """
    针对 Kimi/Moonshot 模型规范化单个消息格式

    Kimi 的 thinking 模式要求：
    - 当启用 thinking 时，assistant 消息必须包含 reasoning_content
    - 如果 tool_calls 消息中缺少 reasoning_content，API 会返回 400 错误

    解决方案：
    - 对于 tool_calls 的 assistant 消息，确保 additional_kwargs 中包含 reasoning_content
    - 即使是空字符串也可以满足 API 的格式验证

    Args:
        message: LangChain 消息对象
        model_name: 模型名称，用于判断是否为 Kimi 模型

    Returns:
        处理后的消息对象
    """
    # 检查是否为 Kimi/Moonshot 模型
    model_lower = model_name.lower() if model_name else ""
    is_kimi = "kimi" in model_lower or "moonshot" in model_lower

    if not is_kimi:
        return message

    from langchain_core.messages import AIMessage

    # 如果是 AIMessage 且有 tool_calls
    if (
        isinstance(message, AIMessage)
        and hasattr(message, "tool_calls")
        and message.tool_calls
    ):
        additional_kwargs = getattr(message, "additional_kwargs", {}) or {}

        # 检查是否缺少 reasoning_content（Kimi thinking 模式要求）
        # 如果原始响应没有 reasoning_content，我们添加一个空字符串
        # 这样可以满足 API 的格式验证
        if "reasoning_content" not in additional_kwargs:
            # 创建新消息，添加空的 reasoning_content
            new_kwargs = dict(additional_kwargs)
            new_kwargs["reasoning_content"] = ""

            return AIMessage(
                content=message.content if hasattr(message, "content") else "",
                tool_calls=message.tool_calls,
                additional_kwargs=new_kwargs,
            )

    return message


def _sanitize_messages_for_kimi(messages: List[Any], model_name: str = "") -> List[Any]:
    """
    针对 Kimi/Moonshot 模型规范化整个消息列表

    遍历所有消息，确保每个 AIMessage（特别是有 tool_calls 的）都包含 reasoning_content。
    这是解决 'thinking is enabled but reasoning_content is missing' 错误的关键。

    Args:
        messages: LangChain 消息列表
        model_name: 模型名称，用于判断是否为 Kimi 模型

    Returns:
        处理后的消息列表
    """
    # 检查是否为 Kimi/Moonshot 模型
    model_lower = model_name.lower() if model_name else ""
    is_kimi = "kimi" in model_lower or "moonshot" in model_lower

    if not is_kimi:
        return messages

    # 规范化每个消息
    return [_sanitize_message_for_kimi(msg, model_name) for msg in messages]


def _get_model_name_from_llm(llm_client: Any) -> str:
    """
    从 LLM 客户端获取模型名称

    Args:
        llm_client: LLM 客户端实例

    Returns:
        模型名称字符串
    """
    # 尝试多种方式获取模型名称
    if hasattr(llm_client, "model_name"):
        return llm_client.model_name
    if hasattr(llm_client, "model"):
        return llm_client.model
    if hasattr(llm_client, "_model_name"):
        return llm_client._model_name
    # 检查是否是绑定了工具的 RunnableBinding
    if hasattr(llm_client, "bound"):
        return _get_model_name_from_llm(llm_client.bound)
    return ""


# ========== 上下文长度管理 ==========

# 默认的模型上下文限制（保守估计）
DEFAULT_MAX_CONTEXT_TOKENS = 128000
# 单个工具结果的最大 token 数
MAX_TOOL_RESULT_TOKENS = 8000
# 预留给响应的 token 数
RESERVED_OUTPUT_TOKENS = 16000


def _estimate_tokens(text: str) -> int:
    """
    快速估算文本的 token 数量

    使用简单规则：
    - 中文字符约 1.5 token
    - 英文字符约 0.25 token (4个字符 ≈ 1 token)

    Args:
        text: 要估算的文本

    Returns:
        估算的 token 数量
    """
    if not text:
        return 0

    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars

    estimated_tokens = int(chinese_chars * 1.5 + other_chars * 0.25)
    return max(1, estimated_tokens)


async def estimate_tokens_async(text: str) -> int:
    """
    异步估算文本的 token 数量（使用线程池）

    对于大量文本处理时使用，避免阻塞事件循环。

    Args:
        text: 要估算的文本

    Returns:
        估算的 token 数量
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_cpu_executor, _estimate_tokens, text)


def _estimate_message_tokens(message: Any) -> int:
    """
    估算单个消息的 token 数量

    Args:
        message: LangChain 消息对象

    Returns:
        估算的 token 数量
    """
    tokens = 4  # 消息格式开销

    # 内容
    if hasattr(message, "content") and message.content:
        tokens += _estimate_tokens(str(message.content))

    # 工具调用
    if hasattr(message, "tool_calls") and message.tool_calls:
        for tool_call in message.tool_calls:
            tokens += 20  # 工具调用格式开销
            if isinstance(tool_call, dict):
                name = tool_call.get("name", "")
                args = tool_call.get("args", {})
                tokens += _estimate_tokens(name)
                tokens += _estimate_tokens(
                    json.dumps(args) if isinstance(args, dict) else str(args)
                )

    return tokens


def _estimate_messages_tokens(messages: List[Any]) -> int:
    """
    估算消息列表的总 token 数量

    Args:
        messages: LangChain 消息列表

    Returns:
        估算的总 token 数量
    """
    total = 3  # 消息列表开销
    for msg in messages:
        total += _estimate_message_tokens(msg)
    return total


def _truncate_text(
    text: str, max_tokens: int, suffix: str = "\n\n[内容已截断...]"
) -> str:
    """
    截断文本到指定 token 数量

    Args:
        text: 原始文本
        max_tokens: 最大 token 数
        suffix: 截断后的后缀

    Returns:
        截断后的文本
    """
    if not text:
        return text

    current_tokens = _estimate_tokens(text)
    if current_tokens <= max_tokens:
        return text

    # 计算大致需要保留的字符数
    # 保守估计：中英混合平均 0.5 token/字符
    target_chars = int(max_tokens * 2)
    suffix_tokens = _estimate_tokens(suffix)
    target_chars = int((max_tokens - suffix_tokens) * 2)

    if target_chars <= 0:
        return suffix

    truncated = text[:target_chars]
    return truncated + suffix


def _truncate_tool_result(result: str, max_tokens: int = MAX_TOOL_RESULT_TOKENS) -> str:
    """
    截断工具结果到合理大小

    Args:
        result: 工具执行结果
        max_tokens: 最大 token 数

    Returns:
        截断后的结果
    """
    return _truncate_text(
        result,
        max_tokens,
        f"\n\n[工具返回内容过长，已截断。原始内容约 {_estimate_tokens(result)} tokens]",
    )


def _truncate_messages_to_fit(
    messages: List[Any],
    max_tokens: int,
    reserved_tokens: int = RESERVED_OUTPUT_TOKENS,
) -> List[Any]:
    """
    截断消息列表以适应上下文限制

    策略：
    1. 保留 SystemMessage 和最新的 HumanMessage（不截断）
    2. 保留最近的几轮对话
    3. 截断早期的工具结果和 AI 响应

    Args:
        messages: 原始消息列表
        max_tokens: 模型的最大上下文 token 数
        reserved_tokens: 预留给输出的 token 数

    Returns:
        截断后的消息列表
    """
    from langchain_core.messages import (
        SystemMessage,
        HumanMessage,
        AIMessage,
        ToolMessage,
    )

    available_tokens = max_tokens - reserved_tokens
    current_tokens = _estimate_messages_tokens(messages)

    if current_tokens <= available_tokens:
        return messages

    logger.warning(
        f"消息上下文超出限制: {current_tokens} tokens > {available_tokens} available "
        f"(max={max_tokens}, reserved={reserved_tokens})，将进行截断"
    )

    # 分类消息
    system_msgs = []
    other_msgs = []

    for msg in messages:
        if isinstance(msg, SystemMessage):
            system_msgs.append(msg)
        else:
            other_msgs.append(msg)

    # 计算 system 消息占用的 tokens
    system_tokens = sum(_estimate_message_tokens(m) for m in system_msgs)
    remaining_tokens = available_tokens - system_tokens

    if remaining_tokens <= 0:
        # 极端情况：连 system 消息都放不下
        logger.error("System 消息过长，无法进行有效截断")
        return messages[:2]  # 至少保留前两条

    # 从后向前保留消息（保留最新的对话）
    truncated_others = []
    accumulated_tokens = 0

    for msg in reversed(other_msgs):
        msg_tokens = _estimate_message_tokens(msg)

        # 如果是 ToolMessage 且太大，先截断内容
        if isinstance(msg, ToolMessage) and msg_tokens > MAX_TOOL_RESULT_TOKENS:
            truncated_content = _truncate_tool_result(
                msg.content, MAX_TOOL_RESULT_TOKENS
            )
            msg = ToolMessage(content=truncated_content, tool_call_id=msg.tool_call_id)
            msg_tokens = _estimate_message_tokens(msg)

        # 如果是 AIMessage 内容太大，也截断
        if isinstance(msg, AIMessage) and msg_tokens > MAX_TOOL_RESULT_TOKENS:
            if hasattr(msg, "content") and msg.content:
                truncated_content = _truncate_text(msg.content, MAX_TOOL_RESULT_TOKENS)
                # 保留 tool_calls 和其他属性
                msg = AIMessage(
                    content=truncated_content,
                    tool_calls=getattr(msg, "tool_calls", []),
                    additional_kwargs=getattr(msg, "additional_kwargs", {}),
                )
                msg_tokens = _estimate_message_tokens(msg)

        if accumulated_tokens + msg_tokens <= remaining_tokens:
            truncated_others.insert(0, msg)
            accumulated_tokens += msg_tokens
        else:
            # 无法容纳更多消息
            # 但要确保至少有一条 HumanMessage
            has_human = any(isinstance(m, HumanMessage) for m in truncated_others)
            if isinstance(msg, HumanMessage) and not has_human:
                # 截断这条 HumanMessage 的内容以适应
                max_content_tokens = remaining_tokens - accumulated_tokens - 10
                if max_content_tokens > 100:
                    truncated_content = _truncate_text(msg.content, max_content_tokens)
                    msg = HumanMessage(content=truncated_content)
                    truncated_others.insert(0, msg)
            break

    result = system_msgs + truncated_others
    final_tokens = _estimate_messages_tokens(result)

    logger.info(
        f"消息截断完成: {len(messages)} -> {len(result)} 条, "
        f"{current_tokens} -> {final_tokens} tokens"
    )

    return result


async def truncate_messages_to_fit_async(
    messages: List[Any],
    max_tokens: int,
    reserved_tokens: int = RESERVED_OUTPUT_TOKENS,
) -> List[Any]:
    """
    异步截断消息列表以适应上下文限制（使用线程池）

    对于大量消息处理时使用，避免阻塞事件循环。

    Args:
        messages: 原始消息列表
        max_tokens: 模型的最大上下文 token 数
        reserved_tokens: 预留给输出的 token 数

    Returns:
        截断后的消息列表
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _cpu_executor,
        _truncate_messages_to_fit,
        messages,
        max_tokens,
        reserved_tokens,
    )


class AgentGraphBuilder:
    """
    Agent 图构建器

    使用 LangGraph 构建标准的 Agent 核心循环
    """

    def __init__(
        self,
        definition: Any,  # AgentDefinition
        workspace: Any,  # AgentWorkspace
        llm_client: Any,
        verifier: Optional[Any] = None,  # BaseVerifier
        tools: Optional[list] = None,
        tool_registry: Optional[Any] = None,  # ToolRegistry for execution
        max_context_tokens: int = 100000,
        compression_threshold: float = 0.8,
    ):
        from ..definitions import AgentDefinition
        from ..workspace import AgentWorkspace
        from ..verification import BaseVerifier

        self.definition: AgentDefinition = definition
        self.workspace: AgentWorkspace = workspace
        self.llm_client = llm_client
        self.verifier: Optional[BaseVerifier] = verifier
        self.tools = tools or []
        self.tool_registry = tool_registry

        # 进度回调函数（由 BaseAgent.run() 设置，用于发送工具调用等中间状态）
        self.progress_callback: Optional[Any] = None  # Callable[[str], Awaitable[None]]
        # 流式回调（发送 LLM 思考/内容 token，dict: type "reasoning"|"content", content）
        self.stream_callback: Optional[Any] = None  # Callable[[Dict], Awaitable[None]]

        # 获取 LangChain 客户端
        self.langchain_llm = (
            llm_client.get_langchain_client()
            if hasattr(llm_client, "get_langchain_client")
            else llm_client
        )

        # 如果有工具，绑定到 LLM
        if self.tools:
            tool_names = [
                getattr(t, "name", getattr(t, "tool_id", str(t))) for t in self.tools
            ]
            logger.info(f"🔧 绑定 {len(self.tools)} 个工具到 LLM: {tool_names}")
            try:
                self.langchain_llm = self.langchain_llm.bind_tools(self.tools)
                logger.info("✅ 工具已成功绑定到 LLM，可进行 function calling")
            except AttributeError as e:
                logger.warning(
                    f"⚠️ LLM 客户端不支持 bind_tools ({type(self.langchain_llm).__name__})，"
                    f"工具可能无法正常使用: {e}"
                )
            except Exception as e:
                logger.error(f"❌ 绑定工具到 LLM 失败: {e}")
        else:
            logger.warning(
                "⚠️ 未提供任何工具 - LLM 将无法执行 function calling。"
                "请检查 Agent 定义中的 tool_references 或 ToolRegistry 配置。"
            )

        # 初始化上下文管理器
        try:
            token_counter = TiktokenCounter(
                model=getattr(definition.model_config, "model_name", "gpt-4")
            )
        except Exception:
            token_counter = SimpleTokenCounter()

        self.context_manager = ContextManager(
            max_tokens=max_context_tokens,
            compression_threshold=compression_threshold,
            token_counter=token_counter,
            llm_client=llm_client,
        )

        # 初始化引用解析器
        self.reference_resolver = ReferenceResolver(
            tool_registry=tool_registry,
            inject_tool_description=True,
            inject_tool_schema=True,
        )

    def build(self):
        """
        构建 Agent 图

        Returns:
            可编译的 StateGraph
        """
        try:
            from langgraph.graph import StateGraph, END
        except ImportError:
            raise ImportError("需要安装 langgraph: pip install langgraph")

        # 创建图
        graph = StateGraph(AgentState)

        # 添加节点
        graph.add_node("gather_context", self._gather_context_node)
        graph.add_node("take_action", self._take_action_node)
        graph.add_node("verify_work", self._verify_work_node)
        graph.add_node("handle_error", self._handle_error_node)

        # 设置入口
        graph.set_entry_point("gather_context")

        # 添加边
        graph.add_edge("gather_context", "take_action")
        graph.add_edge("take_action", "verify_work")

        # 条件边：验证后决定下一步
        graph.add_conditional_edges(
            "verify_work",
            self._should_continue,
            {
                "continue": "gather_context",  # 验证失败，继续迭代
                "complete": END,  # 验证通过，结束
                "max_iterations": END,  # 达到最大迭代
                "error": "handle_error",  # 错误处理
            },
        )

        graph.add_edge("handle_error", END)

        return graph

    def compile(self, checkpointer=None, checkpointer_config=None):
        """
        编译图

        Args:
            checkpointer: 检查点存储实例（用于持久化和恢复）
            checkpointer_config: 检查点存储配置（可替代直接传入 checkpointer）
                - CheckpointerConfig 实例
                - 或字典形式的配置

        Returns:
            编译后的可执行图
        """
        from ..storage.checkpointers import CheckpointerFactory
        from ..storage.config import (
            CheckpointStorageConfig as CheckpointerConfig,
            CheckpointerType,
        )

        graph = self.build()

        # 如果提供了配置，使用工厂创建检查点存储
        if checkpointer is None and checkpointer_config is not None:
            if isinstance(checkpointer_config, dict):
                # 从字典创建配置
                config_type = checkpointer_config.get("type", "memory")
                if isinstance(config_type, str):
                    config_type = CheckpointerType(config_type)
                checkpointer_config = CheckpointerConfig(
                    type=config_type,
                    **{k: v for k, v in checkpointer_config.items() if k != "type"},
                )

            checkpointer = CheckpointerFactory.create(checkpointer_config)
            logger.info(f"使用 {checkpointer_config.type.value} 检查点存储")

        # 默认使用内存检查点
        if checkpointer is None:
            try:
                from langgraph.checkpoint.memory import MemorySaver

                checkpointer = MemorySaver()
            except ImportError:
                logger.warning("未安装 langgraph checkpoint，将不使用检查点功能")
                checkpointer = None

        if checkpointer:
            return graph.compile(checkpointer=checkpointer)
        else:
            return graph.compile()

    # ========== 节点实现 ==========

    async def _gather_context_node(self, state: AgentState) -> Dict[str, Any]:
        """
        收集上下文节点

        职责：
        1. 读取任务描述
        2. 调用搜索工具收集信息
        3. 处理之前的验证反馈
        4. 管理上下文大小，自动压缩
        """
        from ..workspace import AgentWorkspace

        workspace = AgentWorkspace.from_path(state["workspace_path"])

        # 读取任务
        task, input_data = workspace.read_task()

        # 添加任务到上下文（高优先级）
        self.context_manager.add(
            content=f"任务: {task}\n输入数据: {input_data}",
            source="task",
            priority=10,
        )

        # 构建收集上下文的 prompt
        context_prompt = self._build_context_prompt(
            task=task,
            input_data=input_data,
            previous_feedback=state.get("verification_feedback", ""),
        )

        # 调用 LLM（可能会调用工具）
        try:
            from langchain_core.messages import (
                HumanMessage,
                AIMessage,
                SystemMessage,
                ToolMessage,
            )

            messages = [
                SystemMessage(content=self.definition.build_system_prompt()),
                HumanMessage(content=context_prompt),
            ]

            # 记录 LLM 调用开始时间
            from datetime import datetime

            llm_start_time = datetime.now()

            response = await self.langchain_llm.ainvoke(messages)

            # 规范化 tool_calls.args（某些 LLM 可能返回字符串而非字典）
            response = _normalize_tool_calls_args(response)

            # 记录 LLM 调用日志
            llm_duration_ms = (datetime.now() - llm_start_time).total_seconds() * 1000
            if hasattr(workspace, "log_llm_call"):
                workspace.log_llm_call(
                    model=getattr(
                        self.langchain_llm,
                        "model_name",
                        getattr(self.langchain_llm, "model", "unknown"),
                    ),
                    messages=[
                        {"role": m.type, "content": str(m.content)[:1000]}
                        for m in messages
                    ],
                    response=(
                        str(response.content)[:2000]
                        if hasattr(response, "content")
                        else str(response)[:2000]
                    ),
                    tool_calls=getattr(response, "tool_calls", None),
                    duration_ms=llm_duration_ms,
                )

            # 关键修复：循环处理工具调用直到无工具调用
            gathered_context = await self._execute_tool_calls_loop(
                response=response,
                messages=messages,
                workspace=workspace,
                max_tool_rounds=10,  # 限制工具调用轮数
            )

            # 添加收集到的上下文到管理器
            self.context_manager.add(
                content=gathered_context,
                source="gathered_context",
                priority=5,
            )

            # 检查并执行上下文压缩（如果接近限制）
            if self.context_manager.is_near_limit:
                logger.info(
                    f"上下文接近限制，执行压缩: {self.context_manager.get_stats()}"
                )
                await self.context_manager.compress_if_needed()

            # 保存上下文
            workspace.save_gathered_context(gathered_context)

            # 记录上下文状态
            context_stats = self.context_manager.get_stats()
            logger.debug(f"上下文状态: {context_stats}")

            return {
                "gathered_context": gathered_context,
                "messages": [{"role": "assistant", "content": gathered_context}],
                "iteration": state["iteration"] + 1,
                "context_stats": context_stats,
            }

        except Exception as e:
            logger.error(f"收集上下文失败: {e}")
            return {
                "errors": state["errors"]
                + [{"phase": "gather_context", "error": str(e)}],
                "iteration": state["iteration"] + 1,
            }

    async def _take_action_node(self, state: AgentState) -> Dict[str, Any]:
        """
        执行动作节点

        职责：
        1. 基于上下文生成输出
        2. 写入草稿
        3. 调用必要的工具
        4. 管理上下文压缩
        """
        from ..workspace import AgentWorkspace
        from langchain_core.messages import HumanMessage, SystemMessage

        workspace = AgentWorkspace.from_path(state["workspace_path"])

        # 使用上下文管理器获取压缩后的上下文
        managed_context = self.context_manager.get_context()

        # 构建执行 prompt（使用管理后的上下文）
        action_prompt = self._build_action_prompt(
            context=managed_context if managed_context else state["gathered_context"],
            previous_draft=state.get("current_draft", ""),
        )

        try:
            from ..definitions.agent_definition import get_output_format_instruction

            # 根据 agent 配置的 data_format 选择对应的输出格式指令
            data_format = getattr(
                self.definition.output_instruction, "data_format", "json"
            )
            output_format_instruction = get_output_format_instruction(data_format)

            # 当 data_format 为 markdown 且定义了 output_schema 时，
            # 将 schema 转换为 Markdown 章节指引附加到提示中
            schema_guide = ""
            if data_format == "markdown" and self.definition.output_schema:
                schema_guide = "\n\n" + schema_to_markdown_guide(
                    self.definition.output_schema
                )

            # 构建消息列表（含输出格式要求：summary + narrative + data）
            system_prompt = (
                self.definition.build_system_prompt()
                + "\n\n"
                + output_format_instruction.strip()
                + schema_guide
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=action_prompt),
            ]

            # 记录 LLM 调用开始时间
            from datetime import datetime

            llm_start_time = datetime.now()

            # 调用 LLM 前发送「正在思考」进度
            if self.progress_callback:
                try:
                    await self.progress_callback(
                        {"type": "thinking", "message": "正在思考..."}
                    )
                except Exception as cb_err:
                    logger.warning(f"进度回调失败: {cb_err}")

            if self.stream_callback and hasattr(self.langchain_llm, "astream"):
                response = None
                try:
                    async for chunk in self.langchain_llm.astream(messages):
                        additional = getattr(chunk, "additional_kwargs", None) or {}
                        reasoning = additional.get(
                            "reasoning_content"
                        ) or additional.get("thinking")
                        if isinstance(reasoning, str) and reasoning.strip():
                            await self.stream_callback(
                                {"type": "reasoning", "content": reasoning}
                            )
                        content = getattr(chunk, "content", None) or ""
                        if isinstance(content, str) and content.strip():
                            await self.stream_callback(
                                {"type": "content", "content": content}
                            )
                        if chunk is not None:
                            try:
                                response = (
                                    chunk if response is None else response + chunk
                                )
                            except TypeError:
                                response = chunk
                except Exception as stream_err:
                    logger.warning(f"流式调用失败，回退 ainvoke: {stream_err}")
                    response = await self.langchain_llm.ainvoke(messages)
                if response is None:
                    response = await self.langchain_llm.ainvoke(messages)
            else:
                response = await self.langchain_llm.ainvoke(messages)

            # 规范化 tool_calls.args（某些 LLM 可能返回字符串而非字典）
            response = _normalize_tool_calls_args(response)

            # 记录 LLM 调用日志
            llm_duration_ms = (datetime.now() - llm_start_time).total_seconds() * 1000
            if hasattr(workspace, "log_llm_call"):
                workspace.log_llm_call(
                    model=getattr(
                        self.langchain_llm,
                        "model_name",
                        getattr(self.langchain_llm, "model", "unknown"),
                    ),
                    messages=[
                        {"role": m.type, "content": str(m.content)[:1000]}
                        for m in messages
                    ],
                    response=(
                        str(response.content)[:2000]
                        if hasattr(response, "content")
                        else str(response)[:2000]
                    ),
                    tool_calls=getattr(response, "tool_calls", None),
                    duration_ms=llm_duration_ms,
                )

            # 处理工具调用（如果有）
            final_content = await self._execute_tool_calls_loop(
                response=response,
                messages=messages,
                workspace=workspace,
                max_tool_rounds=10,
            )

            # 解析结果
            result = self._parse_response(final_content)

            # 添加生成的内容到上下文（用于后续迭代）
            self.context_manager.add(
                content=f"草稿 v{len(state['draft_versions']) + 1}:\n{final_content[:2000]}...",
                source="draft",
                priority=3,
            )

            # 写入草稿
            draft_version = len(state["draft_versions"]) + 1
            draft_path = f"scratch/draft_v{draft_version}.md"
            workspace.write_file(draft_path, final_content)

            # 获取更新后的上下文统计
            context_stats = self.context_manager.get_stats()

            return {
                "result": result,
                "current_draft": final_content,
                "draft_versions": state["draft_versions"] + [draft_path],
                "messages": [{"role": "assistant", "content": final_content}],
                "context_stats": context_stats,
            }

        except Exception as e:
            logger.error(f"执行动作失败: {e}")
            return {
                "errors": state["errors"] + [{"phase": "take_action", "error": str(e)}]
            }

    async def _verify_work_node(self, state: AgentState) -> Dict[str, Any]:
        """
        验证工作节点

        职责：
        1. 规则验证
        2. LLM 评判（可选）
        3. 记录验证结果
        """
        from ..workspace import AgentWorkspace

        if self.verifier is None:
            return {
                "verification_passed": True,
                "verification_feedback": "",
                "verification_score": 1.0,
                "phase": "complete",
            }

        try:
            # 执行验证
            result = await self.verifier.verify(
                output=state["result"],
                context={
                    "gathered_context": state["gathered_context"],
                    "iteration": state["iteration"],
                },
            )

            workspace = AgentWorkspace.from_path(state["workspace_path"])
            workspace.log_action(
                "verification",
                {
                    "passed": result.passed,
                    "score": result.score,
                    "feedback": result.feedback,
                },
            )

            return {
                "verification_passed": result.passed,
                "verification_feedback": result.feedback,
                "verification_score": result.score,
                "phase": "complete" if result.passed else "gather_context",
            }

        except Exception as e:
            logger.error(f"验证失败: {e}")
            return {
                "errors": state["errors"] + [{"phase": "verify_work", "error": str(e)}],
                "verification_passed": False,
                "verification_feedback": f"验证异常: {str(e)}",
                "verification_score": 0.0,
            }

    async def _handle_error_node(self, state: AgentState) -> Dict[str, Any]:
        """错误处理节点"""
        from ..workspace import AgentWorkspace

        workspace = AgentWorkspace.from_path(state["workspace_path"])
        workspace.log_error("Agent execution failed", {"errors": state["errors"]})

        return {"phase": "failed"}

    # ========== 条件判断 ==========

    def _should_continue(
        self, state: AgentState
    ) -> Literal["continue", "complete", "max_iterations", "error"]:
        """判断是否继续迭代"""

        if state.get("errors") and len(state["errors"]) >= 3:
            return "error"

        if state["iteration"] >= state["max_iterations"]:
            return "max_iterations"

        if state["verification_passed"]:
            return "complete"

        return "continue"

    # ========== 辅助方法 ==========

    def _build_context_prompt(
        self, task: str, input_data: Optional[Dict[str, Any]], previous_feedback: str
    ) -> str:
        """构建上下文收集 prompt，支持 @工具名 和 #上下文名 引用解析"""
        # 获取运行时时间上下文
        time_context = get_current_time_context()

        prompt_parts = [
            time_context,
            f"\n## 任务\n{task}",
            f"\n## 输入数据\n{input_data}",
        ]

        if previous_feedback:
            prompt_parts.append(
                f"\n## 之前的验证反馈（请据此补充信息）\n{previous_feedback}"
            )

        prompt_parts.append(
            "\n## 执行指南\n"
            "请收集完成任务所需的上下文信息。\n"
            "如果需要搜索或查询数据，请使用可用的工具。\n"
            "**重要**: 在查询数据时，请基于上述「当前执行环境」中的时间信息确定查询的时间范围。"
        )

        raw_prompt = "\n".join(prompt_parts)

        # 解析引用
        result = self.reference_resolver.resolve(
            raw_prompt, context={"task": task, "input_data": input_data}
        )

        if result.unresolved_references:
            logger.warning(f"未解析的引用: {result.unresolved_references}")

        return result.resolved_prompt

    def _build_action_prompt(self, context: str, previous_draft: str) -> str:
        """构建执行动作 prompt，支持 @工具名 和 #上下文名 引用解析"""
        # 获取运行时时间上下文
        time_context = get_current_time_context()

        prompt_parts = [
            time_context,
            "",
            "## 重要提示",
            "这是**生成阶段**，你已经收集了足够的上下文信息。",
            "请直接根据下方的上下文信息生成最终输出，不要再调用工具收集更多信息。",
            "你的回复内容将直接作为任务结果返回。",
            "",
            f"## 收集的上下文\n{context}",
            f"\n## 输出要求\n{self.definition.build_output_prompt()}",
        ]

        if previous_draft:
            prompt_parts.append(f"\n## 之前的草稿（请改进）\n{previous_draft}")

        prompt_parts.append(
            f"\n## 任务\n{self.definition.user_instruction.task_description}"
        )

        prompt_parts.append(
            "\n## 执行要求\n"
            "请直接在回复中输出符合上述格式要求的结果内容。\n"
            "如果输出格式要求是 JSON，请直接返回 JSON 格式的内容。\n"
            "不要调用工具来读取更多文件，上下文信息已经足够。\n"
            "**注意**: 在输出中涉及时间、日期时，请确保与当前执行环境的时间一致。"
        )

        raw_prompt = "\n".join(prompt_parts)

        # 解析引用
        result = self.reference_resolver.resolve(
            raw_prompt,
            context={"gathered_context": context, "previous_draft": previous_draft},
        )

        if result.unresolved_references:
            logger.warning(f"未解析的引用: {result.unresolved_references}")

        return result.resolved_prompt

    async def _execute_tool_calls_loop(
        self,
        response: Any,
        messages: List[Any],
        workspace: Any,
        max_tool_rounds: int = 10,
    ) -> str:
        """
        循环执行工具调用直到 LLM 返回最终答案

        这是文件系统交互总线的核心实现，所有工具调用都会被记录到工作空间日志。

        Args:
            response: LLM 的初始响应
            messages: 对话历史
            workspace: 工作空间
            max_tool_rounds: 最大工具调用轮数

        Returns:
            最终的响应内容
        """
        from langchain_core.messages import ToolMessage

        current_response = response
        current_messages = messages.copy()
        tool_round = 0

        while (
            hasattr(current_response, "tool_calls")
            and current_response.tool_calls
            and tool_round < max_tool_rounds
        ):
            tool_round += 1
            tool_messages = []

            # 迭代边界进度（便于前端叙事展示）
            if self.progress_callback:
                try:
                    await self.progress_callback(
                        {
                            "type": "iteration",
                            "iteration": tool_round,
                            "message": f"第 {tool_round} 轮分析...",
                        }
                    )
                except Exception as cb_err:
                    logger.warning(f"进度回调失败: {cb_err}")

            for tool_call in current_response.tool_calls:
                tool_name = tool_call.get(
                    "name", tool_call.get("function", {}).get("name", "unknown")
                )
                tool_args = tool_call.get(
                    "args", tool_call.get("function", {}).get("arguments", {})
                )

                # 确保 tool_args 是字典（某些 LLM 可能返回 JSON 字符串）
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except json.JSONDecodeError:
                        logger.warning(
                            f"无法解析 tool_args 字符串: {tool_args[:100]}..."
                        )
                        tool_args = {"raw_args": tool_args}

                tool_call_id = tool_call.get("id", f"call_{tool_round}_{tool_name}")

                logger.info(f"执行工具调用: {tool_name}({tool_args})")

                # 发送工具调用开始的进度事件（结构化，便于前端叙事展示）
                if self.progress_callback:
                    try:
                        args_summary = self._summarize_tool_args(tool_name, tool_args)
                        payload = {
                            "type": "tool_start",
                            "tool_name": tool_name,
                            "tool_args_summary": args_summary,
                            "message": f"正在使用 {tool_name}..."
                            + (f" ({args_summary})" if args_summary else ""),
                        }
                        await self.progress_callback(payload)
                    except Exception as cb_err:
                        logger.warning(f"进度回调失败: {cb_err}")

                # 实际执行工具
                try:
                    result = await self._execute_single_tool(
                        tool_name=tool_name, tool_args=tool_args, workspace=workspace
                    )

                    result_str = str(result)

                    # 发送工具执行完成的进度事件（结构化）
                    if self.progress_callback:
                        try:
                            result_summary = self._generate_tool_result_summary(
                                tool_name, result
                            )
                            payload = {
                                "type": "tool_result",
                                "tool_name": tool_name,
                                "result_summary": result_summary,
                                "message": result_summary,
                            }
                            await self.progress_callback(payload)
                        except Exception as cb_err:
                            logger.warning(f"进度回调失败: {cb_err}")

                    # 截断过长的工具结果，避免上下文爆炸
                    original_tokens = _estimate_tokens(result_str)
                    if original_tokens > MAX_TOOL_RESULT_TOKENS:
                        result_str = _truncate_tool_result(
                            result_str, MAX_TOOL_RESULT_TOKENS
                        )
                        logger.info(
                            f"工具 {tool_name} 结果已截断: {original_tokens} -> {_estimate_tokens(result_str)} tokens"
                        )

                    tool_messages.append(
                        ToolMessage(content=result_str, tool_call_id=tool_call_id)
                    )
                    logger.debug(f"工具 {tool_name} 执行成功")

                    # 添加工具结果到上下文管理器（中等优先级，已截断）
                    self.context_manager.add(
                        content=f"工具 {tool_name} 结果:\n{result_str[:5000]}",
                        source=f"tool:{tool_name}",
                        priority=4,
                        metadata={"tool_args": tool_args},
                    )

                except Exception as e:
                    error_msg = f"工具执行错误: {str(e)}"
                    logger.error(f"工具 {tool_name} 执行失败: {e}")

                    # 发送工具执行失败的进度事件（结构化）
                    if self.progress_callback:
                        try:
                            payload = {
                                "type": "tool_failed",
                                "tool_name": tool_name,
                                "message": f"工具 {tool_name} 执行失败",
                            }
                            await self.progress_callback(payload)
                        except Exception as cb_err:
                            logger.warning(f"进度回调失败: {cb_err}")

                    tool_messages.append(
                        ToolMessage(content=error_msg, tool_call_id=tool_call_id)
                    )

            # 将 AI 响应和工具结果添加到消息历史
            # 针对 Kimi/Moonshot 模型，规范化消息格式以避免 thinking 模式的验证错误
            model_name = _get_model_name_from_llm(self.langchain_llm)
            sanitized_response = _sanitize_message_for_kimi(
                current_response, model_name
            )
            current_messages.append(sanitized_response)
            current_messages.extend(tool_messages)

            # 记录 LLM 调用开始时间
            from datetime import datetime

            llm_start_time = datetime.now()

            # 针对 Kimi/Moonshot 模型，在调用前规范化整个消息列表
            # 确保所有 AIMessage（特别是有 tool_calls 的）都包含 reasoning_content
            messages_to_send = _sanitize_messages_for_kimi(current_messages, model_name)

            # 获取模型的上下文限制并截断消息
            # 从 LLM 客户端获取 max_tokens，如果没有则使用默认值
            model_max_tokens = getattr(self.langchain_llm, "max_tokens", None)
            if hasattr(self.langchain_llm, "bound"):
                # 如果是 RunnableBinding，尝试从 bound 获取
                model_max_tokens = getattr(
                    self.langchain_llm.bound, "max_tokens", model_max_tokens
                )

            # 使用模型配置的 max_tokens 或默认值
            # 注意：这里的 max_tokens 是输出限制，上下文限制通常更大
            # 对于 kimi-k2.5，上下文限制是 262144
            context_limit = DEFAULT_MAX_CONTEXT_TOKENS
            if "kimi" in model_name.lower() or "moonshot" in model_name.lower():
                context_limit = 262144  # kimi-k2.5 的上下文限制

            # 截断消息以适应上下文限制
            messages_to_send = _truncate_messages_to_fit(
                messages_to_send,
                max_tokens=context_limit,
                reserved_tokens=RESERVED_OUTPUT_TOKENS,
            )

            # 调用 LLM 前发送“思考中”进度
            if self.progress_callback:
                try:
                    await self.progress_callback(
                        {
                            "type": "thinking",
                            "message": "正在思考...",
                        }
                    )
                except Exception as cb_err:
                    logger.warning(f"进度回调失败: {cb_err}")

            # 调用 LLM 获取下一步响应
            current_response = await self.langchain_llm.ainvoke(messages_to_send)

            # 规范化 tool_calls.args（某些 LLM 可能返回字符串而非字典）
            current_response = _normalize_tool_calls_args(current_response)

            # 若仍有工具调用，发送“决定使用工具”进度
            if (
                self.progress_callback
                and hasattr(current_response, "tool_calls")
                and current_response.tool_calls
            ):
                try:
                    tool_names = [
                        tc.get("name", tc.get("function", {}).get("name", "unknown"))
                        for tc in current_response.tool_calls
                    ]
                    names_str = "、".join(tool_names[:3]) + (
                        " 等" if len(tool_names) > 3 else ""
                    )
                    await self.progress_callback(
                        {
                            "type": "decision",
                            "message": f"决定使用 {names_str} 继续处理...",
                            "tool_names": tool_names,
                        }
                    )
                except Exception as cb_err:
                    logger.warning(f"进度回调失败: {cb_err}")

            # 记录 LLM 调用日志（工具循环中的后续调用）
            llm_duration_ms = (datetime.now() - llm_start_time).total_seconds() * 1000
            if workspace and hasattr(workspace, "log_llm_call"):
                workspace.log_llm_call(
                    model=getattr(
                        self.langchain_llm,
                        "model_name",
                        getattr(self.langchain_llm, "model", "unknown"),
                    ),
                    messages=[
                        {
                            "role": "tool_results",
                            "content": f"[{len(tool_messages)} tool results]",
                        }
                    ],
                    response=(
                        str(current_response.content)[:2000]
                        if hasattr(current_response, "content")
                        else str(current_response)[:2000]
                    ),
                    tool_calls=getattr(current_response, "tool_calls", None),
                    duration_ms=llm_duration_ms,
                )

        # 返回最终的文本内容
        final_content = (
            str(current_response.content)
            if hasattr(current_response, "content")
            else str(current_response)
        )

        # 检查并警告空内容
        if not final_content.strip() and tool_round > 0:
            logger.warning(
                f"工具调用循环执行了 {tool_round} 轮后，LLM 返回的内容为空。"
                "这可能是因为 LLM 没有理解需要在回复中直接输出结果。"
            )

        return final_content

    def _summarize_tool_args(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """生成工具参数的人类可读摘要，用于进度展示"""
        if not tool_args or not isinstance(tool_args, dict):
            return ""
        parts = []
        for k, v in list(tool_args.items())[:3]:  # 最多 3 个参数
            if v is None or v == "":
                continue
            if isinstance(v, str) and len(v) > 40:
                v = v[:37] + "..."
            parts.append(f"{k}: {v}")
        return ", ".join(parts) if parts else ""

    def _generate_tool_result_summary(self, tool_name: str, result: Any) -> str:
        """
        生成工具执行结果的简短摘要

        Args:
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            简短的结果摘要字符串
        """
        try:
            if result is None:
                return f"{tool_name}: 无返回结果"

            # 处理字典类型结果
            if isinstance(result, dict):
                # 优先查找常见的摘要字段
                for key in ["summary", "message", "result", "status", "data"]:
                    if key in result:
                        value = result[key]
                        if isinstance(value, str) and len(value) < 100:
                            return f"{tool_name}: {value}"
                        elif isinstance(value, (list, tuple)):
                            return f"{tool_name}: 获取了 {len(value)} 条数据"
                        elif isinstance(value, dict):
                            return f"{tool_name}: 返回 {len(value)} 个字段"

                # 如果有 count 或 total 字段
                if "count" in result:
                    return f"{tool_name}: 共 {result['count']} 条"
                if "total" in result:
                    return f"{tool_name}: 共 {result['total']} 条"

                # 默认：显示字段数量
                return f"{tool_name}: 返回 {len(result)} 个字段"

            # 处理列表类型结果
            if isinstance(result, (list, tuple)):
                return f"{tool_name}: 获取了 {len(result)} 条数据"

            # 处理字符串结果
            if isinstance(result, str):
                if len(result) <= 80:
                    return f"{tool_name}: {result}"
                else:
                    return f"{tool_name}: {result[:77]}..."

            # 处理数字结果
            if isinstance(result, (int, float)):
                return f"{tool_name}: {result}"

            # 默认
            result_str = str(result)
            if len(result_str) <= 80:
                return f"{tool_name}: {result_str}"
            return f"{tool_name}: 执行完成"

        except Exception as e:
            logger.warning(f"生成工具结果摘要失败: {e}")
            return f"{tool_name}: 执行完成"

    async def _execute_single_tool(
        self, tool_name: str, tool_args: Dict[str, Any], workspace: Any
    ) -> Any:
        """
        执行单个工具调用

        Args:
            tool_name: 工具名称
            tool_args: 工具参数
            workspace: 工作空间

        Returns:
            工具执行结果
        """
        from datetime import datetime

        start_time = datetime.now()
        result = None
        error_msg = None
        executed_via_registry = False

        # 创建执行上下文
        context = {"workspace": workspace}

        try:
            # 优先使用 ToolRegistry 执行（ToolRegistry 内部会记录日志）
            if self.tool_registry:
                try:
                    result = await self.tool_registry.execute(
                        tool_id=tool_name, params=tool_args, context=context
                    )
                    executed_via_registry = True
                    return result
                except ValueError:
                    # 工具未在 registry 中注册，尝试其他方式
                    pass

            # 查找 LangChain 工具并执行
            for tool in self.tools:
                if hasattr(tool, "name") and tool.name == tool_name:
                    # 注入上下文
                    tool_args_with_context = tool_args.copy()
                    tool_args_with_context["_context"] = context

                    # 执行工具
                    if hasattr(tool, "ainvoke"):
                        result = await tool.ainvoke(tool_args_with_context)
                    elif hasattr(tool, "invoke"):
                        result = tool.invoke(tool_args_with_context)
                    elif callable(tool):
                        import asyncio
                        import inspect

                        if inspect.iscoroutinefunction(tool):
                            result = await tool(**tool_args_with_context)
                        else:
                            result = await asyncio.to_thread(
                                tool, **tool_args_with_context
                            )

                    return result

            raise ValueError(f"工具 '{tool_name}' 未找到")

        except Exception as e:
            error_msg = str(e)
            raise

        finally:
            # 如果不是通过 ToolRegistry 执行的，需要在这里记录日志
            # ToolRegistry 内部已经会记录日志，避免重复
            if not executed_via_registry:
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                if workspace and hasattr(workspace, "log_tool_call"):
                    workspace.log_tool_call(
                        tool_id=tool_name,
                        input_params=tool_args,
                        output=result,
                        error=error_msg,
                        phase="success" if error_msg is None else "error",
                        duration_ms=duration_ms,
                    )

    def _parse_response(self, content: str) -> Dict[str, Any]:
        """
        解析响应内容，优先提取 summary / narrative / data / highlights 结构

        委托给 json_utils.extract_structured_output() 实现，支持：
        1. JSON 优化（移除 markdown 标记、提取 JSON 边界等）
        2. 双重编码处理 {"result": "JSON字符串"}
        3. summary 清洗（移除 markdown 代码块标记）
        4. 兜底处理
        """
        return extract_structured_output(content)

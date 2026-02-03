"""
引用解析器

解析 prompt 中的特殊引用语法：
- @工具名：注入工具描述和使用说明
- #上下文名：注入上下文内容

这是声明式配置的核心组件，允许在 prompt 中动态引用工具和上下文。
"""

import re
from typing import Dict, Any, Optional, List, Tuple, Set
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class ResolvedReference:
    """已解析的引用"""

    original: str  # 原始引用字符串（如 @股票价格）
    ref_type: str  # 引用类型（tool 或 context）
    ref_name: str  # 引用名称
    resolved_content: str  # 解析后的内容
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReferenceResolutionResult:
    """引用解析结果"""

    resolved_prompt: str  # 解析后的 prompt
    tool_references: List[ResolvedReference] = field(default_factory=list)
    context_references: List[ResolvedReference] = field(default_factory=list)
    unresolved_references: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


class ReferenceResolver:
    """
    引用解析器

    解析 prompt 中的 @工具名 和 #上下文名 引用，将其替换为实际内容。

    使用示例:
    ```python
    resolver = ReferenceResolver(
        tool_registry=registry,
        context_providers={
            "市场数据": MarketDataProvider(),
            "用户偏好": UserPreferencesProvider(),
        }
    )

    # 解析 prompt
    prompt = "请使用 @股票价格 查询 #当前持仓 中的股票"
    result = resolver.resolve(prompt)

    print(result.resolved_prompt)
    # 输出: "请使用【工具：股票价格查询】查询... 中的股票"
    ```
    """

    # 引用模式
    # 工具引用: @工具名
    # 使用负向前瞻和后瞻排除邮箱地址（如 contact@example.com）和 URL
    # - (?<![a-zA-Z0-9_.]) 确保 @ 前没有邮箱用户名字符
    # - (?!\.[a-zA-Z]{2,}) 确保匹配内容后没有域名后缀（如 .com, .org）
    TOOL_REF_PATTERN = r"(?<![a-zA-Z0-9_.])@([\w\u4e00-\u9fff]+)(?!\.[a-zA-Z]{2,})"
    CONTEXT_REF_PATTERN = r"#([\w\u4e00-\u9fff]+)"  # #上下文名

    def __init__(
        self,
        tool_registry: Optional[Any] = None,
        context_providers: Optional[Dict[str, Any]] = None,
        allowed_tools: Optional[Set[str]] = None,
        allowed_contexts: Optional[Set[str]] = None,
        inject_tool_description: bool = True,
        inject_tool_schema: bool = False,
        tool_description_template: Optional[str] = None,
        context_template: Optional[str] = None,
    ):
        """
        初始化引用解析器

        Args:
            tool_registry: 工具注册表
            context_providers: 上下文提供者字典 {名称: 提供者}
            allowed_tools: 允许的工具别名集合（None 表示全部允许）
            allowed_contexts: 允许的上下文名称集合（None 表示全部允许）
            inject_tool_description: 是否注入工具描述
            inject_tool_schema: 是否注入工具输入 schema
            tool_description_template: 工具描述模板
            context_template: 上下文模板
        """
        self.tool_registry = tool_registry
        self.context_providers = context_providers or {}
        self.allowed_tools = allowed_tools
        self.allowed_contexts = allowed_contexts
        self.inject_tool_description = inject_tool_description
        self.inject_tool_schema = inject_tool_schema

        # 默认模板
        self.tool_description_template = tool_description_template or (
            "【工具：{name}】\n" "描述：{description}\n" "{schema}"
        )
        self.context_template = context_template or ("【{name}】\n{content}")

        # 静态上下文缓存
        self._static_contexts: Dict[str, str] = {}

    def add_static_context(self, name: str, content: str) -> None:
        """
        添加静态上下文

        Args:
            name: 上下文名称
            content: 上下文内容
        """
        self._static_contexts[name] = content

    def add_context_provider(self, name: str, provider: Any) -> None:
        """
        添加上下文提供者

        Args:
            name: 上下文名称
            provider: 提供者（可以是 Callable 或有 get_context 方法的对象）
        """
        self.context_providers[name] = provider

    def resolve(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ReferenceResolutionResult:
        """
        解析 prompt 中的所有引用

        Args:
            prompt: 原始 prompt
            context: 额外上下文（传递给上下文提供者）

        Returns:
            引用解析结果
        """
        context = context or {}
        resolved_prompt = prompt
        tool_refs: List[ResolvedReference] = []
        context_refs: List[ResolvedReference] = []
        unresolved: List[str] = []

        # 1. 解析工具引用
        tool_matches = re.findall(self.TOOL_REF_PATTERN, prompt)
        for tool_alias in tool_matches:
            original = f"@{tool_alias}"

            # 检查是否允许
            if self.allowed_tools and tool_alias not in self.allowed_tools:
                unresolved.append(original)
                logger.debug(f"工具引用 {original} 不在允许列表中")
                continue

            # 解析工具
            resolved = self._resolve_tool_reference(tool_alias)
            if resolved:
                tool_refs.append(resolved)
                resolved_prompt = resolved_prompt.replace(
                    original, resolved.resolved_content, 1
                )
            else:
                unresolved.append(original)
                logger.warning(f"无法解析工具引用: {original}")

        # 2. 解析上下文引用
        context_matches = re.findall(self.CONTEXT_REF_PATTERN, prompt)
        for ctx_name in context_matches:
            original = f"#{ctx_name}"

            # 检查是否允许
            if self.allowed_contexts and ctx_name not in self.allowed_contexts:
                unresolved.append(original)
                logger.debug(f"上下文引用 {original} 不在允许列表中")
                continue

            # 解析上下文
            resolved = self._resolve_context_reference(ctx_name, context)
            if resolved:
                context_refs.append(resolved)
                resolved_prompt = resolved_prompt.replace(
                    original, resolved.resolved_content, 1
                )
            else:
                unresolved.append(original)
                logger.warning(f"无法解析上下文引用: {original}")

        return ReferenceResolutionResult(
            resolved_prompt=resolved_prompt,
            tool_references=tool_refs,
            context_references=context_refs,
            unresolved_references=unresolved,
            stats={
                "tool_refs_found": len(tool_matches),
                "tool_refs_resolved": len(tool_refs),
                "context_refs_found": len(context_matches),
                "context_refs_resolved": len(context_refs),
                "unresolved_count": len(unresolved),
            },
        )

    def _resolve_tool_reference(self, tool_alias: str) -> Optional[ResolvedReference]:
        """解析工具引用"""
        if not self.tool_registry:
            return None

        # 尝试通过别名获取工具
        tool_def = self.tool_registry.get_by_alias(tool_alias)

        if not tool_def:
            # 尝试通过 ID 获取
            tool_def = self.tool_registry.get(tool_alias)

        if not tool_def:
            return None

        # 构建工具描述
        schema_str = ""
        if self.inject_tool_schema and tool_def.input_schema:
            schema_str = f"参数: {tool_def.input_schema}"

        resolved_content = self.tool_description_template.format(
            name=tool_def.name,
            description=tool_def.description,
            schema=schema_str,
        ).strip()

        return ResolvedReference(
            original=f"@{tool_alias}",
            ref_type="tool",
            ref_name=tool_alias,
            resolved_content=resolved_content,
            metadata={
                "tool_id": tool_def.tool_id,
                "tool_name": tool_def.name,
                "category": tool_def.category.value if tool_def.category else None,
            },
        )

    def _resolve_context_reference(
        self, ctx_name: str, context: Dict[str, Any]
    ) -> Optional[ResolvedReference]:
        """解析上下文引用"""
        content = None

        # 1. 先检查静态上下文
        if ctx_name in self._static_contexts:
            content = self._static_contexts[ctx_name]

        # 2. 再检查上下文提供者
        elif ctx_name in self.context_providers:
            provider = self.context_providers[ctx_name]
            try:
                if callable(provider):
                    content = provider(context)
                elif hasattr(provider, "get_context"):
                    content = provider.get_context(context)
                else:
                    content = str(provider)
            except Exception as e:
                logger.error(f"获取上下文 {ctx_name} 失败: {e}")
                return None

        # 3. 检查传入的 context 参数
        elif ctx_name in context:
            content = context[ctx_name]

        if content is None:
            return None

        # 格式化内容
        resolved_content = self.context_template.format(
            name=ctx_name,
            content=str(content),
        ).strip()

        return ResolvedReference(
            original=f"#{ctx_name}",
            ref_type="context",
            ref_name=ctx_name,
            resolved_content=resolved_content,
            metadata={
                "source": "static" if ctx_name in self._static_contexts else "provider"
            },
        )

    def get_referenced_tools(self, prompt: str) -> List[str]:
        """
        获取 prompt 中引用的所有工具别名

        Args:
            prompt: 原始 prompt

        Returns:
            工具别名列表
        """
        return re.findall(self.TOOL_REF_PATTERN, prompt)

    def get_referenced_contexts(self, prompt: str) -> List[str]:
        """
        获取 prompt 中引用的所有上下文名称

        Args:
            prompt: 原始 prompt

        Returns:
            上下文名称列表
        """
        return re.findall(self.CONTEXT_REF_PATTERN, prompt)


class ContextProvider(ABC):
    """上下文提供者抽象基类"""

    @abstractmethod
    def get_context(self, params: Optional[Dict[str, Any]] = None) -> str:
        """获取上下文内容"""
        ...


class WorkspaceContextProvider(ContextProvider):
    """
    工作空间上下文提供者

    从工作空间读取上下文文件。
    """

    def __init__(self, workspace: Any, context_file: str):
        """
        初始化

        Args:
            workspace: AgentWorkspace 实例
            context_file: 上下文文件路径（相对于工作空间）
        """
        self.workspace = workspace
        self.context_file = context_file

    def get_context(self, params: Optional[Dict[str, Any]] = None) -> str:
        try:
            return self.workspace.read_file(self.context_file)
        except FileNotFoundError:
            return ""


class DynamicContextProvider(ContextProvider):
    """
    动态上下文提供者

    通过回调函数动态生成上下文。
    """

    def __init__(self, callback):
        """
        初始化

        Args:
            callback: 回调函数，签名: (params: Dict) -> str
        """
        self.callback = callback

    def get_context(self, params: Optional[Dict[str, Any]] = None) -> str:
        return self.callback(params or {})


# 全局解析器实例
_default_resolver: Optional[ReferenceResolver] = None


def get_default_resolver() -> ReferenceResolver:
    """获取默认的引用解析器"""
    global _default_resolver
    if _default_resolver is None:
        from ..tools import ToolRegistry

        _default_resolver = ReferenceResolver(tool_registry=ToolRegistry.get_default())
    return _default_resolver


def set_default_resolver(resolver: ReferenceResolver) -> None:
    """设置默认的引用解析器"""
    global _default_resolver
    _default_resolver = resolver


def resolve_references(
    prompt: str,
    context: Optional[Dict[str, Any]] = None,
) -> ReferenceResolutionResult:
    """
    便捷函数：解析 prompt 中的引用

    Args:
        prompt: 原始 prompt
        context: 额外上下文

    Returns:
        解析结果
    """
    return get_default_resolver().resolve(prompt, context)


# 导出
__all__ = [
    "ReferenceResolver",
    "ReferenceResolutionResult",
    "ResolvedReference",
    "ContextProvider",
    "WorkspaceContextProvider",
    "DynamicContextProvider",
    "get_default_resolver",
    "set_default_resolver",
    "resolve_references",
]

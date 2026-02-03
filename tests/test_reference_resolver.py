"""
引用解析器测试

测试 ReferenceResolver 的各项功能。
"""

import pytest
from src.core.reference_resolver import (
    ReferenceResolver,
    ReferenceResolutionResult,
    ResolvedReference,
    DynamicContextProvider,
)
from src.tools.registry import ToolRegistry
from src.definitions.tool_definition import ToolDefinition, ToolCategory


class TestReferenceResolver:
    """ReferenceResolver 测试"""

    @pytest.fixture
    def registry_with_tools(self):
        """创建带有注册工具的 ToolRegistry"""
        registry = ToolRegistry()

        # 注册测试工具
        tool_def = ToolDefinition(
            tool_id="stock_price",
            name="股票价格查询",
            alias="股票价格",
            description="查询股票实时价格",
            category=ToolCategory.STOCK_DATA,
            input_schema={
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
            output_schema={"type": "object"},
        )
        registry.register(tool_def, lambda **kwargs: {"price": 100.0})

        return registry

    def test_resolve_tool_reference(self, registry_with_tools):
        """测试解析工具引用"""
        resolver = ReferenceResolver(
            tool_registry=registry_with_tools,
            inject_tool_description=True,
        )

        prompt = "请使用 @股票价格 查询苹果的股价"
        result = resolver.resolve(prompt)

        assert len(result.tool_references) == 1
        assert result.tool_references[0].ref_name == "股票价格"
        assert (
            "股票价格查询" in result.resolved_prompt or "工具" in result.resolved_prompt
        )

    def test_resolve_context_reference(self):
        """测试解析上下文引用"""
        resolver = ReferenceResolver(
            context_providers={
                "当前持仓": lambda ctx: "AAPL: 100, GOOGL: 50",
            }
        )

        prompt = "分析 #当前持仓 中的股票"
        result = resolver.resolve(prompt)

        assert len(result.context_references) == 1
        assert "AAPL" in result.resolved_prompt

    def test_resolve_multiple_references(self, registry_with_tools):
        """测试解析多个引用"""
        resolver = ReferenceResolver(
            tool_registry=registry_with_tools,
            context_providers={
                "市场数据": lambda ctx: "市场趋势: 上涨",
            },
        )

        prompt = "使用 @股票价格 查询 #市场数据 中提到的股票"
        result = resolver.resolve(prompt)

        assert len(result.tool_references) == 1
        assert len(result.context_references) == 1

    def test_unresolved_references(self):
        """测试未解析的引用"""
        resolver = ReferenceResolver()

        prompt = "使用 @不存在的工具 和 #不存在的上下文"
        result = resolver.resolve(prompt)

        assert len(result.unresolved_references) == 2

    def test_static_context(self):
        """测试静态上下文"""
        resolver = ReferenceResolver()
        resolver.add_static_context("用户信息", "用户: Alice, ID: 123")

        prompt = "获取 #用户信息"
        result = resolver.resolve(prompt)

        assert "Alice" in result.resolved_prompt

    def test_allowed_tools_filter(self, registry_with_tools):
        """测试工具白名单过滤"""
        resolver = ReferenceResolver(
            tool_registry=registry_with_tools,
            allowed_tools={"其他工具"},  # 不包含 "股票价格"
        )

        prompt = "使用 @股票价格 查询"
        result = resolver.resolve(prompt)

        assert len(result.tool_references) == 0
        assert len(result.unresolved_references) == 1

    def test_get_referenced_tools(self, registry_with_tools):
        """测试获取引用的工具列表"""
        resolver = ReferenceResolver(tool_registry=registry_with_tools)

        prompt = "使用 @股票价格 和 @财务数据 分析"
        tools = resolver.get_referenced_tools(prompt)

        assert "股票价格" in tools
        assert "财务数据" in tools

    def test_get_referenced_contexts(self):
        """测试获取引用的上下文列表"""
        resolver = ReferenceResolver()

        prompt = "查看 #用户偏好 和 #市场趋势"
        contexts = resolver.get_referenced_contexts(prompt)

        assert "用户偏好" in contexts
        assert "市场趋势" in contexts

    def test_custom_templates(self, registry_with_tools):
        """测试自定义模板"""
        resolver = ReferenceResolver(
            tool_registry=registry_with_tools,
            tool_description_template="[TOOL: {name}] {description}",
            context_template="<{name}>{content}</{name}>",
        )
        resolver.add_static_context("测试", "测试内容")

        prompt = "@股票价格 #测试"
        result = resolver.resolve(prompt)

        assert "[TOOL:" in result.resolved_prompt
        assert "<测试>" in result.resolved_prompt

    def test_resolution_stats(self, registry_with_tools):
        """测试解析统计"""
        resolver = ReferenceResolver(
            tool_registry=registry_with_tools,
            context_providers={"ctx": lambda _: "data"},
        )

        prompt = "@股票价格 #ctx #不存在"
        result = resolver.resolve(prompt)

        assert result.stats["tool_refs_found"] == 1
        assert result.stats["tool_refs_resolved"] == 1
        assert result.stats["context_refs_found"] == 2
        assert result.stats["context_refs_resolved"] == 1
        assert result.stats["unresolved_count"] == 1

    def test_email_addresses_not_matched_as_tool_refs(self, registry_with_tools):
        """测试邮箱地址不会被误识别为工具引用"""
        resolver = ReferenceResolver(
            tool_registry=registry_with_tools,
        )

        # 包含邮箱地址的文本，不应该匹配任何工具引用
        prompt_with_email = "请联系 contact@example.com 或 user@econdb.org 获取帮助"
        result = resolver.resolve(prompt_with_email)

        # 邮箱地址不应该被识别为工具引用
        assert len(result.tool_references) == 0
        assert len(result.unresolved_references) == 0

        # 包含 Markdown 链接格式的邮箱地址
        prompt_with_markdown_email = "[联系我们](mailto:support@example.com)"
        result = resolver.resolve(prompt_with_markdown_email)

        assert len(result.tool_references) == 0
        assert len(result.unresolved_references) == 0

        # 正常的工具引用应该仍然能被识别
        prompt_with_tool = "请使用 @股票价格 查询，有问题联系 help@test.com"
        result = resolver.resolve(prompt_with_tool)

        assert len(result.tool_references) == 1
        assert result.tool_references[0].ref_name == "股票价格"
        assert len(result.unresolved_references) == 0


class TestDynamicContextProvider:
    """DynamicContextProvider 测试"""

    def test_callback_provider(self):
        """测试回调函数提供者"""
        call_count = [0]

        def callback(params):
            call_count[0] += 1
            return f"Data for {params.get('user', 'unknown')}"

        provider = DynamicContextProvider(callback)

        result = provider.get_context({"user": "Alice"})
        assert "Alice" in result
        assert call_count[0] == 1

        result = provider.get_context({"user": "Bob"})
        assert "Bob" in result
        assert call_count[0] == 2


class TestResolvedReference:
    """ResolvedReference 测试"""

    def test_create_resolved_reference(self):
        """测试创建解析后的引用"""
        ref = ResolvedReference(
            original="@工具",
            ref_type="tool",
            ref_name="工具",
            resolved_content="工具描述内容",
            metadata={"tool_id": "test_tool"},
        )

        assert ref.original == "@工具"
        assert ref.ref_type == "tool"
        assert ref.metadata["tool_id"] == "test_tool"

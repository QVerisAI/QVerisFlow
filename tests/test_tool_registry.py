"""
工具注册表测试

测试 ToolRegistry 的各项功能。
"""

import pytest
from src.tools.registry import ToolRegistry, tool
from src.definitions.tool_definition import ToolDefinition, ToolCategory


class TestToolRegistry:
    """ToolRegistry 测试"""

    def test_register_tool(self, tool_registry):
        """测试注册工具"""
        tool_def = ToolDefinition(
            tool_id="test_tool",
            name="测试工具",
            alias="测试",
            description="一个测试工具",
            category=ToolCategory.FILE_SYSTEM,
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object"},
        )

        tool_registry.register(tool_def, lambda: "test result")

        assert tool_registry.get("test_tool") is not None
        assert tool_registry.get_by_alias("测试") is not None

    def test_get_by_alias(self, tool_registry):
        """测试通过别名获取工具"""
        tool_def = ToolDefinition(
            tool_id="my_tool",
            name="我的工具",
            alias="我的",
            description="描述",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={},
            output_schema={},
        )

        tool_registry.register(tool_def, lambda: None)

        result = tool_registry.get_by_alias("我的")
        assert result is not None
        assert result.tool_id == "my_tool"

    def test_get_nonexistent_tool(self, tool_registry):
        """测试获取不存在的工具"""
        assert tool_registry.get("nonexistent") is None
        assert tool_registry.get_by_alias("不存在") is None

    def test_get_by_category(self, tool_registry):
        """测试按分类获取工具"""
        tool_def1 = ToolDefinition(
            tool_id="file_tool_1",
            name="文件工具1",
            alias="文件1",
            description="",
            category=ToolCategory.FILE_SYSTEM,
            input_schema={},
            output_schema={},
        )
        tool_def2 = ToolDefinition(
            tool_id="file_tool_2",
            name="文件工具2",
            alias="文件2",
            description="",
            category=ToolCategory.FILE_SYSTEM,
            input_schema={},
            output_schema={},
        )
        tool_def3 = ToolDefinition(
            tool_id="bash_tool",
            name="Bash工具",
            alias="bash",
            description="",
            category=ToolCategory.BASH,
            input_schema={},
            output_schema={},
        )

        tool_registry.register(tool_def1, lambda: None)
        tool_registry.register(tool_def2, lambda: None)
        tool_registry.register(tool_def3, lambda: None)

        file_tools = tool_registry.get_by_category(ToolCategory.FILE_SYSTEM)
        assert len(file_tools) == 2

        bash_tools = tool_registry.get_by_category(ToolCategory.BASH)
        assert len(bash_tools) == 1

    def test_list_all(self, tool_registry):
        """测试列出所有工具"""
        tool_def = ToolDefinition(
            tool_id="list_test",
            name="列表测试",
            alias="列表",
            description="",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={},
            output_schema={},
        )

        tool_registry.register(tool_def, lambda: None)

        tools = tool_registry.list_all()
        assert len(tools) >= 1
        assert any(t["tool_id"] == "list_test" for t in tools)

    def test_unregister_tool(self, tool_registry):
        """测试取消注册工具"""
        tool_def = ToolDefinition(
            tool_id="to_unregister",
            name="待取消",
            alias="取消",
            description="",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={},
            output_schema={},
        )

        tool_registry.register(tool_def, lambda: None)
        assert tool_registry.get("to_unregister") is not None

        result = tool_registry.unregister("to_unregister")
        assert result is True
        assert tool_registry.get("to_unregister") is None

    def test_copy_registry(self, tool_registry):
        """测试复制注册表"""
        tool_def = ToolDefinition(
            tool_id="copy_test",
            name="复制测试",
            alias="复制",
            description="",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={},
            output_schema={},
        )

        tool_registry.register(tool_def, lambda: None)

        copied = tool_registry.copy()
        assert copied.get("copy_test") is not None
        assert copied is not tool_registry

    def test_merge_registries(self):
        """测试合并注册表"""
        registry1 = ToolRegistry()
        registry2 = ToolRegistry()

        tool1 = ToolDefinition(
            tool_id="tool1",
            name="工具1",
            alias="工具1",
            description="",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={},
            output_schema={},
        )
        tool2 = ToolDefinition(
            tool_id="tool2",
            name="工具2",
            alias="工具2",
            description="",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={},
            output_schema={},
        )

        registry1.register(tool1, lambda: None)
        registry2.register(tool2, lambda: None)

        registry1.merge(registry2)

        assert registry1.get("tool1") is not None
        assert registry1.get("tool2") is not None

    def test_reset_registry(self, tool_registry):
        """测试重置注册表"""
        tool_def = ToolDefinition(
            tool_id="reset_test",
            name="重置测试",
            alias="重置",
            description="",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={},
            output_schema={},
        )

        tool_registry.register(tool_def, lambda: None)
        assert len(tool_registry.list_all()) >= 1

        tool_registry.reset()
        assert len(tool_registry.list_all()) == 0


class TestToolRegistryAsync:
    """ToolRegistry 异步方法测试"""

    @pytest.mark.asyncio
    async def test_execute_sync_tool(self, tool_registry):
        """测试执行同步工具"""
        tool_def = ToolDefinition(
            tool_id="sync_tool",
            name="同步工具",
            alias="同步",
            description="",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={"type": "object", "properties": {}},
            output_schema={},
            is_async=False,
        )

        def sync_impl(**kwargs):
            return {"status": "success"}

        tool_registry.register(tool_def, sync_impl)

        result = await tool_registry.execute("sync_tool", {})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_execute_async_tool(self, tool_registry):
        """测试执行异步工具"""
        tool_def = ToolDefinition(
            tool_id="async_tool",
            name="异步工具",
            alias="异步",
            description="",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={"type": "object", "properties": {}},
            output_schema={},
            is_async=True,
        )

        async def async_impl(**kwargs):
            return {"status": "async_success"}

        tool_registry.register(tool_def, async_impl)

        result = await tool_registry.execute("async_tool", {})
        assert result["status"] == "async_success"

    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool(self, tool_registry):
        """测试执行不存在的工具"""
        with pytest.raises(ValueError):
            await tool_registry.execute("nonexistent", {})

    @pytest.mark.asyncio
    async def test_execute_with_validation(self, tool_registry):
        """测试执行时的参数验证"""
        tool_def = ToolDefinition(
            tool_id="validated_tool",
            name="验证工具",
            alias="验证",
            description="",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
            output_schema={},
        )

        tool_registry.register(tool_def, lambda name, **kwargs: {"name": name})

        # 有效参数
        result = await tool_registry.execute("validated_tool", {"name": "test"})
        assert result["name"] == "test"

        # 缺少必需参数（应该验证失败）
        from src.tools.validation import ToolValidationError

        with pytest.raises(ToolValidationError):
            await tool_registry.execute("validated_tool", {})


class TestToolDecorator:
    """@tool 装饰器测试"""

    def test_tool_decorator(self):
        """测试工具装饰器"""
        registry = ToolRegistry()

        @tool(
            tool_id="decorated_tool",
            name="装饰器工具",
            alias="装饰",
            description="使用装饰器注册的工具",
            category=ToolCategory.CODE_EXECUTION,
            input_schema={"type": "object"},
            registry=registry,
        )
        def my_tool(**kwargs):
            return "decorated result"

        assert registry.get("decorated_tool") is not None
        assert hasattr(my_tool, "_tool_definition")

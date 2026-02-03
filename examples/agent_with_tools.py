"""
工具集成示例

展示如何注册和使用自定义工具：
1. 使用 @tool 装饰器注册工具
2. 手动注册工具
3. 执行工具

配置文件: config/app_config.yaml
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tools import ToolRegistry, tool
from src.definitions import ToolDefinition, ToolReferenceType, ToolCategory


# 创建工具注册表
registry = ToolRegistry()


# ============================================================
# 方式一：使用装饰器注册工具
# ============================================================


@tool(
    tool_id="example_stock_price",
    name="示例股票价格查询",
    alias="股票价格",
    description="查询股票实时价格（示例工具）",
    category=ToolCategory.SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "股票代码，如 600519.SH"}
        },
        "required": ["ticker"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "price": {"type": "number"},
            "change": {"type": "number"},
        },
    },
    registry=registry,
)
async def get_stock_price(ticker: str, **kwargs) -> dict:
    """
    查询股票价格（示例实现）

    在实际使用中，这里应该调用真实的股票数据 API。
    """
    # 模拟数据
    mock_prices = {
        "600519.SH": {"price": 1850.00, "change": 0.02},
        "000001.SZ": {"price": 15.50, "change": -0.01},
        "300750.SZ": {"price": 220.00, "change": 0.03},
    }

    data = mock_prices.get(ticker, {"price": 100.00, "change": 0.00})

    return {
        "ticker": ticker,
        "price": data["price"],
        "change": data["change"],
        "source": "mock_data",
    }


@tool(
    tool_id="example_calculator",
    name="示例计算器",
    alias="计算器",
    description="执行基本数学运算",
    category=ToolCategory.SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 2+2"}
        },
        "required": ["expression"],
    },
    registry=registry,
)
async def calculate(expression: str, **kwargs) -> dict:
    """执行数学计算"""
    try:
        # 注意：在生产环境中应使用安全的表达式解析器
        # 这里仅作演示
        allowed_chars = set("0123456789+-*/.()")
        if not all(c in allowed_chars or c.isspace() for c in expression):
            raise ValueError("表达式包含非法字符")

        result = eval(expression)
        return {"expression": expression, "result": result, "success": True}
    except Exception as e:
        return {"expression": expression, "error": str(e), "success": False}


# ============================================================
# 方式二：手动注册工具
# ============================================================


def register_manual_tool():
    """手动注册工具示例"""

    # 1. 定义工具
    tool_def = ToolDefinition(
        tool_id="example_search",
        name="示例搜索",
        alias="搜索",
        description="模拟搜索功能",
        category=ToolCategory.WEB_SEARCH,
        reference_type=ToolReferenceType.BUILTIN,
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {"results": {"type": "array"}, "total": {"type": "integer"}},
        },
    )

    # 2. 实现工具函数
    async def search(query: str, limit: int = 5, **kwargs) -> dict:
        """模拟搜索"""
        results = [
            {"title": f"搜索结果 {i}", "snippet": f"关于 {query} 的内容 {i}"}
            for i in range(1, limit + 1)
        ]
        return {"query": query, "results": results, "total": len(results)}

    # 3. 注册到注册表
    registry.register(tool_def, search)
    print(f"   手动注册工具: {tool_def.name}")


async def demonstrate_tool_execution(verbose: bool = False):
    """演示工具执行"""
    print("\n3. 执行工具...")

    # 执行股票价格查询
    print("\n   [执行] 股票价格查询")
    result = await registry.execute(
        tool_id="example_stock_price", params={"ticker": "600519.SH"}
    )
    print(f"   结果: {result}")

    # 执行计算器
    print("\n   [执行] 计算器")
    result = await registry.execute(
        tool_id="example_calculator", params={"expression": "100 * 1.05"}
    )
    print(f"   结果: {result}")

    # 执行搜索
    print("\n   [执行] 搜索")
    result = await registry.execute(
        tool_id="example_search", params={"query": "人工智能", "limit": 3}
    )
    print(f"   结果: {result}")

    # 通过别名查找工具
    print("\n   [查找] 通过别名查找工具")
    tool_def = registry.get_by_alias("股票价格")
    if tool_def:
        print(f"   找到工具: {tool_def.name} (ID: {tool_def.tool_id})")


async def run_example(verbose: bool = False):
    """示例入口"""
    print("=" * 50)
    print("工具集成示例")
    print("=" * 50)

    # 1. 查看装饰器注册的工具
    print("\n1. 装饰器注册的工具:")
    for tool_info in registry.list_all():
        print(f"   - {tool_info['name']} (@{tool_info.get('alias', 'N/A')})")

    # 2. 手动注册工具
    print("\n2. 手动注册工具...")
    register_manual_tool()

    # 3. 再次查看所有工具
    print("\n   当前所有工具:")
    for tool_info in registry.list_all():
        print(f"   - {tool_info['name']} (ID: {tool_info['tool_id']})")

    # 4. 演示工具执行
    await demonstrate_tool_execution(verbose)

    # 5. 工具验证示例
    print("\n4. 工具参数验证...")
    try:
        # 缺少必需参数
        await registry.execute(tool_id="example_stock_price", params={})  # 缺少 ticker
    except Exception as e:
        print(f"   预期错误: {type(e).__name__} - 缺少必需参数")

    print("\n" + "=" * 50)
    print("示例完成")
    print("=" * 50)

    return {"status": "success"}


if __name__ == "__main__":
    asyncio.run(run_example(verbose=True))

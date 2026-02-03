"""
QVeris 工具集成示例

演示如何将 QVeris 远程工具集成到 Agent Framework 中。

功能演示：
1. 初始化 QVeris 适配器
2. 搜索远程工具
3. 执行远程工具
4. 在 Agent 中使用 QVeris 工具

前置条件：
- 设置环境变量 QVERIS_API_KEY
- 安装 httpx: pip install httpx
"""

import asyncio
import os
from typing import Optional

# 设置 API Key（实际使用时应通过环境变量设置）
# os.environ["QVERIS_API_KEY"] = "your-api-key-here"


async def example_basic_usage():
    """
    示例 1: 基本用法 - 直接使用 QVerisClient
    """
    from src.tools.qveris_client import QVerisClient

    print("=" * 60)
    print("示例 1: 基本用法 - 直接使用 QVerisClient")
    print("=" * 60)

    # 创建客户端
    async with QVerisClient() as client:
        # 搜索工具
        print("\n1. 搜索天气相关工具...")
        search_result = await client.search_tools(
            query="weather forecast API",
            limit=5,
        )

        print(f"   找到 {search_result.total_count} 个工具")
        print(f"   Search ID: {search_result.search_id}")

        for tool in search_result.tools:
            print(f"\n   - {tool.name} ({tool.tool_id})")
            print(f"     描述: {tool.description[:100]}...")
            if tool.weighted_success_rate:
                print(f"     成功率: {tool.weighted_success_rate:.2%}")
            if tool.avg_execution_time:
                print(f"     平均执行时间: {tool.avg_execution_time:.2f}s")

        # 如果找到工具，执行第一个
        if search_result.tools:
            print("\n2. 执行第一个工具...")
            first_tool = search_result.tools[0]

            # 注意：实际参数需要根据工具的 input_schema 提供
            exec_result = await client.execute_tool(
                tool_id=first_tool.tool_id,
                search_id=search_result.search_id,
                params={"city": "London", "units": "metric"},
            )

            if exec_result.success:
                print(f"   执行成功！耗时: {exec_result.execution_time_ms:.2f}ms")
                print(f"   结果: {str(exec_result.content)[:200]}...")
            else:
                print(f"   执行失败: {exec_result.error}")


async def example_with_tool_registry():
    """
    示例 2: 与 ToolRegistry 集成
    """
    from src.tools import ToolRegistry, QVerisToolAdapter

    print("\n" + "=" * 60)
    print("示例 2: 与 ToolRegistry 集成")
    print("=" * 60)

    # 获取默认 ToolRegistry
    registry = ToolRegistry.get_default()

    # 创建 QVeris 适配器并注册元工具
    adapter = QVerisToolAdapter(
        tool_registry=registry,
        auto_register_discovered=True,  # 自动注册发现的工具
    )
    adapter.register_meta_tools()

    print("\n1. 已注册的 QVeris 元工具:")
    print("   - qveris_search_tools: 搜索远程工具")
    print("   - qveris_execute_tool: 执行远程工具")
    print("   - qveris_get_tool_info: 获取工具信息")

    # 通过 ToolRegistry 搜索工具
    print("\n2. 通过 ToolRegistry 搜索工具...")
    search_result = await registry.execute(
        "qveris_search_tools",
        {"query": "stock price API", "limit": 3},
    )

    print(f"   找到 {search_result['total_count']} 个工具")
    for tool in search_result["tools"]:
        print(f"   - {tool['name']}")

    # 执行工具
    if search_result["tools"]:
        print("\n3. 通过 ToolRegistry 执行工具...")
        first_tool = search_result["tools"][0]

        exec_result = await registry.execute(
            "qveris_execute_tool",
            {
                "tool_id": first_tool["tool_id"],
                "search_id": search_result["search_id"],
                "params": {"symbol": "AAPL"},
            },
        )

        if exec_result["success"]:
            print(f"   执行成功！")
            print(f"   结果: {str(exec_result['content'])[:200]}...")
        else:
            print(f"   执行失败: {exec_result['error']}")

    # 查看动态注册的工具
    print("\n4. 动态注册的代理工具:")
    discovered = adapter.get_discovered_tools()
    for tool_def in discovered[:5]:
        print(f"   - {tool_def.tool_id}: {tool_def.name}")

    # 清理
    await adapter.close()


async def example_with_agent():
    """
    示例 3: 在 Agent 中使用 QVeris 工具
    """
    from src.tools import ToolRegistry, QVerisToolAdapter, create_qveris_adapter
    from src.core import BaseAgent
    from src.definitions import AgentDefinition, ModelConfig
    from src.workspace import AgentWorkspace, WorkspaceConfig

    print("\n" + "=" * 60)
    print("示例 3: 在 Agent 中使用 QVeris 工具")
    print("=" * 60)

    # 使用便捷函数创建适配器
    registry = ToolRegistry.get_default()
    adapter = create_qveris_adapter(
        tool_registry=registry,
        auto_register=True,
    )

    # 获取推荐的系统提示词
    qveris_prompt = QVerisToolAdapter.get_recommended_system_prompt()
    print(f"\n推荐的系统提示词:\n{qveris_prompt}")

    # 创建 Agent 定义（包含 QVeris 系统提示）
    agent_def = AgentDefinition(
        agent_id="qveris_demo_agent",
        name="QVeris Demo Agent",
        description="演示如何使用 QVeris 远程工具的 Agent",
        llm_config=ModelConfig(
            model_name="deepseek/deepseek-chat",
            max_tokens=4096,
        ),
        system_prompt=f"""你是一个智能助手，可以动态搜索和使用各种工具来完成任务。

{qveris_prompt}

注意事项：
1. 先搜索可能有用的工具
2. 根据成功率和执行时间选择最佳工具
3. 正确传递工具所需的参数
""",
        tool_ids=[
            "qveris_search_tools",
            "qveris_execute_tool",
            "qveris_get_tool_info",
        ],
    )

    # 创建工作空间
    workspace_config = WorkspaceConfig(
        task_id="qveris_demo_task",
        base_path="/tmp/agent_workspaces",
    )
    workspace = AgentWorkspace(workspace_config)
    workspace.initialize()

    # 创建 Agent
    agent = BaseAgent(
        definition=agent_def,
        workspace=workspace,
        tool_registry=registry,
    )

    print("\nAgent 已配置完成，可以开始使用 QVeris 工具！")

    # 示例任务
    # result = await agent.run(
    #     task_description="请帮我查询苹果公司（AAPL）的最新股价",
    # )
    # print(f"Agent 执行结果: {result}")

    # 清理
    await adapter.close()


async def example_configuration():
    """
    示例 4: 通过配置文件使用 QVeris
    """
    from src.config import get_config

    print("\n" + "=" * 60)
    print("示例 4: 通过配置文件使用 QVeris")
    print("=" * 60)

    # 通过配置管理器获取配置
    config = get_config()

    print("\nQVeris 配置:")
    print(f"  enabled: {config.qveris.enabled}")
    print(f"  base_url: {config.qveris.base_url}")
    print(f"  default_limit: {config.qveris.default_limit}")
    print(f"  cache_ttl: {config.qveris.cache_ttl}s")
    print(f"  max_response_size: {config.qveris.max_response_size} bytes")

    # 通过环境变量配置
    print("\n通过环境变量配置 QVeris:")
    print("  export QVERIS_API_KEY=your-api-key")
    print("  export AGENT_FRAMEWORK__QVERIS__ENABLED=true")
    print("  export AGENT_FRAMEWORK__QVERIS__BASE_URL=https://qveris.ai/api/v1")

    # 或通过配置文件
    print("\n或通过 YAML 配置文件:")
    print(
        """
qveris:
  enabled: true
  api_key: "your-api-key"
  base_url: "https://qveris.ai/api/v1"
  default_limit: 20
  cache_ttl: 3600
  max_response_size: 20480
  auto_register_discovered: true
"""
    )


async def example_error_handling():
    """
    示例 5: 错误处理
    """
    from src.tools.qveris_client import QVerisClient, QVerisAPIError

    print("\n" + "=" * 60)
    print("示例 5: 错误处理")
    print("=" * 60)

    # 使用无效的 API Key 演示错误处理
    client = QVerisClient(api_key="invalid-key")

    try:
        await client.search_tools("test query")
    except QVerisAPIError as e:
        print(f"\n捕获到 QVeris API 错误:")
        print(f"  消息: {e.message}")
        print(f"  状态码: {e.status_code}")
        print(f"  可恢复: 否 (需要有效的 API Key)")

    finally:
        await client.close()

    print("\n建议的错误处理策略:")
    print("  1. 捕获 QVerisAPIError 处理 API 错误")
    print("  2. 检查 status_code 判断错误类型")
    print("  3. 429 错误自动重试（已内置）")
    print("  4. 5xx 错误可重试（已内置）")
    print("  5. 4xx 客户端错误需检查参数")


async def main():
    """运行所有示例"""
    print("\n" + "=" * 60)
    print("QVeris 工具集成示例")
    print("=" * 60)

    # 检查 API Key
    api_key = os.environ.get("QVERIS_API_KEY")
    if not api_key:
        print("\n⚠️  警告: 未设置 QVERIS_API_KEY 环境变量")
        print("   部分示例需要有效的 API Key 才能运行")
        print("   请设置: export QVERIS_API_KEY=your-api-key")

    try:
        # 运行配置示例（不需要 API Key）
        await example_configuration()

        # 以下示例需要有效的 API Key
        if api_key:
            await example_basic_usage()
            await example_with_tool_registry()
            # await example_with_agent()  # 需要完整的 Agent 环境
        else:
            print("\n跳过需要 API Key 的示例...")

        # 错误处理示例（会失败，但用于演示）
        # await example_error_handling()

    except Exception as e:
        print(f"\n示例运行出错: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

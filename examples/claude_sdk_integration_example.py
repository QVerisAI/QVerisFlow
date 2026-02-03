"""
Claude Agent SDK 集成示例

展示如何在 agent_framework 中使用 Claude Agent SDK 的各项功能。

运行前准备：
1. 安装 Claude Agent SDK: pip install claude-agent-sdk
2. 设置环境变量: export ANTHROPIC_API_KEY=your_key
3. 准备工作空间目录
"""

import asyncio
from pathlib import Path

# ========== 示例 1: 使用 Claude SDK 客户端 ==========


async def example_1_claude_sdk_client():
    """示例1：在现有 Agent 中使用 Claude SDK 客户端"""

    print("=" * 60)
    print("示例 1: 使用 Claude SDK 客户端")
    print("=" * 60)

    from src.core import BaseAgent
    from src.definitions import (
        AgentDefinition,
        AgentExecutionType,
        AgentDomainType,
        LLMConfig,
        BackgroundInstruction,
        OutputInstruction,
        UserInstruction,
    )
    from src.workspace import AgentWorkspace, WorkspaceConfig
    from src.utils.claude_client import ClaudeSDKClient

    # 1. 创建 Agent 定义
    agent_def = AgentDefinition(
        agent_id="financial_analyst",
        name="金融分析师",
        description="使用 Claude SDK 的金融分析 Agent",
        execution_type=AgentExecutionType.REASONING_EXECUTOR,
        domain_type=AgentDomainType.FINANCIAL_ANALYSIS,
        background_instruction=BackgroundInstruction(
            role_description="你是一位资深金融分析师",
            core_capability="分析股票数据并给出投资建议",
            task_context="基于提供的数据进行专业分析",
        ),
        output_instruction=OutputInstruction(
            format_type="json", format_requirements=["输出 JSON 格式", "包含分析和建议"]
        ),
        user_instruction=UserInstruction(task_description="请分析股票并给出投资建议"),
        llm_config=LLMConfig(
            model_name="claude-sonnet-4-20250514", temperature=0.3, max_tokens=2048
        ),
    )

    # 2. 创建工作空间
    workspace_config = WorkspaceConfig(
        base_path="./workspaces", task_id="task_claude_sdk_001"
    )
    workspace = AgentWorkspace(workspace_config)

    # 3. 创建 Claude SDK 客户端
    claude_client = ClaudeSDKClient(
        model_name="claude-sonnet-4-20250514", temperature=0.3, max_tokens=2048
    )

    # 4. 创建 Agent
    agent = BaseAgent(
        definition=agent_def, workspace=workspace, llm_client=claude_client
    )

    # 5. 运行 Agent
    result = await agent.run(
        task_description="分析股票 600519.SH 的投资价值",
        input_data={"ticker": "600519.SH", "price": 1850.0, "pe_ratio": 35.2},
    )

    print(f"\n✅ 执行结果: {result['success']}")
    print(f"迭代次数: {result['iterations']}")
    print(f"结果: {result.get('result', 'N/A')}")


# ========== 示例 2: Claude 原生 Agent ==========


async def example_2_claude_native_agent():
    """示例2：使用 Claude 原生 Agent（完全基于 SDK）"""

    print("\n" + "=" * 60)
    print("示例 2: Claude 原生 Agent")
    print("=" * 60)

    from src.core.claude_agent import ClaudeNativeAgent
    from src.definitions import AgentDefinition
    from src.workspace import AgentWorkspace, WorkspaceConfig

    # 从 YAML 加载 Agent 定义（假设已存在）
    # agent_def = AgentDefinition.from_yaml_file("agents/financial_analyst.yaml")

    # 或者直接创建
    from src.definitions import (
        BackgroundInstruction,
        OutputInstruction,
        UserInstruction,
        LLMConfig,
        AgentExecutionType,
        AgentDomainType,
    )

    agent_def = AgentDefinition(
        agent_id="claude_native_analyst",
        name="Claude 原生分析师",
        description="完全基于 Claude SDK 的分析 Agent",
        execution_type=AgentExecutionType.REASONING_EXECUTOR,
        domain_type=AgentDomainType.FINANCIAL_ANALYSIS,
        background_instruction=BackgroundInstruction(
            role_description="你是一位使用最新 AI 技术的金融分析师",
            core_capability="深度分析金融数据",
            task_context="利用所有可用工具进行分析",
        ),
        output_instruction=OutputInstruction(
            format_type="json",
            format_requirements=["清晰的 JSON 结构", "详细的分析过程"],
        ),
        user_instruction=UserInstruction(task_description="进行全面的金融分析"),
        llm_config=LLMConfig(model_name="claude-sonnet-4-20250514", max_iterations=5),
    )

    workspace_config = WorkspaceConfig(
        base_path="./workspaces", task_id="task_claude_native_002"
    )

    # 创建 Claude 原生 Agent
    agent = ClaudeNativeAgent(
        definition=agent_def,
        workspace=AgentWorkspace(workspace_config),
        use_sdk_execution=True,  # 使用 SDK 原生执行
    )

    result = await agent.run(
        task_description="分析科技股投资机会", input_data={"sector": "technology"}
    )

    print(f"\n✅ 执行结果: {result['success']}")
    print(f"执行模式: {result.get('execution_mode', 'unknown')}")


# ========== 示例 3: MCP 工具集成 ==========


async def example_3_mcp_tools():
    """示例3：集成 MCP 工具"""

    print("\n" + "=" * 60)
    print("示例 3: MCP 工具集成")
    print("=" * 60)

    from src.tools import ToolRegistry, MCPToolAdapter
    from src.tools.mcp_adapter import mcp_tool
    from src.definitions import ToolCategory

    # 1. 创建工具注册表
    tool_registry = ToolRegistry()

    # 2. 创建 MCP 适配器
    mcp_adapter = MCPToolAdapter(tool_registry)

    # 3. 方式A: 使用装饰器快速注册工具
    @mcp_tool(
        tool_id="stock_price",
        name="股票价格查询",
        description="查询股票实时价格",
        input_schema={
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "股票代码"}},
            "required": ["ticker"],
        },
        category=ToolCategory.STOCK_DATA,
        alias="股票价格",
    )
    async def get_stock_price(ticker: str) -> dict:
        # 实际实现会调用 API
        return {"ticker": ticker, "price": 1850.0, "change": +2.5}

    # 4. 方式B: 注册 SDK MCP 服务器
    try:
        from claude_agent_sdk import tool, create_sdk_mcp_server

        @tool("calculate", "计算数学表达式", {"expression": str})
        async def calculate(args):
            expression = args.get("expression", "")
            # 安全计算（生产环境需要沙箱）
            try:
                result = eval(expression)
                return {"content": [{"type": "text", "text": f"结果: {result}"}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"错误: {str(e)}"}]}

        # 创建 SDK 服务器
        calculator_server = create_sdk_mcp_server(
            name="calculator", version="1.0.0", tools=[calculate]
        )

        # 注册到适配器
        mcp_adapter.register_sdk_server("calculator", calculator_server)

        print("✅ MCP 工具注册成功")

    except ImportError:
        print("⚠️ Claude SDK 未安装，跳过 SDK 服务器注册")

    # 5. 获取配置用于 Agent
    mcp_config = mcp_adapter.get_mcp_server_config()
    allowed_tools = mcp_adapter.get_allowed_tools()

    print(f"MCP 服务器: {list(mcp_config.keys())}")
    print(f"可用工具: {allowed_tools}")

    # 6. 在 Agent 中使用
    from src.core.claude_agent import ClaudeNativeAgent
    from src.definitions import AgentDefinition
    from src.workspace import WorkspaceConfig, AgentWorkspace

    # 创建使用 MCP 工具的 Agent
    # agent = ClaudeNativeAgent(
    #     definition=agent_def,
    #     workspace=workspace,
    #     tool_registry=tool_registry,
    #     mcp_servers=mcp_config
    # )


# ========== 示例 4: Hooks 机制 ==========


async def example_4_hooks():
    """示例4：使用 Hooks 机制"""

    print("\n" + "=" * 60)
    print("示例 4: Hooks 机制")
    print("=" * 60)

    from src.orchestration.hooks import (
        HooksManager,
        HookEvent,
        CommonHooks,
        create_security_hooks,
    )
    from src.core.claude_agent import ClaudeNativeAgent

    # 1. 创建 Hooks 管理器
    hooks_mgr = HooksManager()

    # 2. 注册自定义 Hook
    @hooks_mgr.register_hook(HookEvent.PRE_TOOL_USE, matcher="stock_api")
    async def validate_stock_ticker(input_data, tool_use_id, context):
        """验证股票代码格式"""
        tool_input = input_data.get("tool_input", {})
        ticker = tool_input.get("ticker", "")

        # 简单的格式验证
        if not ticker or len(ticker) < 6:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "股票代码格式不正确",
                }
            }

        print(f"✅ 股票代码验证通过: {ticker}")
        return {}

    # 3. 使用预定义 Hooks
    hooks_mgr.register_hook(
        HookEvent.PRE_TOOL_USE, "Bash", CommonHooks.block_dangerous_commands
    )

    # 4. 获取配置
    hooks_config = hooks_mgr.get_hooks_config()

    print(f"注册的 Hook 事件: {list(hooks_config.keys())}")

    # 5. 在 Agent 中使用
    # agent = ClaudeNativeAgent(
    #     definition=agent_def,
    #     workspace=workspace,
    #     hooks=hooks_config
    # )

    # 6. 或使用便捷函数
    security_hooks = create_security_hooks()
    print(f"安全 Hooks: {list(security_hooks.keys())}")


# ========== 示例 5: 完整集成 ==========


async def example_5_full_integration():
    """示例5：完整集成示例"""

    print("\n" + "=" * 60)
    print("示例 5: 完整集成（SDK + MCP + Hooks）")
    print("=" * 60)

    from src.core.claude_agent import ClaudeNativeAgent
    from src.definitions import (
        AgentDefinition,
        BackgroundInstruction,
        OutputInstruction,
        UserInstruction,
        LLMConfig,
        AgentExecutionType,
        AgentDomainType,
    )
    from src.workspace import AgentWorkspace, WorkspaceConfig
    from src.tools import ToolRegistry, MCPToolAdapter
    from src.tools.mcp_adapter import mcp_tool
    from src.orchestration.hooks import HooksManager, HookEvent, create_security_hooks
    from src.verification import RuleBasedVerifier
    from src.verification.rule_verifier import JSONFormatRule, RequiredFieldsRule
    from src.definitions import ToolCategory

    # 1. 准备工具
    tool_registry = ToolRegistry()
    mcp_adapter = MCPToolAdapter(tool_registry)

    @mcp_tool(
        tool_id="analyze_stock",
        name="股票分析",
        description="深度分析股票",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "metrics": {"type": "array", "items": {"type": "string"}},
            },
        },
        category=ToolCategory.STOCK_DATA,
    )
    async def analyze_stock(ticker: str, metrics: list) -> dict:
        return {
            "ticker": ticker,
            "analysis": f"分析 {ticker} 的 {len(metrics)} 个指标",
            "recommendation": "持有",
        }

    # 2. 准备 Hooks
    hooks_mgr = HooksManager()

    @hooks_mgr.register_hook(HookEvent.PRE_TOOL_USE, "analyze_stock")
    async def log_analysis(input_data, tool_use_id, context):
        print(f"📊 开始股票分析: {tool_use_id}")
        return {}

    # 3. 准备验证器
    verifier = RuleBasedVerifier(
        [JSONFormatRule(), RequiredFieldsRule(["ticker", "analysis", "recommendation"])]
    )

    # 4. 创建 Agent 定义
    agent_def = AgentDefinition(
        agent_id="full_integration_agent",
        name="完整集成 Agent",
        description="展示所有集成功能的 Agent",
        execution_type=AgentExecutionType.REASONING_EXECUTOR,
        domain_type=AgentDomainType.FINANCIAL_ANALYSIS,
        background_instruction=BackgroundInstruction(
            role_description="综合使用多种工具的智能分析师",
            core_capability="全面分析并给出建议",
            task_context="利用所有可用资源",
        ),
        output_instruction=OutputInstruction(
            format_type="json", format_requirements=["JSON 格式", "包含所有必需字段"]
        ),
        user_instruction=UserInstruction(task_description="进行全面分析"),
        llm_config=LLMConfig(model_name="claude-sonnet-4-20250514", max_iterations=3),
    )

    # 5. 创建工作空间
    workspace_config = WorkspaceConfig(
        base_path="./workspaces", task_id="task_full_integration"
    )
    workspace = AgentWorkspace(workspace_config)

    # 6. 创建 Agent（集成所有功能）
    agent = ClaudeNativeAgent(
        definition=agent_def,
        workspace=workspace,
        tool_registry=tool_registry,
        verifier=verifier,
        mcp_servers=mcp_adapter.get_mcp_server_config(),
        hooks=hooks_mgr.get_hooks_config(),
        use_sdk_execution=True,
    )

    # 7. 运行
    result = await agent.run(
        task_description="分析贵州茅台的投资价值",
        input_data={"ticker": "600519.SH", "metrics": ["PE", "ROE", "growth"]},
    )

    print(f"\n✅ 执行完成")
    print(f"成功: {result['success']}")
    print(f"迭代: {result['iterations']}")
    print(f"验证: {result.get('verification_passed', 'N/A')}")
    print(f"结果: {result.get('result', 'N/A')}")


# ========== 主函数 ==========


async def main():
    """运行所有示例"""

    print("\n" + "🚀 " * 30)
    print("Claude Agent SDK 集成示例")
    print("🚀 " * 30 + "\n")

    try:
        # 运行示例（根据需要选择）
        # await example_1_claude_sdk_client()
        # await example_2_claude_native_agent()
        await example_3_mcp_tools()
        await example_4_hooks()
        # await example_5_full_integration()

        print("\n" + "✅ " * 30)
        print("所有示例运行完成")
        print("✅ " * 30 + "\n")

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

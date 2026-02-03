"""
简单 Agent 示例

展示 Agent Framework 的基本用法：
1. 创建 Agent 定义
2. 设置工作空间
3. 使用真实 LLM 运行 Agent

配置文件: config/app_config.yaml
- 配置 OpenRouter/OpenAI API Key
- 配置模型和参数
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# 确保能导入 src 模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import BaseAgent
from src.definitions import (
    AgentDefinition,
    AgentExecutionType,
    AgentDomainType,
    BackgroundInstruction,
    OutputInstruction,
    UserInstruction,
    ModelConfig,
)
from src.workspace import AgentWorkspace, WorkspaceConfig
from src.tools import ToolRegistry
from src.config import create_llm_client, get_app_config_loader


def create_simple_agent_definition(model_name: str = "qwen-plus") -> AgentDefinition:
    """
    创建简单的 Agent 定义（代码方式）

    Args:
        model_name: 要使用的模型名称
    """
    return AgentDefinition(
        agent_id="simple_demo_agent",
        name="简单演示 Agent",
        description="用于演示基本功能的简单 Agent",
        execution_type=AgentExecutionType.EXECUTOR,
        domain_type=AgentDomainType.GENERAL,
        background_instruction=BackgroundInstruction(
            role_description="你是一个专业的助手，能够回答各种问题并提供有价值的分析。",
            core_capability="你擅长分析问题、提取关键信息，并给出结构化的答案。",
            task_context="在本任务中，你需要根据用户的问题提供详细的分析和建议。",
        ),
        output_instruction=OutputInstruction(
            format_type="json",
            format_requirements=[
                "输出 JSON 格式",
                "包含 answer（答案）、key_points（关键要点列表）、confidence（置信度 0-1）字段",
                "不要使用 markdown 代码块包裹",
            ],
            style_requirements=[
                "回答详细且有深度",
                "保持专业和客观的态度",
                "使用中文回答",
            ],
            output_schema={
                "type": "object",
                "required": ["answer", "key_points", "confidence"],
                "properties": {
                    "answer": {"type": "string", "description": "详细的回答"},
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关键要点列表",
                    },
                    "confidence": {"type": "number", "description": "置信度 0-1"},
                },
            },
        ),
        user_instruction=UserInstruction(
            task_description="请根据输入的问题进行分析并给出回答。",
            tool_references=[],
            context_references=[],
        ),
        llm_config=ModelConfig(
            model_name=model_name, temperature=0.3, max_iterations=3, max_tokens=4096
        ),
    )


async def run_simple_agent(
    question: str = "请分析一下人工智能行业的发展趋势",
    verbose: bool = False,
    model_tier: str = "default",
):
    """
    运行简单 Agent 示例

    Args:
        question: 要回答的问题
        verbose: 是否显示详细输出
        model_tier: 模型层级 (default, light, medium, strong)
    """
    print("=" * 60)
    print("🤖 简单 Agent 示例 - 使用真实 LLM")
    print("=" * 60)

    # 0. 加载配置
    print("\n📋 加载配置...")
    try:
        loader = get_app_config_loader()
        loader.load()  # 加载 config/app_config.yaml
        model_config = loader.get_model_config(model_tier)
        openai_config = loader.get_openai_config()
        model_name = model_config.get("name", "qwen-plus")
        base_url = openai_config.get("base_url", "https://openrouter.ai/api/v1")

        print(f"   模型: {model_name}")
        print(f"   API URL: {base_url}")
        print(f"   可用 tiers: {loader.get_available_tiers()}")
    except Exception as e:
        print(f"   ⚠️ 配置加载失败: {e}")
        print("   使用默认配置...")
        model_name = "qwen-plus"

    # 1. 创建 Agent 定义
    print("\n1️⃣ 创建 Agent 定义...")
    agent_def = create_simple_agent_definition(model_name=model_name)
    print(f"   Agent ID: {agent_def.agent_id}")
    print(f"   名称: {agent_def.name}")

    # 2. 创建工作空间
    print("\n2️⃣ 创建工作空间...")
    workspace_config = WorkspaceConfig(
        base_path="./workspaces/examples",
        task_id=f"simple_demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    )
    workspace = AgentWorkspace(workspace_config)
    print(f"   工作空间路径: {workspace.root}")

    # 3. 创建工具注册表
    print("\n3️⃣ 创建工具注册表...")
    tool_registry = ToolRegistry()
    print(f"   已注册工具数量: {len(tool_registry.list_all())}")

    # 4. 创建真实 LLM 客户端
    print("\n4️⃣ 创建 LLM 客户端...")
    try:
        # 使用 src/config.py 中的 create_llm_client 函数
        unified_client = create_llm_client(tier=model_tier, client_type="langchain")
        langchain_client = unified_client.get_langchain_client()
        print(f"   ✅ LLM 客户端创建成功: {unified_client.model_name}")
    except Exception as e:
        print(f"   ❌ LLM 客户端创建失败: {e}")
        print("   请检查 config/app_config.yaml 中的 API 配置")
        return {"status": "failed", "error": str(e)}

    # 5. 创建 Agent
    print("\n5️⃣ 创建 Agent...")
    try:
        agent = BaseAgent(
            definition=agent_def,
            workspace=workspace,
            tool_registry=tool_registry,
            llm_client=langchain_client,
        )
        print(f"   ✅ Agent 创建成功")
    except ImportError as e:
        print(f"   ⚠️ LangGraph 未安装，使用简化模式: {e}")
        agent = None
    except Exception as e:
        print(f"   ❌ Agent 创建失败: {e}")
        if verbose:
            import traceback

            traceback.print_exc()
        return {"status": "failed", "error": str(e)}

    # 6. 运行 Agent
    print("\n6️⃣ 运行 Agent...")
    print(f"   📝 问题: {question}")
    print("   ⏳ 正在处理...")

    if agent:
        try:
            result = await agent.run(
                task_description=question, input_data={"question": question}
            )

            print(f"\n   ✅ 执行结果: {'成功' if result.get('success') else '失败'}")
            print(f"   📊 迭代次数: {result.get('iterations', 'N/A')}")

            if result.get("result"):
                print("\n" + "-" * 40)
                print("📤 Agent 输出:")
                print("-" * 40)
                output = result["result"]
                if isinstance(output, dict):
                    print(json.dumps(output, ensure_ascii=False, indent=2))
                else:
                    print(output)

            if verbose and result.get("verification_feedback"):
                print(f"\n   验证反馈: {result['verification_feedback']}")

        except Exception as e:
            print(f"   ❌ 执行失败: {e}")
            if verbose:
                import traceback

                traceback.print_exc()
            return {"status": "failed", "error": str(e)}
    else:
        # 直接使用 LangChain 客户端演示
        print("   [直接调用 LLM]")
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=agent_def.build_system_prompt()),
            HumanMessage(content=question),
        ]

        response = await langchain_client.ainvoke(messages)
        print(f"\n📤 LLM 响应:\n{response.content}")

    print("\n" + "=" * 60)
    print("✅ 示例完成")
    print("=" * 60)

    return {"status": "success"}


async def run_from_yaml(verbose: bool = False, model_tier: str = "default"):
    """从 YAML 文件加载 Agent 定义并运行"""
    print("\n" + "=" * 60)
    print("📄 从 YAML 加载 Agent 定义")
    print("=" * 60)

    yaml_path = Path(__file__).parent / "agents" / "simple_analyst.yaml"

    if not yaml_path.exists():
        print(f"   ⚠️ YAML 文件不存在: {yaml_path}")
        return

    print(f"\n📂 加载 YAML: {yaml_path}")

    try:
        agent_def = AgentDefinition.from_yaml_file(str(yaml_path))
        print(f"   ✅ Agent ID: {agent_def.agent_id}")
        print(f"   ✅ 名称: {agent_def.name}")
        print(f"   ✅ 描述: {agent_def.description}")
        print(f"   ✅ LLM 配置: {agent_def.llm_config.model_name}")

        # 显示 Prompt 结构
        print("\n📝 System Prompt 预览:")
        system_prompt = agent_def.build_system_prompt()
        # 只显示前 500 字符
        preview = (
            system_prompt[:500] + "..." if len(system_prompt) > 500 else system_prompt
        )
        print(f"   {preview}")

    except Exception as e:
        print(f"   ❌ 加载失败: {e}")
        if verbose:
            import traceback

            traceback.print_exc()


async def run_example(
    verbose: bool = False,
    question: str = "请分析一下人工智能行业的发展趋势，包括主要技术方向、市场前景和挑战。",
    model_tier: str = "default",
):
    """
    示例入口

    Args:
        verbose: 是否显示详细输出
        question: 要回答的问题
        model_tier: 模型层级
    """
    await run_simple_agent(question=question, verbose=verbose, model_tier=model_tier)
    await run_from_yaml(verbose=verbose, model_tier=model_tier)
    return {"status": "success"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="简单 Agent 示例")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细输出")
    parser.add_argument(
        "-q",
        "--question",
        type=str,
        default="请分析一下人工智能行业的发展趋势，包括主要技术方向、市场前景和挑战。",
        help="要回答的问题",
    )
    parser.add_argument(
        "-t",
        "--tier",
        type=str,
        default="default",
        choices=["default", "light", "medium", "strong"],
        help="模型层级",
    )

    args = parser.parse_args()

    asyncio.run(
        run_example(verbose=args.verbose, question=args.question, model_tier=args.tier)
    )

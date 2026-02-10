#!/usr/bin/env python3
"""
执行已生成的工作流

运行方式:
    uv run python examples/run_workflow.py <workflow_json_path> [checkpoint_json_path]

示例:
    uv run python examples/run_workflow.py workspaces/interactive_builder_demo/final_workflow.json workspaces/interactive_builder_demo/iterations/ckpt_20260201_183807_01a116.json
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import AppConfigLoader, create_qveris_adapter
from src.tools.registry import ToolRegistry
from src.tools.builtin import register_builtin_tools
from src.registry import AgentRegistry
from src.definitions import AgentDefinition, WorkflowDefinition
from src.orchestration import WorkflowEngine


async def run_workflow(
    workflow_path: str, checkpoint_path: str = None, task_input: dict = None
):
    """执行工作流"""
    print("=" * 60)
    print("  执行工作流")
    print("=" * 60)

    # 初始化组件
    print("\n📦 初始化组件...")

    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)

    # 注册 QVeris 远程工具（从配置文件加载 API Key）
    qveris_adapter = create_qveris_adapter(tool_registry)
    if qveris_adapter:
        qveris_adapter.register_meta_tools()
        print("   ✅ QVeris 远程工具已注册（API Key 已配置）")
    else:
        print("   ⚠️ QVeris 未启用或配置错误")

    agent_registry = AgentRegistry()

    config_loader = AppConfigLoader()
    llm_client = config_loader.create_llm_client(tier="default")
    print(f"   ✅ LLM 客户端已创建")

    # 加载工作流定义
    print(f"\n📋 加载工作流: {workflow_path}")
    with open(workflow_path, "r", encoding="utf-8") as f:
        workflow_data = json.load(f)

    workflow = WorkflowDefinition(**workflow_data)
    print(f"   工作流 ID: {workflow.workflow_id}")
    print(f"   名称: {workflow.name}")
    print(f"   节点数: {len(workflow.nodes)}")

    # 如果提供了检查点，加载智能体定义
    if checkpoint_path:
        print(f"\n📦 加载智能体定义: {checkpoint_path}")
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            checkpoint_data = json.load(f)

        draft_agents = checkpoint_data.get("state", {}).get("draft_agents", [])
        print(f"   找到 {len(draft_agents)} 个智能体定义")

        for agent_data in draft_agents:
            try:
                agent_def = AgentDefinition(**agent_data)
                agent_registry.register_definition(agent_def)
                print(f"   ✅ 注册智能体: {agent_def.agent_id}")
            except Exception as e:
                print(
                    f"   ⚠️ 注册智能体失败 ({agent_data.get('agent_id', 'unknown')}): {e}"
                )

    # 设置工作空间
    workspace_base = Path("workspaces/workflow_execution")
    workspace_base.mkdir(parents=True, exist_ok=True)

    # 创建工作流引擎
    print("\n🔧 创建工作流引擎...")
    engine = WorkflowEngine(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        llm_client=llm_client,
        workspace_base_path=str(workspace_base),
    )

    # 默认任务输入
    if task_input is None:
        task_input = {
            "task": "分析原油类LOF基金下周走势",
            "target": "原油类LOF",
            "analysis_type": "forecast",
        }

    print(f"\n📝 任务输入: {json.dumps(task_input, ensure_ascii=False, indent=2)}")

    # 执行工作流
    print("\n🚀 开始执行工作流...")
    print("-" * 60)

    try:
        result = await engine.execute(
            workflow_definition=workflow,
            initial_context=task_input,
        )

        print("\n" + "=" * 60)
        print("  执行完成！")
        print("=" * 60)

        print(f"\n📊 执行结果:")
        print(
            f"   状态: {result.status.value if hasattr(result.status, 'value') else result.status}"
        )
        print(f"   耗时: {result.total_duration_ms:.2f}ms")

        # 显示节点执行结果
        if result.node_results:
            print("\n📋 节点执行结果:")
            for node_id, node_result in result.node_results.items():
                status_icon = "✅" if node_result.status == "success" else "❌"
                print(f"   {status_icon} {node_id}")

        # 保存结果
        result_path = workspace_base / f"{workflow.workflow_id}_result.json"
        result_dict = result.to_dict() if hasattr(result, "to_dict") else result
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n💾 结果已保存: {result_path}")

        return result

    except Exception as e:
        print(f"\n❌ 执行失败: {e}")
        import traceback

        traceback.print_exc()
        return None


async def main():
    """主函数"""
    if len(sys.argv) < 2:
        print(
            "用法: uv run python examples/run_workflow.py <workflow_json_path> [checkpoint_json_path]"
        )
        print("\n示例:")
        print(
            "  uv run python examples/run_workflow.py workspaces/interactive_builder_demo/final_workflow.json workspaces/interactive_builder_demo/iterations/ckpt_20260201_183807_01a116.json"
        )
        sys.exit(1)

    workflow_path = sys.argv[1]
    checkpoint_path = sys.argv[2] if len(sys.argv) > 2 else None

    await run_workflow(workflow_path, checkpoint_path)


if __name__ == "__main__":
    asyncio.run(main())

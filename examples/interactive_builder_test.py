#!/usr/bin/env python3
"""
交互式工作流构建器测试示例

演示如何使用 InteractiveWorkflowBuilder 边生成边调整工作流。

运行方式:
    uv run python examples/interactive_builder_test.py

功能演示:
1. 启动交互式会话
2. 审核和修改规划方案
3. 逐步生成 Agent 并支持调整
4. 组装工作流并添加数据引用
5. 检查点和回滚
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import AppConfigLoader, create_llm_client
from src.tools.registry import ToolRegistry
from src.tools.builtin import register_builtin_tools
from src.tools.qveris_adapter import QVerisToolAdapter
from src.registry import AgentRegistry
from src.evolution import (
    MetaAgent,
    InteractiveWorkflowBuilder,
    CLIInteractionCallback,
    InteractionLevel,
)


class InteractiveBuilderDemo:
    """交互式构建器演示"""

    def __init__(self):
        self.tool_registry = ToolRegistry()
        self.agent_registry = AgentRegistry()
        self.llm_client = None
        self.meta_agent = None
        self.builder = None

        # 工作空间
        self.workspace_path = Path("workspaces/interactive_builder_demo")
        self.workspace_path.mkdir(parents=True, exist_ok=True)

    async def initialize(self):
        """初始化组件"""
        print("\n" + "=" * 60)
        print("  交互式工作流构建器演示")
        print("=" * 60)

        print("\n📦 初始化组件...")
        print("-" * 50)

        # 注册内置工具
        register_builtin_tools(self.tool_registry)

        # 注册 QVeris 远程工具
        qveris_adapter = QVerisToolAdapter(self.tool_registry)
        qveris_adapter.register_meta_tools()
        print("   ✅ QVeris 远程工具已注册 (qveris_search_tools, qveris_execute_tool)")

        # 创建 LLM 客户端
        config_loader = AppConfigLoader()
        self.llm_client = config_loader.create_llm_client(tier="default")
        print(
            f"   ✅ LLM 客户端: {config_loader.get_models_config().get('model_name', 'unknown')}"
        )

        # 创建 MetaAgent
        self.meta_agent = MetaAgent(
            llm_client=self.llm_client,
            agent_registry=self.agent_registry,
            tool_registry=self.tool_registry,
        )
        print("   ✅ MetaAgent 创建成功")

        # 创建交互式构建器
        self.builder = InteractiveWorkflowBuilder(
            meta_agent=self.meta_agent,
            callback=CLIInteractionCallback(use_colors=True),
            storage_path=self.workspace_path,
            max_iterations_per_step=3,
        )
        print("   ✅ InteractiveWorkflowBuilder 创建成功")

    async def run_demo(self, task: str, interaction_level: str = "moderate"):
        """运行演示"""
        print("\n" + "=" * 60)
        print("  启动交互式构建会话")
        print("=" * 60)

        print(f"\n📝 任务: {task}")
        print(f"📊 交互级别: {interaction_level}")
        print("\n" + "-" * 60)
        print("提示: 在每个阶段，您可以:")
        print("  - 批准当前生成的内容")
        print("  - 修改或要求重新生成")
        print("  - 添加数据引用 (context_refs)")
        print("  - 回滚到之前的检查点")
        print("-" * 60)

        # 转换交互级别
        level_map = {
            "minimal": InteractionLevel.MINIMAL,
            "moderate": InteractionLevel.MODERATE,
            "comprehensive": InteractionLevel.COMPREHENSIVE,
        }
        level = level_map.get(interaction_level, InteractionLevel.MODERATE)

        try:
            # 启动交互式会话
            workflow = await self.builder.start_interactive_session(
                task_description=task,
                interaction_level=level,
            )

            print("\n" + "=" * 60)
            print("  构建完成！")
            print("=" * 60)

            # 显示结果
            self._display_result(workflow)

            # 显示会话摘要
            self._display_session_summary()

            return workflow

        except asyncio.CancelledError:
            print("\n⚠️ 会话已取消")
            return None
        except Exception as e:
            print(f"\n❌ 构建失败: {e}")
            import traceback

            traceback.print_exc()
            return None

    def _display_result(self, workflow):
        """显示构建结果"""
        print("\n📋 工作流定义:")
        print(f"   ID: {workflow.workflow_id}")
        print(f"   名称: {workflow.name}")
        print(f"   描述: {workflow.description}")
        print(f"   节点数: {len(workflow.nodes)}")
        print(f"   边数: {len(workflow.edges)}")

        print("\n📦 节点列表:")
        for node in workflow.nodes:
            deps = node.dependencies if node.dependencies else []
            refs = node.context_refs if node.context_refs else []

            print(f"   [{node.node_type.value}] {node.node_id}: {node.name}")
            if node.agent_id:
                print(f"        Agent: {node.agent_id}")
            if deps:
                print(f"        依赖: {deps}")
            if refs:
                print(f"        数据引用: {refs}")

        print("\n🔗 执行流程:")
        for edge in workflow.edges:
            print(f"   {edge.from_node} → {edge.to_node}")

        # 保存工作流
        output_path = self.workspace_path / "final_workflow.json"
        import json

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                (
                    workflow.model_dump()
                    if hasattr(workflow, "model_dump")
                    else vars(workflow)
                ),
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        print(f"\n💾 工作流已保存: {output_path}")

    def _display_session_summary(self):
        """显示会话摘要"""
        summary = self.builder.get_session_summary()

        print("\n📊 会话摘要:")
        print(f"   会话 ID: {summary['session_id']}")
        print(f"   Agent 数量: {summary['agents_created']}")
        print(f"   总迭代次数: {summary['total_iterations']}")
        print(f"   检查点数量: {summary['checkpoints']}")

        # 显示迭代历史
        iterations = summary["history"]["iterations"]
        if iterations:
            print("\n📜 迭代历史 (最近 5 条):")
            for record in iterations[-5:]:
                action_emoji = {
                    "approve": "✅",
                    "modify": "✏️",
                    "regenerate": "🔄",
                    "skip": "⏭️",
                    "rollback": "⏪",
                    "add_context_ref": "📎",
                }.get(record["action"], "•")

                print(f"   {action_emoji} [{record['stage']}] {record['action']}")


async def main():
    """主函数"""
    demo = InteractiveBuilderDemo()
    await demo.initialize()

    # 默认任务
    default_task = "对比亚迪进行全面的投资分析，包括数据收集、财务分析和报告生成"

    # 获取用户输入
    print("\n" + "-" * 60)
    task = input(f"请输入任务描述 (直接回车使用默认任务):\n> ").strip()
    if not task:
        task = default_task
        print(f"使用默认任务: {task}")

    # 选择交互级别
    print("\n交互级别:")
    print("  [1] minimal - 只在关键节点征求意见")
    print("  [2] moderate - 每个 Agent 生成后征求意见 (推荐)")
    print("  [3] comprehensive - 每步都征求意见")

    level_choice = input("请选择 [1-3, 默认 2]: ").strip()
    level_map = {"1": "minimal", "2": "moderate", "3": "comprehensive"}
    level = level_map.get(level_choice, "moderate")

    # 运行演示
    await demo.run_demo(task, level)


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
交互式工作流构建器自动化测试

使用模拟的用户回调来自动化测试 InteractiveWorkflowBuilder 的完整流程。

运行方式:
    uv run python examples/interactive_builder_auto_test.py
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import AppConfigLoader
from src.tools.registry import ToolRegistry
from src.tools.builtin import register_builtin_tools
from src.tools.qveris_adapter import QVerisToolAdapter
from src.registry import AgentRegistry
from src.evolution import (
    MetaAgent,
    InteractiveWorkflowBuilder,
    InteractionStage,
    InteractionLevel,
    UserAction,
    UserFeedback,
)


class AutoApproveCallback:
    """
    自动批准回调 - 用于自动化测试

    自动批准所有请求，模拟用户快速通过流程。
    """

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.interactions = []

    async def request_approval(
        self,
        stage: InteractionStage,
        content: Any,
        options: List[UserAction],
        context: Optional[Dict[str, Any]] = None,
    ) -> UserFeedback:
        """自动批准所有请求"""

        if self.verbose:
            print(f"\n📋 [{stage.value}] 自动批准请求")
            if isinstance(content, dict):
                if "plan" in content:
                    print(
                        f"   规划: {len(content['plan'].get('agent_specs', []))} 个智能体"
                    )
                elif "agent_definition" in content:
                    agent = content["agent_definition"]
                    print(
                        f"   智能体: {agent.get('name', agent.get('agent_id', 'unknown'))}"
                    )
                elif "workflow" in content:
                    workflow = content["workflow"]
                    print(
                        f"   工作流: {workflow.get('name', workflow.get('workflow_id', 'unknown'))}"
                    )

        # 记录交互
        self.interactions.append(
            {
                "stage": stage.value,
                "action": "approve",
                "content_type": type(content).__name__,
            }
        )

        # 始终返回批准
        return UserFeedback(action=UserAction.APPROVE)

    async def notify_progress(
        self,
        stage: InteractionStage,
        progress: float,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """显示进度"""
        if self.verbose:
            bar_width = 20
            filled = int(bar_width * progress)
            bar = "█" * filled + "░" * (bar_width - filled)
            print(f"\r   [{bar}] {progress*100:.0f}% {message}", end="")
            if progress >= 1.0:
                print()

    async def request_input(
        self,
        prompt: str,
        input_type: str,
        options: Optional[List[str]] = None,
        default: Optional[Any] = None,
    ) -> Any:
        """返回默认值"""
        if self.verbose:
            print(f"   输入请求: {prompt} -> 使用默认值: {default}")
        return default

    async def display_message(
        self,
        message: str,
        level: str = "info",
    ) -> None:
        """显示消息"""
        if self.verbose:
            level_emoji = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "success": "✅"}
            print(f"   {level_emoji.get(level, '•')} {message}")

    async def display_diff(
        self,
        before: Dict[str, Any],
        after: Dict[str, Any],
        title: str = "Changes",
    ) -> None:
        """显示差异"""
        if self.verbose:
            print(f"   📊 差异: {title}")


async def run_auto_test():
    """运行自动化测试"""
    print("=" * 60)
    print("  InteractiveWorkflowBuilder 自动化测试")
    print("=" * 60)

    # 初始化组件
    print("\n📦 初始化组件...")

    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)

    # 注册 QVeris 远程工具
    qveris_adapter = QVerisToolAdapter(tool_registry)
    qveris_adapter.register_meta_tools()

    agent_registry = AgentRegistry()

    config_loader = AppConfigLoader()
    llm_client = config_loader.create_llm_client(tier="default")

    meta_agent = MetaAgent(
        llm_client=llm_client,
        agent_registry=agent_registry,
        tool_registry=tool_registry,
    )

    # 创建自动批准回调
    callback = AutoApproveCallback(verbose=True)

    # 创建构建器
    workspace_path = Path("workspaces/interactive_builder_auto_test")
    workspace_path.mkdir(parents=True, exist_ok=True)

    builder = InteractiveWorkflowBuilder(
        meta_agent=meta_agent,
        callback=callback,
        storage_path=workspace_path,
        max_iterations_per_step=2,
    )

    print("   ✅ 组件初始化完成")

    # 运行交互式会话
    print("\n" + "=" * 60)
    print("  开始交互式构建会话 (自动批准模式)")
    print("=" * 60)

    task = "对比亚迪进行投资分析，包括数据收集、财务分析和报告生成"
    print(f"\n📝 任务: {task}")

    try:
        workflow = await builder.start_interactive_session(
            task_description=task,
            interaction_level=InteractionLevel.MODERATE,
        )

        print("\n" + "=" * 60)
        print("  测试结果")
        print("=" * 60)

        # 显示结果
        print(f"\n✅ 工作流构建成功!")
        print(f"   ID: {workflow.workflow_id}")
        print(f"   名称: {workflow.name}")
        print(f"   节点数: {len(workflow.nodes)}")
        print(f"   边数: {len(workflow.edges)}")

        # 显示节点详情
        print("\n📦 节点列表:")
        for node in workflow.nodes:
            refs = node.context_refs if node.context_refs else []
            print(f"   - [{node.node_type.value}] {node.node_id}")
            if node.agent_id:
                print(f"     智能体: {node.agent_id}")
            if refs:
                print(f"     数据引用: {refs}")

        # 显示交互统计
        print(f"\n📊 交互统计:")
        print(f"   总交互次数: {len(callback.interactions)}")

        stage_counts = {}
        for interaction in callback.interactions:
            stage = interaction["stage"]
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

        for stage, count in stage_counts.items():
            print(f"   - {stage}: {count} 次")

        # 显示会话摘要
        summary = builder.get_session_summary()
        print(f"\n📜 会话摘要:")
        print(f"   会话 ID: {summary['session_id']}")
        print(f"   智能体数量: {summary['agents_created']}")
        print(f"   迭代次数: {summary['total_iterations']}")
        print(f"   检查点数: {summary['checkpoints']}")

        # 保存结果
        import json

        output_path = workspace_path / "test_result.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "workflow": (
                        workflow.model_dump() if hasattr(workflow, "model_dump") else {}
                    ),
                    "summary": summary,
                    "interactions": callback.interactions,
                },
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        print(f"\n💾 结果已保存: {output_path}")

        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """主函数"""
    success = await run_auto_test()

    print("\n" + "=" * 60)
    if success:
        print("  ✅ 自动化测试通过!")
    else:
        print("  ❌ 自动化测试失败!")
    print("=" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

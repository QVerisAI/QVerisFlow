"""
工作流示例

展示多 Agent 协作工作流：
1. 工作流定义
2. 工作流引擎
3. 节点执行和数据传递

配置文件: config/app_config.yaml
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.definitions import WorkflowDefinition
from src.orchestration import WorkflowEngine
from src.registry import AgentRegistry
from src.tools import ToolRegistry, register_builtin_tools
from src.workspace import AgentWorkspace, WorkspaceConfig
from src.config import create_llm_client, create_qveris_adapter, get_qveris_config
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_simple_workflow() -> WorkflowDefinition:
    """创建简单工作流定义（代码方式）"""
    from src.definitions.workflow_definition import (
        WorkflowDefinition,
        WorkflowNode,
        WorkflowEdge,
        NodeType,
    )

    return WorkflowDefinition(
        workflow_id="simple_workflow",
        name="简单工作流",
        description="演示基本工作流功能",
        version="1.0.0",
        entry_node="start",
        exit_nodes=["end"],
        nodes=[
            WorkflowNode(
                node_id="start",
                name="开始",
                node_type=NodeType.START,
            ),
            WorkflowNode(
                node_id="process",
                name="处理",
                node_type=NodeType.AGENT,
                agent_id="simple_analyst",
                dependencies=["start"],
                timeout=60,
            ),
            WorkflowNode(
                node_id="end",
                name="结束",
                node_type=NodeType.END,
                dependencies=["process"],
            ),
        ],
        edges=[
            WorkflowEdge(from_node="start", to_node="process"),
            WorkflowEdge(from_node="process", to_node="end"),
        ],
    )


async def demonstrate_workflow_definition(verbose: bool = False):
    """演示工作流定义"""
    print("\n1. 创建工作流定义")
    print("-" * 40)

    # 代码方式创建
    workflow = create_simple_workflow()
    print(f"   工作流 ID: {workflow.workflow_id}")
    print(f"   名称: {workflow.name}")
    print(f"   节点数: {len(workflow.nodes)}")
    print(f"   边数: {len(workflow.edges)}")

    # 从 YAML 加载
    yaml_path = Path(__file__).parent / "workflows" / "analysis_workflow.yaml"
    if yaml_path.exists():
        print(f"\n   从 YAML 加载工作流: {yaml_path.name}")
        try:
            yaml_workflow = WorkflowDefinition.from_yaml_file(str(yaml_path))
            print(f"   工作流 ID: {yaml_workflow.workflow_id}")
            print(f"   节点: {[n.name for n in yaml_workflow.nodes]}")
        except Exception as e:
            print(f"   加载失败: {e}")


async def demonstrate_workflow_execution(
    verbose: bool = False, model_tier: str = "default"
):
    """演示工作流执行"""
    print("\n2. 工作流执行")
    print("-" * 40)

    # 创建真实 LLM 客户端
    print("   创建 LLM 客户端...")
    try:
        unified_client = create_llm_client(tier=model_tier, client_type="langchain")
        llm_client = unified_client.get_langchain_client()
        print(f"   ✅ LLM 客户端: {unified_client.model_name}")
    except Exception as e:
        print(f"   ❌ LLM 客户端创建失败: {e}")
        print("   请检查 config/app_config.yaml 中的 API 配置")
        return

    # 创建工具注册表并注册内置工具
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)
    print(f"   ✅ 内置工具已注册: {len(tool_registry.list_all())} 个")

    # 从配置文件注册 QVeris 远程工具
    qveris_config = get_qveris_config()
    if qveris_config.get("enabled", False):
        try:
            qveris_adapter = create_qveris_adapter(tool_registry)
            if qveris_adapter:
                qveris_adapter.register_meta_tools()
                print("   ✅ QVeris 远程工具已注册")
            else:
                print("   ⚠️ QVeris 适配器创建失败")
        except Exception as e:
            logger.warning(f"QVeris 工具注册失败: {e}")
            print(f"   ⚠️ QVeris 工具注册失败: {e}")
    else:
        print("   ℹ️ QVeris 未启用（在 config/app_config.yaml 中配置）")

    agent_registry = AgentRegistry()

    # 注册 Agent（从 YAML 目录）
    agents_dir = Path(__file__).parent / "agents"
    if agents_dir.exists():
        try:
            agent_registry.register_from_yaml(str(agents_dir))
            agent_ids = [a["agent_id"] for a in agent_registry.list_all()]
            print(f"   已注册 Agent: {agent_ids}")
        except Exception as e:
            print(f"   注册 Agent 失败: {e}")

    # 加载工作流
    workflow = create_simple_workflow()

    # 创建工作流引擎
    try:
        engine = WorkflowEngine(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            llm_client=llm_client,
            workspace_base_path="./workspaces/workflow_example",
        )
        print("   工作流引擎创建成功")

        # 执行工作流
        print("\n   执行工作流...")
        result = await engine.execute(
            workflow_definition=workflow,
            initial_context={
                "task": "分析泡泡玛特2026年1月24日的投资价值和机会",
                "company": "泡泡玛特",
                "ticker": "09992.HK",
            },
        )

        print(f"   执行状态: {result.status}")
        print(f"   总耗时: {result.total_duration_ms}ms")

        if verbose:
            print("\n   节点结果:")
            for node_id, node_result in result.node_results.items():
                print(f"     - {node_id}: {node_result.status}")

    except ImportError as e:
        print(f"   注意: 工作流引擎需要完整依赖")
        if verbose:
            print(f"   详情: {e}")
    except Exception as e:
        print(f"   执行失败: {e}")
        if verbose:
            import traceback

            traceback.print_exc()


async def demonstrate_workflow_visualization(verbose: bool = False):
    """演示工作流可视化"""
    print("\n3. 工作流结构")
    print("-" * 40)

    workflow = create_simple_workflow()

    # 打印工作流结构
    print("\n   节点:")
    for node in workflow.nodes:
        deps = f" (依赖: {node.dependencies})" if node.dependencies else ""
        print(f"     [{node.node_type.value}] {node.name}{deps}")

    print("\n   边:")
    for edge in workflow.edges:
        print(f"     {edge.from_node} -> {edge.to_node}")

    # 生成 Mermaid 图
    print("\n   Mermaid 图:")
    print("   ```mermaid")
    print("   graph TD")
    for edge in workflow.edges:
        print(f"       {edge.from_node} --> {edge.to_node}")
    print("   ```")


async def run_example(verbose: bool = False, model_tier: str = "default"):
    """示例入口"""
    print("=" * 50)
    print("工作流示例")
    print("=" * 50)

    await demonstrate_workflow_definition(verbose)
    await demonstrate_workflow_visualization(verbose)
    await demonstrate_workflow_execution(verbose, model_tier)

    print("\n" + "=" * 50)
    print("示例完成")
    print("=" * 50)

    return {"status": "success"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="工作流示例")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细输出")
    parser.add_argument(
        "-t",
        "--tier",
        type=str,
        default="default",
        choices=["default", "light", "medium", "strong"],
        help="模型层级",
    )

    args = parser.parse_args()
    asyncio.run(run_example(verbose=args.verbose, model_tier=args.tier))

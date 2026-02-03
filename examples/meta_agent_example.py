"""
Meta Agent 示例

展示智能演化功能：
1. 使用 MetaAgent 动态创建 Agent
2. 生成工作流
3. 监控 Agent 性能

配置文件: config/app_config.yaml
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.evolution import MetaAgent
from src.registry import AgentRegistry
from src.tools import ToolRegistry
from src.tools.builtin import register_builtin_tools
from src.definitions import AgentDefinition, AgentExecutionType, AgentDomainType
from src.config import create_llm_client


async def demonstrate_create_agent(verbose: bool = False, model_tier: str = "default"):
    """演示使用 MetaAgent 创建 Agent"""
    print("\n1. 使用 MetaAgent 创建 Agent")
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

    agent_registry = AgentRegistry()
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)

    # 加载现有 Agent 作为参考
    agents_dir = Path(__file__).parent / "agents"
    if agents_dir.exists():
        try:
            agent_registry.register_from_yaml(str(agents_dir))
            agent_ids = [a["agent_id"] for a in agent_registry.list_all()]
            print(f"   已加载参考 Agent: {agent_ids}")
        except Exception as e:
            print(f"   加载参考 Agent 失败: {e}")

    try:
        # 创建 MetaAgent
        meta_agent = MetaAgent(
            llm_client=llm_client,
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            temperature=0.3,
            max_tokens=4000,
        )
        print("   MetaAgent 创建成功")

        # 根据需求创建新 Agent
        print("\n   创建新 Agent...")
        new_agent = await meta_agent.create_agent(
            task_description="""
            我需要一个专门分析新能源汽车行业的 Agent，它应该能够：
            1. 分析产业链上下游公司
            2. 跟踪行业政策变化
            3. 对比主要公司的竞争力
            4. 预测行业发展趋势
            
            输出应该是结构化的行业分析报告。
            """,
            reference_agents=["simple_analyst"],
            tools=["news_search", "financial_data"],
            constraints={
                "max_iterations": 5,
                "domain": AgentDomainType.FINANCIAL_ANALYSIS.value,
            },
        )

        print(f"   创建成功: {new_agent.name}")
        print(f"   Agent ID: {new_agent.agent_id}")

        if verbose:
            print(f"\n   Agent 定义:")
            print(f"     执行类型: {new_agent.execution_type}")
            print(f"     领域类型: {new_agent.domain_type}")

    except Exception as e:
        print(f"   创建失败: {e}")
        if verbose:
            import traceback

            traceback.print_exc()


async def demonstrate_generate_workflow(
    verbose: bool = False, model_tier: str = "default"
):
    """演示使用 MetaAgent 生成工作流"""
    print("\n2. 使用 MetaAgent 生成工作流")
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

    agent_registry = AgentRegistry()
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)

    # 加载现有 Agent
    agents_dir = Path(__file__).parent / "agents"
    if agents_dir.exists():
        try:
            agent_registry.register_from_yaml(str(agents_dir))
        except Exception:
            pass

    try:
        meta_agent = MetaAgent(
            llm_client=llm_client,
            agent_registry=agent_registry,
            tool_registry=tool_registry,
        )

        # 生成工作流
        print("   生成工作流...")
        agent_ids = [a["agent_id"] for a in agent_registry.list_all()]
        workflow = await meta_agent.generate_workflow(
            task_description="端到端的股票分析报告生成流程",
            available_agents=agent_ids,
        )

        print(f"   工作流名称: {workflow.name}")
        print(f"   节点数量: {len(workflow.nodes)}")

        if verbose:
            print("\n   节点列表:")
            for node in workflow.nodes:
                print(f"     - {node.name} ({node.node_type.value})")

    except Exception as e:
        print(f"   生成失败: {e}")
        if verbose:
            import traceback

            traceback.print_exc()


async def demonstrate_performance_monitoring(verbose: bool = False):
    """演示 Agent 性能监控"""
    print("\n3. Agent 性能监控")
    print("-" * 40)

    try:
        from src.evolution import (
            AgentPerformanceMonitor,
            AlertRule,
            AlertSeverity,
            LogNotificationChannel,
        )

        # 创建监控器
        monitor = AgentPerformanceMonitor()

        # 添加通知渠道（使用正确的方法名）
        monitor.add_notification_channel("log", LogNotificationChannel())

        # 注册告警规则（使用正确的方法名）
        monitor.add_alert_rule(
            AlertRule(
                rule_id="low_success_rate",
                name="低成功率告警",
                condition="success_rate < 0.8",
                severity=AlertSeverity.WARNING,
                cooldown_minutes=1,
            )
        )

        print("   监控器创建成功")
        print("   已注册告警规则: low_success_rate")

        # 模拟记录执行
        agent_id = "demo_agent"
        print(f"\n   模拟 {agent_id} 执行...")

        for i in range(5):
            success = i < 3  # 60% 成功率
            await monitor.record_execution(
                agent_id=agent_id,
                success=success,
                duration_ms=2000 + i * 500,
                iterations=3,
                verification_score=0.9 if success else 0.5,
            )

        # 收集指标
        metrics = await monitor.collect_metrics(agent_id)
        print(f"\n   收集到的指标:")
        print(f"     成功率: {metrics.success_rate:.2%}")
        print(f"     平均执行时间: {metrics.avg_duration_ms:.0f}ms")
        print(f"     总执行次数: {metrics.total_executions}")

        # 检查告警
        alerts = await monitor.check_alerts(agent_id)
        if alerts:
            print(f"\n   触发的告警:")
            for alert in alerts:
                print(f"     [{alert.severity.value}] {alert.rule.name}")

    except ImportError as e:
        print(f"   需要完整依赖: {e}")
    except Exception as e:
        print(f"   监控失败: {e}")
        if verbose:
            import traceback

            traceback.print_exc()


async def run_example(verbose: bool = False, model_tier: str = "default"):
    """示例入口"""
    print("=" * 50)
    print("Meta Agent 示例")
    print("=" * 50)

    await demonstrate_create_agent(verbose, model_tier)
    await demonstrate_generate_workflow(verbose, model_tier)
    await demonstrate_performance_monitoring(verbose)

    print("\n" + "=" * 50)
    print("示例完成")
    print("=" * 50)

    return {"status": "success"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Meta Agent 示例")
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

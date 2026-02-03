"""
A/B 测试示例

展示智能演化的 A/B 测试功能：
1. 创建实验
2. 分配变体
3. 记录指标
4. 分析结果

配置文件: config/app_config.yaml
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.evolution import (
    ABTestingFramework,
    PromptOptimizer,
    VersionControl,
)
from src.config import create_llm_client


async def demonstrate_ab_testing(verbose: bool = False):
    """演示 A/B 测试"""
    print("\n1. A/B 测试")
    print("-" * 40)

    try:
        # 创建 A/B 测试框架
        ab_framework = ABTestingFramework()
        print("   A/B 测试框架创建成功")

        # 创建实验
        experiment = ab_framework.create_experiment(
            experiment_id="prompt_v1_vs_v2",
            name="Prompt V1 vs V2",
            description="测试优化后的 Prompt 效果",
            variants={"v1": 0.5, "v2": 0.5},
            metrics=["quality_score", "latency"],
        )
        print(f"\n   创建实验: {experiment.name}")
        print(f"   实验 ID: {experiment.experiment_id}")
        print(f"   变体: v1 (50%), v2 (50%)")

        # 启动实验
        ab_framework.start_experiment(experiment.experiment_id)
        print("   实验已启动")

        # 模拟用户测试
        print("\n   模拟用户测试:")
        test_users = ["user_001", "user_002", "user_003", "user_004", "user_005"]

        for user_id in test_users:
            # 获取分配的变体
            variant = ab_framework.get_variant(experiment.experiment_id, user_id)

            # 模拟执行
            start_time = time.time()
            await asyncio.sleep(0.1)  # 模拟延迟
            latency = time.time() - start_time

            # 模拟质量评分（v2 效果更好）
            quality = 0.85 if variant == "v2" else 0.75

            # 记录指标
            ab_framework.record_metric(
                experiment.experiment_id, user_id, "latency", latency
            )
            ab_framework.record_metric(
                experiment.experiment_id, user_id, "quality_score", quality
            )

            # 记录转化
            ab_framework.record_conversion(experiment.experiment_id, user_id)

            print(f"     {user_id}: 变体={variant}, 质量={quality:.2f}")

        # 获取结果
        print("\n   实验结果:")
        results = ab_framework.get_results(experiment.experiment_id)

        # results 是一个 dict，包含 variants 和 analysis
        if "variants" in results:
            for variant_id, variant_data in results["variants"].items():
                print(f"     {variant_id}:")
                print(f"       转化率: {variant_data.get('conversion_rate', 0):.2%}")
                print(f"       样本数: {variant_data.get('impressions', 0)}")
        elif verbose:
            print(f"     原始结果: {results}")

        # 结束实验
        ab_framework.conclude_experiment(experiment.experiment_id)
        print(f"\n   实验已结束")
        print(f"   获胜者: {experiment.winner or '未确定'}")

    except Exception as e:
        print(f"   A/B 测试失败: {e}")
        if verbose:
            import traceback

            traceback.print_exc()


async def demonstrate_prompt_optimization(
    verbose: bool = False, model_tier: str = "default"
):
    """演示 Prompt 优化"""
    print("\n2. Prompt 优化")
    print("-" * 40)

    try:
        # 创建真实 LLM 客户端
        print("   创建 LLM 客户端...")
        unified_client = create_llm_client(tier=model_tier, client_type="langchain")
        llm_client = unified_client.get_langchain_client()
        print(f"   ✅ LLM 客户端: {unified_client.model_name}")

        optimizer = PromptOptimizer(llm_client)

        # 注册原始 Prompt
        original_prompt = """
        请分析目标公司的投资价值，输出 JSON 格式的分析报告。
        """

        # 使用正确的参数名
        optimizer.register_prompt(
            prompt_id="analyst_prompt_v1",
            initial_prompt=original_prompt,
            notes="金融分析 Prompt 初始版本",
        )
        print("   已注册原始 Prompt")
        print(f"   原始: {original_prompt.strip()}")

        # 优化 Prompt
        print("\n   正在优化...")
        from src.evolution.prompt_optimizer import OptimizationType

        optimized = await optimizer.optimize(
            prompt_id="analyst_prompt_v1",
            optimization_type=OptimizationType.QUALITY,
        )

        print(f"   优化完成")
        if verbose and optimized:
            optimized_text = (
                optimized.current_prompt
                if hasattr(optimized, "current_prompt")
                else str(optimized)
            )
            print(f"   优化后: {optimized_text[:100]}...")

    except Exception as e:
        print(f"   Prompt 优化失败: {e}")
        print("   请检查 config/app_config.yaml 中的 API 配置")
        if verbose:
            import traceback

            traceback.print_exc()


async def demonstrate_version_control(verbose: bool = False):
    """演示版本控制"""
    print("\n3. 版本控制")
    print("-" * 40)

    try:
        # 创建版本控制器
        vc = VersionControl(storage_path="./versions_example")
        print("   版本控制器创建成功")

        # 模拟 Agent 定义
        agent_def_v1 = {
            "agent_id": "demo_agent",
            "name": "演示 Agent",
            "version": "1.0.0",
            "description": "初始版本",
        }

        agent_def_v2 = {
            "agent_id": "demo_agent",
            "name": "演示 Agent",
            "version": "1.1.0",
            "description": "优化后版本",
        }

        # 提交版本
        print("\n   提交版本:")
        v1 = vc.commit(
            agent_id="demo_agent",
            definition=agent_def_v1,
            version="1.0.0",
            message="初始版本",
        )
        print(f"     v1.0.0: 初始版本")

        v2 = vc.commit(
            agent_id="demo_agent",
            definition=agent_def_v2,
            version="1.1.0",
            message="优化后版本",
        )
        print(f"     v1.1.0: 优化后版本")

        # 获取版本历史（使用 list_versions 而不是 get_history）
        versions = vc.list_versions("demo_agent")
        print(f"\n   版本历史 ({len(versions)} 个版本):")
        for v in versions:
            print(f"     - {v.version}: {v.message}")

        # 获取活跃版本
        print("\n   获取活跃版本:")
        active = vc.get_active_version("demo_agent")
        if active:
            print(f"     活跃版本: {active.version}")
            print(f"     描述: {active.definition.get('description', 'N/A')}")
        else:
            print("     无活跃版本")

    except Exception as e:
        print(f"   版本控制失败: {e}")
        if verbose:
            import traceback

            traceback.print_exc()


async def run_example(verbose: bool = False, model_tier: str = "default"):
    """示例入口"""
    print("=" * 50)
    print("A/B 测试和演化示例")
    print("=" * 50)

    await demonstrate_ab_testing(verbose)
    await demonstrate_prompt_optimization(verbose, model_tier)
    await demonstrate_version_control(verbose)

    print("\n" + "=" * 50)
    print("示例完成")
    print("=" * 50)

    return {"status": "success"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="A/B 测试示例")
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

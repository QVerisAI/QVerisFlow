"""
演进层集成测试

测试智能演进功能，包括：
- Meta Agent 创建和优化 Agent
- Prompt 优化器变体管理
- 版本控制的提交和回滚
- A/B 测试实验管理
"""

import pytest
import asyncio
from pathlib import Path
from datetime import datetime


class TestPromptOptimizer:
    """Prompt 优化器测试"""

    @pytest.mark.asyncio
    async def test_prompt_registration(self, prompt_optimizer):
        """测试 Prompt 注册"""
        variant_id = prompt_optimizer.register_prompt(
            prompt_id="greeting",
            initial_prompt="Hello, how can I help you?",
            notes="Initial greeting prompt",
        )

        assert variant_id == "greeting_v1"
        assert "greeting" in prompt_optimizer.variants

    @pytest.mark.asyncio
    async def test_get_best_variant(self, prompt_optimizer):
        """测试获取最佳变体"""
        prompt_optimizer.register_prompt(
            prompt_id="test_prompt",
            initial_prompt="Initial prompt text",
        )

        # 最初只有一个变体
        best = prompt_optimizer.get_best_variant("test_prompt")
        assert best is not None
        assert best.variant_id == "test_prompt_v1"

    @pytest.mark.asyncio
    async def test_ab_test_variant_selection(self, prompt_optimizer):
        """测试 A/B 测试变体选择"""
        prompt_optimizer.register_prompt(
            prompt_id="ab_test",
            initial_prompt="Test prompt",
        )

        # 多次获取变体
        variants_selected = set()
        for _ in range(100):
            variant = prompt_optimizer.get_variant_for_ab_test(
                "ab_test",
                exploration_rate=0.5,  # 高探索率
            )
            variants_selected.add(variant.variant_id)

        # 应该至少选择到初始变体
        assert "ab_test_v1" in variants_selected

    @pytest.mark.asyncio
    async def test_execution_recording(self, prompt_optimizer):
        """测试执行记录"""
        prompt_optimizer.register_prompt(
            prompt_id="record_test",
            initial_prompt="Test prompt for recording",
        )

        # 记录多次执行
        for i in range(5):
            need_optimize = prompt_optimizer.record_execution(
                prompt_id="record_test",
                variant_id="record_test_v1",
                success=i % 2 == 0,  # 交替成功失败
                latency=1.0 + i * 0.1,
                tokens_used=100 + i * 10,
                output_quality=0.8,
            )

        # 检查变体统计
        variant = prompt_optimizer.get_best_variant("record_test")
        assert variant.execution_count == 5
        assert variant.success_count == 3  # 0, 2, 4 成功

    @pytest.mark.asyncio
    async def test_optimization_trigger(self, prompt_optimizer, mock_llm):
        """测试优化触发"""
        prompt_optimizer.optimization_interval = 5  # 设置较小的间隔

        prompt_optimizer.register_prompt(
            prompt_id="optimize_test",
            initial_prompt="Original prompt",
        )

        # 设置 mock 响应
        mock_llm.set_response("Optimized prompt text")

        # 记录执行直到触发优化
        need_optimize = False
        for i in range(5):
            need_optimize = prompt_optimizer.record_execution(
                prompt_id="optimize_test",
                variant_id="optimize_test_v1",
                success=True,
                latency=1.0,
                tokens_used=100,
            )

        assert need_optimize  # 第 5 次应该触发优化建议

    @pytest.mark.asyncio
    async def test_prompt_optimization(self, prompt_optimizer, mock_llm):
        """测试 Prompt 优化"""
        prompt_optimizer.register_prompt(
            prompt_id="to_optimize",
            initial_prompt="Please help the user.",
        )

        # 记录一些执行
        for i in range(10):
            prompt_optimizer.record_execution(
                prompt_id="to_optimize",
                variant_id="to_optimize_v1",
                success=i > 5,
                latency=2.0,
                tokens_used=200,
                output_quality=0.6,
                feedback="Could be more helpful" if i <= 5 else None,
            )

        # 设置优化响应
        mock_llm.set_response(
            "Please help the user with their request in a friendly and detailed manner."
        )

        # 执行优化
        new_variant = await prompt_optimizer.optimize("to_optimize")

        assert new_variant.variant_id == "to_optimize_v2"
        assert (
            "friendly" in new_variant.prompt_text.lower()
            or len(new_variant.prompt_text) > 0
        )

    @pytest.mark.asyncio
    async def test_variant_comparison(self, prompt_optimizer):
        """测试变体比较"""
        prompt_optimizer.register_prompt(
            prompt_id="compare_test",
            initial_prompt="Version 1",
        )

        # 手动添加第二个变体
        from src.evolution.prompt_optimizer import PromptVariant

        v2 = PromptVariant(
            variant_id="compare_test_v2",
            prompt_text="Version 2",
            execution_count=20,
            success_count=18,
            avg_latency=1.0,
            performance_score=0.9,
        )
        prompt_optimizer.variants["compare_test"].append(v2)

        # 更新 v1 的统计
        v1 = prompt_optimizer.variants["compare_test"][0]
        v1.execution_count = 15
        v1.success_count = 10
        v1.performance_score = 0.7

        comparison = prompt_optimizer.compare_variants(
            "compare_test",
            "compare_test_v1",
            "compare_test_v2",
        )

        assert comparison["winner"] == "compare_test_v2"
        assert comparison["variant_b"]["score"] > comparison["variant_a"]["score"]


class TestVersionControl:
    """版本控制测试"""

    @pytest.mark.asyncio
    async def test_version_commit(self, version_control):
        """测试版本提交"""
        version = version_control.commit(
            agent_id="test_agent",
            definition={"name": "Test Agent", "description": "A test agent"},
            version="1.0.0",
            author="tester",
            message="Initial version",
        )

        assert version.version == "1.0.0"
        assert version.agent_id == "test_agent"
        assert version.author == "tester"

    @pytest.mark.asyncio
    async def test_version_retrieval(self, version_control):
        """测试版本检索"""
        version_control.commit(
            agent_id="retrieve_test",
            definition={"name": "Test"},
            version="1.0.0",
        )

        # 获取活跃版本
        active = version_control.get_active_version("retrieve_test")
        assert active is not None
        assert active.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_multiple_versions(self, version_control):
        """测试多版本管理"""
        # 提交多个版本
        for i in range(3):
            version_control.commit(
                agent_id="multi_version",
                definition={"name": f"Version {i + 1}"},
                version=f"1.{i}.0",
                auto_activate=True,
            )

        # 列出所有版本
        versions = version_control.list_versions("multi_version")
        assert len(versions) == 3

        # 最新版本应该是活跃的
        active = version_control.get_active_version("multi_version")
        assert active.version == "1.2.0"

    @pytest.mark.asyncio
    async def test_version_rollback(self, version_control):
        """测试版本回滚"""
        # 提交两个版本
        v1 = version_control.commit(
            agent_id="rollback_test",
            definition={"name": "V1"},
            version="1.0.0",
            auto_activate=True,
        )
        v2 = version_control.commit(
            agent_id="rollback_test",
            definition={"name": "V2"},
            version="2.0.0",
            auto_activate=True,
        )

        # 当前活跃是 v2
        assert version_control.get_active_version("rollback_test").version == "2.0.0"

        # 回滚到 v1
        version_control.rollback("rollback_test", v1.version_id)

        # 现在活跃应该是 v1
        active = version_control.get_active_version("rollback_test")
        assert active.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_version_diff(self, version_control):
        """测试版本差异比较"""
        v1 = version_control.commit(
            agent_id="diff_test",
            definition={"name": "Agent", "config": {"max_tokens": 100}},
            version="1.0.0",
        )
        v2 = version_control.commit(
            agent_id="diff_test",
            definition={"name": "Agent Updated", "config": {"max_tokens": 200}},
            version="2.0.0",
        )

        diff = version_control.diff(v1.version_id, v2.version_id)

        assert len(diff["differences"]) > 0
        assert diff["summary"]["changed"] > 0

    @pytest.mark.asyncio
    async def test_version_tagging(self, version_control):
        """测试版本标签"""
        version = version_control.commit(
            agent_id="tag_test",
            definition={"name": "Tagged Agent"},
            version="1.0.0",
            tags=["production", "stable"],
        )

        # 通过标签获取版本
        tagged = version_control.get_version_by_tag("tag_test", "production")
        assert tagged is not None
        assert tagged.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_version_history(self, version_control):
        """测试版本历史链"""
        # 创建版本链
        for i in range(5):
            version_control.commit(
                agent_id="history_test",
                definition={"version": i + 1},
                version=f"1.{i}.0",
                auto_activate=True,
            )

        # 获取最新版本
        latest = version_control.get_active_version("history_test")

        # 获取历史
        history = version_control.get_version_history(latest.version_id, depth=10)

        assert len(history) == 5


class TestABTesting:
    """A/B 测试框架测试"""

    @pytest.mark.asyncio
    async def test_experiment_creation(self, ab_testing):
        """测试实验创建"""
        experiment = ab_testing.create_experiment(
            experiment_id="test_exp",
            name="Test Experiment",
            description="A test experiment",
            variants={"control": 0.5, "treatment": 0.5},
            metrics=["latency", "quality"],
        )

        assert experiment.experiment_id == "test_exp"
        assert len(experiment.variants) == 2
        assert experiment.status.value == "running"

    @pytest.mark.asyncio
    async def test_variant_assignment(self, ab_testing):
        """测试变体分配"""
        ab_testing.create_experiment(
            experiment_id="assign_exp",
            name="Assignment Test",
            description="Test variant assignment",
            variants={"control": 0.5, "treatment": 0.5},
            metrics=["conversion"],
        )

        # 同一用户应该总是得到相同的变体
        user_variant = ab_testing.get_variant("assign_exp", "user123")
        for _ in range(10):
            assert ab_testing.get_variant("assign_exp", "user123") == user_variant

    @pytest.mark.asyncio
    async def test_traffic_distribution(self, ab_testing):
        """测试流量分配"""
        ab_testing.create_experiment(
            experiment_id="traffic_exp",
            name="Traffic Test",
            description="Test traffic distribution",
            variants={"control": 0.7, "treatment": 0.3},
            metrics=["clicks"],
        )

        # 分配大量用户
        assignments = {"control": 0, "treatment": 0}
        for i in range(1000):
            variant = ab_testing.get_variant("traffic_exp", f"user_{i}")
            assignments[variant] += 1

        # 检查分配比例（允许一定误差）
        control_ratio = assignments["control"] / 1000
        assert 0.6 < control_ratio < 0.8  # 约 70%

    @pytest.mark.asyncio
    async def test_metric_recording(self, ab_testing):
        """测试指标记录"""
        ab_testing.create_experiment(
            experiment_id="metric_exp",
            name="Metric Test",
            description="Test metric recording",
            variants={"control": 0.5, "treatment": 0.5},
            metrics=["latency", "quality"],
        )

        # 分配并记录指标
        for i in range(20):
            user_id = f"user_{i}"
            ab_testing.get_variant("metric_exp", user_id)
            ab_testing.record_metric("metric_exp", user_id, "latency", 1.0 + i * 0.1)
            ab_testing.record_metric("metric_exp", user_id, "quality", 0.8 + i * 0.01)

        # 获取结果
        results = ab_testing.get_results("metric_exp")

        assert results["experiment_id"] == "metric_exp"
        # 检查变体结果
        for variant_id, variant_data in results["variants"].items():
            assert variant_data["impressions"] > 0
            if variant_data["metrics"].get("latency"):
                assert variant_data["metrics"]["latency"]["count"] > 0

    @pytest.mark.asyncio
    async def test_conversion_tracking(self, ab_testing):
        """测试转化跟踪"""
        ab_testing.create_experiment(
            experiment_id="conversion_exp",
            name="Conversion Test",
            description="Test conversion tracking",
            variants={"control": 0.5, "treatment": 0.5},
            metrics=["revenue"],
        )

        # 模拟用户转化
        for i in range(100):
            user_id = f"user_{i}"
            ab_testing.get_variant("conversion_exp", user_id)
            if i % 3 == 0:  # 约 33% 转化率
                ab_testing.record_conversion("conversion_exp", user_id)

        results = ab_testing.get_results("conversion_exp")

        # 检查转化数据
        total_conversions = sum(v["conversions"] for v in results["variants"].values())
        assert total_conversions > 0

    @pytest.mark.asyncio
    async def test_experiment_conclusion(self, ab_testing):
        """测试实验结束"""
        ab_testing.create_experiment(
            experiment_id="conclude_exp",
            name="Conclusion Test",
            description="Test experiment conclusion",
            variants={"control": 0.5, "treatment": 0.5},
            metrics=["score"],
        )

        # 模拟执行
        for i in range(200):
            user_id = f"user_{i}"
            variant = ab_testing.get_variant("conclude_exp", user_id)
            # treatment 组转化率更高
            if variant == "treatment" and i % 2 == 0:
                ab_testing.record_conversion("conclude_exp", user_id)
            elif variant == "control" and i % 4 == 0:
                ab_testing.record_conversion("conclude_exp", user_id)

        # 结束实验
        conclusion = ab_testing.conclude_experiment("conclude_exp")

        assert conclusion["status"] == "completed"
        # 应该有获胜者
        assert conclusion["winner"] is not None

    @pytest.mark.asyncio
    async def test_significance_analysis(self, ab_testing):
        """测试显著性分析"""
        ab_testing.create_experiment(
            experiment_id="significance_exp",
            name="Significance Test",
            description="Test significance analysis",
            variants={"control": 0.5, "treatment": 0.5},
            metrics=["value"],
        )

        # 模拟大量数据以获得显著性
        for i in range(500):
            user_id = f"user_{i}"
            variant = ab_testing.get_variant("significance_exp", user_id)
            # treatment 明显更好
            if variant == "treatment":
                if i % 5 != 0:  # 80% 转化
                    ab_testing.record_conversion("significance_exp", user_id)
            else:
                if i % 3 == 0:  # 33% 转化
                    ab_testing.record_conversion("significance_exp", user_id)

        results = ab_testing.get_results("significance_exp")

        # 检查显著性分析
        assert "significance" in results
        if "control_vs_treatment" in results["significance"]:
            sig = results["significance"]["control_vs_treatment"]
            assert "lift" in sig
            assert sig["lift"] > 0  # treatment 更好

    @pytest.mark.asyncio
    async def test_experiment_pause_resume(self, ab_testing):
        """测试实验暂停和恢复"""
        ab_testing.create_experiment(
            experiment_id="pause_exp",
            name="Pause Test",
            description="Test pause and resume",
            variants={"control": 0.5, "treatment": 0.5},
            metrics=["test"],
        )

        # 暂停
        assert ab_testing.pause_experiment("pause_exp")
        exp = ab_testing.get_experiment("pause_exp")
        assert exp.status.value == "paused"

        # 暂停期间获取变体应返回默认值
        variant = ab_testing.get_variant("pause_exp", "user_pause")
        assert variant == "control"

        # 恢复
        assert ab_testing.resume_experiment("pause_exp")
        exp = ab_testing.get_experiment("pause_exp")
        assert exp.status.value == "running"


class TestMetaAgent:
    """Meta Agent 测试"""

    @pytest.mark.asyncio
    async def test_meta_agent_initialization(self, mock_llm):
        """测试 Meta Agent 初始化"""
        from src.evolution.meta_agent import MetaAgent

        meta_agent = MetaAgent(llm_client=mock_llm)
        assert meta_agent is not None

    @pytest.mark.asyncio
    async def test_create_agent_definition(self, mock_llm):
        """测试创建 Agent 定义"""
        from src.evolution.meta_agent import MetaAgent

        meta_agent = MetaAgent(llm_client=mock_llm)

        # 设置 mock 响应 - 需要包含所有必需字段
        mock_llm.set_response(
            """
{
    "agent_id": "generated_agent",
    "name": "Generated Agent",
    "description": "An auto-generated agent",
    "background_instruction": {
        "role_description": "You are a Data Analysis Assistant",
        "core_capability": "You help with data analysis tasks",
        "task_context": "Analyze data and provide insights"
    },
    "output_instruction": {
        "format_type": "json"
    },
    "user_instruction": {
        "task_description": "Analyze: {task}"
    }
}
"""
        )

        definition = await meta_agent.create_agent(
            task_description="Create an agent that helps with data analysis",
            tools=["test_tool"],
        )

        assert definition is not None
        assert definition.agent_id == "generated_agent"

    @pytest.mark.asyncio
    async def test_optimize_agent(self, mock_llm):
        """测试优化 Agent"""
        from src.evolution.meta_agent import MetaAgent
        from src.registry import AgentRegistry
        from src.definitions import (
            AgentDefinition,
            BackgroundInstruction,
            OutputInstruction,
            UserInstruction,
        )

        # 先注册一个 agent 以便优化
        registry = AgentRegistry()

        original_agent = AgentDefinition(
            agent_id="original_agent",
            name="Original Agent",
            description="An original agent",
            background_instruction=BackgroundInstruction(
                role_description="You are a test agent",
                core_capability="Testing capabilities",
                task_context="Testing context",
            ),
            output_instruction=OutputInstruction(
                format_type="text",
            ),
            user_instruction=UserInstruction(
                task_description="Do the task: {task}",
            ),
        )
        registry.register_definition(original_agent)

        meta_agent = MetaAgent(llm_client=mock_llm, agent_registry=registry)

        # 设置优化响应
        mock_llm.set_response(
            """
{
    "background_instruction": {
        "role_description": "You are a highly efficient and helpful agent.",
        "core_capability": "Enhanced testing capabilities",
        "task_context": "Optimized testing context"
    }
}
"""
        )

        # 使用 optimize_prompt 方法而不是 optimize_agent
        optimized = await meta_agent.optimize_prompt(
            agent_id="original_agent",
            feedback_history=[
                {
                    "task": "test task",
                    "success": False,
                    "feedback": "Could be more detailed",
                },
            ],
        )

        assert optimized is not None

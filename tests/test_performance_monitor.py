"""
Agent 性能监控测试

测试 AgentPerformanceMonitor 的各项功能。
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.evolution.performance_monitor import (
    AlertSeverity,
    MetricType,
    Metric,
    AgentMetrics,
    AlertRule,
    Alert,
    PerformanceReport,
    NotificationChannel,
    LogNotificationChannel,
    AgentPerformanceMonitor,
)


class TestMetric:
    """Metric 测试"""

    def test_create_metric(self):
        """测试创建指标"""
        metric = Metric(
            name="request_count",
            value=100,
            metric_type=MetricType.COUNTER,
            labels={"agent": "test"},
        )

        assert metric.name == "request_count"
        assert metric.value == 100
        assert metric.metric_type == MetricType.COUNTER
        assert metric.labels["agent"] == "test"

    def test_to_dict(self):
        """测试指标序列化"""
        metric = Metric(
            name="latency", value=150.5, metric_type=MetricType.GAUGE, labels={}
        )

        d = metric.to_dict()

        assert d["name"] == "latency"
        assert d["value"] == 150.5
        assert d["type"] == "gauge"


class TestAgentMetrics:
    """AgentMetrics 测试"""

    def test_success_rate(self):
        """测试成功率计算"""
        metrics = AgentMetrics(
            agent_id="test",
            total_executions=100,
            successful_executions=80,
            failed_executions=20,
        )

        assert metrics.success_rate == pytest.approx(0.8)
        assert metrics.failure_rate == pytest.approx(0.2)

    def test_success_rate_no_executions(self):
        """测试无执行时的成功率"""
        metrics = AgentMetrics(agent_id="test", total_executions=0)

        assert metrics.success_rate == 0.0
        assert metrics.failure_rate == 1.0

    def test_to_dict(self):
        """测试序列化"""
        metrics = AgentMetrics(
            agent_id="test_agent",
            total_executions=50,
            successful_executions=45,
            failed_executions=5,
            avg_duration_ms=1500.0,
            avg_iterations=2.5,
        )

        d = metrics.to_dict()

        assert d["agent_id"] == "test_agent"
        assert d["total_executions"] == 50
        assert d["success_rate"] == 0.9
        assert d["avg_duration_ms"] == 1500.0


class TestAlertRule:
    """AlertRule 测试"""

    def test_create_rule(self):
        """测试创建告警规则"""
        rule = AlertRule(
            rule_id="low_success",
            name="低成功率",
            condition="success_rate < 0.8",
            severity=AlertSeverity.WARNING,
        )

        assert rule.rule_id == "low_success"
        assert rule.severity == AlertSeverity.WARNING
        assert rule.is_enabled is True

    def test_evaluate_true(self):
        """测试规则评估为真"""
        rule = AlertRule(
            rule_id="test",
            name="Test",
            condition="success_rate < 0.8",
            severity=AlertSeverity.WARNING,
            min_executions=5,
        )

        metrics = AgentMetrics(
            agent_id="test",
            total_executions=10,
            successful_executions=5,
            failed_executions=5,
        )

        assert rule.evaluate(metrics) is True

    def test_evaluate_false(self):
        """测试规则评估为假"""
        rule = AlertRule(
            rule_id="test",
            name="Test",
            condition="success_rate < 0.8",
            severity=AlertSeverity.WARNING,
            min_executions=5,
        )

        metrics = AgentMetrics(
            agent_id="test",
            total_executions=10,
            successful_executions=9,
            failed_executions=1,
        )

        assert rule.evaluate(metrics) is False

    def test_evaluate_min_executions(self):
        """测试最小执行次数检查"""
        rule = AlertRule(
            rule_id="test",
            name="Test",
            condition="success_rate < 0.8",
            severity=AlertSeverity.WARNING,
            min_executions=10,
        )

        metrics = AgentMetrics(
            agent_id="test",
            total_executions=5,  # 小于最小执行次数
            successful_executions=0,
            failed_executions=5,
        )

        # 不满足最小执行次数，不触发告警
        assert rule.evaluate(metrics) is False

    def test_evaluate_disabled(self):
        """测试禁用的规则"""
        rule = AlertRule(
            rule_id="test",
            name="Test",
            condition="success_rate < 0.8",
            severity=AlertSeverity.WARNING,
            is_enabled=False,
        )

        metrics = AgentMetrics(
            agent_id="test",
            total_executions=10,
            successful_executions=0,
        )

        assert rule.evaluate(metrics) is False

    def test_evaluate_cooldown(self):
        """测试冷却时间"""
        rule = AlertRule(
            rule_id="test",
            name="Test",
            condition="success_rate < 0.8",
            severity=AlertSeverity.WARNING,
            cooldown_minutes=30,
            min_executions=1,
        )

        # 设置最近触发时间
        rule.last_triggered = datetime.now()

        metrics = AgentMetrics(
            agent_id="test",
            total_executions=10,
            successful_executions=0,
        )

        # 在冷却期内，不触发告警
        assert rule.evaluate(metrics) is False

    def test_evaluate_complex_condition(self):
        """测试复杂条件表达式"""
        rule = AlertRule(
            rule_id="test",
            name="Test",
            condition="success_rate < 0.9 and avg_duration_ms > 5000",
            severity=AlertSeverity.WARNING,
            min_executions=1,
        )

        # 满足所有条件
        metrics = AgentMetrics(
            agent_id="test",
            total_executions=10,
            successful_executions=7,
            avg_duration_ms=6000,
        )
        assert rule.evaluate(metrics) is True

        # 只满足部分条件
        metrics2 = AgentMetrics(
            agent_id="test",
            total_executions=10,
            successful_executions=9,  # success_rate = 0.9，不满足 < 0.9
            avg_duration_ms=6000,
        )
        assert rule.evaluate(metrics2) is False


class TestAlert:
    """Alert 测试"""

    def test_is_active(self):
        """测试告警活跃状态"""
        rule = AlertRule(
            rule_id="test",
            name="Test",
            condition="success_rate < 0.8",
            severity=AlertSeverity.WARNING,
        )

        alert = Alert(
            alert_id="alert_1",
            rule=rule,
            agent_id="test_agent",
            triggered_at=datetime.now(),
        )

        assert alert.is_active is True

        # 解除后
        alert.resolved_at = datetime.now()
        assert alert.is_active is False

    def test_to_dict(self):
        """测试告警序列化"""
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition="success_rate < 0.8",
            severity=AlertSeverity.CRITICAL,
        )

        alert = Alert(
            alert_id="alert_123",
            rule=rule,
            agent_id="my_agent",
            triggered_at=datetime.now(),
            message="Test alert message",
        )

        d = alert.to_dict()

        assert d["alert_id"] == "alert_123"
        assert d["rule_id"] == "test_rule"
        assert d["agent_id"] == "my_agent"
        assert d["severity"] == "critical"
        assert d["is_active"] is True


class TestLogNotificationChannel:
    """LogNotificationChannel 测试"""

    @pytest.mark.asyncio
    async def test_send(self):
        """测试发送日志通知"""
        channel = LogNotificationChannel()

        rule = AlertRule(
            rule_id="test",
            name="Test",
            condition="success_rate < 0.8",
            severity=AlertSeverity.WARNING,
        )

        alert = Alert(
            alert_id="alert_1",
            rule=rule,
            agent_id="test",
            triggered_at=datetime.now(),
            message="Test message",
        )

        result = await channel.send(alert)
        assert result is True


class TestAgentPerformanceMonitor:
    """AgentPerformanceMonitor 测试"""

    @pytest.fixture
    def monitor(self):
        """创建监控器"""
        return AgentPerformanceMonitor()

    # ========== 执行记录测试 ==========

    @pytest.mark.asyncio
    async def test_record_execution(self, monitor):
        """测试记录执行"""
        await monitor.record_execution(
            agent_id="test_agent",
            success=True,
            duration_ms=1500,
            iterations=3,
            verification_score=0.95,
        )

        assert "test_agent" in monitor._execution_records
        assert len(monitor._execution_records["test_agent"]) == 1

    @pytest.mark.asyncio
    async def test_record_execution_max_records(self, monitor):
        """测试记录数量限制"""
        # 模拟大量记录
        for i in range(12000):
            await monitor.record_execution(
                agent_id="test_agent", success=True, duration_ms=100
            )

        # 应该限制在 10000 条
        assert len(monitor._execution_records["test_agent"]) <= 10000

    # ========== 指标收集测试 ==========

    @pytest.mark.asyncio
    async def test_collect_metrics_empty(self, monitor):
        """测试空记录的指标收集"""
        metrics = await monitor.collect_metrics("nonexistent")

        assert metrics.agent_id == "nonexistent"
        assert metrics.total_executions == 0

    @pytest.mark.asyncio
    async def test_collect_metrics(self, monitor):
        """测试指标收集"""
        # 记录执行
        for i in range(10):
            await monitor.record_execution(
                agent_id="test",
                success=i < 8,  # 80% 成功率
                duration_ms=1000 + i * 100,
                iterations=2,
                verification_score=0.9,
                tokens_used=500,
            )

        metrics = await monitor.collect_metrics("test")

        assert metrics.total_executions == 10
        assert metrics.successful_executions == 8
        assert metrics.failed_executions == 2
        assert metrics.success_rate == pytest.approx(0.8)
        assert metrics.avg_duration_ms > 0
        assert metrics.avg_iterations == pytest.approx(2.0)
        assert metrics.avg_verification_score == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_collect_metrics_time_window(self, monitor):
        """测试时间窗口过滤"""
        # 记录当前时间的执行
        await monitor.record_execution(agent_id="test", success=True, duration_ms=1000)

        # 收集最近1小时的指标
        metrics = await monitor.collect_metrics("test", time_window=timedelta(hours=1))

        assert metrics.total_executions == 1

    # ========== 告警规则测试 ==========

    def test_add_alert_rule(self, monitor):
        """测试添加告警规则"""
        rule = AlertRule(
            rule_id="custom_rule",
            name="Custom Rule",
            condition="success_rate < 0.9",
            severity=AlertSeverity.INFO,
        )

        monitor.add_alert_rule(rule)

        rules = monitor.get_alert_rules()
        rule_ids = [r.rule_id for r in rules]
        assert "custom_rule" in rule_ids

    def test_remove_alert_rule(self, monitor):
        """测试移除告警规则"""
        # 移除默认规则
        result = monitor.remove_alert_rule("low_success_rate_warning")

        assert result is True
        rules = monitor.get_alert_rules()
        rule_ids = [r.rule_id for r in rules]
        assert "low_success_rate_warning" not in rule_ids

    def test_remove_nonexistent_rule(self, monitor):
        """测试移除不存在的规则"""
        result = monitor.remove_alert_rule("nonexistent")
        assert result is False

    def test_default_rules(self, monitor):
        """测试默认告警规则"""
        rules = monitor.get_alert_rules()
        rule_ids = [r.rule_id for r in rules]

        assert "low_success_rate_critical" in rule_ids
        assert "low_success_rate_warning" in rule_ids
        assert "high_latency" in rule_ids

    # ========== 告警检查测试 ==========

    @pytest.mark.asyncio
    async def test_check_alerts_triggered(self, monitor):
        """测试告警触发"""
        # 记录失败的执行
        for i in range(15):
            await monitor.record_execution(
                agent_id="failing_agent",
                success=i < 3,  # 只有 3 次成功，成功率 20%
                duration_ms=1000,
            )

        alerts = await monitor.check_alerts("failing_agent")

        # 应该触发低成功率告警
        assert len(alerts) > 0
        severities = [a.severity for a in alerts]
        assert AlertSeverity.CRITICAL in severities

    @pytest.mark.asyncio
    async def test_check_alerts_not_triggered(self, monitor):
        """测试告警不触发"""
        # 记录成功的执行
        for i in range(15):
            await monitor.record_execution(
                agent_id="healthy_agent",
                success=True,
                duration_ms=1000,
                verification_score=0.95,
            )

        alerts = await monitor.check_alerts("healthy_agent")

        # 不应该有活跃告警
        active_alerts = [a for a in alerts if a.is_active]
        # 默认规则不应该触发（因为成功率 100%）
        critical_or_warning = [
            a
            for a in active_alerts
            if a.severity in [AlertSeverity.CRITICAL, AlertSeverity.WARNING]
        ]
        assert len(critical_or_warning) == 0

    @pytest.mark.asyncio
    async def test_alert_auto_resolve(self, monitor):
        """测试告警自动解除"""
        # 先触发告警
        for i in range(15):
            await monitor.record_execution(
                agent_id="test", success=False, duration_ms=1000
            )

        alerts = await monitor.check_alerts("test")
        assert len([a for a in alerts if a.is_active]) > 0

        # 清空并记录成功执行
        monitor._execution_records["test"] = []
        for i in range(15):
            await monitor.record_execution(
                agent_id="test", success=True, duration_ms=1000
            )

        # 再次检查，应该自动解除
        await monitor.check_alerts("test")

        # 活跃告警应该减少
        active = monitor.get_active_alerts("test")
        # 注意：由于 success_rate 现在是 100%，不应该有低成功率告警
        low_success_alerts = [a for a in active if "success" in a.rule.rule_id.lower()]
        assert len(low_success_alerts) == 0

    def test_get_active_alerts(self, monitor):
        """测试获取活跃告警"""
        # 手动添加告警
        rule = AlertRule(
            rule_id="test",
            name="Test",
            condition="success_rate < 1",
            severity=AlertSeverity.WARNING,
        )
        alert = Alert(
            alert_id="test_alert",
            rule=rule,
            agent_id="agent1",
            triggered_at=datetime.now(),
        )
        monitor._active_alerts["agent1:test"] = alert

        # 获取所有
        all_alerts = monitor.get_active_alerts()
        assert len(all_alerts) == 1

        # 按 agent 过滤
        agent1_alerts = monitor.get_active_alerts("agent1")
        assert len(agent1_alerts) == 1

        agent2_alerts = monitor.get_active_alerts("agent2")
        assert len(agent2_alerts) == 0

    # ========== 通知渠道测试 ==========

    def test_add_notification_channel(self, monitor):
        """测试添加通知渠道"""
        mock_channel = MagicMock(spec=NotificationChannel)
        monitor.add_notification_channel("mock", mock_channel)

        assert "mock" in monitor._notification_channels

    # ========== 报告生成测试 ==========

    @pytest.mark.asyncio
    async def test_generate_report(self, monitor):
        """测试生成性能报告"""
        # 记录一些执行
        for i in range(20):
            await monitor.record_execution(
                agent_id="report_agent",
                success=i < 18,
                duration_ms=1000 + i * 50,
                iterations=2,
                verification_score=0.85,
            )

        report = await monitor.generate_report("report_agent")

        assert report.agent_id == "report_agent"
        assert report.metrics.total_executions == 20
        assert "trends" in report.to_dict()
        assert "recommendations" in report.to_dict()

    @pytest.mark.asyncio
    async def test_generate_report_recommendations(self, monitor):
        """测试报告建议"""
        # 记录低成功率的执行
        for i in range(20):
            await monitor.record_execution(
                agent_id="poor_agent",
                success=i < 10,  # 50% 成功率
                duration_ms=50000,  # 50秒，很慢
                iterations=8,  # 很多迭代
                verification_score=0.5,  # 低分
            )

        report = await monitor.generate_report("poor_agent")

        # 应该有多个建议
        assert len(report.recommendations) > 0

        # 检查建议内容
        recommendations_text = " ".join(report.recommendations)
        assert "成功率" in recommendations_text or "执行时间" in recommendations_text

    @pytest.mark.asyncio
    async def test_report_to_dict(self, monitor):
        """测试报告序列化"""
        await monitor.record_execution(agent_id="test", success=True, duration_ms=1000)

        report = await monitor.generate_report("test")
        d = report.to_dict()

        assert "agent_id" in d
        assert "metrics" in d
        assert "alerts" in d
        assert "trends" in d
        assert "recommendations" in d
        assert "generated_at" in d

    # ========== 趋势计算测试 ==========

    @pytest.mark.asyncio
    async def test_calculate_trends(self, monitor):
        """测试趋势计算"""
        # 前半段：低成功率
        for i in range(10):
            await monitor.record_execution(
                agent_id="trend_agent",
                success=i < 5,  # 50% 成功率
                duration_ms=2000,
            )

        # 后半段：高成功率
        for i in range(10):
            await monitor.record_execution(
                agent_id="trend_agent",
                success=True,  # 100% 成功率
                duration_ms=1000,
            )

        report = await monitor.generate_report(
            "trend_agent", time_window=timedelta(hours=1)
        )

        # 应该显示成功率改善
        assert "trends" in report.to_dict()

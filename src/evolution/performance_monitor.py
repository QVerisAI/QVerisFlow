"""
Agent 性能监控和告警系统

提供自动化的 Agent 性能监控、指标收集和告警功能。

特性：
- 实时性能指标收集
- 可配置的告警规则
- 性能报告生成
- 多渠道告警通知
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union
import asyncio
import json
import re

from src.utils.logger import get_logger

logger = get_logger(__name__)


class AlertSeverity(str, Enum):
    """告警严重级别"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class MetricType(str, Enum):
    """指标类型"""

    COUNTER = "counter"  # 计数器（单调递增）
    GAUGE = "gauge"  # 瞬时值
    HISTOGRAM = "histogram"  # 直方图
    SUMMARY = "summary"  # 摘要统计


@dataclass
class Metric:
    """
    性能指标
    """

    name: str
    value: float
    metric_type: MetricType
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "type": self.metric_type.value,
            "labels": self.labels,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AgentMetrics:
    """
    Agent 性能指标集合
    """

    agent_id: str

    # 执行指标
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0

    # 时间指标
    total_duration_ms: float = 0
    avg_duration_ms: float = 0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0
    p50_duration_ms: float = 0
    p95_duration_ms: float = 0
    p99_duration_ms: float = 0

    # 迭代指标
    avg_iterations: float = 0
    max_iterations: int = 0

    # 验证指标
    avg_verification_score: float = 0
    verification_pass_rate: float = 0

    # 资源指标
    total_tokens_used: int = 0
    avg_tokens_per_execution: float = 0

    # 时间范围
    time_window_start: Optional[datetime] = None
    time_window_end: Optional[datetime] = None

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_executions == 0:
            return 0.0
        return self.successful_executions / self.total_executions

    @property
    def failure_rate(self) -> float:
        """失败率"""
        return 1.0 - self.success_rate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "success_rate": round(self.success_rate, 4),
            "failure_rate": round(self.failure_rate, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "min_duration_ms": (
                round(self.min_duration_ms, 2)
                if self.min_duration_ms != float("inf")
                else None
            ),
            "max_duration_ms": round(self.max_duration_ms, 2),
            "p50_duration_ms": round(self.p50_duration_ms, 2),
            "p95_duration_ms": round(self.p95_duration_ms, 2),
            "p99_duration_ms": round(self.p99_duration_ms, 2),
            "avg_iterations": round(self.avg_iterations, 2),
            "max_iterations": self.max_iterations,
            "avg_verification_score": round(self.avg_verification_score, 4),
            "verification_pass_rate": round(self.verification_pass_rate, 4),
            "total_tokens_used": self.total_tokens_used,
            "avg_tokens_per_execution": round(self.avg_tokens_per_execution, 2),
            "time_window": {
                "start": (
                    self.time_window_start.isoformat()
                    if self.time_window_start
                    else None
                ),
                "end": (
                    self.time_window_end.isoformat() if self.time_window_end else None
                ),
            },
        }


@dataclass
class AlertRule:
    """
    告警规则

    定义触发告警的条件和行为。

    用法:
        ```python
        rule = AlertRule(
            rule_id="low_success_rate",
            name="低成功率告警",
            condition="success_rate < 0.8",
            severity=AlertSeverity.WARNING,
            cooldown_minutes=30,
            notification_channels=["email", "slack"],
        )
        ```
    """

    rule_id: str
    name: str
    condition: str  # 条件表达式，如 "success_rate < 0.8"
    severity: AlertSeverity

    # 告警配置
    cooldown_minutes: int = 15  # 冷却时间，避免重复告警
    auto_resolve: bool = True  # 条件恢复时自动解除告警

    # 通知配置
    notification_channels: List[str] = field(default_factory=list)
    notification_template: Optional[str] = None

    # 附加条件
    min_executions: int = 10  # 最小执行次数（避免样本不足时误报）

    # 状态
    is_enabled: bool = True
    last_triggered: Optional[datetime] = None

    def evaluate(self, metrics: AgentMetrics) -> bool:
        """
        评估告警条件

        Args:
            metrics: Agent 指标

        Returns:
            是否触发告警
        """
        if not self.is_enabled:
            return False

        # 检查最小执行次数
        if metrics.total_executions < self.min_executions:
            return False

        # 检查冷却时间
        if self.last_triggered:
            cooldown_end = self.last_triggered + timedelta(
                minutes=self.cooldown_minutes
            )
            if datetime.now() < cooldown_end:
                return False

        # 评估条件表达式
        try:
            # 构建评估上下文
            context = {
                "success_rate": metrics.success_rate,
                "failure_rate": metrics.failure_rate,
                "avg_duration_ms": metrics.avg_duration_ms,
                "max_duration_ms": metrics.max_duration_ms,
                "p95_duration_ms": metrics.p95_duration_ms,
                "p99_duration_ms": metrics.p99_duration_ms,
                "avg_iterations": metrics.avg_iterations,
                "avg_verification_score": metrics.avg_verification_score,
                "verification_pass_rate": metrics.verification_pass_rate,
                "total_executions": metrics.total_executions,
            }

            # 安全评估（只允许比较操作）
            return self._safe_eval(self.condition, context)

        except Exception as e:
            logger.error(f"评估告警条件失败: {self.condition}, error={e}")
            return False

    def _safe_eval(self, condition: str, context: Dict[str, Any]) -> bool:
        """安全评估条件表达式"""
        # 简单的条件解析器
        # 支持: <, >, <=, >=, ==, !=, and, or

        # 替换变量
        expr = condition
        for key, value in context.items():
            expr = re.sub(rf"\b{key}\b", str(value), expr)

        # 只允许安全的操作符和数字
        allowed_pattern = r"^[\d\.\s\<\>\=\!\&\|\(\)andor]+$"
        if not re.match(allowed_pattern, expr.replace("and", "").replace("or", "")):
            raise ValueError(f"不安全的条件表达式: {condition}")

        # 转换 and/or 为 Python 语法
        expr = expr.replace(" and ", " and ").replace(" or ", " or ")

        return eval(expr)


@dataclass
class Alert:
    """
    告警实例
    """

    alert_id: str
    rule: AlertRule
    agent_id: str
    triggered_at: datetime
    resolved_at: Optional[datetime] = None
    metrics_snapshot: Optional[Dict[str, Any]] = None
    message: str = ""

    @property
    def is_active(self) -> bool:
        """告警是否活跃"""
        return self.resolved_at is None

    @property
    def severity(self) -> AlertSeverity:
        """获取告警严重级别"""
        return self.rule.severity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "rule_id": self.rule.rule_id,
            "rule_name": self.rule.name,
            "agent_id": self.agent_id,
            "severity": self.rule.severity.value,
            "triggered_at": self.triggered_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "is_active": self.is_active,
            "message": self.message,
            "metrics_snapshot": self.metrics_snapshot,
        }


@dataclass
class PerformanceReport:
    """
    性能报告
    """

    agent_id: str
    report_id: str
    generated_at: datetime
    time_window: timedelta
    metrics: AgentMetrics
    alerts: List[Alert]
    trends: Dict[str, Any]
    recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "report_id": self.report_id,
            "generated_at": self.generated_at.isoformat(),
            "time_window_hours": self.time_window.total_seconds() / 3600,
            "metrics": self.metrics.to_dict(),
            "alerts": [a.to_dict() for a in self.alerts],
            "trends": self.trends,
            "recommendations": self.recommendations,
        }


class NotificationChannel:
    """
    通知渠道基类
    """

    async def send(self, alert: Alert) -> bool:
        """
        发送告警通知

        Args:
            alert: 告警实例

        Returns:
            是否发送成功
        """
        raise NotImplementedError


class LogNotificationChannel(NotificationChannel):
    """日志通知渠道"""

    async def send(self, alert: Alert) -> bool:
        logger.warning(
            f"🚨 告警: [{alert.severity.value.upper()}] {alert.rule.name} "
            f"- Agent: {alert.agent_id} - {alert.message}"
        )
        return True


class WebhookNotificationChannel(NotificationChannel):
    """Webhook 通知渠道"""

    def __init__(self, webhook_url: str, headers: Optional[Dict[str, str]] = None):
        self.webhook_url = webhook_url
        self.headers = headers or {"Content-Type": "application/json"}

    async def send(self, alert: Alert) -> bool:
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json=alert.to_dict(),
                    headers=self.headers,
                    timeout=10,
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Webhook 通知失败: {e}")
            return False


class AgentPerformanceMonitor:
    """
    Agent 性能监控器

    收集和分析 Agent 的性能指标，管理告警规则，发送通知。

    用法:
        ```python
        monitor = AgentPerformanceMonitor()

        # 添加告警规则
        monitor.add_alert_rule(AlertRule(
            rule_id="low_success",
            name="成功率过低",
            condition="success_rate < 0.7",
            severity=AlertSeverity.CRITICAL,
        ))

        # 记录执行结果
        await monitor.record_execution(
            agent_id="analyzer",
            success=True,
            duration_ms=1500,
            iterations=3,
            verification_score=0.95,
        )

        # 获取指标
        metrics = await monitor.collect_metrics("analyzer")

        # 检查告警
        alerts = await monitor.check_alerts("analyzer")

        # 生成报告
        report = await monitor.generate_report("analyzer")
        ```
    """

    def __init__(
        self,
        metrics_storage: Optional[Any] = None,
        default_notification_channel: Optional[NotificationChannel] = None,
    ):
        """
        初始化性能监控器

        Args:
            metrics_storage: 指标存储后端（可选，默认使用内存存储）
            default_notification_channel: 默认通知渠道
        """
        self._metrics_storage = metrics_storage
        self._notification_channels: Dict[str, NotificationChannel] = {
            "log": LogNotificationChannel(),
        }
        if default_notification_channel:
            self._notification_channels["default"] = default_notification_channel

        # 告警规则
        self._alert_rules: Dict[str, AlertRule] = {}

        # 活跃告警
        self._active_alerts: Dict[str, Alert] = {}

        # 内存存储（如果未提供外部存储）
        self._execution_records: Dict[str, List[Dict[str, Any]]] = {}

        # 默认告警规则
        self._setup_default_rules()

        logger.info("Agent 性能监控器初始化完成")

    def _setup_default_rules(self):
        """设置默认告警规则"""
        default_rules = [
            AlertRule(
                rule_id="low_success_rate_critical",
                name="成功率严重过低",
                condition="success_rate < 0.5",
                severity=AlertSeverity.CRITICAL,
                notification_channels=["log"],
            ),
            AlertRule(
                rule_id="low_success_rate_warning",
                name="成功率过低",
                condition="success_rate < 0.8",
                severity=AlertSeverity.WARNING,
                notification_channels=["log"],
            ),
            AlertRule(
                rule_id="high_latency",
                name="响应时间过长",
                condition="p95_duration_ms > 60000",  # 60秒
                severity=AlertSeverity.WARNING,
                notification_channels=["log"],
            ),
            AlertRule(
                rule_id="low_verification_score",
                name="验证分数过低",
                condition="avg_verification_score < 0.6",
                severity=AlertSeverity.WARNING,
                notification_channels=["log"],
            ),
        ]

        for rule in default_rules:
            self._alert_rules[rule.rule_id] = rule

    # ========== 指标收集 ==========

    async def record_execution(
        self,
        agent_id: str,
        success: bool,
        duration_ms: float,
        iterations: int = 1,
        verification_score: float = 1.0,
        tokens_used: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        记录 Agent 执行结果

        Args:
            agent_id: Agent ID
            success: 是否成功
            duration_ms: 执行时间（毫秒）
            iterations: 迭代次数
            verification_score: 验证分数
            tokens_used: 使用的 token 数
            metadata: 附加元数据
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "duration_ms": duration_ms,
            "iterations": iterations,
            "verification_score": verification_score,
            "tokens_used": tokens_used,
            "metadata": metadata or {},
        }

        # 存储记录
        if agent_id not in self._execution_records:
            self._execution_records[agent_id] = []

        self._execution_records[agent_id].append(record)

        # 限制内存存储大小
        max_records = 10000
        if len(self._execution_records[agent_id]) > max_records:
            self._execution_records[agent_id] = self._execution_records[agent_id][
                -max_records:
            ]

        logger.debug(
            f"记录 Agent {agent_id} 执行: success={success}, duration={duration_ms}ms"
        )

    async def collect_metrics(
        self,
        agent_id: str,
        time_window: timedelta = timedelta(hours=24),
    ) -> AgentMetrics:
        """
        收集 Agent 性能指标

        Args:
            agent_id: Agent ID
            time_window: 统计时间窗口

        Returns:
            AgentMetrics 实例
        """
        # 获取时间范围内的记录
        cutoff_time = datetime.now() - time_window
        records = [
            r
            for r in self._execution_records.get(agent_id, [])
            if datetime.fromisoformat(r["timestamp"]) >= cutoff_time
        ]

        if not records:
            return AgentMetrics(
                agent_id=agent_id,
                time_window_start=cutoff_time,
                time_window_end=datetime.now(),
            )

        # 计算指标
        total = len(records)
        successes = sum(1 for r in records if r["success"])
        durations = [r["duration_ms"] for r in records]
        iterations = [r["iterations"] for r in records]
        scores = [r["verification_score"] for r in records]
        tokens = [r["tokens_used"] for r in records]

        # 计算百分位数
        sorted_durations = sorted(durations)

        def percentile(values: List[float], p: float) -> float:
            if not values:
                return 0.0
            k = (len(values) - 1) * p / 100
            f = int(k)
            c = f + 1 if f + 1 < len(values) else f
            return values[f] + (k - f) * (values[c] - values[f])

        return AgentMetrics(
            agent_id=agent_id,
            total_executions=total,
            successful_executions=successes,
            failed_executions=total - successes,
            total_duration_ms=sum(durations),
            avg_duration_ms=sum(durations) / total,
            min_duration_ms=min(durations),
            max_duration_ms=max(durations),
            p50_duration_ms=percentile(sorted_durations, 50),
            p95_duration_ms=percentile(sorted_durations, 95),
            p99_duration_ms=percentile(sorted_durations, 99),
            avg_iterations=sum(iterations) / total,
            max_iterations=max(iterations),
            avg_verification_score=sum(scores) / total,
            verification_pass_rate=sum(1 for s in scores if s >= 0.6) / total,
            total_tokens_used=sum(tokens),
            avg_tokens_per_execution=sum(tokens) / total,
            time_window_start=cutoff_time,
            time_window_end=datetime.now(),
        )

    # ========== 告警管理 ==========

    def add_alert_rule(self, rule: AlertRule) -> None:
        """添加告警规则"""
        self._alert_rules[rule.rule_id] = rule
        logger.info(f"添加告警规则: {rule.rule_id}")

    def remove_alert_rule(self, rule_id: str) -> bool:
        """移除告警规则"""
        if rule_id in self._alert_rules:
            del self._alert_rules[rule_id]
            return True
        return False

    def get_alert_rules(self) -> List[AlertRule]:
        """获取所有告警规则"""
        return list(self._alert_rules.values())

    async def check_alerts(
        self,
        agent_id: str,
        time_window: timedelta = timedelta(hours=1),
    ) -> List[Alert]:
        """
        检查 Agent 的告警

        Args:
            agent_id: Agent ID
            time_window: 指标统计时间窗口

        Returns:
            触发的告警列表
        """
        metrics = await self.collect_metrics(agent_id, time_window)
        triggered_alerts = []

        for rule in self._alert_rules.values():
            if rule.evaluate(metrics):
                # 检查是否已有活跃告警
                alert_key = f"{agent_id}:{rule.rule_id}"

                if alert_key not in self._active_alerts:
                    # 创建新告警
                    alert = Alert(
                        alert_id=f"{alert_key}:{datetime.now().strftime('%Y%m%d%H%M%S')}",
                        rule=rule,
                        agent_id=agent_id,
                        triggered_at=datetime.now(),
                        metrics_snapshot=metrics.to_dict(),
                        message=f"Agent {agent_id} 触发告警规则 '{rule.name}': {rule.condition}",
                    )

                    self._active_alerts[alert_key] = alert
                    rule.last_triggered = datetime.now()

                    # 发送通知
                    await self._send_notifications(alert)

                    triggered_alerts.append(alert)
                else:
                    triggered_alerts.append(self._active_alerts[alert_key])
            else:
                # 检查是否需要解除告警
                alert_key = f"{agent_id}:{rule.rule_id}"
                if alert_key in self._active_alerts and rule.auto_resolve:
                    alert = self._active_alerts[alert_key]
                    alert.resolved_at = datetime.now()
                    del self._active_alerts[alert_key]
                    logger.info(f"告警已解除: {alert.alert_id}")

        return triggered_alerts

    def get_active_alerts(self, agent_id: Optional[str] = None) -> List[Alert]:
        """获取活跃告警"""
        if agent_id:
            return [a for a in self._active_alerts.values() if a.agent_id == agent_id]
        return list(self._active_alerts.values())

    # ========== 通知 ==========

    def add_notification_channel(self, name: str, channel: NotificationChannel) -> None:
        """添加通知渠道"""
        self._notification_channels[name] = channel

    async def _send_notifications(self, alert: Alert) -> None:
        """发送告警通知"""
        channels_to_use = alert.rule.notification_channels or ["log"]

        for channel_name in channels_to_use:
            channel = self._notification_channels.get(channel_name)
            if channel:
                try:
                    await channel.send(alert)
                except Exception as e:
                    logger.error(f"发送通知失败 ({channel_name}): {e}")

    # ========== 报告生成 ==========

    async def generate_report(
        self,
        agent_id: str,
        time_window: timedelta = timedelta(hours=24),
    ) -> PerformanceReport:
        """
        生成性能报告

        Args:
            agent_id: Agent ID
            time_window: 报告时间范围

        Returns:
            PerformanceReport 实例
        """
        metrics = await self.collect_metrics(agent_id, time_window)
        alerts = self.get_active_alerts(agent_id)

        # 计算趋势
        trends = await self._calculate_trends(agent_id, time_window)

        # 生成建议
        recommendations = self._generate_recommendations(metrics, alerts)

        return PerformanceReport(
            agent_id=agent_id,
            report_id=f"report_{agent_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            generated_at=datetime.now(),
            time_window=time_window,
            metrics=metrics,
            alerts=alerts,
            trends=trends,
            recommendations=recommendations,
        )

    async def _calculate_trends(
        self,
        agent_id: str,
        time_window: timedelta,
    ) -> Dict[str, Any]:
        """计算趋势"""
        # 分两个时间段比较
        half_window = time_window / 2

        current_metrics = await self.collect_metrics(agent_id, half_window)

        # 获取前半段记录
        cutoff_current = datetime.now() - half_window
        cutoff_previous = datetime.now() - time_window

        previous_records = [
            r
            for r in self._execution_records.get(agent_id, [])
            if cutoff_previous
            <= datetime.fromisoformat(r["timestamp"])
            < cutoff_current
        ]

        if not previous_records:
            return {"trend": "insufficient_data"}

        # 计算前半段指标
        prev_success_rate = sum(1 for r in previous_records if r["success"]) / len(
            previous_records
        )
        prev_avg_duration = sum(r["duration_ms"] for r in previous_records) / len(
            previous_records
        )

        # 比较趋势
        success_trend = (
            "improving"
            if current_metrics.success_rate > prev_success_rate
            else (
                "declining"
                if current_metrics.success_rate < prev_success_rate
                else "stable"
            )
        )
        duration_trend = (
            "improving"
            if current_metrics.avg_duration_ms < prev_avg_duration
            else (
                "declining"
                if current_metrics.avg_duration_ms > prev_avg_duration
                else "stable"
            )
        )

        return {
            "success_rate": {
                "current": current_metrics.success_rate,
                "previous": prev_success_rate,
                "trend": success_trend,
                "change": current_metrics.success_rate - prev_success_rate,
            },
            "avg_duration_ms": {
                "current": current_metrics.avg_duration_ms,
                "previous": prev_avg_duration,
                "trend": duration_trend,
                "change": current_metrics.avg_duration_ms - prev_avg_duration,
            },
        }

    def _generate_recommendations(
        self,
        metrics: AgentMetrics,
        alerts: List[Alert],
    ) -> List[str]:
        """生成改进建议"""
        recommendations = []

        # 基于指标生成建议
        if metrics.success_rate < 0.7:
            recommendations.append("成功率偏低，建议检查 Agent 的提示配置和工具可用性")

        if metrics.avg_duration_ms > 30000:
            recommendations.append("平均执行时间较长，考虑优化工具调用或简化任务分解")

        if metrics.avg_iterations > 5:
            recommendations.append("平均迭代次数较高，可能需要优化验证规则或提示明确性")

        if metrics.avg_verification_score < 0.7:
            recommendations.append("验证分数偏低，建议调整输出格式要求或增强背景指令")

        # 基于告警生成建议
        critical_alerts = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        if critical_alerts:
            recommendations.insert(
                0, f"⚠️ 有 {len(critical_alerts)} 个严重告警需要立即处理"
            )

        if not recommendations:
            recommendations.append("Agent 运行状况良好，无需特别优化")

        return recommendations


# 导出
__all__ = [
    # 枚举
    "AlertSeverity",
    "MetricType",
    # 数据类
    "Metric",
    "AgentMetrics",
    "AlertRule",
    "Alert",
    "PerformanceReport",
    # 通知渠道
    "NotificationChannel",
    "LogNotificationChannel",
    "WebhookNotificationChannel",
    # 核心类
    "AgentPerformanceMonitor",
]

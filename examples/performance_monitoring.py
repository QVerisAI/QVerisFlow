"""
性能监控示例

展示如何使用 AgentPerformanceMonitor 进行 Agent 性能监控和告警。

运行方式：
    python -m examples performance_monitoring
"""

import asyncio
from typing import Dict, Any

from src.evolution.performance_monitor import (
    AgentPerformanceMonitor,
    AlertRule,
    AlertSeverity,
    LogNotificationChannel,
)


async def run_performance_monitoring():
    """运行性能监控示例"""
    print("=" * 60)
    print("性能监控示例")
    print("=" * 60)

    # 1. 创建性能监控器
    monitor = AgentPerformanceMonitor()

    # 2. 配置告警规则
    rules = [
        AlertRule(
            rule_id="low_success_rate",
            name="成功率低于阈值",
            severity=AlertSeverity.WARNING,
            condition="success_rate < 0.8",
        ),
        AlertRule(
            rule_id="high_error_rate",
            name="错误率过高",
            severity=AlertSeverity.CRITICAL,
            condition="success_rate < 0.5",
        ),
        AlertRule(
            rule_id="slow_execution",
            name="执行时间过长",
            severity=AlertSeverity.WARNING,
            condition="avg_duration_seconds > 30.0",
        ),
    ]

    for rule in rules:
        monitor.add_alert_rule(rule)

    print(f"\n已配置 {len(rules)} 条告警规则")

    # 3. 添加通知渠道
    monitor.add_notification_channel("log", LogNotificationChannel())
    print("已添加日志通知渠道")

    # 4. 模拟收集执行指标
    print("\n模拟 Agent 执行并收集指标...")

    executions = [
        {
            "agent_id": "analyst_001",
            "success": True,
            "duration_ms": 5200,
            "iterations": 3,
            "tokens": 1500,
        },
        {
            "agent_id": "analyst_001",
            "success": True,
            "duration_ms": 4800,
            "iterations": 2,
            "tokens": 1200,
        },
        {
            "agent_id": "analyst_001",
            "success": False,
            "duration_ms": 10100,
            "iterations": 5,
            "tokens": 2500,
        },
        {
            "agent_id": "analyst_001",
            "success": True,
            "duration_ms": 6300,
            "iterations": 4,
            "tokens": 1800,
        },
        {
            "agent_id": "analyst_002",
            "success": True,
            "duration_ms": 35500,
            "iterations": 8,
            "tokens": 8000,
        },
        {
            "agent_id": "analyst_002",
            "success": False,
            "duration_ms": 40200,
            "iterations": 10,
            "tokens": 10000,
        },
        {
            "agent_id": "analyst_002",
            "success": False,
            "duration_ms": 38100,
            "iterations": 10,
            "tokens": 9500,
        },
    ]

    for exec_data in executions:
        await monitor.record_execution(
            agent_id=exec_data["agent_id"],
            success=exec_data["success"],
            duration_ms=exec_data["duration_ms"],
            iterations=exec_data["iterations"],
            tokens_used=exec_data["tokens"],
        )

    print(f"已记录 {len(executions)} 条执行记录")

    # 5. 收集并展示指标
    print("\n" + "-" * 40)
    print("Agent 性能指标")
    print("-" * 40)

    for agent_id in ["analyst_001", "analyst_002"]:
        metrics = await monitor.collect_metrics(agent_id)
        if metrics:
            print(f"\n{agent_id}:")
            print(f"  执行次数: {metrics.total_executions}")
            print(f"  成功率: {metrics.success_rate:.2%}")
            print(f"  平均时长: {metrics.avg_duration_ms:.2f}ms")
            print(f"  平均迭代: {metrics.avg_iterations:.1f}")
            print(f"  总 Tokens: {metrics.total_tokens_used}")

    # 6. 检查告警
    print("\n" + "-" * 40)
    print("检查告警")
    print("-" * 40)

    for agent_id in ["analyst_001", "analyst_002"]:
        alerts = await monitor.check_alerts(agent_id)
        if alerts:
            print(f"\n{agent_id} 触发的告警:")
            for alert in alerts:
                severity_icon = {
                    AlertSeverity.INFO: "ℹ️",
                    AlertSeverity.WARNING: "⚠️",
                    AlertSeverity.CRITICAL: "🚨",
                }.get(alert.severity, "❓")

                print(
                    f"  {severity_icon} [{alert.severity.value.upper()}] {alert.rule_name}"
                )
                print(f"     消息: {alert.message}")
        else:
            print(f"\n{agent_id}: 无告警")

    # 7. 生成性能报告
    print("\n" + "-" * 40)
    print("性能报告")
    print("-" * 40)

    for agent_id in ["analyst_001", "analyst_002"]:
        report = await monitor.generate_report(agent_id)
        print(f"\n{agent_id} 报告:")
        print(f"  报告 ID: {report.report_id}")
        print(f"  报告时间: {report.generated_at}")
        print(f"  总执行次数: {report.metrics.total_executions}")
        print(f"  成功率: {report.metrics.success_rate:.2%}")
        print(f"  触发告警数: {len(report.alerts)}")
        if report.recommendations:
            print(f"  建议: {report.recommendations[0]}")

    print("\n" + "=" * 60)
    print("性能监控示例完成")
    print("=" * 60)


async def run_example(verbose: bool = False):
    """示例入口"""
    await run_performance_monitoring()
    return {"status": "success"}


async def main():
    """主函数"""
    await run_example()


if __name__ == "__main__":
    asyncio.run(main())

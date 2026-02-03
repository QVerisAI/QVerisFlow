"""
指标收集

提供框架的指标收集能力，支持：
- Counter（计数器）
- Gauge（仪表）
- Histogram（直方图）
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import threading
import time

from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class MetricPoint:
    """指标数据点"""

    value: float
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)


class Metric:
    """指标基类"""

    def __init__(
        self, name: str, description: str = "", labels: Optional[List[str]] = None
    ):
        self.name = name
        self.description = description
        self.label_names = labels or []
        self._lock = threading.Lock()


class Counter(Metric):
    """
    计数器

    只能递增的指标，用于统计事件次数
    """

    def __init__(
        self, name: str, description: str = "", labels: Optional[List[str]] = None
    ):
        super().__init__(name, description, labels)
        self._values: Dict[tuple, float] = defaultdict(float)

    def inc(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """递增计数器"""
        if value < 0:
            raise ValueError("Counter 只能递增")

        label_key = self._get_label_key(labels)
        with self._lock:
            self._values[label_key] += value

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """获取当前值"""
        label_key = self._get_label_key(labels)
        return self._values.get(label_key, 0.0)

    def _get_label_key(self, labels: Optional[Dict[str, str]]) -> tuple:
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def collect(self) -> List[MetricPoint]:
        """收集所有指标点"""
        points = []
        now = time.time()
        for label_key, value in self._values.items():
            points.append(
                MetricPoint(
                    value=value,
                    timestamp=now,
                    labels=dict(label_key),
                )
            )
        return points


class Gauge(Metric):
    """
    仪表

    可以任意增减的指标，用于表示当前状态
    """

    def __init__(
        self, name: str, description: str = "", labels: Optional[List[str]] = None
    ):
        super().__init__(name, description, labels)
        self._values: Dict[tuple, float] = defaultdict(float)

    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """设置值"""
        label_key = self._get_label_key(labels)
        with self._lock:
            self._values[label_key] = value

    def inc(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """递增"""
        label_key = self._get_label_key(labels)
        with self._lock:
            self._values[label_key] += value

    def dec(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """递减"""
        label_key = self._get_label_key(labels)
        with self._lock:
            self._values[label_key] -= value

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """获取当前值"""
        label_key = self._get_label_key(labels)
        return self._values.get(label_key, 0.0)

    def _get_label_key(self, labels: Optional[Dict[str, str]]) -> tuple:
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def collect(self) -> List[MetricPoint]:
        """收集所有指标点"""
        points = []
        now = time.time()
        for label_key, value in self._values.items():
            points.append(
                MetricPoint(
                    value=value,
                    timestamp=now,
                    labels=dict(label_key),
                )
            )
        return points


class Histogram(Metric):
    """
    直方图

    用于统计分布，如请求延迟
    """

    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

    def __init__(
        self,
        name: str,
        description: str = "",
        labels: Optional[List[str]] = None,
        buckets: Optional[List[float]] = None,
    ):
        super().__init__(name, description, labels)
        self.buckets = sorted(buckets or self.DEFAULT_BUCKETS)
        self._bucket_counts: Dict[tuple, Dict[float, int]] = defaultdict(
            lambda: {b: 0 for b in self.buckets + [float("inf")]}
        )
        self._sums: Dict[tuple, float] = defaultdict(float)
        self._counts: Dict[tuple, int] = defaultdict(int)

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """观察一个值"""
        label_key = self._get_label_key(labels)
        with self._lock:
            self._sums[label_key] += value
            self._counts[label_key] += 1

            for bucket in self.buckets + [float("inf")]:
                if value <= bucket:
                    self._bucket_counts[label_key][bucket] += 1

    def get_sum(self, labels: Optional[Dict[str, str]] = None) -> float:
        """获取总和"""
        label_key = self._get_label_key(labels)
        return self._sums.get(label_key, 0.0)

    def get_count(self, labels: Optional[Dict[str, str]] = None) -> int:
        """获取计数"""
        label_key = self._get_label_key(labels)
        return self._counts.get(label_key, 0)

    def get_average(self, labels: Optional[Dict[str, str]] = None) -> float:
        """获取平均值"""
        count = self.get_count(labels)
        if count == 0:
            return 0.0
        return self.get_sum(labels) / count

    def _get_label_key(self, labels: Optional[Dict[str, str]]) -> tuple:
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def collect(self) -> List[MetricPoint]:
        """收集所有指标点"""
        points = []
        now = time.time()

        for label_key in self._counts.keys():
            labels = dict(label_key)

            # Sum
            points.append(
                MetricPoint(
                    value=self._sums[label_key],
                    timestamp=now,
                    labels={**labels, "type": "sum"},
                )
            )

            # Count
            points.append(
                MetricPoint(
                    value=self._counts[label_key],
                    timestamp=now,
                    labels={**labels, "type": "count"},
                )
            )

            # Buckets
            for bucket, count in self._bucket_counts[label_key].items():
                points.append(
                    MetricPoint(
                        value=count,
                        timestamp=now,
                        labels={**labels, "type": "bucket", "le": str(bucket)},
                    )
                )

        return points


class MetricsCollector:
    """
    指标收集器

    管理所有指标的注册和收集
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._metrics: Dict[str, Metric] = {}
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "MetricsCollector":
        """获取单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def counter(
        self,
        name: str,
        description: str = "",
        labels: Optional[List[str]] = None,
    ) -> Counter:
        """创建或获取计数器"""
        if name not in self._metrics:
            self._metrics[name] = Counter(name, description, labels)
        return self._metrics[name]

    def gauge(
        self,
        name: str,
        description: str = "",
        labels: Optional[List[str]] = None,
    ) -> Gauge:
        """创建或获取仪表"""
        if name not in self._metrics:
            self._metrics[name] = Gauge(name, description, labels)
        return self._metrics[name]

    def histogram(
        self,
        name: str,
        description: str = "",
        labels: Optional[List[str]] = None,
        buckets: Optional[List[float]] = None,
    ) -> Histogram:
        """创建或获取直方图"""
        if name not in self._metrics:
            self._metrics[name] = Histogram(name, description, labels, buckets)
        return self._metrics[name]

    def collect_all(self) -> Dict[str, List[MetricPoint]]:
        """收集所有指标"""
        result = {}
        for name, metric in self._metrics.items():
            result[name] = metric.collect()
        return result

    def get_metric(self, name: str) -> Optional[Metric]:
        """获取指标"""
        return self._metrics.get(name)

    def list_metrics(self) -> List[str]:
        """列出所有指标名"""
        return list(self._metrics.keys())


# 全局指标收集器
_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """获取全局指标收集器"""
    global _collector
    if _collector is None:
        _collector = MetricsCollector.get_instance()
    return _collector


# 预定义的框架指标
def _setup_default_metrics():
    """设置默认指标"""
    collector = get_metrics_collector()

    # Agent 相关指标
    collector.counter(
        "agent_runs_total",
        "Agent 运行总次数",
        ["agent_id", "status"],
    )
    collector.histogram(
        "agent_run_duration_seconds",
        "Agent 运行耗时",
        ["agent_id"],
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
    )
    collector.gauge(
        "agent_active_runs",
        "当前活跃的 Agent 运行数",
        ["agent_id"],
    )

    # 工具相关指标
    collector.counter(
        "tool_calls_total",
        "工具调用总次数",
        ["tool_id", "status"],
    )
    collector.histogram(
        "tool_call_duration_seconds",
        "工具调用耗时",
        ["tool_id"],
    )

    # 工作流相关指标
    collector.counter(
        "workflow_runs_total",
        "工作流运行总次数",
        ["workflow_id", "status"],
    )
    collector.histogram(
        "workflow_run_duration_seconds",
        "工作流运行耗时",
        ["workflow_id"],
    )

    # Token 使用指标
    collector.counter(
        "llm_tokens_total",
        "LLM Token 使用总量",
        ["model", "type"],  # type: input/output
    )
    collector.counter(
        "llm_calls_total",
        "LLM 调用总次数",
        ["model", "status"],
    )


# 初始化默认指标
_setup_default_metrics()

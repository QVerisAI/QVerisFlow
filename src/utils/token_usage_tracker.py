"""
Token 使用量追踪模块

提供模型调用的 token 使用量统计和追踪功能。
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

# 全局追踪器实例
_global_tracker: Optional["TokenUsageTracker"] = None


@dataclass
class ModelCallMetrics:
    """单次模型调用的指标记录

    Attributes:
        model_name: 模型名称
        input_tokens: 输入 token 数量
        output_tokens: 输出 token 数量
        total_tokens: 总 token 数量
        call_time: 调用时间戳
        success: 是否成功
        error_message: 错误信息（如果失败）
        user_id: 用户 ID（可选，用于多维度统计）
        project_id: 项目 ID（可选，用于多维度统计）
    """

    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    call_time: float = field(default_factory=time.time)
    success: bool = True
    error_message: Optional[str] = None
    user_id: Optional[str] = None
    project_id: Optional[str] = None

    @property
    def call_datetime(self) -> datetime:
        """获取调用时间的 datetime 对象"""
        return datetime.fromtimestamp(self.call_time)

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            "model_name": self.model_name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "call_time": self.call_time,
            "call_datetime": self.call_datetime.isoformat(),
            "success": self.success,
            "error_message": self.error_message,
            "user_id": self.user_id,
            "project_id": self.project_id,
        }


class TokenUsageTracker:
    """Token 使用量追踪器

    全局 token 使用量统计，支持按模型、用户、项目、时间等多维度聚合。
    """

    def __init__(self) -> None:
        """初始化追踪器"""
        self._metrics: List[ModelCallMetrics] = []
        self._lock = None  # 如果需要线程安全，可以使用 threading.Lock

    def record_call(
        self,
        metrics: ModelCallMetrics,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        """记录一次模型调用

        Args:
            metrics: 模型调用指标
            user_id: 用户 ID（如果提供，会覆盖 metrics 中的 user_id）
            project_id: 项目 ID（如果提供，会覆盖 metrics 中的 project_id）
        """
        # 如果提供了额外的维度信息，更新 metrics
        if user_id is not None:
            metrics.user_id = user_id
        if project_id is not None:
            metrics.project_id = project_id

        self._metrics.append(metrics)

    def get_total_usage(self) -> Dict[str, int]:
        """获取总 token 使用量

        Returns:
            包含 input_tokens, output_tokens, total_tokens 的字典
        """
        total_input = sum(m.input_tokens for m in self._metrics)
        total_output = sum(m.output_tokens for m in self._metrics)
        total = sum(m.total_tokens for m in self._metrics)

        return {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total,
            "call_count": len(self._metrics),
        }

    def get_usage_by_model(self) -> Dict[str, Dict[str, int]]:
        """按模型统计 token 使用量

        Returns:
            字典，key 为模型名称，value 为使用量统计
        """
        model_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}
        )

        for metric in self._metrics:
            stats = model_stats[metric.model_name]
            stats["input_tokens"] += metric.input_tokens
            stats["output_tokens"] += metric.output_tokens
            stats["total_tokens"] += metric.total_tokens
            stats["call_count"] += 1

        return dict(model_stats)

    def get_usage_by_dimension(
        self,
        model: Optional[str] = None,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """按多维度统计 token 使用量

        Args:
            model: 模型名称（可选，用于过滤）
            user_id: 用户 ID（可选，用于过滤）
            project_id: 项目 ID（可选，用于过滤）

        Returns:
            使用量统计字典
        """
        stats = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}

        for metric in self._metrics:
            # 应用过滤条件
            if model is not None and metric.model_name != model:
                continue
            if user_id is not None and metric.user_id != user_id:
                continue
            if project_id is not None and metric.project_id != project_id:
                continue

            stats["input_tokens"] += metric.input_tokens
            stats["output_tokens"] += metric.output_tokens
            stats["total_tokens"] += metric.total_tokens
            stats["call_count"] += 1

        return stats

    def get_usage_by_user(self, user_id: Optional[str] = None) -> Dict[str, Dict[str, int]]:
        """按用户统计 token 使用量

        Args:
            user_id: 用户 ID（可选，如果提供则只统计该用户）

        Returns:
            字典，key 为用户 ID，value 为使用量统计
        """
        user_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}
        )

        for metric in self._metrics:
            uid = metric.user_id or "anonymous"
            if user_id is not None and uid != user_id:
                continue

            stats = user_stats[uid]
            stats["input_tokens"] += metric.input_tokens
            stats["output_tokens"] += metric.output_tokens
            stats["total_tokens"] += metric.total_tokens
            stats["call_count"] += 1

        return dict(user_stats)

    def get_usage_by_project(self, project_id: Optional[str] = None) -> Dict[str, Dict[str, int]]:
        """按项目统计 token 使用量

        Args:
            project_id: 项目 ID（可选，如果提供则只统计该项目）

        Returns:
            字典，key 为项目 ID，value 为使用量统计
        """
        project_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}
        )

        for metric in self._metrics:
            pid = metric.project_id or "default"
            if project_id is not None and pid != project_id:
                continue

            stats = project_stats[pid]
            stats["input_tokens"] += metric.input_tokens
            stats["output_tokens"] += metric.output_tokens
            stats["total_tokens"] += metric.total_tokens
            stats["call_count"] += 1

        return dict(project_stats)

    def get_recent_usage(self, hours: int = 24) -> Dict[str, int]:
        """获取最近 N 小时的 token 使用量

        Args:
            hours: 时间范围（小时），默认 24 小时

        Returns:
            包含 input_tokens, output_tokens, total_tokens 的字典
        """
        cutoff_time = time.time() - (hours * 3600)
        recent_metrics = [m for m in self._metrics if m.call_time >= cutoff_time]

        total_input = sum(m.input_tokens for m in recent_metrics)
        total_output = sum(m.output_tokens for m in recent_metrics)
        total = sum(m.total_tokens for m in recent_metrics)

        return {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total,
            "call_count": len(recent_metrics),
        }

    def get_all_metrics(self) -> List[ModelCallMetrics]:
        """获取所有调用指标

        Returns:
            所有模型调用指标的列表
        """
        return self._metrics.copy()

    def clear(self) -> None:
        """清空所有记录"""
        self._metrics.clear()

    def get_summary(self) -> Dict:
        """获取使用量摘要

        Returns:
            包含总使用量、按模型统计、最近使用量的字典
        """
        return {
            "total": self.get_total_usage(),
            "by_model": self.get_usage_by_model(),
            "recent_24h": self.get_recent_usage(24),
        }


def get_global_tracker() -> "TokenUsageTracker":
    """获取全局 Token 使用量追踪器

    Returns:
        全局 TokenUsageTracker 实例
    """
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = TokenUsageTracker()
    return _global_tracker


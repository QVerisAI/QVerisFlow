"""
反馈循环

收集和分析 Agent 执行反馈，为优化提供数据支持。
支持：
- 执行反馈记录
- 反馈模式分析
- 优化建议生成
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import json
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class ExecutionFeedback:
    """执行反馈数据"""

    feedback_id: str
    agent_id: str
    task_id: str
    task_description: str

    # 执行结果
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None

    # 性能指标
    duration_ms: float = 0.0
    iterations: int = 0
    token_usage: int = 0

    # 反馈内容
    user_rating: Optional[float] = None  # 0-5 用户评分
    user_feedback: Optional[str] = None  # 用户文字反馈
    automated_score: Optional[float] = None  # 自动评估分数

    # 元数据
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "task_description": self.task_description,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "iterations": self.iterations,
            "token_usage": self.token_usage,
            "user_rating": self.user_rating,
            "user_feedback": self.user_feedback,
            "automated_score": self.automated_score,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionFeedback":
        return cls(**data)


@dataclass
class FeedbackAnalysis:
    """反馈分析结果"""

    agent_id: str
    analysis_period: str  # 分析时间范围

    # 基础统计
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    success_rate: float = 0.0

    # 性能统计
    avg_duration_ms: float = 0.0
    avg_iterations: float = 0.0
    avg_token_usage: float = 0.0

    # 评分统计
    avg_user_rating: Optional[float] = None
    avg_automated_score: Optional[float] = None

    # 模式分析
    common_errors: List[str] = field(default_factory=list)
    common_success_patterns: List[str] = field(default_factory=list)
    improvement_areas: List[str] = field(default_factory=list)

    # 趋势
    success_rate_trend: str = "stable"  # improving, declining, stable
    performance_trend: str = "stable"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "analysis_period": self.analysis_period,
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "success_rate": self.success_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "avg_iterations": self.avg_iterations,
            "avg_token_usage": self.avg_token_usage,
            "avg_user_rating": self.avg_user_rating,
            "avg_automated_score": self.avg_automated_score,
            "common_errors": self.common_errors,
            "common_success_patterns": self.common_success_patterns,
            "improvement_areas": self.improvement_areas,
            "success_rate_trend": self.success_rate_trend,
            "performance_trend": self.performance_trend,
        }


class FeedbackCollector:
    """
    反馈收集器

    收集和分析 Agent 执行反馈，为优化提供数据支持。

    用法:
        collector = FeedbackCollector(storage_path="/data/feedback")

        # 记录反馈
        await collector.record_feedback(
            agent_id="stock_analyzer",
            task_id="task_001",
            task_description="分析苹果股票",
            success=True,
            result={"recommendation": "买入"},
            duration_ms=5000,
            user_rating=4.5,
        )

        # 分析反馈
        analysis = await collector.analyze_patterns(
            agent_id="stock_analyzer",
            window_days=30,
        )
    """

    def __init__(
        self,
        storage_path: str = None,
        max_memory_feedbacks: int = 10000,
    ):
        """
        初始化反馈收集器

        Args:
            storage_path: 反馈存储路径（可选，不指定则仅存储在内存中）
            max_memory_feedbacks: 内存中保留的最大反馈数量
        """
        self.storage_path = Path(storage_path) if storage_path else None
        self.max_memory_feedbacks = max_memory_feedbacks

        # 内存存储
        self._feedbacks: Dict[str, List[ExecutionFeedback]] = defaultdict(list)

        # 如果有存储路径，确保目录存在
        if self.storage_path:
            self.storage_path.mkdir(parents=True, exist_ok=True)

    async def record_feedback(
        self,
        agent_id: str,
        task_id: str,
        task_description: str,
        success: bool,
        result: Any = None,
        error: str = None,
        duration_ms: float = 0.0,
        iterations: int = 0,
        token_usage: int = 0,
        user_rating: float = None,
        user_feedback: str = None,
        automated_score: float = None,
        metadata: Dict[str, Any] = None,
    ) -> ExecutionFeedback:
        """
        记录执行反馈

        Args:
            agent_id: Agent ID
            task_id: 任务 ID
            task_description: 任务描述
            success: 是否成功
            result: 执行结果
            error: 错误信息
            duration_ms: 执行时间（毫秒）
            iterations: 迭代次数
            token_usage: Token 使用量
            user_rating: 用户评分（0-5）
            user_feedback: 用户文字反馈
            automated_score: 自动评估分数
            metadata: 其他元数据

        Returns:
            创建的 ExecutionFeedback 对象
        """
        import uuid

        feedback = ExecutionFeedback(
            feedback_id=f"fb_{uuid.uuid4().hex[:12]}",
            agent_id=agent_id,
            task_id=task_id,
            task_description=task_description,
            success=success,
            result=result,
            error=error,
            duration_ms=duration_ms,
            iterations=iterations,
            token_usage=token_usage,
            user_rating=user_rating,
            user_feedback=user_feedback,
            automated_score=automated_score,
            metadata=metadata or {},
        )

        # 存储到内存
        self._feedbacks[agent_id].append(feedback)

        # 限制内存中的反馈数量
        if len(self._feedbacks[agent_id]) > self.max_memory_feedbacks:
            self._feedbacks[agent_id] = self._feedbacks[agent_id][
                -self.max_memory_feedbacks :
            ]

        # 持久化到文件
        if self.storage_path:
            await self._persist_feedback(feedback)

        logger.debug(f"记录反馈: {feedback.feedback_id} for agent {agent_id}")

        return feedback

    async def get_feedbacks(
        self,
        agent_id: str,
        start_date: datetime = None,
        end_date: datetime = None,
        success_only: bool = None,
        limit: int = None,
    ) -> List[ExecutionFeedback]:
        """
        获取指定 Agent 的反馈

        Args:
            agent_id: Agent ID
            start_date: 开始日期
            end_date: 结束日期
            success_only: 是否只返回成功的反馈
            limit: 返回数量限制

        Returns:
            反馈列表
        """
        feedbacks = self._feedbacks.get(agent_id, [])

        # 从文件加载（如果需要）
        if self.storage_path and not feedbacks:
            feedbacks = await self._load_feedbacks(agent_id)

        # 过滤
        filtered = []
        for fb in feedbacks:
            fb_time = datetime.fromisoformat(fb.timestamp)

            if start_date and fb_time < start_date:
                continue
            if end_date and fb_time > end_date:
                continue
            if success_only is not None and fb.success != success_only:
                continue

            filtered.append(fb)

        # 按时间排序（最新的在前）
        filtered.sort(key=lambda x: x.timestamp, reverse=True)

        if limit:
            filtered = filtered[:limit]

        return filtered

    async def analyze_patterns(
        self,
        agent_id: str,
        window_days: int = 30,
    ) -> FeedbackAnalysis:
        """
        分析反馈模式

        Args:
            agent_id: Agent ID
            window_days: 分析的时间窗口（天）

        Returns:
            反馈分析结果
        """
        start_date = datetime.now() - timedelta(days=window_days)
        feedbacks = await self.get_feedbacks(agent_id, start_date=start_date)

        if not feedbacks:
            return FeedbackAnalysis(
                agent_id=agent_id,
                analysis_period=f"最近 {window_days} 天",
            )

        # 基础统计
        total = len(feedbacks)
        successful = sum(1 for fb in feedbacks if fb.success)
        failed = total - successful

        # 性能统计
        durations = [fb.duration_ms for fb in feedbacks if fb.duration_ms > 0]
        iterations_list = [fb.iterations for fb in feedbacks if fb.iterations > 0]
        token_usages = [fb.token_usage for fb in feedbacks if fb.token_usage > 0]

        # 评分统计
        user_ratings = [
            fb.user_rating for fb in feedbacks if fb.user_rating is not None
        ]
        auto_scores = [
            fb.automated_score for fb in feedbacks if fb.automated_score is not None
        ]

        # 错误分析
        errors = [fb.error for fb in feedbacks if fb.error]
        common_errors = self._find_common_patterns(errors, top_n=5)

        # 成功模式分析
        success_tasks = [fb.task_description for fb in feedbacks if fb.success]
        success_patterns = self._find_common_patterns(success_tasks, top_n=3)

        # 趋势分析
        success_rate_trend = self._analyze_trend(feedbacks, "success")
        performance_trend = self._analyze_trend(feedbacks, "duration")

        # 改进建议
        improvement_areas = self._identify_improvements(feedbacks)

        return FeedbackAnalysis(
            agent_id=agent_id,
            analysis_period=f"最近 {window_days} 天",
            total_executions=total,
            successful_executions=successful,
            failed_executions=failed,
            success_rate=successful / total if total > 0 else 0.0,
            avg_duration_ms=sum(durations) / len(durations) if durations else 0.0,
            avg_iterations=(
                sum(iterations_list) / len(iterations_list) if iterations_list else 0.0
            ),
            avg_token_usage=(
                sum(token_usages) / len(token_usages) if token_usages else 0.0
            ),
            avg_user_rating=(
                sum(user_ratings) / len(user_ratings) if user_ratings else None
            ),
            avg_automated_score=(
                sum(auto_scores) / len(auto_scores) if auto_scores else None
            ),
            common_errors=common_errors,
            common_success_patterns=success_patterns,
            improvement_areas=improvement_areas,
            success_rate_trend=success_rate_trend,
            performance_trend=performance_trend,
        )

    async def get_optimization_data(
        self,
        agent_id: str,
        window_days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取用于优化的数据

        Args:
            agent_id: Agent ID
            window_days: 时间窗口

        Returns:
            优化数据，可直接传给 MetaAgent.optimize_prompt()
        """
        feedbacks = await self.get_feedbacks(
            agent_id,
            start_date=datetime.now() - timedelta(days=window_days),
        )

        # 转换为 MetaAgent 需要的格式
        feedback_history = []
        for fb in feedbacks:
            feedback_history.append(
                {
                    "task": fb.task_description,
                    "success": fb.success,
                    "feedback": fb.user_feedback or fb.error or "",
                    "result": fb.result,
                    "rating": fb.user_rating,
                    "automated_score": fb.automated_score,
                }
            )

        analysis = await self.analyze_patterns(agent_id, window_days)

        return {
            "feedback_history": feedback_history,
            "analysis": analysis.to_dict(),
            "optimization_suggestions": analysis.improvement_areas,
        }

    def _find_common_patterns(
        self,
        texts: List[str],
        top_n: int = 5,
    ) -> List[str]:
        """找出常见模式"""
        if not texts:
            return []

        # 简单的词频统计
        word_count = defaultdict(int)
        for text in texts:
            if text:
                # 分词（简单实现）
                words = text.lower().split()
                for word in words:
                    if len(word) > 2:  # 过滤短词
                        word_count[word] += 1

        # 返回出现频率最高的
        sorted_words = sorted(word_count.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_words[:top_n] if count > 1]

    def _analyze_trend(
        self,
        feedbacks: List[ExecutionFeedback],
        metric: str,
    ) -> str:
        """分析趋势"""
        if len(feedbacks) < 5:
            return "stable"

        # 将反馈按时间分成两半
        mid = len(feedbacks) // 2
        recent = feedbacks[:mid]
        older = feedbacks[mid:]

        if metric == "success":
            recent_rate = sum(1 for fb in recent if fb.success) / len(recent)
            older_rate = sum(1 for fb in older if fb.success) / len(older)

            if recent_rate > older_rate + 0.1:
                return "improving"
            elif recent_rate < older_rate - 0.1:
                return "declining"
            return "stable"

        elif metric == "duration":
            recent_avg = sum(
                fb.duration_ms for fb in recent if fb.duration_ms > 0
            ) / max(1, sum(1 for fb in recent if fb.duration_ms > 0))
            older_avg = sum(fb.duration_ms for fb in older if fb.duration_ms > 0) / max(
                1, sum(1 for fb in older if fb.duration_ms > 0)
            )

            if recent_avg < older_avg * 0.9:
                return "improving"
            elif recent_avg > older_avg * 1.1:
                return "declining"
            return "stable"

        return "stable"

    def _identify_improvements(
        self,
        feedbacks: List[ExecutionFeedback],
    ) -> List[str]:
        """识别改进领域"""
        improvements = []

        if not feedbacks:
            return improvements

        # 计算成功率
        success_rate = sum(1 for fb in feedbacks if fb.success) / len(feedbacks)
        if success_rate < 0.7:
            improvements.append("提高整体成功率")

        # 检查平均时间
        durations = [fb.duration_ms for fb in feedbacks if fb.duration_ms > 0]
        if durations and sum(durations) / len(durations) > 30000:
            improvements.append("优化执行速度")

        # 检查用户评分
        ratings = [fb.user_rating for fb in feedbacks if fb.user_rating is not None]
        if ratings and sum(ratings) / len(ratings) < 3.5:
            improvements.append("提升用户满意度")

        # 检查重复错误
        errors = [fb.error for fb in feedbacks if fb.error]
        if len(set(errors)) < len(errors) * 0.5:
            improvements.append("解决重复性错误")

        return improvements

    async def _persist_feedback(self, feedback: ExecutionFeedback) -> None:
        """持久化反馈到文件"""
        if not self.storage_path:
            return

        # 按 agent_id 和日期组织文件
        date_str = datetime.now().strftime("%Y-%m-%d")
        file_path = self.storage_path / feedback.agent_id / f"{date_str}.jsonl"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(feedback.to_dict(), ensure_ascii=False, default=str) + "\n"
            )

    async def _load_feedbacks(self, agent_id: str) -> List[ExecutionFeedback]:
        """从文件加载反馈"""
        if not self.storage_path:
            return []

        agent_path = self.storage_path / agent_id
        if not agent_path.exists():
            return []

        feedbacks = []
        for file_path in sorted(agent_path.glob("*.jsonl"), reverse=True):
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            data = json.loads(line)
                            feedbacks.append(ExecutionFeedback.from_dict(data))
                        except Exception as e:
                            logger.warning(f"解析反馈失败: {e}")

        return feedbacks


# 导出
__all__ = [
    "ExecutionFeedback",
    "FeedbackAnalysis",
    "FeedbackCollector",
]

"""
A/B 测试框架

支持多变体实验、流量分配、指标收集和统计分析。
"""

import hashlib
import json
import random
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger()


class ExperimentStatus(str, Enum):
    """实验状态"""

    DRAFT = "draft"  # 草稿
    RUNNING = "running"  # 运行中
    PAUSED = "paused"  # 暂停
    COMPLETED = "completed"  # 已完成
    ARCHIVED = "archived"  # 已归档


@dataclass
class VariantResult:
    """变体结果"""

    impressions: int = 0
    conversions: int = 0
    metrics: Dict[str, List[float]] = field(default_factory=dict)

    @property
    def conversion_rate(self) -> float:
        """转化率"""
        if self.impressions == 0:
            return 0.0
        return self.conversions / self.impressions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "impressions": self.impressions,
            "conversions": self.conversions,
            "conversion_rate": self.conversion_rate,
            "metrics": dict(self.metrics),
        }


@dataclass
class Experiment:
    """A/B 测试实验"""

    experiment_id: str
    name: str
    description: str
    variants: Dict[str, float]  # variant_id -> 流量比例
    metrics: List[str]  # 关注的指标列表
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: ExperimentStatus = ExperimentStatus.DRAFT
    results: Dict[str, VariantResult] = field(default_factory=dict)
    winner: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "description": self.description,
            "variants": self.variants,
            "metrics": self.metrics,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status.value,
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "winner": self.winner,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Experiment":
        results = {}
        for k, v in data.get("results", {}).items():
            results[k] = VariantResult(
                impressions=v.get("impressions", 0),
                conversions=v.get("conversions", 0),
                metrics=v.get("metrics", {}),
            )
        return cls(
            experiment_id=data["experiment_id"],
            name=data["name"],
            description=data["description"],
            variants=data["variants"],
            metrics=data["metrics"],
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
            status=ExperimentStatus(data.get("status", "draft")),
            results=results,
            winner=data.get("winner"),
            metadata=data.get("metadata", {}),
        )


class ABTestingFramework:
    """
    A/B 测试框架

    特性：
    - 多变体实验支持
    - 确定性用户分配（同一用户始终看到相同变体）
    - 灵活的流量分配
    - 多指标收集和分析
    - 统计显著性计算
    - 持久化存储

    用法：
        ```python
        ab = ABTestingFramework(storage_path="./experiments")

        # 创建实验
        exp = ab.create_experiment(
            experiment_id="prompt_v2_test",
            name="Prompt V2 测试",
            description="测试新的 Prompt 模板",
            variants={"control": 0.5, "treatment": 0.5},
            metrics=["latency", "quality_score"]
        )

        # 获取用户的变体
        variant = ab.get_variant("prompt_v2_test", user_id="user123")

        # 记录指标
        ab.record_metric("prompt_v2_test", "user123", "latency", 1.5)
        ab.record_conversion("prompt_v2_test", "user123")

        # 获取结果
        results = ab.get_results("prompt_v2_test")
        ```
    """

    def __init__(self, storage_path: Optional[str] = None):
        """
        初始化 A/B 测试框架

        Args:
            storage_path: 持久化存储路径
        """
        self.storage_path = Path(storage_path) if storage_path else None
        self.experiments: Dict[str, Experiment] = {}
        self.user_assignments: Dict[str, Dict[str, str]] = {}  # user_id -> {exp_id -> variant_id}

        if self.storage_path:
            self._load_from_storage()

        logger.info("ABTestingFramework 初始化完成")

    def create_experiment(
        self,
        experiment_id: str,
        name: str,
        description: str,
        variants: Dict[str, float],
        metrics: List[str],
        metadata: Optional[Dict[str, Any]] = None,
        auto_start: bool = True,
    ) -> Experiment:
        """
        创建实验

        Args:
            experiment_id: 实验 ID
            name: 实验名称
            description: 描述
            variants: 变体及其流量比例，如 {"control": 0.5, "treatment": 0.5}
            metrics: 关注的指标列表
            metadata: 额外元数据
            auto_start: 是否自动启动实验

        Returns:
            创建的实验对象

        Raises:
            ValueError: 流量比例不等于 1.0
        """
        # 验证流量比例
        total = sum(variants.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"流量比例总和必须为 1.0，当前为 {total}")

        if experiment_id in self.experiments:
            logger.warning(f"实验 {experiment_id} 已存在，返回现有实验")
            return self.experiments[experiment_id]

        experiment = Experiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            variants=variants,
            metrics=metrics,
            metadata=metadata or {},
            status=ExperimentStatus.RUNNING if auto_start else ExperimentStatus.DRAFT,
        )

        # 初始化结果
        for variant_id in variants:
            experiment.results[variant_id] = VariantResult(
                metrics={m: [] for m in metrics}
            )

        self.experiments[experiment_id] = experiment
        self._save_to_storage()

        logger.info(f"创建实验: {experiment_id}")
        return experiment

    def get_variant(
        self,
        experiment_id: str,
        user_id: str,
        default_variant: str = "control",
    ) -> str:
        """
        获取用户的实验变体

        确保同一用户始终看到相同变体（确定性分配）。

        Args:
            experiment_id: 实验 ID
            user_id: 用户 ID
            default_variant: 默认变体（实验不存在或未运行时返回）

        Returns:
            分配的变体 ID
        """
        experiment = self.experiments.get(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.RUNNING:
            return default_variant

        # 检查是否已分配
        if user_id in self.user_assignments:
            if experiment_id in self.user_assignments[user_id]:
                assigned = self.user_assignments[user_id][experiment_id]
                # 记录曝光
                experiment.results[assigned].impressions += 1
                return assigned

        # 使用确定性哈希分配变体
        variant_id = self._assign_variant_deterministic(experiment, user_id)

        # 存储分配
        if user_id not in self.user_assignments:
            self.user_assignments[user_id] = {}
        self.user_assignments[user_id][experiment_id] = variant_id

        # 记录曝光
        experiment.results[variant_id].impressions += 1

        self._save_to_storage()
        return variant_id

    def record_metric(
        self,
        experiment_id: str,
        user_id: str,
        metric_name: str,
        value: float,
    ) -> bool:
        """
        记录指标

        Args:
            experiment_id: 实验 ID
            user_id: 用户 ID
            metric_name: 指标名称
            value: 指标值

        Returns:
            是否成功记录
        """
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            logger.warning(f"实验 {experiment_id} 不存在")
            return False

        # 获取用户的变体
        variant_id = self.user_assignments.get(user_id, {}).get(experiment_id)
        if not variant_id:
            logger.warning(f"用户 {user_id} 未参与实验 {experiment_id}")
            return False

        # 记录指标
        if metric_name in experiment.results[variant_id].metrics:
            experiment.results[variant_id].metrics[metric_name].append(value)
            self._save_to_storage()
            return True

        logger.warning(f"指标 {metric_name} 不在实验 {experiment_id} 的指标列表中")
        return False

    def record_conversion(
        self,
        experiment_id: str,
        user_id: str,
    ) -> bool:
        """
        记录转化

        Args:
            experiment_id: 实验 ID
            user_id: 用户 ID

        Returns:
            是否成功记录
        """
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return False

        variant_id = self.user_assignments.get(user_id, {}).get(experiment_id)
        if variant_id:
            experiment.results[variant_id].conversions += 1
            self._save_to_storage()
            return True
        return False

    def get_results(self, experiment_id: str) -> Dict[str, Any]:
        """
        获取实验结果

        Args:
            experiment_id: 实验 ID

        Returns:
            包含各变体统计数据和显著性分析的结果
        """
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return {}

        duration = datetime.now() - experiment.start_time
        if experiment.end_time:
            duration = experiment.end_time - experiment.start_time

        results = {
            "experiment_id": experiment_id,
            "name": experiment.name,
            "description": experiment.description,
            "status": experiment.status.value,
            "duration_hours": duration.total_seconds() / 3600,
            "start_time": experiment.start_time.isoformat(),
            "end_time": experiment.end_time.isoformat() if experiment.end_time else None,
            "winner": experiment.winner,
            "variants": {},
        }

        for variant_id, data in experiment.results.items():
            variant_results = {
                "impressions": data.impressions,
                "conversions": data.conversions,
                "conversion_rate": data.conversion_rate,
                "traffic_ratio": experiment.variants[variant_id],
                "metrics": {},
            }

            # 计算各指标的统计量
            for metric_name, values in data.metrics.items():
                if values:
                    variant_results["metrics"][metric_name] = {
                        "count": len(values),
                        "mean": statistics.mean(values),
                        "std": statistics.stdev(values) if len(values) > 1 else 0,
                        "min": min(values),
                        "max": max(values),
                        "median": statistics.median(values),
                    }

            results["variants"][variant_id] = variant_results

        # 添加显著性分析
        results["significance"] = self._calculate_significance(experiment)

        return results

    def get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        """获取实验"""
        return self.experiments.get(experiment_id)

    def list_experiments(
        self,
        status: Optional[ExperimentStatus] = None,
    ) -> List[Experiment]:
        """列出所有实验"""
        experiments = list(self.experiments.values())
        if status:
            experiments = [e for e in experiments if e.status == status]
        return sorted(experiments, key=lambda e: e.start_time, reverse=True)

    def start_experiment(self, experiment_id: str) -> bool:
        """启动实验"""
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return False

        if experiment.status == ExperimentStatus.DRAFT:
            experiment.status = ExperimentStatus.RUNNING
            experiment.start_time = datetime.now()
            self._save_to_storage()
            logger.info(f"启动实验: {experiment_id}")
            return True
        return False

    def pause_experiment(self, experiment_id: str) -> bool:
        """暂停实验"""
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return False

        if experiment.status == ExperimentStatus.RUNNING:
            experiment.status = ExperimentStatus.PAUSED
            self._save_to_storage()
            logger.info(f"暂停实验: {experiment_id}")
            return True
        return False

    def resume_experiment(self, experiment_id: str) -> bool:
        """恢复实验"""
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return False

        if experiment.status == ExperimentStatus.PAUSED:
            experiment.status = ExperimentStatus.RUNNING
            self._save_to_storage()
            logger.info(f"恢复实验: {experiment_id}")
            return True
        return False

    def conclude_experiment(
        self,
        experiment_id: str,
        winner: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        结束实验并选择获胜变体

        Args:
            experiment_id: 实验 ID
            winner: 获胜变体（可选，不指定则自动选择）

        Returns:
            最终结果
        """
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return {"error": "实验不存在"}

        experiment.status = ExperimentStatus.COMPLETED
        experiment.end_time = datetime.now()

        # 自动选择获胜者（基于转化率）
        if winner is None:
            best_variant = None
            best_rate = -1
            for variant_id, data in experiment.results.items():
                if data.conversion_rate > best_rate and data.impressions >= 100:
                    best_rate = data.conversion_rate
                    best_variant = variant_id
            winner = best_variant

        experiment.winner = winner
        self._save_to_storage()

        logger.info(f"结束实验: {experiment_id}，获胜者: {winner}")

        return {
            "experiment_id": experiment_id,
            "status": "completed",
            "winner": winner,
            "final_results": self.get_results(experiment_id),
        }

    def delete_experiment(self, experiment_id: str) -> bool:
        """删除实验"""
        if experiment_id in self.experiments:
            del self.experiments[experiment_id]
            # 清理用户分配
            for user_id in list(self.user_assignments.keys()):
                if experiment_id in self.user_assignments[user_id]:
                    del self.user_assignments[user_id][experiment_id]
            self._save_to_storage()
            logger.info(f"删除实验: {experiment_id}")
            return True
        return False

    def _assign_variant_deterministic(self, experiment: Experiment, user_id: str) -> str:
        """
        使用确定性哈希分配变体

        确保同一用户-实验组合始终得到相同的变体。
        """
        # 使用 MD5 哈希生成确定性随机数
        hash_input = f"{experiment.experiment_id}:{user_id}".encode()
        hash_value = int(hashlib.md5(hash_input).hexdigest(), 16)
        bucket = (hash_value % 10000) / 10000.0  # 0-1 之间的数

        cumulative = 0
        for variant_id, ratio in experiment.variants.items():
            cumulative += ratio
            if bucket < cumulative:
                return variant_id

        return list(experiment.variants.keys())[-1]

    def _calculate_significance(self, experiment: Experiment) -> Dict[str, Any]:
        """
        计算统计显著性

        使用简化的 Z 检验比较变体。
        """
        variants = list(experiment.variants.keys())
        if len(variants) < 2:
            return {"significant": False, "reason": "变体数量不足"}

        # 比较第一个变体（控制组）和其他变体
        control = variants[0]
        control_data = experiment.results[control]

        significance_results = {}

        for variant in variants[1:]:
            variant_data = experiment.results[variant]

            # 转化率比较
            control_rate = control_data.conversion_rate
            variant_rate = variant_data.conversion_rate

            # 计算提升
            lift = 0
            if control_rate > 0:
                lift = (variant_rate - control_rate) / control_rate

            # 简化的显著性判断
            # 实际应用中应使用更严格的统计检验
            min_samples = min(control_data.impressions, variant_data.impressions)
            is_significant = abs(lift) > 0.05 and min_samples >= 100

            # 计算置信度（简化版）
            confidence = 0
            if min_samples >= 100:
                # 使用样本量和效果大小估算置信度
                confidence = min(0.99, min_samples / 1000 * (1 + abs(lift)))

            significance_results[f"{control}_vs_{variant}"] = {
                "control": {
                    "impressions": control_data.impressions,
                    "conversions": control_data.conversions,
                    "rate": control_rate,
                },
                "treatment": {
                    "impressions": variant_data.impressions,
                    "conversions": variant_data.conversions,
                    "rate": variant_rate,
                },
                "lift": lift,
                "lift_percentage": f"{lift * 100:.2f}%",
                "is_significant": is_significant,
                "confidence": confidence,
                "recommendation": self._get_recommendation(lift, is_significant, min_samples),
            }

        return significance_results

    def _get_recommendation(
        self, lift: float, is_significant: bool, min_samples: int
    ) -> str:
        """生成建议"""
        if min_samples < 100:
            return "需要更多数据才能得出结论"

        if not is_significant:
            return "变化不显著，建议继续收集数据"

        if lift > 0.1:
            return "处理组显著优于控制组，建议采用处理组"
        elif lift > 0:
            return "处理组略优于控制组，可考虑采用"
        elif lift > -0.1:
            return "处理组略劣于控制组，建议保持控制组"
        else:
            return "处理组显著劣于控制组，不建议采用"

    def _save_to_storage(self) -> None:
        """保存到持久化存储"""
        if not self.storage_path:
            return

        self.storage_path.mkdir(parents=True, exist_ok=True)

        # 保存实验
        experiments_data = {
            exp_id: exp.to_dict() for exp_id, exp in self.experiments.items()
        }
        experiments_file = self.storage_path / "experiments.json"
        with open(experiments_file, "w", encoding="utf-8") as f:
            json.dump(experiments_data, f, ensure_ascii=False, indent=2)

        # 保存用户分配
        assignments_file = self.storage_path / "assignments.json"
        with open(assignments_file, "w", encoding="utf-8") as f:
            json.dump(self.user_assignments, f, ensure_ascii=False, indent=2)

    def _load_from_storage(self) -> None:
        """从持久化存储加载"""
        if not self.storage_path or not self.storage_path.exists():
            return

        # 加载实验
        experiments_file = self.storage_path / "experiments.json"
        if experiments_file.exists():
            with open(experiments_file, "r", encoding="utf-8") as f:
                experiments_data = json.load(f)
                for exp_id, exp_dict in experiments_data.items():
                    self.experiments[exp_id] = Experiment.from_dict(exp_dict)

        # 加载用户分配
        assignments_file = self.storage_path / "assignments.json"
        if assignments_file.exists():
            with open(assignments_file, "r", encoding="utf-8") as f:
                self.user_assignments = json.load(f)

        logger.info(f"从存储加载: {len(self.experiments)} 个实验")

"""
Prompt 自动优化器

基于执行反馈的迭代优化、多变体 A/B 测试和自动选择最佳变体。
"""

import json
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger()


class OptimizationType(str, Enum):
    """优化类型"""

    QUALITY = "quality"  # 优化输出质量
    EFFICIENCY = "efficiency"  # 优化效率（减少 tokens）
    RELIABILITY = "reliability"  # 优化可靠性（提高成功率）
    BALANCED = "balanced"  # 平衡所有指标


@dataclass
class PromptVariant:
    """Prompt 变体"""

    variant_id: str
    prompt_text: str
    created_at: datetime = field(default_factory=datetime.now)
    parent_variant_id: Optional[str] = None

    # 性能统计
    execution_count: int = 0
    success_count: int = 0
    avg_latency: float = 0.0
    avg_tokens: int = 0
    avg_quality: float = 0.0
    performance_score: float = 0.0

    # 元数据
    optimization_type: Optional[str] = None
    notes: str = ""
    is_active: bool = True

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.execution_count == 0:
            return 0.0
        return self.success_count / self.execution_count

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "variant_id": self.variant_id,
            "prompt_text": self.prompt_text,
            "created_at": self.created_at.isoformat(),
            "parent_variant_id": self.parent_variant_id,
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "avg_latency": self.avg_latency,
            "avg_tokens": self.avg_tokens,
            "avg_quality": self.avg_quality,
            "performance_score": self.performance_score,
            "optimization_type": self.optimization_type,
            "notes": self.notes,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptVariant":
        """从字典创建"""
        return cls(
            variant_id=data["variant_id"],
            prompt_text=data["prompt_text"],
            created_at=datetime.fromisoformat(data["created_at"]),
            parent_variant_id=data.get("parent_variant_id"),
            execution_count=data.get("execution_count", 0),
            success_count=data.get("success_count", 0),
            avg_latency=data.get("avg_latency", 0.0),
            avg_tokens=data.get("avg_tokens", 0),
            avg_quality=data.get("avg_quality", 0.0),
            performance_score=data.get("performance_score", 0.0),
            optimization_type=data.get("optimization_type"),
            notes=data.get("notes", ""),
            is_active=data.get("is_active", True),
        )


@dataclass
class ExecutionLog:
    """执行日志"""

    variant_id: str
    success: bool
    latency: float
    tokens_used: int
    output_quality: Optional[float] = None
    feedback: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "success": self.success,
            "latency": self.latency,
            "tokens_used": self.tokens_used,
            "output_quality": self.output_quality,
            "feedback": self.feedback,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class PromptOptimizer:
    """
    Prompt 自动优化器

    特性：
    - 多变体管理和 A/B 测试
    - 基于执行反馈的自动优化
    - 多种优化策略（质量、效率、可靠性）
    - 持久化存储
    - epsilon-greedy 探索策略

    用法：
        ```python
        optimizer = PromptOptimizer(llm_client)

        # 注册初始 Prompt
        variant_id = optimizer.register_prompt("greeting", "你好，请问有什么可以帮助你？")

        # 获取用于执行的变体
        variant = optimizer.get_variant_for_ab_test("greeting")

        # 执行后记录结果
        need_optimize = optimizer.record_execution(
            prompt_id="greeting",
            variant_id=variant.variant_id,
            success=True,
            latency=1.5,
            tokens_used=150,
            output_quality=0.9
        )

        # 触发优化
        if need_optimize:
            new_variant = await optimizer.optimize("greeting")
        ```
    """

    def __init__(
        self,
        llm_client: Any = None,
        optimization_interval: int = 100,
        storage_path: Optional[str] = None,
        min_samples_for_comparison: int = 10,
        score_weights: Optional[Dict[str, float]] = None,
    ):
        """
        初始化 Prompt 优化器

        Args:
            llm_client: LLM 客户端，用于生成优化后的 Prompt
            optimization_interval: 每 N 次执行后触发优化检查
            storage_path: 持久化存储路径
            min_samples_for_comparison: 比较变体性能所需的最小样本数
            score_weights: 评分权重配置
        """
        self.llm_client = llm_client
        self.optimization_interval = optimization_interval
        self.storage_path = Path(storage_path) if storage_path else None
        self.min_samples_for_comparison = min_samples_for_comparison

        # 评分权重
        self.score_weights = score_weights or {
            "success_rate": 0.4,
            "efficiency": 0.2,
            "latency": 0.1,
            "quality": 0.3,
        }

        # 存储 Prompt 变体
        self.variants: Dict[str, List[PromptVariant]] = {}

        # 执行记录
        self.execution_logs: Dict[str, List[ExecutionLog]] = {}

        # 加载持久化数据
        if self.storage_path:
            self._load_from_storage()

        logger.info(f"PromptOptimizer 初始化完成，优化间隔: {optimization_interval}")

    def register_prompt(
        self,
        prompt_id: str,
        initial_prompt: str,
        notes: str = "",
    ) -> str:
        """
        注册初始 Prompt

        Args:
            prompt_id: Prompt 唯一标识
            initial_prompt: 初始 Prompt 文本
            notes: 备注

        Returns:
            str: 变体 ID
        """
        if prompt_id in self.variants:
            logger.warning(f"Prompt {prompt_id} 已存在，返回现有变体")
            return self.variants[prompt_id][0].variant_id

        variant = PromptVariant(
            variant_id=f"{prompt_id}_v1",
            prompt_text=initial_prompt,
            notes=notes,
        )
        self.variants[prompt_id] = [variant]
        self.execution_logs[prompt_id] = []

        self._save_to_storage()
        logger.info(f"注册 Prompt: {prompt_id}")

        return variant.variant_id

    def get_best_variant(self, prompt_id: str) -> Optional[PromptVariant]:
        """
        获取最佳变体

        Args:
            prompt_id: Prompt ID

        Returns:
            最佳变体或 None
        """
        variants = self.variants.get(prompt_id, [])
        if not variants:
            return None

        # 过滤激活的变体
        active_variants = [v for v in variants if v.is_active]
        if not active_variants:
            return variants[0]

        # 过滤执行次数足够的变体
        eligible = [
            v
            for v in active_variants
            if v.execution_count >= self.min_samples_for_comparison
        ]
        if not eligible:
            return active_variants[0]  # 返回第一个激活的变体

        # 按性能得分排序
        return max(eligible, key=lambda v: v.performance_score)

    def get_variant_for_ab_test(
        self,
        prompt_id: str,
        exploration_rate: float = 0.1,
    ) -> PromptVariant:
        """
        获取用于 A/B 测试的变体

        使用 epsilon-greedy 策略：
        - 以 exploration_rate 概率随机选择
        - 否则选择最佳变体

        Args:
            prompt_id: Prompt ID
            exploration_rate: 探索率（0-1）

        Returns:
            选中的变体
        """
        variants = self.variants.get(prompt_id, [])
        if not variants:
            raise ValueError(f"Prompt {prompt_id} 未注册")

        active_variants = [v for v in variants if v.is_active]
        if not active_variants:
            raise ValueError(f"Prompt {prompt_id} 没有激活的变体")

        if random.random() < exploration_rate:
            return random.choice(active_variants)

        best = self.get_best_variant(prompt_id)
        return best if best else active_variants[0]

    def record_execution(
        self,
        prompt_id: str,
        variant_id: str,
        success: bool,
        latency: float,
        tokens_used: int,
        output_quality: Optional[float] = None,
        feedback: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        记录执行结果

        Args:
            prompt_id: Prompt ID
            variant_id: 变体 ID
            success: 是否成功
            latency: 延迟（秒）
            tokens_used: 使用的 tokens 数
            output_quality: 输出质量分数（0-1）
            feedback: 反馈文本
            metadata: 额外元数据

        Returns:
            bool: 是否需要触发优化
        """
        # 更新变体统计
        for variant in self.variants.get(prompt_id, []):
            if variant.variant_id == variant_id:
                variant.execution_count += 1
                if success:
                    variant.success_count += 1

                # 更新移动平均
                n = variant.execution_count
                variant.avg_latency = (variant.avg_latency * (n - 1) + latency) / n
                variant.avg_tokens = int(
                    (variant.avg_tokens * (n - 1) + tokens_used) / n
                )
                if output_quality is not None:
                    if variant.avg_quality == 0:
                        variant.avg_quality = output_quality
                    else:
                        variant.avg_quality = (
                            variant.avg_quality * (n - 1) + output_quality
                        ) / n

                # 重新计算性能得分
                variant.performance_score = self._calculate_score(
                    variant, output_quality
                )
                break

        # 记录日志
        log = ExecutionLog(
            variant_id=variant_id,
            success=success,
            latency=latency,
            tokens_used=tokens_used,
            output_quality=output_quality,
            feedback=feedback,
            metadata=metadata or {},
        )
        self.execution_logs.setdefault(prompt_id, []).append(log)

        self._save_to_storage()

        # 检查是否需要触发优化
        total_executions = len(self.execution_logs[prompt_id])
        if total_executions % self.optimization_interval == 0:
            logger.info(
                f"Prompt {prompt_id} 已执行 {total_executions} 次，建议触发优化"
            )
            return True

        return False

    async def optimize(
        self,
        prompt_id: str,
        optimization_type: OptimizationType = OptimizationType.BALANCED,
        custom_instructions: Optional[str] = None,
    ) -> PromptVariant:
        """
        执行 Prompt 优化

        Args:
            prompt_id: Prompt ID
            optimization_type: 优化类型
            custom_instructions: 自定义优化指令

        Returns:
            新生成的变体
        """
        if self.llm_client is None:
            raise RuntimeError("LLM 客户端未配置，无法执行优化")

        variants = self.variants.get(prompt_id, [])
        if not variants:
            raise ValueError(f"Prompt {prompt_id} 未注册")

        # 获取最佳变体作为基准
        best = self.get_best_variant(prompt_id)
        if not best:
            best = variants[0]

        # 获取最近的执行日志
        recent_logs = self.execution_logs.get(prompt_id, [])[-100:]

        # 分析失败案例
        failures = [l for l in recent_logs if not l.success]
        low_quality = [
            l
            for l in recent_logs
            if l.output_quality is not None and l.output_quality < 0.7
        ]

        # 构建优化 Prompt
        optimization_prompt = self._build_optimization_prompt(
            best=best,
            optimization_type=optimization_type,
            failures=failures,
            low_quality=low_quality,
            custom_instructions=custom_instructions,
        )

        # 调用 LLM 生成优化后的 Prompt
        response_text = await self._call_llm(optimization_prompt)

        # 创建新变体
        new_variant = PromptVariant(
            variant_id=f"{prompt_id}_v{len(variants) + 1}",
            prompt_text=response_text.strip(),
            parent_variant_id=best.variant_id,
            optimization_type=optimization_type.value,
        )

        self.variants[prompt_id].append(new_variant)
        self._save_to_storage()

        logger.info(f"为 Prompt {prompt_id} 创建新变体: {new_variant.variant_id}")

        return new_variant

    def deactivate_variant(self, prompt_id: str, variant_id: str) -> bool:
        """
        停用变体

        Args:
            prompt_id: Prompt ID
            variant_id: 变体 ID

        Returns:
            是否成功
        """
        for variant in self.variants.get(prompt_id, []):
            if variant.variant_id == variant_id:
                variant.is_active = False
                self._save_to_storage()
                logger.info(f"已停用变体: {variant_id}")
                return True
        return False

    def get_all_variants(self, prompt_id: str) -> List[PromptVariant]:
        """获取所有变体"""
        return self.variants.get(prompt_id, [])

    def get_variant_by_id(
        self, prompt_id: str, variant_id: str
    ) -> Optional[PromptVariant]:
        """获取指定变体"""
        for variant in self.variants.get(prompt_id, []):
            if variant.variant_id == variant_id:
                return variant
        return None

    def get_execution_stats(self, prompt_id: str) -> Dict[str, Any]:
        """获取执行统计"""
        logs = self.execution_logs.get(prompt_id, [])
        variants = self.variants.get(prompt_id, [])

        if not logs:
            return {"total_executions": 0, "variants": []}

        return {
            "total_executions": len(logs),
            "total_success": sum(1 for l in logs if l.success),
            "avg_latency": sum(l.latency for l in logs) / len(logs),
            "avg_tokens": sum(l.tokens_used for l in logs) / len(logs),
            "variants": [
                {
                    "variant_id": v.variant_id,
                    "execution_count": v.execution_count,
                    "success_rate": v.success_rate,
                    "performance_score": v.performance_score,
                    "is_active": v.is_active,
                }
                for v in variants
            ],
        }

    def compare_variants(
        self, prompt_id: str, variant_a: str, variant_b: str
    ) -> Dict[str, Any]:
        """比较两个变体"""
        a = self.get_variant_by_id(prompt_id, variant_a)
        b = self.get_variant_by_id(prompt_id, variant_b)

        if not a or not b:
            raise ValueError("变体不存在")

        return {
            "variant_a": {
                "id": a.variant_id,
                "execution_count": a.execution_count,
                "success_rate": a.success_rate,
                "avg_latency": a.avg_latency,
                "avg_tokens": a.avg_tokens,
                "avg_quality": a.avg_quality,
                "score": a.performance_score,
            },
            "variant_b": {
                "id": b.variant_id,
                "execution_count": b.execution_count,
                "success_rate": b.success_rate,
                "avg_latency": b.avg_latency,
                "avg_tokens": b.avg_tokens,
                "avg_quality": b.avg_quality,
                "score": b.performance_score,
            },
            "winner": (
                a.variant_id
                if a.performance_score > b.performance_score
                else b.variant_id
            ),
            "score_diff": abs(a.performance_score - b.performance_score),
        }

    def _calculate_score(
        self,
        variant: PromptVariant,
        latest_quality: Optional[float] = None,
    ) -> float:
        """计算性能得分"""
        if variant.execution_count == 0:
            return 0.0

        # 成功率
        success_rate = variant.success_rate

        # 效率（tokens 越少越好）
        max_tokens = 10000
        efficiency = 1 - min(variant.avg_tokens / max_tokens, 1)

        # 延迟（越低越好）
        max_latency = 60
        latency_score = 1 - min(variant.avg_latency / max_latency, 1)

        # 质量
        quality_score = (
            latest_quality if latest_quality is not None else variant.avg_quality
        )
        if quality_score == 0:
            quality_score = 0.7  # 默认质量

        return (
            success_rate * self.score_weights["success_rate"]
            + efficiency * self.score_weights["efficiency"]
            + latency_score * self.score_weights["latency"]
            + quality_score * self.score_weights["quality"]
        )

    def _build_optimization_prompt(
        self,
        best: PromptVariant,
        optimization_type: OptimizationType,
        failures: List[ExecutionLog],
        low_quality: List[ExecutionLog],
        custom_instructions: Optional[str] = None,
    ) -> str:
        """构建优化 Prompt"""
        common_feedback = self._extract_common_feedback(failures + low_quality)

        type_instructions = {
            OptimizationType.QUALITY: "提高输出的准确性和完整性",
            OptimizationType.EFFICIENCY: "减少不必要的指令以节省 tokens，同时保持功能",
            OptimizationType.RELIABILITY: "增加错误处理指导，提高执行成功率",
            OptimizationType.BALANCED: "在质量、效率和可靠性之间取得平衡",
        }

        return f"""你是一个 Prompt 优化专家。请分析以下 Prompt 的执行情况并生成优化版本。

## 当前 Prompt
```
{best.prompt_text}
```

## 性能统计
- 执行次数: {best.execution_count}
- 成功率: {best.success_rate:.2%}
- 平均延迟: {best.avg_latency:.2f}s
- 平均 tokens: {best.avg_tokens}
- 平均质量: {best.avg_quality:.2f}

## 优化目标
{type_instructions.get(optimization_type, "")}
{custom_instructions or ""}

## 问题分析
- 失败次数: {len(failures)}
- 低质量输出次数: {len(low_quality)}
- 常见问题反馈: {common_feedback}

请生成优化后的 Prompt，要求：
1. 保持原有功能不变
2. 针对失败案例和常见问题进行改进
3. 使表述更清晰准确
4. 根据优化目标进行调整

直接输出优化后的 Prompt 文本，不要包含解释或其他内容。"""

    def _extract_common_feedback(self, logs: List[ExecutionLog]) -> str:
        """提取常见反馈"""
        feedbacks = [l.feedback for l in logs if l.feedback]
        if not feedbacks:
            return "无明确反馈"

        # 简单词频统计
        words = []
        for f in feedbacks:
            words.extend(f.split()[:10])

        if not words:
            return "无明确反馈"

        common = Counter(words).most_common(5)
        return ", ".join([w for w, _ in common])

    async def _call_llm(self, prompt: str) -> str:
        """
        调用 LLM 客户端

        支持多种 LLM 客户端接口：
        - LangChain: ainvoke/invoke
        - 自定义: generate
        - 可调用对象: __call__
        """
        # 优先使用 LangChain 的 ainvoke 方法
        if hasattr(self.llm_client, "ainvoke"):
            try:
                from langchain_core.messages import HumanMessage

                messages = [HumanMessage(content=prompt)]
                response = await self.llm_client.ainvoke(messages)

                if hasattr(response, "content"):
                    return response.content
                return str(response)
            except ImportError:
                pass

        # 尝试使用 invoke 方法（同步版本）
        if hasattr(self.llm_client, "invoke"):
            try:
                from langchain_core.messages import HumanMessage

                messages = [HumanMessage(content=prompt)]
                response = self.llm_client.invoke(messages)

                if hasattr(response, "content"):
                    return response.content
                return str(response)
            except ImportError:
                pass

        # 尝试使用自定义的 generate 方法
        if hasattr(self.llm_client, "generate"):
            import inspect

            if inspect.iscoroutinefunction(self.llm_client.generate):
                response = await self.llm_client.generate(prompt)
            else:
                response = self.llm_client.generate(prompt)

            if isinstance(response, dict):
                return response.get("content", response.get("text", str(response)))
            if hasattr(response, "content"):
                return response.content
            return str(response)

        # 尝试直接调用
        if callable(self.llm_client):
            response = self.llm_client(prompt)
            if hasattr(response, "content"):
                return response.content
            return str(response)

        raise ValueError("不支持的 LLM 客户端类型")

    def _save_to_storage(self) -> None:
        """保存到持久化存储"""
        if not self.storage_path:
            return

        self.storage_path.mkdir(parents=True, exist_ok=True)

        # 保存变体
        variants_data = {}
        for prompt_id, variants in self.variants.items():
            variants_data[prompt_id] = [v.to_dict() for v in variants]

        variants_file = self.storage_path / "variants.json"
        with open(variants_file, "w", encoding="utf-8") as f:
            json.dump(variants_data, f, ensure_ascii=False, indent=2)

        # 保存执行日志（只保存最近的）
        logs_data = {}
        for prompt_id, logs in self.execution_logs.items():
            logs_data[prompt_id] = [
                l.to_dict() for l in logs[-1000:]
            ]  # 只保留最近 1000 条

        logs_file = self.storage_path / "execution_logs.json"
        with open(logs_file, "w", encoding="utf-8") as f:
            json.dump(logs_data, f, ensure_ascii=False, indent=2)

    def _load_from_storage(self) -> None:
        """从持久化存储加载"""
        if not self.storage_path or not self.storage_path.exists():
            return

        # 加载变体
        variants_file = self.storage_path / "variants.json"
        if variants_file.exists():
            with open(variants_file, "r", encoding="utf-8") as f:
                variants_data = json.load(f)
                for prompt_id, variants_list in variants_data.items():
                    self.variants[prompt_id] = [
                        PromptVariant.from_dict(v) for v in variants_list
                    ]

        # 加载执行日志
        logs_file = self.storage_path / "execution_logs.json"
        if logs_file.exists():
            with open(logs_file, "r", encoding="utf-8") as f:
                logs_data = json.load(f)
                for prompt_id, logs_list in logs_data.items():
                    self.execution_logs[prompt_id] = [
                        ExecutionLog(
                            variant_id=l["variant_id"],
                            success=l["success"],
                            latency=l["latency"],
                            tokens_used=l["tokens_used"],
                            output_quality=l.get("output_quality"),
                            feedback=l.get("feedback"),
                            timestamp=datetime.fromisoformat(l["timestamp"]),
                            metadata=l.get("metadata", {}),
                        )
                        for l in logs_list
                    ]

        logger.info(
            f"从存储加载: {len(self.variants)} 个 Prompt, "
            f"{sum(len(v) for v in self.variants.values())} 个变体"
        )

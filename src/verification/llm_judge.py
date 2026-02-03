"""
LLM 评判验证器

使用 LLM 对 Agent 输出进行质量评估和验证。
支持自定义评估标准、多维度评分和详细反馈。
"""

from typing import Dict, Any, Optional, List, Union
import json
import re

from .base import BaseVerifier, VerificationResult
from src.utils.logger import get_logger

logger = get_logger()


class LLMJudgeVerifier(BaseVerifier):
    """
    基于 LLM 的输出验证器

    使用 LLM 对 Agent 输出进行多维度评估，支持：
    - 自定义评估标准
    - 多维度评分
    - 详细反馈生成
    - 可配置的通过阈值

    用法:
        verifier = LLMJudgeVerifier(
            llm_client=my_llm_client,
            criteria=[
                "内容完整性：输出是否包含所有必需的信息",
                "逻辑正确性：推理过程是否合理",
                "格式规范性：输出格式是否符合要求",
            ],
            passing_score=0.7,
        )

        result = await verifier.verify(
            output="Agent的输出内容...",
            context={"task": "原始任务描述", "expected_format": "JSON"}
        )
    """

    def __init__(
        self,
        llm_client: Any,
        criteria: List[str],
        passing_score: float = 0.7,
        model: str = None,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        include_reasoning: bool = True,
        evaluation_prompt_template: str = None,
    ):
        """
        初始化 LLM 评判验证器

        Args:
            llm_client: LLM 客户端（需要支持 generate 或 invoke 方法）
            criteria: 评估标准列表，每个标准描述一个评估维度
            passing_score: 通过阈值（0-1），默认 0.7
            model: 使用的模型名称（可选，使用客户端默认值）
            temperature: 生成温度，越低越确定性
            max_tokens: 最大生成 token 数
            include_reasoning: 是否在反馈中包含推理过程
            evaluation_prompt_template: 自定义评估提示模板
        """
        self.llm_client = llm_client
        self.criteria = criteria
        self.passing_score = passing_score
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.include_reasoning = include_reasoning
        self.evaluation_prompt_template = (
            evaluation_prompt_template or self._default_prompt_template()
        )

    def _default_prompt_template(self) -> str:
        """默认评估提示模板"""
        return """你是一个专业的 AI 输出质量评估专家。请根据以下评估标准，对给定的输出内容进行评估。

## 评估任务
{task_description}

## 评估标准
{criteria_text}

## 待评估的输出
```
{output}
```

## 上下文信息
{context_text}

## 评估要求
请对每个评估标准进行打分（0-10分），并给出综合评价。

请使用以下 JSON 格式输出评估结果：
```json
{{
    "criteria_scores": {{
        "标准1名称": {{
            "score": 8,
            "reasoning": "评分理由..."
        }},
        "标准2名称": {{
            "score": 7,
            "reasoning": "评分理由..."
        }}
    }},
    "overall_score": 7.5,
    "overall_feedback": "综合评价...",
    "strengths": ["优点1", "优点2"],
    "weaknesses": ["不足1", "不足2"],
    "suggestions": ["改进建议1", "改进建议2"]
}}
```

请确保 JSON 格式正确，分数在 0-10 之间。"""

    async def verify(
        self,
        output: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        """
        使用 LLM 验证输出

        Args:
            output: 待验证的输出（字符串或可序列化对象）
            context: 验证上下文，可包含：
                - task: 原始任务描述
                - expected_format: 期望的输出格式
                - additional_context: 其他上下文信息

        Returns:
            验证结果，包含分数、是否通过、详细反馈
        """
        context = context or {}

        try:
            # 构建评估提示
            prompt = self._build_evaluation_prompt(output, context)

            # 调用 LLM 进行评估
            response = await self._call_llm(prompt)

            # 解析评估结果
            evaluation = self._parse_evaluation(response)

            # 计算归一化分数（0-10 转为 0-1）
            normalized_score = evaluation.get("overall_score", 0) / 10.0
            normalized_score = max(0.0, min(1.0, normalized_score))

            # 生成反馈
            feedback = self._generate_feedback(evaluation)

            return VerificationResult(
                passed=normalized_score >= self.passing_score,
                score=normalized_score,
                feedback=feedback,
                details={
                    "criteria_scores": evaluation.get("criteria_scores", {}),
                    "overall_score_raw": evaluation.get("overall_score", 0),
                    "strengths": evaluation.get("strengths", []),
                    "weaknesses": evaluation.get("weaknesses", []),
                    "suggestions": evaluation.get("suggestions", []),
                    "verifier_name": "llm_judge",
                    "passing_threshold": self.passing_score,
                },
            )

        except Exception as e:
            logger.error(f"LLM 评估失败: {e}")
            return VerificationResult(
                passed=False,
                score=0.0,
                feedback=f"评估过程出错: {str(e)}",
                details={
                    "error": str(e),
                    "verifier_name": "llm_judge",
                },
            )

    def _build_evaluation_prompt(
        self,
        output: Any,
        context: Dict[str, Any],
    ) -> str:
        """构建评估提示"""
        # 转换输出为字符串
        if isinstance(output, str):
            output_text = output
        elif isinstance(output, (dict, list)):
            try:
                output_text = json.dumps(output, ensure_ascii=False, indent=2)
            except Exception:
                output_text = str(output)
        else:
            output_text = str(output)

        # 构建评估标准文本
        criteria_text = "\n".join(
            f"{i+1}. {criterion}" for i, criterion in enumerate(self.criteria)
        )

        # 构建上下文文本
        context_parts = []
        if context.get("task"):
            context_parts.append(f"任务描述: {context['task']}")
        if context.get("expected_format"):
            context_parts.append(f"期望格式: {context['expected_format']}")
        if context.get("additional_context"):
            context_parts.append(f"附加信息: {context['additional_context']}")

        context_text = "\n".join(context_parts) if context_parts else "无额外上下文"

        # 任务描述
        task_description = context.get("task", "评估以下输出的质量")

        # 填充模板
        return self.evaluation_prompt_template.format(
            task_description=task_description,
            criteria_text=criteria_text,
            output=output_text,
            context_text=context_text,
        )

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM"""
        # 支持多种 LLM 客户端接口
        if hasattr(self.llm_client, "generate"):
            # 自定义客户端
            kwargs = {
                "prompt": prompt,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if self.model:
                kwargs["model"] = self.model

            response = await self.llm_client.generate(**kwargs)

            if isinstance(response, dict):
                return response.get("content", response.get("text", str(response)))
            return str(response)

        elif hasattr(self.llm_client, "ainvoke"):
            # LangChain 风格
            from langchain_core.messages import HumanMessage

            messages = [HumanMessage(content=prompt)]
            response = await self.llm_client.ainvoke(messages)

            if hasattr(response, "content"):
                return response.content
            return str(response)

        elif hasattr(self.llm_client, "invoke"):
            # 同步 LangChain
            from langchain_core.messages import HumanMessage
            import asyncio

            messages = [HumanMessage(content=prompt)]
            response = await asyncio.to_thread(self.llm_client.invoke, messages)

            if hasattr(response, "content"):
                return response.content
            return str(response)

        else:
            raise ValueError("不支持的 LLM 客户端类型")

    def _parse_evaluation(self, response: str) -> Dict[str, Any]:
        """解析 LLM 评估响应"""
        # 尝试提取 JSON
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析整个响应
            json_str = response

        try:
            evaluation = json.loads(json_str)
            return evaluation
        except json.JSONDecodeError:
            logger.warning(f"无法解析 LLM 评估响应为 JSON: {response[:200]}...")

            # 尝试从文本中提取分数
            score_match = re.search(
                r"(?:overall_score|综合评分|总分)[：:\s]*(\d+(?:\.\d+)?)", response
            )
            score = float(score_match.group(1)) if score_match else 5.0

            return {
                "overall_score": score,
                "overall_feedback": response,
                "criteria_scores": {},
                "strengths": [],
                "weaknesses": [],
                "suggestions": [],
            }

    def _generate_feedback(self, evaluation: Dict[str, Any]) -> str:
        """生成反馈文本"""
        parts = []

        # 综合评价
        overall_feedback = evaluation.get("overall_feedback", "")
        if overall_feedback:
            parts.append(f"综合评价: {overall_feedback}")

        # 分数
        overall_score = evaluation.get("overall_score", 0)
        parts.append(f"综合评分: {overall_score}/10")

        # 优点
        strengths = evaluation.get("strengths", [])
        if strengths:
            parts.append(f"优点: {', '.join(strengths)}")

        # 不足
        weaknesses = evaluation.get("weaknesses", [])
        if weaknesses:
            parts.append(f"不足: {', '.join(weaknesses)}")

        # 建议
        suggestions = evaluation.get("suggestions", [])
        if suggestions:
            parts.append(f"改进建议: {'; '.join(suggestions)}")

        return " | ".join(parts)


class MultiCriteriaLLMJudge(LLMJudgeVerifier):
    """
    多维度 LLM 评判器

    支持为不同评估标准设置不同的权重，
    实现更灵活的评估策略。
    """

    def __init__(
        self,
        llm_client: Any,
        criteria_with_weights: Dict[str, float],
        passing_score: float = 0.7,
        **kwargs,
    ):
        """
        初始化多维度评判器

        Args:
            llm_client: LLM 客户端
            criteria_with_weights: 评估标准及其权重，如：
                {
                    "内容完整性": 0.3,
                    "逻辑正确性": 0.4,
                    "格式规范性": 0.3,
                }
            passing_score: 通过阈值
            **kwargs: 其他参数传递给父类
        """
        criteria = list(criteria_with_weights.keys())
        super().__init__(
            llm_client=llm_client,
            criteria=criteria,
            passing_score=passing_score,
            **kwargs,
        )
        self.criteria_weights = criteria_with_weights

        # 归一化权重
        total_weight = sum(criteria_with_weights.values())
        if total_weight > 0:
            self.criteria_weights = {
                k: v / total_weight for k, v in criteria_with_weights.items()
            }

    async def verify(
        self,
        output: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        """
        使用加权评分进行验证
        """
        # 先调用父类方法获取基础评估
        result = await super().verify(output, context)

        # 如果评估成功，使用加权分数
        criteria_scores = result.details.get("criteria_scores", {})
        if criteria_scores:
            weighted_score = 0.0

            for criterion, weight in self.criteria_weights.items():
                if criterion in criteria_scores:
                    score_data = criteria_scores[criterion]
                    raw_score = score_data.get("score", 5) / 10.0
                    weighted_score += raw_score * weight

            # 更新结果
            result.score = max(0.0, min(1.0, weighted_score))
            result.passed = result.score >= self.passing_score
            result.details["weighted_score"] = weighted_score
            result.details["criteria_weights"] = self.criteria_weights

        return result


# 导出
__all__ = [
    "LLMJudgeVerifier",
    "MultiCriteriaLLMJudge",
]

"""
规则验证器

提供基于规则的验证器实现，包括 JSON 格式验证、
必填字段验证等常见规则。
"""

from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
import json
from src.utils.logger import get_logger

from .base import BaseVerifier, VerificationResult

logger = get_logger()


class ValidationRule(ABC):
    """验证规则抽象基类"""
    
    @abstractmethod
    def validate(self, output: Any, context: Optional[Dict[str, Any]] = None) -> tuple[bool, str]:
        """
        执行验证
        
        Returns:
            (是否通过, 反馈信息)
        """
        pass


class JSONFormatRule(ValidationRule):
    """JSON 格式验证规则"""
    
    def validate(self, output: Any, context: Optional[Dict[str, Any]] = None) -> tuple[bool, str]:
        """验证输出是否为有效的 JSON"""
        if isinstance(output, dict):
            return True, "输出为有效 dict"
        
        if isinstance(output, str):
            try:
                json.loads(output)
                return True, "输出为有效 JSON 字符串"
            except json.JSONDecodeError as e:
                return False, f"JSON 格式错误: {str(e)}"
        
        return False, "输出既不是 dict 也不是 JSON 字符串"


class RequiredFieldsRule(ValidationRule):
    """必填字段验证规则"""
    
    def __init__(self, required_fields: List[str]):
        self.required_fields = required_fields
    
    def validate(self, output: Any, context: Optional[Dict[str, Any]] = None) -> tuple[bool, str]:
        """验证输出是否包含所有必填字段"""
        if not isinstance(output, dict):
            return False, "输出不是字典类型"
        
        missing_fields = []
        for field in self.required_fields:
            if field not in output:
                missing_fields.append(field)
        
        if missing_fields:
            return False, f"缺少必填字段: {', '.join(missing_fields)}"
        
        return True, "所有必填字段都存在"


class NonEmptyRule(ValidationRule):
    """非空验证规则"""
    
    def __init__(self, fields: List[str]):
        self.fields = fields
    
    def validate(self, output: Any, context: Optional[Dict[str, Any]] = None) -> tuple[bool, str]:
        """验证指定字段是否非空"""
        if not isinstance(output, dict):
            return False, "输出不是字典类型"
        
        empty_fields = []
        for field in self.fields:
            value = output.get(field)
            if not value or (isinstance(value, str) and not value.strip()):
                empty_fields.append(field)
        
        if empty_fields:
            return False, f"以下字段为空: {', '.join(empty_fields)}"
        
        return True, "所有字段都非空"


class LengthRule(ValidationRule):
    """长度验证规则"""
    
    def __init__(self, field: str, min_length: Optional[int] = None, max_length: Optional[int] = None):
        self.field = field
        self.min_length = min_length
        self.max_length = max_length
    
    def validate(self, output: Any, context: Optional[Dict[str, Any]] = None) -> tuple[bool, str]:
        """验证字段值的长度"""
        if not isinstance(output, dict):
            return False, "输出不是字典类型"
        
        value = output.get(self.field)
        if value is None:
            return False, f"字段 {self.field} 不存在"
        
        length = len(str(value))
        
        if self.min_length is not None and length < self.min_length:
            return False, f"字段 {self.field} 长度 ({length}) 小于最小值 ({self.min_length})"
        
        if self.max_length is not None and length > self.max_length:
            return False, f"字段 {self.field} 长度 ({length}) 超过最大值 ({self.max_length})"
        
        return True, f"字段 {self.field} 长度符合要求"


class RuleBasedVerifier(BaseVerifier):
    """
    基于规则的验证器
    
    按顺序执行多个验证规则，所有规则都通过才算验证成功。
    """
    
    def __init__(self, rules: List[ValidationRule]):
        self.rules = rules
    
    async def verify(
        self,
        output: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> VerificationResult:
        """
        执行所有验证规则
        
        Args:
            output: 待验证的输出
            context: 验证上下文
        
        Returns:
            验证结果
        """
        # 如果输出是 JSON 字符串，解析为 dict
        parsed_output = output
        if isinstance(output, str):
            try:
                parsed_output = json.loads(output)
            except json.JSONDecodeError:
                pass  # 保持原始字符串，让 JSONFormatRule 处理
        
        passed_count = 0
        feedback_parts = []
        rule_results = []
        
        for i, rule in enumerate(self.rules):
            rule_name = rule.__class__.__name__
            try:
                passed, message = rule.validate(parsed_output, context)
                
                rule_results.append({
                    "rule": rule_name,
                    "passed": passed,
                    "message": message
                })
                
                if passed:
                    passed_count += 1
                    feedback_parts.append(f"✓ {rule_name}: {message}")
                else:
                    feedback_parts.append(f"✗ {rule_name}: {message}")
            
            except Exception as e:
                logger.error(f"规则 {rule_name} 执行失败: {e}")
                rule_results.append({
                    "rule": rule_name,
                    "passed": False,
                    "message": f"执行失败: {str(e)}"
                })
                feedback_parts.append(f"✗ {rule_name}: 执行失败 - {str(e)}")
        
        # 计算分数
        score = passed_count / len(self.rules) if self.rules else 0.0
        all_passed = (passed_count == len(self.rules))
        
        feedback = "\n".join(feedback_parts)
        
        return VerificationResult(
            passed=all_passed,
            score=score,
            feedback=feedback,
            details={"rule_results": rule_results}
        )


class CompositeVerifier(BaseVerifier):
    """
    组合验证器
    
    组合多个验证器，可以配置通过策略（全部通过 / 任意通过 / 加权平均）。
    """
    
    def __init__(
        self,
        verifiers: List[BaseVerifier],
        strategy: str = "all",  # all, any, weighted
        weights: Optional[List[float]] = None
    ):
        self.verifiers = verifiers
        self.strategy = strategy
        self.weights = weights or [1.0] * len(verifiers)
        
        if len(self.weights) != len(self.verifiers):
            raise ValueError("权重数量必须与验证器数量一致")
    
    async def verify(
        self,
        output: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> VerificationResult:
        """
        执行所有验证器
        
        Args:
            output: 待验证的输出
            context: 验证上下文
        
        Returns:
            验证结果
        """
        results = []
        for verifier in self.verifiers:
            try:
                result = await verifier.verify(output, context)
                results.append(result)
            except Exception as e:
                logger.error(f"验证器 {verifier.__class__.__name__} 执行失败: {e}")
                results.append(VerificationResult(
                    passed=False,
                    score=0.0,
                    feedback=f"验证器执行失败: {str(e)}",
                    details={"error": str(e)}
                ))
        
        # 根据策略决定最终结果
        if self.strategy == "all":
            # 所有验证器都必须通过
            passed = all(r.passed for r in results)
            score = sum(r.score for r in results) / len(results) if results else 0.0
        
        elif self.strategy == "any":
            # 任意验证器通过即可
            passed = any(r.passed for r in results)
            score = max(r.score for r in results) if results else 0.0
        
        elif self.strategy == "weighted":
            # 加权平均
            total_weight = sum(self.weights)
            weighted_score = sum(
                r.score * w for r, w in zip(results, self.weights)
            ) / total_weight
            score = weighted_score
            passed = score >= 0.7  # 默认阈值
        
        else:
            raise ValueError(f"未知的验证策略: {self.strategy}")
        
        # 合并反馈
        feedback_parts = [
            f"{i+1}. {verifier.__class__.__name__}:\n{result.feedback}"
            for i, (verifier, result) in enumerate(zip(self.verifiers, results))
        ]
        feedback = "\n\n".join(feedback_parts)
        
        return VerificationResult(
            passed=passed,
            score=score,
            feedback=feedback,
            details={
                "strategy": self.strategy,
                "individual_results": [r.model_dump() for r in results]
            }
        )


# 便捷函数
def create_default_verifier(required_fields: Optional[List[str]] = None) -> RuleBasedVerifier:
    """
    创建默认的规则验证器
    
    Args:
        required_fields: 必填字段列表
    
    Returns:
        RuleBasedVerifier 实例
    """
    rules = [JSONFormatRule()]
    
    if required_fields:
        rules.append(RequiredFieldsRule(required_fields))
        rules.append(NonEmptyRule(required_fields))
    
    return RuleBasedVerifier(rules)


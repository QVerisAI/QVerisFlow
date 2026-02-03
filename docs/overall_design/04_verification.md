# 三层验证机制

## 1. 设计理念

基于 Anthropic 官方推荐的验证最佳实践：

> "The best form of feedback is providing clearly defined rules for an output, then explaining which rules failed and why."

### 三层验证架构

```
┌─────────────────────────────────────────────────────────────┐
│                      验证层 (Verification)                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ 第一层       │  │ 第二层       │  │ 第三层       │      │
│  │ 规则验证     │─▶│ 视觉验证(暂不实现)     │─▶│ LLM 评判     │      │
│  │ Rules        │  │ Visual       │  │ LLM Judge    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                              │
│  特点：            特点：            特点：                  │
│  - 快速、确定性    - 格式/布局验证   - 模糊规则评估          │
│  - 成本低          - 截图对比        - 内容质量评估          │
│  - 可解释性强      - UI 一致性       - 逻辑完整性            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

| 验证层 | 适用场景 | 优点 | 缺点 |
|--------|----------|------|------|
| **规则验证** | 格式检查、必填字段、数据类型 | 快速、确定、低成本 | 只能检查明确规则 |
| **视觉验证（暂不实现）** | UI 布局、图表渲染、文档格式 | 直观、全面 | 需要截图能力 |
| **LLM 评判** | 内容质量、逻辑性、专业性 | 灵活、智能 | 成本高、延迟大 |

---

## 2. 验证结果模型

```python
# etf_common/agent_framework/verification/verifier.py

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from enum import Enum


class VerificationSeverity(str, Enum):
    """验证问题严重程度"""
    ERROR = "error"        # 错误：必须修复
    WARNING = "warning"    # 警告：建议修复
    INFO = "info"          # 信息：仅供参考


class RuleResult(BaseModel):
    """单条规则验证结果"""
    
    rule_name: str = Field(description="规则名称")
    passed: bool = Field(description="是否通过")
    severity: VerificationSeverity = Field(
        default=VerificationSeverity.ERROR,
        description="严重程度"
    )
    message: str = Field(default="", description="结果消息")
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="详细信息"
    )


class VerificationResult(BaseModel):
    """验证结果"""
    
    passed: bool = Field(description="是否通过验证")
    score: float = Field(
        default=0.0,
        ge=0, le=1,
        description="验证得分 (0-1)"
    )
    feedback: str = Field(default="", description="反馈信息")
    rule_results: List[RuleResult] = Field(
        default_factory=list,
        description="各规则验证结果"
    )
    
    # 分层结果
    rules_passed: bool = Field(default=True, description="规则验证是否通过")
    visual_passed: Optional[bool] = Field(default=None, description="视觉验证是否通过")
    llm_passed: Optional[bool] = Field(default=None, description="LLM评判是否通过")
    
    def get_failed_rules(self) -> List[RuleResult]:
        """获取失败的规则"""
        return [r for r in self.rule_results if not r.passed]
    
    def get_errors(self) -> List[RuleResult]:
        """获取错误级别的失败规则"""
        return [
            r for r in self.rule_results 
            if not r.passed and r.severity == VerificationSeverity.ERROR
        ]
    
    def format_feedback(self) -> str:
        """格式化反馈信息"""
        lines = []
        
        if self.passed:
            lines.append("✅ 验证通过")
        else:
            lines.append("❌ 验证未通过")
        
        lines.append(f"\n得分: {self.score:.2%}")
        
        failed = self.get_failed_rules()
        if failed:
            lines.append("\n**失败的验证项：**")
            for r in failed:
                icon = "🔴" if r.severity == VerificationSeverity.ERROR else "🟡"
                lines.append(f"{icon} {r.rule_name}: {r.message}")
        
        if self.feedback:
            lines.append(f"\n**详细反馈：**\n{self.feedback}")
        
        return "\n".join(lines)


class BaseVerifier(ABC):
    """验证器基类"""
    
    @abstractmethod
    async def verify(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> VerificationResult:
        """
        执行验证
        
        Args:
            output: 待验证的输出
            context: 上下文信息
            
        Returns:
            验证结果
        """
        pass
```

---

## 3. 规则验证器

```python
# etf_common/agent_framework/verification/rule_verifier.py

from typing import List, Dict, Any, Optional, Callable
from abc import ABC, abstractmethod
import json
import re

from .verifier import (
    BaseVerifier, 
    VerificationResult, 
    RuleResult,
    VerificationSeverity
)


class VerificationRule(ABC):
    """验证规则基类"""
    
    def __init__(
        self,
        name: str,
        description: str,
        severity: VerificationSeverity = VerificationSeverity.ERROR
    ):
        self.name = name
        self.description = description
        self.severity = severity
    
    @abstractmethod
    async def check(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> RuleResult:
        """
        检查规则
        
        Returns:
            RuleResult
        """
        pass


# ============================================================================
# 内置验证规则
# ============================================================================

class JSONFormatRule(VerificationRule):
    """JSON 格式验证规则"""
    
    def __init__(self):
        super().__init__(
            name="JSON格式检查",
            description="验证输出是有效的 JSON 格式"
        )
    
    async def check(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> RuleResult:
        if isinstance(output, dict):
            return RuleResult(
                rule_name=self.name,
                passed=True,
                severity=self.severity,
                message="输出是有效的字典"
            )
        
        if isinstance(output, str):
            try:
                json.loads(output)
                return RuleResult(
                    rule_name=self.name,
                    passed=True,
                    severity=self.severity,
                    message="字符串是有效的 JSON"
                )
            except json.JSONDecodeError as e:
                return RuleResult(
                    rule_name=self.name,
                    passed=False,
                    severity=self.severity,
                    message=f"JSON 解析失败: {e}",
                    details={"error": str(e)}
                )
        
        return RuleResult(
            rule_name=self.name,
            passed=False,
            severity=self.severity,
            message=f"不支持的输出类型: {type(output).__name__}"
        )


class RequiredFieldsRule(VerificationRule):
    """必需字段验证规则"""
    
    def __init__(self, required_fields: List[str]):
        super().__init__(
            name="必需字段检查",
            description=f"验证输出包含必需字段: {required_fields}"
        )
        self.required_fields = required_fields
    
    async def check(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> RuleResult:
        # 处理字符串输入
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                return RuleResult(
                    rule_name=self.name,
                    passed=False,
                    severity=self.severity,
                    message="输出不是有效的 JSON"
                )
        
        if not isinstance(output, dict):
            return RuleResult(
                rule_name=self.name,
                passed=False,
                severity=self.severity,
                message="输出不是字典类型"
            )
        
        missing = [f for f in self.required_fields if f not in output]
        
        if missing:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                severity=self.severity,
                message=f"缺少必需字段: {missing}",
                details={"missing_fields": missing}
            )
        
        return RuleResult(
            rule_name=self.name,
            passed=True,
            severity=self.severity,
            message="所有必需字段都存在"
        )


class FieldTypeRule(VerificationRule):
    """字段类型验证规则"""
    
    def __init__(self, field_types: Dict[str, type]):
        super().__init__(
            name="字段类型检查",
            description="验证字段类型是否正确"
        )
        self.field_types = field_types
    
    async def check(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> RuleResult:
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                return RuleResult(
                    rule_name=self.name,
                    passed=False,
                    severity=self.severity,
                    message="输出不是有效的 JSON"
                )
        
        type_errors = []
        for field, expected_type in self.field_types.items():
            if field in output:
                actual_value = output[field]
                if not isinstance(actual_value, expected_type):
                    type_errors.append({
                        "field": field,
                        "expected": expected_type.__name__,
                        "actual": type(actual_value).__name__
                    })
        
        if type_errors:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                severity=self.severity,
                message=f"字段类型错误: {len(type_errors)} 个",
                details={"type_errors": type_errors}
            )
        
        return RuleResult(
            rule_name=self.name,
            passed=True,
            severity=self.severity,
            message="所有字段类型正确"
        )


class ValueRangeRule(VerificationRule):
    """数值范围验证规则"""
    
    def __init__(
        self,
        field: str,
        min_value: float = None,
        max_value: float = None
    ):
        super().__init__(
            name=f"数值范围检查({field})",
            description=f"验证 {field} 在 [{min_value}, {max_value}] 范围内"
        )
        self.field = field
        self.min_value = min_value
        self.max_value = max_value
    
    async def check(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> RuleResult:
        if isinstance(output, str):
            output = json.loads(output)
        
        if self.field not in output:
            return RuleResult(
                rule_name=self.name,
                passed=True,  # 字段不存在时跳过
                severity=VerificationSeverity.INFO,
                message=f"字段 {self.field} 不存在，跳过检查"
            )
        
        value = output[self.field]
        
        if self.min_value is not None and value < self.min_value:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                severity=self.severity,
                message=f"{self.field}={value} 小于最小值 {self.min_value}"
            )
        
        if self.max_value is not None and value > self.max_value:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                severity=self.severity,
                message=f"{self.field}={value} 大于最大值 {self.max_value}"
            )
        
        return RuleResult(
            rule_name=self.name,
            passed=True,
            severity=self.severity,
            message=f"{self.field}={value} 在有效范围内"
        )


class EnumValueRule(VerificationRule):
    """枚举值验证规则"""
    
    def __init__(self, field: str, allowed_values: List[Any]):
        super().__init__(
            name=f"枚举值检查({field})",
            description=f"验证 {field} 是否在允许的值列表中"
        )
        self.field = field
        self.allowed_values = allowed_values
    
    async def check(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> RuleResult:
        if isinstance(output, str):
            output = json.loads(output)
        
        if self.field not in output:
            return RuleResult(
                rule_name=self.name,
                passed=True,
                severity=VerificationSeverity.INFO,
                message=f"字段 {self.field} 不存在，跳过检查"
            )
        
        value = output[self.field]
        
        if value not in self.allowed_values:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                severity=self.severity,
                message=f"{self.field}={value} 不在允许的值列表中: {self.allowed_values}"
            )
        
        return RuleResult(
            rule_name=self.name,
            passed=True,
            severity=self.severity,
            message=f"{self.field}={value} 是有效的枚举值"
        )


class CustomRule(VerificationRule):
    """自定义验证规则"""
    
    def __init__(
        self,
        name: str,
        check_func: Callable[[Any, Dict], bool],
        message_func: Callable[[Any, Dict], str] = None,
        severity: VerificationSeverity = VerificationSeverity.ERROR
    ):
        super().__init__(name=name, description="自定义规则", severity=severity)
        self.check_func = check_func
        self.message_func = message_func or (lambda o, c: "自定义规则检查")
    
    async def check(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> RuleResult:
        try:
            passed = self.check_func(output, context or {})
            message = self.message_func(output, context or {})
            
            return RuleResult(
                rule_name=self.name,
                passed=passed,
                severity=self.severity,
                message=message
            )
        except Exception as e:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                severity=self.severity,
                message=f"规则执行出错: {e}"
            )


# ============================================================================
# 规则验证器
# ============================================================================

class RuleBasedVerifier(BaseVerifier):
    """
    规则验证器
    
    官方推荐：最佳验证形式是提供清晰定义的规则，并解释哪些规则失败及原因
    """
    
    def __init__(self, rules: List[VerificationRule]):
        self.rules = rules
    
    async def verify(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> VerificationResult:
        """执行规则验证"""
        rule_results = []
        all_passed = True
        error_count = 0
        
        for rule in self.rules:
            result = await rule.check(output, context)
            rule_results.append(result)
            
            if not result.passed:
                if result.severity == VerificationSeverity.ERROR:
                    all_passed = False
                    error_count += 1
        
        # 计算得分
        total_rules = len(self.rules)
        passed_rules = sum(1 for r in rule_results if r.passed)
        score = passed_rules / total_rules if total_rules > 0 else 0
        
        # 生成反馈
        feedback_parts = []
        for r in rule_results:
            if not r.passed:
                icon = "❌" if r.severity == VerificationSeverity.ERROR else "⚠️"
                feedback_parts.append(f"{icon} {r.rule_name}: {r.message}")
        
        feedback = "\n".join(feedback_parts) if feedback_parts else "✅ 所有规则验证通过"
        
        return VerificationResult(
            passed=all_passed,
            score=score,
            feedback=feedback,
            rule_results=rule_results,
            rules_passed=all_passed
        )
```

---

## 4. LLM 评判验证器

```python
# etf_common/agent_framework/verification/llm_judge.py

from typing import List, Dict, Any, Optional
import json

from .verifier import BaseVerifier, VerificationResult, RuleResult, VerificationSeverity


class LLMJudgeVerifier(BaseVerifier):
    """
    LLM 评判验证器
    
    官方说明：
    "This is generally not a very robust method, and can have heavy latency
    tradeoffs, but for applications where any boost in performance is worth
    the cost, it can be helpful."
    
    适用场景：模糊规则、主观评估、内容质量
    """
    
    def __init__(
        self,
        llm_client: Any,
        criteria: List[str],
        threshold: float = 0.7,
        model_name: str = None
    ):
        """
        初始化 LLM 评判验证器
        
        Args:
            llm_client: LLM 客户端
            criteria: 评估标准列表
            threshold: 通过阈值 (0-1)
            model_name: 指定模型（可选）
        """
        self.llm_client = llm_client
        self.criteria = criteria
        self.threshold = threshold
        self.model_name = model_name
    
    async def verify(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> VerificationResult:
        """使用 LLM 评判输出质量"""
        
        # 序列化输出
        if isinstance(output, dict):
            output_str = json.dumps(output, ensure_ascii=False, indent=2)
        else:
            output_str = str(output)
        
        # 构建评判 prompt
        criteria_text = "\n".join([f"- {c}" for c in self.criteria])
        context_text = ""
        if context:
            context_text = f"\n## 上下文信息\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        
        prompt = f"""请作为评审专家，评估以下输出是否符合要求。

## 评估标准
{criteria_text}

## 待评估的输出
```
{output_str[:10000]}
```
{context_text}

请按以下 JSON 格式输出评估结果（直接输出 JSON，不要包含代码块）：
{{
    "passed": true或false,
    "score": 0到1之间的分数,
    "overall_feedback": "总体评价",
    "criteria_results": [
        {{
            "criterion": "标准名称",
            "passed": true或false,
            "score": 0到1之间的分数,
            "comment": "具体评语"
        }}
    ],
    "improvement_suggestions": ["改进建议1", "改进建议2"]
}}"""

        try:
            response = await self.llm_client.generate(prompt)
            
            # 解析响应
            result = self._parse_response(response)
            
            # 判断是否通过
            score = result.get("score", 0)
            passed = result.get("passed", False) and score >= self.threshold
            
            # 构建规则结果
            rule_results = []
            for cr in result.get("criteria_results", []):
                rule_results.append(RuleResult(
                    rule_name=cr.get("criterion", "未知标准"),
                    passed=cr.get("passed", False),
                    severity=VerificationSeverity.WARNING,
                    message=cr.get("comment", ""),
                    details={"score": cr.get("score", 0)}
                ))
            
            # 构建反馈
            feedback_parts = [result.get("overall_feedback", "")]
            suggestions = result.get("improvement_suggestions", [])
            if suggestions:
                feedback_parts.append("\n**改进建议：**")
                for s in suggestions:
                    feedback_parts.append(f"- {s}")
            
            return VerificationResult(
                passed=passed,
                score=score,
                feedback="\n".join(feedback_parts),
                rule_results=rule_results,
                llm_passed=passed
            )
            
        except Exception as e:
            return VerificationResult(
                passed=False,
                score=0,
                feedback=f"LLM 评判失败: {e}",
                rule_results=[],
                llm_passed=False
            )
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 响应"""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取 JSON
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                if end > start:
                    return json.loads(response[start:end].strip())
            
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
            
            return {"passed": False, "score": 0, "overall_feedback": "无法解析响应"}
```

---

## 5. 组合验证器

```python
# etf_common/agent_framework/verification/composite_verifier.py

from typing import List, Dict, Any
from .verifier import BaseVerifier, VerificationResult, RuleResult


class CompositeVerifier(BaseVerifier):
    """
    组合验证器 - 支持多层验证
    
    执行顺序：规则验证 → 视觉验证 → LLM 评判
    可配置为：全部通过 / 任一通过 / 加权评分
    """
    
    def __init__(
        self,
        verifiers: List[BaseVerifier],
        mode: str = "all",  # all, any, weighted
        weights: List[float] = None,
        short_circuit: bool = True  # 是否在失败时短路
    ):
        """
        初始化组合验证器
        
        Args:
            verifiers: 验证器列表
            mode: 组合模式
                - "all": 所有验证器都通过才算通过
                - "any": 任一验证器通过即算通过
                - "weighted": 加权评分
            weights: 各验证器权重（用于 weighted 模式）
            short_circuit: 是否在第一个失败时停止
        """
        self.verifiers = verifiers
        self.mode = mode
        self.weights = weights or [1.0] * len(verifiers)
        self.short_circuit = short_circuit
    
    async def verify(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> VerificationResult:
        """执行组合验证"""
        
        all_results: List[VerificationResult] = []
        all_rule_results: List[RuleResult] = []
        
        for i, verifier in enumerate(self.verifiers):
            result = await verifier.verify(output, context)
            all_results.append(result)
            all_rule_results.extend(result.rule_results)
            
            # 短路逻辑
            if self.short_circuit and not result.passed and self.mode == "all":
                break
            if self.short_circuit and result.passed and self.mode == "any":
                break
        
        # 计算最终结果
        if self.mode == "all":
            passed = all(r.passed for r in all_results)
            score = sum(r.score for r in all_results) / len(all_results) if all_results else 0
            
        elif self.mode == "any":
            passed = any(r.passed for r in all_results)
            score = max(r.score for r in all_results) if all_results else 0
            
        else:  # weighted
            total_weight = sum(self.weights[:len(all_results)])
            weighted_score = sum(
                r.score * w 
                for r, w in zip(all_results, self.weights)
            )
            score = weighted_score / total_weight if total_weight > 0 else 0
            passed = score >= 0.7  # 加权模式使用阈值
        
        # 合并反馈
        feedback_parts = []
        for i, r in enumerate(all_results):
            verifier_name = type(self.verifiers[i]).__name__
            status = "✅" if r.passed else "❌"
            feedback_parts.append(f"\n### {verifier_name} {status}")
            feedback_parts.append(r.feedback)
        
        return VerificationResult(
            passed=passed,
            score=score,
            feedback="\n".join(feedback_parts),
            rule_results=all_rule_results,
            rules_passed=all_results[0].rules_passed if all_results else True,
            llm_passed=next(
                (r.llm_passed for r in all_results if r.llm_passed is not None),
                None
            )
        )
```

---

## 6. 领域验证规则示例

```python
# etf_common/agent_framework/verification/rules/financial_rules.py

from typing import Dict, Any
from ..rule_verifier import VerificationRule, RuleResult, VerificationSeverity
import json


class FinancialDataAccuracyRule(VerificationRule):
    """财务数据准确性验证"""
    
    def __init__(self):
        super().__init__(
            name="财务数据准确性",
            description="验证财务数据的合理性和一致性"
        )
    
    async def check(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> RuleResult:
        if isinstance(output, str):
            output = json.loads(output)
        
        errors = []
        
        # 检查利润率合理性
        financial = output.get("financial_analysis", {})
        if "gross_margin" in financial:
            margin = financial["gross_margin"]
            if margin < 0 or margin > 100:
                errors.append(f"毛利率 {margin}% 超出合理范围 (0-100%)")
        
        if "net_margin" in financial:
            margin = financial["net_margin"]
            if margin < -100 or margin > 100:
                errors.append(f"净利率 {margin}% 超出合理范围")
        
        # 检查增长率合理性
        if "revenue_growth" in financial:
            growth = financial["revenue_growth"]
            if abs(growth) > 500:
                errors.append(f"营收增长率 {growth}% 异常，请确认数据")
        
        if errors:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                severity=self.severity,
                message=f"发现 {len(errors)} 个数据问题",
                details={"errors": errors}
            )
        
        return RuleResult(
            rule_name=self.name,
            passed=True,
            severity=self.severity,
            message="财务数据通过合理性检查"
        )


class InvestmentOpinionConsistencyRule(VerificationRule):
    """投资建议一致性验证"""
    
    def __init__(self):
        super().__init__(
            name="投资建议一致性",
            description="验证投资建议与分析结论的一致性"
        )
    
    async def check(
        self,
        output: Any,
        context: Dict[str, Any] = None
    ) -> RuleResult:
        if isinstance(output, str):
            output = json.loads(output)
        
        opinion = output.get("investment_opinion", {})
        risk = output.get("risk_analysis", {})
        
        recommendation = opinion.get("opinion", "")
        risk_level = risk.get("risk_level", "")
        
        # 检查一致性：高风险不应该强烈推荐
        inconsistencies = []
        
        if risk_level == "高" and recommendation in ["强烈推荐", "推荐"]:
            inconsistencies.append(
                f"风险等级为'{risk_level}'，但投资建议为'{recommendation}'，存在矛盾"
            )
        
        if risk_level == "低" and recommendation in ["回避", "谨慎"]:
            inconsistencies.append(
                f"风险等级为'{risk_level}'，但投资建议为'{recommendation}'，请确认逻辑"
            )
        
        if inconsistencies:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                severity=VerificationSeverity.WARNING,
                message="投资建议与风险评估存在不一致",
                details={"inconsistencies": inconsistencies}
            )
        
        return RuleResult(
            rule_name=self.name,
            passed=True,
            severity=self.severity,
            message="投资建议与分析结论一致"
        )
```

---

## 7. 使用示例

```python
# 示例：创建金融分析验证器

from etf_common.agent_framework.verification import (
    CompositeVerifier,
    RuleBasedVerifier,
    LLMJudgeVerifier,
    JSONFormatRule,
    RequiredFieldsRule,
    EnumValueRule,
    FinancialDataAccuracyRule,
    InvestmentOpinionConsistencyRule
)

def create_financial_analysis_verifier(llm_client):
    """创建金融分析验证器"""
    
    # 第一层：规则验证
    rule_verifier = RuleBasedVerifier([
        # 基础格式
        JSONFormatRule(),
        RequiredFieldsRule([
            "company_name",
            "summary",
            "financial_analysis",
            "risk_analysis",
            "investment_opinion"
        ]),
        
        # 枚举值
        EnumValueRule(
            field="investment_opinion.opinion",
            allowed_values=["强烈推荐", "推荐", "中性", "谨慎", "回避"]
        ),
        EnumValueRule(
            field="risk_analysis.risk_level",
            allowed_values=["高", "中", "低"]
        ),
        
        # 业务规则
        FinancialDataAccuracyRule(),
        InvestmentOpinionConsistencyRule(),
    ])
    
    # 第二层：LLM 评判（仅在规则通过后执行）
    llm_verifier = LLMJudgeVerifier(
        llm_client=llm_client,
        criteria=[
            "分析逻辑是否清晰完整",
            "数据引用是否准确",
            "风险分析是否全面",
            "投资建议是否有充分支撑"
        ],
        threshold=0.7
    )
    
    # 组合验证器
    return CompositeVerifier(
        verifiers=[rule_verifier, llm_verifier],
        mode="all",
        short_circuit=True  # 规则验证失败则不执行 LLM 评判
    )


# 使用验证器
async def verify_analysis_result(result: dict, llm_client):
    verifier = create_financial_analysis_verifier(llm_client)
    
    verification_result = await verifier.verify(
        output=result,
        context={"task": "金融分析"}
    )
    
    print(verification_result.format_feedback())
    
    if not verification_result.passed:
        # 返回失败原因，让 Agent 修改
        return {
            "passed": False,
            "feedback": verification_result.feedback,
            "failed_rules": [
                r.rule_name for r in verification_result.get_failed_rules()
            ]
        }
    
    return {"passed": True}
```


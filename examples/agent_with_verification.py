"""
验证器示例

展示如何使用验证系统：
1. 规则验证器 (RuleBasedVerifier)
2. JSON 格式验证
3. 必填字段验证
4. 组合验证器 (CompositeVerifier)

配置文件: config/app_config.yaml
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.verification import (
    RuleBasedVerifier,
    CompositeVerifier,
    JSONFormatRule,
    RequiredFieldsRule,
    VerificationResult,
)
from src.config import create_llm_client


def create_simple_verifier() -> RuleBasedVerifier:
    """创建简单的规则验证器"""
    return RuleBasedVerifier(rules=[
        JSONFormatRule(),
        RequiredFieldsRule(["name", "value"]),
    ])


def create_financial_verifier() -> CompositeVerifier:
    """创建金融分析验证器"""
    
    # 规则验证器
    rule_verifier = RuleBasedVerifier(rules=[
        JSONFormatRule(),
        RequiredFieldsRule([
            "company_name",
            "analysis_date",
            "recommendation",
        ]),
    ])
    
    # 组合验证器
    return CompositeVerifier(
        verifiers=[rule_verifier],
        strategy="all",  # 所有验证器都必须通过
    )


async def demonstrate_json_validation(verbose: bool = False):
    """演示 JSON 格式验证"""
    print("\n1. JSON 格式验证")
    print("-" * 40)
    
    rule = JSONFormatRule()
    
    # 有效的 JSON
    valid_json = '{"name": "test", "value": 123}'
    passed, feedback = rule.validate(valid_json)  # 规则验证是同步的
    print(f"   有效 JSON: {'通过' if passed else '失败'}")
    
    # 无效的 JSON
    invalid_json = '{name: test}'
    passed, feedback = rule.validate(invalid_json)
    print(f"   无效 JSON: {'通过' if passed else '失败'}")
    if verbose:
        print(f"   反馈: {feedback}")


async def demonstrate_required_fields(verbose: bool = False):
    """演示必填字段验证"""
    print("\n2. 必填字段验证")
    print("-" * 40)
    
    rule = RequiredFieldsRule(["name", "email", "age"])
    
    # 完整数据（使用 dict，不是 JSON 字符串）
    complete_data = {"name": "John", "email": "john@example.com", "age": 25}
    passed, feedback = rule.validate(complete_data)  # 规则验证是同步的
    print(f"   完整数据: {'通过' if passed else '失败'}")
    
    # 缺失字段
    incomplete_data = {"name": "John"}
    passed, feedback = rule.validate(incomplete_data)
    print(f"   缺失字段: {'通过' if passed else '失败'}")
    if verbose:
        print(f"   反馈: {feedback}")


async def demonstrate_rule_verifier(verbose: bool = False):
    """演示规则验证器"""
    print("\n3. 规则验证器 (RuleBasedVerifier)")
    print("-" * 40)
    
    verifier = create_simple_verifier()
    
    # 有效输出
    valid_output = '{"name": "test", "value": 100}'
    result = await verifier.verify(valid_output)
    print(f"   有效输出: {'通过' if result.passed else '失败'}")
    print(f"   评分: {result.score:.2f}")
    
    # 无效输出
    invalid_output = '{"name": "test"}'  # 缺少 value
    result = await verifier.verify(invalid_output)
    print(f"   无效输出: {'通过' if result.passed else '失败'}")
    print(f"   评分: {result.score:.2f}")
    if verbose and result.feedback:
        print(f"   反馈: {result.feedback}")


async def demonstrate_composite_verifier(verbose: bool = False):
    """演示组合验证器"""
    print("\n4. 组合验证器 (CompositeVerifier)")
    print("-" * 40)
    
    verifier = create_financial_verifier()
    
    # 有效的金融分析输出
    valid_analysis = '''{
        "company_name": "贵州茅台",
        "analysis_date": "2024-01-15",
        "recommendation": "买入",
        "target_price": 2000
    }'''
    
    result = await verifier.verify(valid_analysis)
    print(f"   有效分析: {'通过' if result.passed else '失败'}")
    print(f"   评分: {result.score:.2f}")
    
    # 无效的金融分析输出（缺少必填字段）
    invalid_analysis = '''{
        "company_name": "贵州茅台",
        "target_price": 2000
    }'''
    
    result = await verifier.verify(invalid_analysis)
    print(f"   无效分析: {'通过' if result.passed else '失败'}")
    print(f"   评分: {result.score:.2f}")
    if verbose and result.feedback:
        print(f"   反馈: {result.feedback}")


async def demonstrate_verification_feedback_loop(verbose: bool = False, model_tier: str = "default"):
    """演示验证反馈循环"""
    print("\n5. 验证反馈循环")
    print("-" * 40)
    
    verifier = create_financial_verifier()
    
    # 模拟 Agent 输出
    agent_output = '{"company_name": "示例公司"}'  # 不完整
    
    max_iterations = 3
    for i in range(max_iterations):
        print(f"\n   迭代 {i + 1}:")
        
        result = await verifier.verify(agent_output)
        print(f"   验证结果: {'通过' if result.passed else '失败'}")
        print(f"   评分: {result.score:.2f}")
        
        if result.passed:
            print("   验证通过，停止迭代")
            break
        
        # 模拟根据反馈修正输出
        if result.feedback:
            print(f"   反馈: {result.feedback[:50]}...")
            # 模拟修正
            agent_output = '''{
                "company_name": "示例公司",
                "analysis_date": "2024-01-15",
                "recommendation": "持有"
            }'''
            print("   [模拟] 根据反馈修正输出")
    
    print("\n   最终结果:")
    final_result = await verifier.verify(agent_output)
    print(f"   验证: {'通过' if final_result.passed else '失败'}")


async def run_example(verbose: bool = False, model_tier: str = "default"):
    """示例入口"""
    print("=" * 50)
    print("验证器示例")
    print("=" * 50)
    
    await demonstrate_json_validation(verbose)
    await demonstrate_required_fields(verbose)
    await demonstrate_rule_verifier(verbose)
    await demonstrate_composite_verifier(verbose)
    await demonstrate_verification_feedback_loop(verbose, model_tier)
    
    print("\n" + "=" * 50)
    print("示例完成")
    print("=" * 50)
    
    return {"status": "success"}


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="验证器示例")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细输出")
    parser.add_argument(
        "-t", "--tier", type=str, default="default",
        choices=["default", "light", "medium", "strong"],
        help="模型层级"
    )
    
    args = parser.parse_args()
    asyncio.run(run_example(verbose=args.verbose, model_tier=args.tier))

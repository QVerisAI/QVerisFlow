#!/usr/bin/env python
"""
Web UI 集成测试

测试对话式工作流构建器的后端功能：
1. 自然语言意图解析
2. 对话式构建器
3. 工作流执行与事件流
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.evolution.nl_intent_processor import (
    NLIntentProcessor,
    UserIntent,
    BuilderContext,
)
from src.evolution.result_extractor import (
    IntermediateResultExtractor,
    ExecutionEvent,
    ExecutionEventType,
)
from src.utils.logger import get_logger

logger = get_logger()


class WebUIIntegrationTest:
    """Web UI 集成测试"""
    
    def __init__(self):
        self.intent_processor = NLIntentProcessor()
        self.result_extractor = IntermediateResultExtractor()
    
    async def test_intent_parsing(self):
        """测试意图解析"""
        print("\n" + "=" * 60)
        print("📝 测试 1: 自然语言意图解析")
        print("=" * 60)
        
        test_cases = [
            # 构建相关
            ("帮我创建一个分析苹果股票的工作流", UserIntent.CREATE),
            ("添加一个新闻情绪分析的步骤", UserIntent.ADD_NODE),
            ("删除数据收集器", UserIntent.REMOVE_NODE),
            ("确认", UserIntent.APPROVE),
            ("撤销", UserIntent.ROLLBACK),
            ("保存", UserIntent.SAVE),
            
            # 执行相关
            ("执行这个工作流", UserIntent.EXECUTE),
            ("用特斯拉的数据测试一下", UserIntent.EXECUTE),
            ("暂停", UserIntent.PAUSE),
            ("继续", UserIntent.RESUME),
            ("停止执行", UserIntent.STOP),
            ("跳过当前节点", UserIntent.SKIP_NODE),
            
            # 通用
            ("这个工作流是做什么的？", UserIntent.QUESTION),
            ("帮助", UserIntent.HELP),
        ]
        
        passed = 0
        failed = 0
        
        for message, expected_intent in test_cases:
            context = BuilderContext()
            result = await self.intent_processor.parse(message, context)
            
            status = "✅" if result.intent == expected_intent else "❌"
            if result.intent == expected_intent:
                passed += 1
            else:
                failed += 1
            
            print(f"  {status} \"{message}\"")
            print(f"     预期: {expected_intent.value}, 实际: {result.intent.value}, 置信度: {result.confidence:.2f}")
            
            if result.entities:
                print(f"     实体: {result.entities}")
        
        print(f"\n  结果: {passed} 通过, {failed} 失败")
        return failed == 0
    
    async def test_context_aware_parsing(self):
        """测试上下文感知解析"""
        print("\n" + "=" * 60)
        print("📝 测试 2: 上下文感知意图解析")
        print("=" * 60)
        
        # 构建上下文
        context = BuilderContext(
            stage="workflow",
            is_executing=False,
            agents=[{"name": "DataCollector"}, {"name": "Analyzer"}],
            workflow_nodes=[{"node_id": "n1"}, {"node_id": "n2"}],
            checkpoints=["ckpt_001", "ckpt_002"],
        )
        
        test_cases = [
            ("好的，就这样", UserIntent.APPROVE),
            ("回滚到 ckpt_001", UserIntent.ROLLBACK),
        ]
        
        for message, expected_intent in test_cases:
            result = await self.intent_processor.parse(message, context)
            status = "✅" if result.intent == expected_intent else "❌"
            print(f"  {status} \"{message}\" -> {result.intent.value}")
        
        # 执行上下文
        exec_context = BuilderContext(
            stage="workflow",
            is_executing=True,
            current_node="analyzer",
        )
        
        exec_cases = [
            ("暂停一下", UserIntent.PAUSE),
            ("跳过", UserIntent.SKIP_NODE),
        ]
        
        print("\n  执行模式下:")
        for message, expected_intent in exec_cases:
            result = await self.intent_processor.parse(message, exec_context)
            status = "✅" if result.intent == expected_intent else "❌"
            print(f"  {status} \"{message}\" -> {result.intent.value}")
        
        return True
    
    async def test_result_extractor(self):
        """测试中间结果提取"""
        print("\n" + "=" * 60)
        print("📝 测试 3: 中间结果提取")
        print("=" * 60)
        
        # 测试关键发现提取
        sample_output = {
            "trend": "bullish",
            "price": 178.5,
            "support_level": 175.0,
            "resistance_level": 185.0,
            "volume": 1500000,
            "analysis": {
                "summary": "股价呈现上涨趋势",
                "confidence": 0.85,
            }
        }
        
        findings = await self.result_extractor.extract_key_findings(sample_output)
        print(f"  提取的关键发现 ({len(findings)} 项):")
        for finding in findings:
            print(f"    - {finding}")
        
        # 测试摘要生成
        summary = await self.result_extractor.summarize_output(sample_output, max_length=100)
        print(f"\n  生成的摘要:")
        print(f"    {summary}")
        
        # 测试事件格式化
        print("\n  测试事件格式化:")
        
        events = [
            ExecutionEvent(
                event_type=ExecutionEventType.WORKFLOW_STARTED,
                workflow_id="test_workflow",
            ),
            ExecutionEvent(
                event_type=ExecutionEventType.NODE_STARTED,
                workflow_id="test_workflow",
                node_id="data_collector",
                node_name="数据收集器",
            ),
            ExecutionEvent(
                event_type=ExecutionEventType.TOOL_CALL,
                workflow_id="test_workflow",
                node_id="data_collector",
                data={"tool_id": "qveris_search_tools", "params": {"query": "stock API"}},
            ),
            ExecutionEvent(
                event_type=ExecutionEventType.NODE_COMPLETED,
                workflow_id="test_workflow",
                node_id="data_collector",
                node_name="数据收集器",
                data={"duration_ms": 12300, "output_preview": {"records": 100}},
            ),
            ExecutionEvent(
                event_type=ExecutionEventType.WORKFLOW_COMPLETED,
                workflow_id="test_workflow",
                data={"total_duration_ms": 45600, "nodes_completed": 3, "total_nodes": 3},
            ),
        ]
        
        for event in events:
            formatted = await self.result_extractor.format_for_chat(event)
            print(f"    [{formatted.message_type}] {formatted.text}")
        
        return True
    
    async def run_all_tests(self):
        """运行所有测试"""
        print("\n" + "=" * 60)
        print("🧪 Web UI 集成测试")
        print("=" * 60)
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        results = []
        
        # 测试 1: 意图解析
        try:
            results.append(("意图解析", await self.test_intent_parsing()))
        except Exception as e:
            print(f"  ❌ 测试失败: {e}")
            results.append(("意图解析", False))
        
        # 测试 2: 上下文感知
        try:
            results.append(("上下文感知", await self.test_context_aware_parsing()))
        except Exception as e:
            print(f"  ❌ 测试失败: {e}")
            results.append(("上下文感知", False))
        
        # 测试 3: 结果提取
        try:
            results.append(("结果提取", await self.test_result_extractor()))
        except Exception as e:
            print(f"  ❌ 测试失败: {e}")
            results.append(("结果提取", False))
        
        # 汇总
        print("\n" + "=" * 60)
        print("📊 测试结果汇总")
        print("=" * 60)
        
        passed = sum(1 for _, success in results if success)
        total = len(results)
        
        for name, success in results:
            status = "✅" if success else "❌"
            print(f"  {status} {name}")
        
        print(f"\n  总计: {passed}/{total} 测试通过")
        print(f"  状态: {'✅ 全部通过' if passed == total else '❌ 存在失败'}")
        
        return passed == total


async def main():
    """主函数"""
    test = WebUIIntegrationTest()
    success = await test.run_all_tests()
    
    print("\n" + "=" * 60)
    print("📖 使用说明")
    print("=" * 60)
    print("""
启动 Web UI 后端:
  uv run python -m src.web.app --host 0.0.0.0 --port 8000

启动前端开发服务器:
  cd web-ui
  npm install
  npm run dev

访问:
  http://localhost:5173
""")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

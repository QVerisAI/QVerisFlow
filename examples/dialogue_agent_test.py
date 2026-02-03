#!/usr/bin/env python3
"""
对话 Agent 测试

测试新的 LLM 对话 Agent 工作流构建功能
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import AppConfigLoader
from src.evolution.meta_agent import MetaAgent
from src.evolution.conversational_builder import ConversationalWorkflowBuilder
from src.tools.registry import ToolRegistry


async def test_dialogue_agent():
    """测试对话 Agent"""
    print("=" * 60)
    print("对话 Agent 测试")
    print("=" * 60)
    
    # 1. 初始化配置
    print("\n📋 初始化配置...")
    config = AppConfigLoader()
    config.load()
    
    # 2. 初始化 LLM 客户端
    print("🤖 初始化 LLM 客户端...")
    llm_client = config.create_llm_client()
    
    # 3. 初始化工具注册表
    print("🔧 初始化工具注册表...")
    tool_registry = ToolRegistry()
    
    # 4. 初始化 MetaAgent
    print("🧠 初始化 MetaAgent...")
    meta_agent = MetaAgent(
        llm_client=llm_client,
        tool_registry=tool_registry,
    )
    
    # 5. 初始化对话式构建器
    print("💬 初始化对话式构建器...")
    builder = ConversationalWorkflowBuilder(
        meta_agent=meta_agent,
        tool_registry=tool_registry,
        llm_client=llm_client,
        storage_path=Path("./workspaces/dialogue_test"),
    )
    
    print("\n✅ 初始化完成!")
    print(f"   会话 ID: {builder.session_id}")
    print(f"   会话模式: {builder.mode.value}")
    
    # 6. 测试对话
    test_messages = [
        "创建一个比特币价格分析工作流，需要收集数据、分析趋势、生成报告",
        "在数据收集之后添加一个技术指标分析的环节",
        "让技术指标分析依赖数据收集",
        "查看当前工作流状态",
        "确认规划",
    ]
    
    print("\n" + "=" * 60)
    print("开始对话测试")
    print("=" * 60)
    
    for i, msg in enumerate(test_messages, 1):
        print(f"\n--- 对话轮次 {i} ---")
        print(f"👤 用户: {msg}")
        
        try:
            response = await builder.process_message(msg)
            print(f"🤖 助手: {response.message[:500]}..." if len(response.message) > 500 else f"🤖 助手: {response.message}")
            
            if response.workflow_changed:
                print("   📊 工作流已更新")
            
            if response.suggested_actions:
                print(f"   💡 建议操作: {', '.join(response.suggested_actions)}")
            
            # 显示当前状态
            session_info = builder.get_session_info()
            print(f"   📌 状态: 模式={session_info['mode']}, 阶段={session_info['stage']}, Agent数={session_info['agent_count']}")
            
        except Exception as e:
            print(f"❌ 错误: {e}")
            import traceback
            traceback.print_exc()
        
        # 短暂等待，避免请求过快
        await asyncio.sleep(1)
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
    
    # 显示最终状态
    final_info = builder.get_session_info()
    print(f"\n📊 最终会话状态:")
    print(f"   - 模式: {final_info['mode']}")
    print(f"   - 阶段: {final_info['stage']}")
    print(f"   - 消息数: {final_info['message_count']}")
    print(f"   - Agent 数: {final_info['agent_count']}")
    print(f"   - 检查点数: {final_info['checkpoint_count']}")


async def test_specific_operations():
    """测试特定操作"""
    print("\n" + "=" * 60)
    print("特定操作测试")
    print("=" * 60)
    
    # 初始化
    config = AppConfigLoader()
    config.load()
    llm_client = config.create_llm_client()
    tool_registry = ToolRegistry()
    meta_agent = MetaAgent(llm_client=llm_client, tool_registry=tool_registry)
    
    builder = ConversationalWorkflowBuilder(
        meta_agent=meta_agent,
        tool_registry=tool_registry,
        llm_client=llm_client,
    )
    
    # 测试各种类型的用户输入
    test_cases = [
        # 创建工作流
        ("创建一个股票分析工作流", "应该创建工作流规划"),
        # 调整依赖
        ("把分析器放在收集器之后", "应该调整依赖关系"),
        # 并行执行
        ("让数据收集和新闻分析并行执行", "应该设置并行"),
        # 重排序
        ("调整执行顺序", "应该理解重排序意图"),
        # 确认
        ("好的，确认", "应该批准当前状态"),
        # 回滚
        ("撤销刚才的操作", "应该回滚"),
    ]
    
    for msg, expected in test_cases:
        print(f"\n测试: {msg}")
        print(f"预期: {expected}")
        
        try:
            response = await builder.process_message(msg)
            print(f"响应: {response.message[:200]}..." if len(response.message) > 200 else f"响应: {response.message}")
            print(f"工作流变更: {response.workflow_changed}")
        except Exception as e:
            print(f"错误: {e}")
        
        await asyncio.sleep(1)


if __name__ == "__main__":
    print("=" * 60)
    print("LLM 对话 Agent 工作流构建测试")
    print("=" * 60)
    
    # 运行测试
    asyncio.run(test_dialogue_agent())

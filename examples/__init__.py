"""
Agent Framework Examples

这个模块包含了 Agent Framework 的完整使用示例，包括：
- 简单 Agent 示例
- 工具集成示例
- 验证器示例
- 多 Agent 工作流示例
- Meta Agent 演化示例
- A/B 测试示例
- 性能监控示例

使用方法:
    python -m examples --list           # 列出所有可用示例
    python -m examples simple           # 运行简单 Agent 示例
    python -m examples tools            # 运行工具集成示例
    python -m examples verification     # 运行验证器示例
    python -m examples workflow         # 运行工作流示例
    python -m examples meta             # 运行 Meta Agent 示例
    python -m examples ab               # 运行 A/B 测试示例
    python -m examples monitor          # 运行性能监控示例
"""

__version__ = "1.0.0"

# 导出示例模块
__all__ = [
    "simple_agent",
    "agent_with_tools",
    "agent_with_verification",
    "workflow_example",
    "meta_agent_example",
    "ab_testing_example",
    "performance_monitoring",
]

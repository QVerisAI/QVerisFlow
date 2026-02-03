"""
Agent Framework

基于 LangGraph 的多智能体框架，支持声明式配置、工作空间管理、
三层验证机制和智能演化能力。

核心特性：
- 文件系统优先 - 所有交互通过文件系统
- 标准核心循环 - gather_context -> take_action -> verify_work -> repeat
- 声明式配置 - YAML/JSON 定义 Agent、工具、工作流
- 智能演化 - 支持动态创建、编辑、优化
- 三层验证 - 规则验证 + LLM 评判 + 组合验证

使用方式:
    from src.definitions import AgentDefinition, ToolDefinition
    from src.core import BaseAgent, AgentGraphBuilder
    from src.tools import ToolRegistry
    from src.workspace import AgentWorkspace
"""

__version__ = "1.0.0"

# 延迟导入，避免在测试时出现循环导入问题
# 实际使用时从 src 子模块导入

__all__ = [
    "__version__",
]

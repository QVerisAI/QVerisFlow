"""
三层 Prompt 结构定义

提供 BackgroundInstruction、OutputInstruction、UserInstruction 的
Pydantic 模型定义，实现分层、可组合的 Prompt 设计。
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class BackgroundInstruction(BaseModel):
    """
    背景指令 - 定义角色和核心能力

    对应设计文档中的第一层 Prompt，用于建立 Agent 的基本角色定位。
    """

    role_description: str = Field(
        description="角色描述，如：'你是一位资深股票技术分析师，专注于突破形态的量化定义与识别'"
    )
    core_capability: str = Field(
        description="核心能力，如：'你的核心能力是制定清晰、可量化的技术标准'"
    )
    task_context: str = Field(
        description="任务上下文，如：'在本工作流中，你的任务是建立一套严格、可执行的规则'"
    )
    references: Optional[List[str]] = Field(
        default=None,
        description="引用的上下文，如 ['#定义突破标准', '#收集关联信息公告']",
    )

    def to_prompt(self) -> str:
        """转换为 prompt 文本"""
        parts = [self.role_description, self.core_capability, self.task_context]
        if self.references:
            parts.append(f"\n# 选择引用\n{', '.join(self.references)}")
        return "\n\n".join(parts)


class OutputInstruction(BaseModel):
    """
    输出指令 - 控制输出格式和风格

    对应设计文档中的第二层 Prompt，用于规范 Agent 的输出格式。
    """

    format_type: str = Field(
        default="json", description="输出格式类型：json, markdown, plain_text, html"
    )
    data_format: str = Field(
        default="json",
        description="data 字段的格式类型：json（结构化 JSON 对象）或 markdown（Markdown 文本）",
    )
    format_requirements: List[str] = Field(
        default_factory=lambda: [
            "**不要把 markdown 尝试包在 json 格式内**",
            "**不要在生成的内容中使用 markdown 代码块语法**",
            "直接输出内容文本，不要用代码块包裹",
        ],
        description="格式要求列表",
    )
    style_requirements: Optional[List[str]] = Field(
        default=None,
        description="风格要求，如：['语言简洁、客观', '聚焦于价格、成交量、关键位等客观事实']",
    )

    def to_prompt(self) -> str:
        """转换为 prompt 文本"""
        parts = []
        if self.style_requirements:
            for req in self.style_requirements:
                parts.append(f"* {req}")
            parts.append("\n**重要格式要求：**")
        for req in self.format_requirements:
            parts.append(f"- {req}")

        return "\n".join(parts)


class UserInstruction(BaseModel):
    """
    用户指令 - 具体任务描述

    对应设计文档中的第三层 Prompt，用于描述具体的执行任务。
    """

    task_description: str = Field(description="任务描述")
    tool_references: List[str] = Field(
        default_factory=list,
        description="工具引用列表，如 ['@公告搜索', '@新闻搜索', '@公司股票价格']",
    )
    context_references: List[str] = Field(
        default_factory=list, description="上下文引用，如 ['#分析信号与信息时序']"
    )
    known_information: Optional[str] = Field(
        default=None, description="已知信息，从之前节点获取"
    )

    def to_prompt(self) -> str:
        """转换为 prompt 文本"""
        parts = [self.task_description]

        if self.known_information:
            parts.append(f"\n已知以下信息：\n{self.known_information}")

        # 工具引用会在 prompt 解析时替换为实际工具描述
        return "\n\n".join(parts)


class PromptStructure(BaseModel):
    """
    完整 Prompt 结构 - 组合三层指令

    将 BackgroundInstruction、OutputInstruction、UserInstruction 组合为完整的 Prompt。
    """

    background: Optional[BackgroundInstruction] = Field(
        default=None, description="背景指令（第一层）"
    )
    output: Optional[OutputInstruction] = Field(
        default=None, description="输出指令（第二层）"
    )
    user: Optional[UserInstruction] = Field(
        default=None, description="用户指令（第三层）"
    )

    def to_prompt(self) -> str:
        """
        转换为完整的 prompt 文本

        按照 背景 -> 输出 -> 用户 的顺序组合。
        """
        parts = []

        if self.background:
            parts.append("# 背景\n" + self.background.to_prompt())

        if self.output:
            parts.append("# 输出要求\n" + self.output.to_prompt())

        if self.user:
            parts.append("# 任务\n" + self.user.to_prompt())

        return "\n\n".join(parts)

"""
Agent 定义模型

提供 Agent 的完整结构化定义，包括角色、能力、Prompt 配置、
模型配置、工具引用等。
"""

from enum import Enum
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field, field_validator

from .prompt_structure import (
    BackgroundInstruction,
    OutputInstruction,
    UserInstruction,
)
from .tool_definition import ToolReference


class AgentExecutionType(str, Enum):
    """
    智能体执行类型 - 决定执行策略

    来自设计文档 02_definitions.md
    """

    REASONING_EXECUTOR = "reasoning_executor"  # 推理执行智能体：需要深度思考，使用 CoT
    EXECUTOR = "executor"  # 执行智能体：快速执行，直接输出
    DEEP_SEARCH = "deep_search"  # 深度搜索：多轮搜索，信息聚合
    FLOW_AGENT = "flow_agent"  # 流程智能体：工作流编排
    HTML_GENERATOR = "html_generator"  # HTML 文档生成
    MARKDOWN_GENERATOR = "markdown_generator"  # Markdown 文档生成


class AgentDomainType(str, Enum):
    """智能体领域类型"""

    FINANCIAL_ANALYSIS = "financial_analysis"  # 金融分析
    DATA_INTEGRATION = "data_integration"  # 数据集成/收集
    DATA_VERIFICATION = "data_verification"  # 数据验证
    RISK_ASSESSMENT = "risk_assessment"  # 风险评估
    SIGNAL_DETECTION = "signal_detection"  # 信号检测
    REPORT_GENERATION = "report_generation"  # 报告生成
    GENERAL = "general"  # 通用


class ModelConfig(BaseModel):
    """模型配置"""

    model_name: str = Field(default="deepseek/deepseek-v3", description="模型名称")
    temperature: float = Field(default=0.3, description="温度参数")
    max_tokens: int = Field(default=4096, description="最大输出 tokens")
    max_iterations: int = Field(
        default=10, description="最大迭代次数（用于深度搜索等）"
    )
    enable_online: bool = Field(default=False, description="是否启用联网模式")


class AgentDefinition(BaseModel):
    """
    完整的 Agent 定义

    对应设计文档中的单个节点配置，包含 Agent 的所有元数据、
    Prompt 配置、模型配置和工具引用。
    """

    # === 基本信息 ===
    agent_id: str = Field(description="Agent 唯一标识")
    name: str = Field(description="Agent 技术名称，如 'DataCollectorAgent'")
    display_name: str = Field(
        default="", description="用户友好的显示名称，如 '数据收集器'"
    )
    description: str = Field(description="Agent 描述")
    version: str = Field(default="1.0.0", description="版本号")

    # === 类型配置 ===
    execution_type: AgentExecutionType = Field(
        default=AgentExecutionType.EXECUTOR, description="执行类型"
    )
    domain_type: AgentDomainType = Field(
        default=AgentDomainType.GENERAL, description="领域类型"
    )

    # === Prompt 配置（三层结构）===
    background_instruction: BackgroundInstruction = Field(description="背景指令")
    output_instruction: OutputInstruction = Field(description="输出指令")
    user_instruction: UserInstruction = Field(description="用户指令")

    # === 模型配置 ===
    llm_config: ModelConfig = Field(
        default_factory=ModelConfig, description="LLM 模型配置"
    )

    # === 工具配置 ===
    tool_references: List[ToolReference] = Field(
        default_factory=list, description="工具引用列表"
    )

    # === 输入输出 Schema ===
    input_schema: Optional[Dict[str, Any]] = Field(
        default=None, description="输入 JSON Schema"
    )
    output_schema: Optional[Dict[str, Any]] = Field(
        default=None, description="输出 JSON Schema"
    )

    # === 文件系统配置 ===
    file_operations: Optional[Dict[str, Any]] = Field(
        default=None, description="文件操作配置：读取、写入、输出路径等"
    )

    # === 元数据 ===
    tags: List[str] = Field(default_factory=list, description="标签")
    author: str = Field(default="system", description="创建者")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    is_active: bool = Field(default=True, description="是否激活")

    @field_validator("tool_references", mode="before")
    @classmethod
    def convert_tool_references(cls, v: Optional[List[Any]]) -> List[ToolReference]:
        """确保 tool_references 中的项都是 ToolReference 对象"""
        if not v:
            return []
        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(ToolReference(**item))
            elif isinstance(item, ToolReference):
                result.append(item)
            else:
                # 尝试转换
                result.append(ToolReference.model_validate(item))
        return result

    def build_system_prompt(self) -> str:
        """构建完整的系统 prompt"""
        return self.background_instruction.to_prompt()

    def build_output_prompt(self) -> str:
        """构建输出指令 prompt"""
        return self.output_instruction.to_prompt()

    def build_user_prompt(self, context: Optional[Dict[str, Any]] = None) -> str:
        """
        构建用户 prompt，注入上下文

        Args:
            context: 上下文字典，可以包含之前节点的输出

        Returns:
            完整的用户 prompt
        """
        prompt = self.user_instruction.to_prompt()

        # 注入已知信息（来自之前节点）
        if context and self.user_instruction.context_references:
            known_info_parts = []
            for ref in self.user_instruction.context_references:
                ref_key = ref.replace("#", "").strip()
                if ref_key in context:
                    known_info_parts.append(f"## {ref_key}\n{context[ref_key]}")

            if known_info_parts:
                prompt = prompt.replace(
                    "已知以下信息：",
                    f"已知以下信息：\n" + "\n\n".join(known_info_parts),
                )

        return prompt

    @classmethod
    def from_yaml_file(cls, file_path: str) -> "AgentDefinition":
        """
        从 YAML 文件加载 Agent 定义

        Args:
            file_path: YAML 文件路径

        Returns:
            AgentDefinition 实例
        """
        import yaml
        from pathlib import Path

        path = Path(file_path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(**data)

    def to_yaml_file(self, file_path: str) -> None:
        """
        保存 Agent 定义到 YAML 文件

        Args:
            file_path: YAML 文件路径
        """
        import yaml
        from pathlib import Path

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                self.model_dump(mode="json"),
                f,
                allow_unicode=True,
                default_flow_style=False,
            )

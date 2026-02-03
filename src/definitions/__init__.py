"""定义层 - Agent、工具、工作流定义模型"""

from .prompt_structure import (
    BackgroundInstruction,
    OutputInstruction,
    UserInstruction,
    PromptStructure,
)
from .tool_definition import (
    ToolCategory,
    ToolReferenceType,
    ToolReference,
    ToolDefinition,
)
from .agent_definition import (
    AgentExecutionType,
    AgentDomainType,
    ModelConfig,
    AgentDefinition,
)
from .workflow_definition import (
    NodeType,
    DataMapping,
    WorkflowNode,
    WorkflowEdge,
    WorkflowDefinition,
)

__all__ = [
    # Prompt structure
    "BackgroundInstruction",
    "OutputInstruction",
    "UserInstruction",
    "PromptStructure",
    # Tool definitions
    "ToolCategory",
    "ToolReferenceType",
    "ToolReference",
    "ToolDefinition",
    # Agent definitions
    "AgentExecutionType",
    "AgentDomainType",
    "ModelConfig",
    "AgentDefinition",
    # Workflow definitions
    "NodeType",
    "DataMapping",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowDefinition",
]

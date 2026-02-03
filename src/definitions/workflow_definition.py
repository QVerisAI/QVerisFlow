"""
工作流定义模型

提供工作流的结构化定义，包括节点、边、数据映射和执行配置。
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """节点类型"""

    START = "start"  # 开始节点
    END = "end"  # 结束节点
    AGENT = "agent"  # Agent 执行节点
    CONDITION = "condition"  # 条件分支
    PARALLEL = "parallel"  # 并行执行
    LOOP = "loop"  # 循环
    HUMAN_IN_LOOP = "human_in_loop"  # 人工介入


class DataMapping(BaseModel):
    """数据映射配置"""

    source_node: str = Field(description="源节点ID")
    source_field: str = Field(description="源字段路径，如 'output.stocks'")
    target_field: str = Field(description="目标字段路径，如 'input.stock_list'")
    transform: Optional[str] = Field(
        default=None, description="转换表达式，如 'json.loads' 或 'lambda x: x[:5]'"
    )


class WorkflowNode(BaseModel):
    """
    工作流节点定义

    对应设计文档中的单个工作流节点，可以是 Agent 执行节点、
    条件分支节点或其他类型的控制节点。
    """

    node_id: str = Field(description="节点ID")
    name: str = Field(description="节点名称，如 '定义突破标准'")
    node_type: NodeType = Field(description="节点类型")

    # === 依赖配置 ===
    dependencies: List[str] = Field(
        default_factory=list, description="依赖的节点 ID 列表，这些节点必须先完成"
    )

    # === 节点配置 ===
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="节点特定配置，如 agent_id、tool_id、parallel_nodes 等",
    )

    # === Agent 配置（当 node_type == AGENT 时）===
    agent_id: Optional[str] = Field(default=None, description="关联的 Agent ID")

    # === 指令覆盖（可以覆盖 Agent 默认配置）===
    background_override: Optional[str] = Field(default=None, description="背景指令覆盖")
    output_override: Optional[str] = Field(default=None, description="输出指令覆盖")
    user_override: Optional[str] = Field(default=None, description="用户指令覆盖")

    # === 模型覆盖 ===
    model_override: Optional[str] = Field(
        default=None, description="模型覆盖，如 'deepseek/deepseek-v3'"
    )
    max_iterations_override: Optional[int] = Field(
        default=None, description="最大迭代次数覆盖"
    )

    # === 工具配置 ===
    additional_tools: List[str] = Field(
        default_factory=list, description="额外的工具引用"
    )
    disabled_tools: List[str] = Field(default_factory=list, description="禁用的工具")

    # === 输入映射（来自其他节点的输出）===
    input_mappings: List[DataMapping] = Field(
        default_factory=list, description="输入数据映射"
    )

    # === 上下文引用 ===
    context_refs: List[str] = Field(
        default_factory=list,
        description="上下文引用，如 ['#定义突破标准', '#收集关联信息公告']",
    )

    # === 条件配置（当 node_type == CONDITION 时）===
    condition_expression: Optional[str] = Field(
        default=None, description="条件表达式，如 'state.score >= 0.7'"
    )

    # === 执行配置 ===
    timeout: int = Field(default=300, description="超时时间（秒）")
    retry_count: int = Field(default=3, description="重试次数")
    continue_on_error: bool = Field(default=False, description="错误时是否继续")


class WorkflowEdge(BaseModel):
    """工作流边（连接）"""

    from_node: str = Field(description="源节点ID")
    to_node: str = Field(description="目标节点ID")
    condition: Optional[str] = Field(default=None, description="条件表达式")
    priority: int = Field(default=0, description="优先级（用于多条边时）")


class WorkflowDefinition(BaseModel):
    """
    完整的工作流定义

    对应设计文档中的工作流配置，定义了节点、边和全局配置。
    """

    workflow_id: str = Field(description="工作流ID")
    name: str = Field(description="工作流名称")
    description: str = Field(description="工作流描述")
    version: str = Field(default="1.0.0", description="版本号")

    # === 节点和边 ===
    nodes: List[WorkflowNode] = Field(description="节点列表")
    edges: List[WorkflowEdge] = Field(description="边列表")

    # === 入口和出口 ===
    entry_node: str = Field(description="入口节点ID")
    exit_nodes: List[str] = Field(description="出口节点ID列表")

    # === 全局配置 ===
    global_context: Dict[str, Any] = Field(
        default_factory=dict, description="全局上下文"
    )
    global_tools: List[str] = Field(default_factory=list, description="全局工具")

    # === 文件系统配置 ===
    workspace_path: Optional[str] = Field(default=None, description="工作空间路径")
    output_path: Optional[str] = Field(default=None, description="输出路径")

    # === 执行配置 ===
    continue_on_error: bool = Field(
        default=False, description="节点失败时是否继续执行后续节点"
    )
    exit_point: Optional[str] = Field(
        default=None, description="主出口节点 ID（可选，默认使用 exit_nodes[0]）"
    )

    # === 元数据 ===
    tags: List[str] = Field(default_factory=list)
    author: str = Field(default="system")
    created_at: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True, description="是否激活")

    @property
    def primary_exit(self) -> Optional[str]:
        """获取主出口节点 ID"""
        return self.exit_point or (self.exit_nodes[0] if self.exit_nodes else None)

    @classmethod
    def from_yaml_file(cls, file_path: str) -> "WorkflowDefinition":
        """
        从 YAML 文件加载工作流定义

        Args:
            file_path: YAML 文件路径

        Returns:
            WorkflowDefinition 实例
        """
        import yaml
        from pathlib import Path

        path = Path(file_path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(**data)

    def to_yaml_file(self, file_path: str) -> None:
        """
        保存工作流定义到 YAML 文件

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

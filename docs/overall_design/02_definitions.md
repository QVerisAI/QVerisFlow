# Agent、工具、工作流定义模型

## 1. 概述

本章定义了框架的核心数据模型，采用声明式设计，支持 YAML/JSON 配置和代码定义两种方式。

核心设计理念：
- **三层 Prompt 结构**：背景指令 + 输出指令 + 用户指令
- **引用语法**：@工具名 和 #上下文名
- **Schema 驱动**：输入输出都有明确的 Schema 定义

---

## 2. Agent 定义模型

### 2.1 完整定义结构

```python
# etf_common/agent_framework/definitions/agent_definition.py

from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class AgentExecutionType(str, Enum):
    """智能体执行类型 - 决定执行策略"""
    
    REASONING_EXECUTOR = "reasoning_executor"      # 推理执行：深度思考，CoT
    EXECUTOR = "executor"                          # 执行智能体：快速执行
    DEEP_SEARCH = "deep_search"                    # 深度搜索：多轮搜索
    FLOW_AGENT = "flow_agent"                      # 流程智能体：工作流编排
    HTML_GENERATOR = "html_generator"              # HTML 生成
    MARKDOWN_GENERATOR = "markdown_generator"      # Markdown 生成


class AgentDomainType(str, Enum):
    """智能体领域类型"""
    
    FINANCIAL_ANALYSIS = "financial_analysis"      # 金融分析
    FACT_VERIFICATION = "fact_verification"        # 事实质证
    DATA_VERIFICATION = "data_verification"        # 数据验证
    RISK_ASSESSMENT = "risk_assessment"            # 风险评估
    SIGNAL_DETECTION = "signal_detection"          # 信号检测
    REPORT_GENERATION = "report_generation"        # 报告生成
    RESEARCH = "research"                          # 研究
    GENERAL = "general"                            # 通用


# ============================================================================
# Prompt 三层结构
# ============================================================================

class BackgroundInstruction(BaseModel):
    """
    背景指令 - 定义角色和核心能力
    
    对应 System Prompt 的角色设定部分
    """
    
    role_description: str = Field(
        description="角色描述，如：'你是一位资深股票技术分析师'"
    )
    core_capability: str = Field(
        description="核心能力，如：'你的核心能力是制定可量化的技术标准'"
    )
    task_context: str = Field(
        description="任务上下文，如：'在本工作流中，你的任务是...'"
    )
    references: Optional[List[str]] = Field(
        default=None,
        description="引用的上下文，如 ['#定义突破标准', '#收集关联信息公告']"
    )
    
    def to_prompt(self) -> str:
        """转换为 prompt 文本"""
        parts = [
            f"## 角色定位\n{self.role_description}",
            f"\n## 核心能力\n{self.core_capability}",
            f"\n## 任务背景\n{self.task_context}"
        ]
        if self.references:
            parts.append(f"\n## 参考上下文\n{', '.join(self.references)}")
        return "\n".join(parts)


class OutputInstruction(BaseModel):
    """
    输出指令 - 控制输出格式和风格
    
    明确规定输出的格式要求，避免 LLM 输出不符合预期
    """
    
    format_type: str = Field(
        default="json",
        description="输出格式类型：json, markdown, plain_text, html"
    )
    format_requirements: List[str] = Field(
        default_factory=lambda: [
            "**不要把 markdown 尝试包在 json 格式内**",
            "**不要在生成的内容中使用 markdown 代码块语法**",
            "直接输出内容文本，不要用代码块包裹"
        ],
        description="格式要求列表"
    )
    style_requirements: Optional[List[str]] = Field(
        default=None,
        description="风格要求，如：['语言简洁、客观', '聚焦于数据事实']"
    )
    output_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description="输出 JSON Schema（用于 format_type=json 时）"
    )
    
    def to_prompt(self) -> str:
        """转换为 prompt 文本"""
        parts = [f"## 输出格式：{self.format_type.upper()}"]
        
        if self.style_requirements:
            parts.append("\n**风格要求：**")
            for req in self.style_requirements:
                parts.append(f"- {req}")
        
        parts.append("\n**格式要求：**")
        for req in self.format_requirements:
            parts.append(f"- {req}")
        
        if self.output_schema and self.format_type == "json":
            import json
            parts.append(f"\n**JSON Schema：**\n```json\n{json.dumps(self.output_schema, indent=2, ensure_ascii=False)}\n```")
        
        return "\n".join(parts)


class UserInstruction(BaseModel):
    """
    用户指令 - 具体任务描述
    
    包含任务描述、工具引用、上下文引用等
    """
    
    task_description: str = Field(
        description="任务描述"
    )
    tool_references: List[str] = Field(
        default_factory=list,
        description="工具引用列表，如 ['@公告搜索', '@新闻搜索', '@公司股票价格']"
    )
    context_references: List[str] = Field(
        default_factory=list,
        description="上下文引用，如 ['#分析信号与信息时序']"
    )
    known_information: Optional[str] = Field(
        default=None,
        description="已知信息，从之前节点获取"
    )
    examples: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Few-shot 示例：[{'input': '...', 'output': '...'}]"
    )
    
    def to_prompt(self, resolved_context: Dict[str, str] = None) -> str:
        """
        转换为 prompt 文本
        
        Args:
            resolved_context: 已解析的上下文引用 {'#上下文名': '内容'}
        """
        parts = [f"## 任务\n{self.task_description}"]
        
        # 注入已知信息
        if self.known_information:
            parts.append(f"\n## 已知信息\n{self.known_information}")
        
        # 注入解析后的上下文
        if resolved_context:
            for ref in self.context_references:
                if ref in resolved_context:
                    ref_name = ref.replace("#", "")
                    parts.append(f"\n## {ref_name}\n{resolved_context[ref]}")
        
        # 添加示例
        if self.examples:
            parts.append("\n## 示例")
            for i, ex in enumerate(self.examples, 1):
                parts.append(f"\n### 示例 {i}")
                parts.append(f"**输入：** {ex.get('input', '')}")
                parts.append(f"**输出：** {ex.get('output', '')}")
        
        # 工具引用说明（实际工具描述由解析器注入）
        if self.tool_references:
            parts.append(f"\n## 可用工具\n{', '.join(self.tool_references)}")
        
        return "\n".join(parts)


# ============================================================================
# 工具引用定义
# ============================================================================

class ToolReferenceType(str, Enum):
    """工具引用类型"""
    
    BUILTIN = "builtin"        # 内置工具
    CUSTOM = "custom"          # 自定义工具
    MCP = "mcp"                # MCP 协议工具
    EXTERNAL = "external"      # 外部 API


class ToolReference(BaseModel):
    """工具引用配置"""
    
    tool_id: str = Field(description="工具 ID")
    alias: str = Field(description="工具别名，用于 @引用，如 '公告搜索'")
    tool_type: ToolReferenceType = Field(
        default=ToolReferenceType.BUILTIN,
        description="工具类型"
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="工具参数覆盖/预设"
    )
    enabled: bool = Field(default=True, description="是否启用")


# ============================================================================
# 模型配置
# ============================================================================

class ModelConfig(BaseModel):
    """模型配置"""
    
    model_name: str = Field(
        default="deepseek/deepseek-v3",
        description="模型名称"
    )
    temperature: float = Field(
        default=0.3,
        ge=0, le=2,
        description="温度参数"
    )
    max_tokens: int = Field(
        default=4096,
        description="最大输出 tokens"
    )
    max_iterations: int = Field(
        default=10,
        description="最大迭代次数（用于深度搜索等）"
    )
    enable_online: bool = Field(
        default=False,
        description="是否启用联网模式"
    )
    fallback_model: Optional[str] = Field(
        default=None,
        description="降级模型名称"
    )


# ============================================================================
# 完整的 Agent 定义
# ============================================================================

class AgentDefinition(BaseModel):
    """
    完整的 Agent 定义
    
    支持 YAML 配置和代码定义两种方式
    """
    
    # === 基本信息 ===
    agent_id: str = Field(description="Agent 唯一标识")
    name: str = Field(description="Agent 名称")
    description: str = Field(description="Agent 描述")
    version: str = Field(default="1.0.0", description="版本号")
    
    # === 类型配置 ===
    execution_type: AgentExecutionType = Field(
        default=AgentExecutionType.EXECUTOR,
        description="执行类型"
    )
    domain_type: AgentDomainType = Field(
        default=AgentDomainType.GENERAL,
        description="领域类型"
    )
    
    # === Prompt 配置（三层结构）===
    background_instruction: BackgroundInstruction = Field(
        description="背景指令"
    )
    output_instruction: OutputInstruction = Field(
        description="输出指令"
    )
    user_instruction: UserInstruction = Field(
        description="用户指令"
    )
    
    # === 模型配置 ===
    model_config: ModelConfig = Field(
        default_factory=ModelConfig,
        description="模型配置"
    )
    
    # === 工具配置 ===
    tool_references: List[ToolReference] = Field(
        default_factory=list,
        description="工具引用列表"
    )
    
    # === 输入输出 Schema ===
    input_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description="输入 JSON Schema"
    )
    output_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description="输出 JSON Schema"
    )
    
    # === 验证配置 ===
    verification_rules: List[str] = Field(
        default_factory=list,
        description="验证规则 ID 列表"
    )
    
    # === 元数据 ===
    tags: List[str] = Field(default_factory=list, description="标签")
    author: str = Field(default="system", description="创建者")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    updated_at: Optional[str] = Field(default=None, description="更新时间")
    
    # === Prompt 构建方法 ===
    
    def build_system_prompt(self) -> str:
        """构建完整的系统 prompt"""
        parts = [
            self.background_instruction.to_prompt(),
            "\n---\n",
            self.output_instruction.to_prompt()
        ]
        return "\n".join(parts)
    
    def build_user_prompt(
        self,
        context: Dict[str, Any] = None,
        resolved_refs: Dict[str, str] = None
    ) -> str:
        """
        构建用户 prompt，注入上下文
        
        Args:
            context: 动态上下文数据
            resolved_refs: 已解析的 #引用
        """
        return self.user_instruction.to_prompt(resolved_refs)
    
    def get_enabled_tools(self) -> List[ToolReference]:
        """获取启用的工具列表"""
        return [t for t in self.tool_references if t.enabled]
    
    def to_yaml(self) -> str:
        """导出为 YAML 格式"""
        import yaml
        return yaml.dump(
            self.model_dump(exclude_none=True),
            allow_unicode=True,
            default_flow_style=False
        )
    
    @classmethod
    def from_yaml(cls, yaml_str: str) -> "AgentDefinition":
        """从 YAML 字符串加载"""
        import yaml
        data = yaml.safe_load(yaml_str)
        return cls(**data)
    
    @classmethod
    def from_yaml_file(cls, path: str) -> "AgentDefinition":
        """从 YAML 文件加载"""
        with open(path, 'r', encoding='utf-8') as f:
            return cls.from_yaml(f.read())
```

### 2.2 YAML 配置示例

```yaml
# agents/financial_analyst.yaml

agent_id: financial_analyst_v1
name: 金融分析师
description: 专业的金融分析 Agent，擅长公司基本面分析和投资价值评估
version: 1.0.0

# 类型配置
execution_type: reasoning_executor
domain_type: financial_analysis

# 背景指令
background_instruction:
  role_description: |
    你是一位资深的金融分析师，拥有超过 10 年的 A 股市场研究经验。
    你擅长从财务数据、行业趋势、公司治理等多维度分析公司的投资价值。
  core_capability: |
    你的核心能力包括：
    - 财务报表分析：营收、利润、现金流等关键指标解读
    - 估值分析：PE、PB、DCF 等多种估值方法
    - 行业比较：同行业公司横向对比
    - 风险识别：识别潜在的投资风险
  task_context: |
    在当前分析任务中，你需要综合考虑公司的财务数据、行业地位、
    竞争格局以及宏观环境，给出客观、专业的分析结论。
  references:
    - "#公司基本信息"
    - "#历史财务数据"

# 输出指令
output_instruction:
  format_type: json
  format_requirements:
    - "输出标准 JSON 格式，不要包含 markdown 代码块"
    - "所有数字保留两位小数"
    - "日期使用 ISO 8601 格式"
  style_requirements:
    - "语言专业、客观"
    - "结论有数据支撑"
    - "风险提示明确"
  output_schema:
    type: object
    required:
      - company_name
      - summary
      - financial_analysis
      - risk_analysis
      - investment_opinion
    properties:
      company_name:
        type: string
      summary:
        type: string
        description: 一句话投资建议
      financial_analysis:
        type: object
        properties:
          revenue_analysis:
            type: string
          profit_analysis:
            type: string
          cash_flow_analysis:
            type: string
      risk_analysis:
        type: object
        properties:
          key_risks:
            type: array
            items:
              type: string
          risk_level:
            type: string
            enum: [高, 中, 低]
      investment_opinion:
        type: object
        properties:
          opinion:
            type: string
            enum: [强烈推荐, 推荐, 中性, 谨慎, 回避]
          target_price:
            type: number
          rationale:
            type: string

# 用户指令
user_instruction:
  task_description: |
    请对目标公司进行全面的投资价值分析，包括：
    1. 公司基本面分析（营收、利润、现金流）
    2. 行业地位和竞争格局分析
    3. 估值水平分析
    4. 风险因素识别
    5. 投资建议和目标价
  tool_references:
    - "@财务数据查询"
    - "@公告搜索"
    - "@研报搜索"
    - "@股票价格"
  context_references:
    - "#公司基本信息"
    - "#历史财务数据"

# 模型配置
model_config:
  model_name: deepseek/deepseek-v3
  temperature: 0.3
  max_tokens: 4096
  max_iterations: 5
  enable_online: false
  fallback_model: deepseek/deepseek-chat

# 工具引用
tool_references:
  - tool_id: financial_data_query
    alias: 财务数据查询
    tool_type: builtin
    enabled: true
  - tool_id: announcement_search
    alias: 公告搜索
    tool_type: builtin
    enabled: true
  - tool_id: research_report_search
    alias: 研报搜索
    tool_type: builtin
    enabled: true
  - tool_id: stock_price
    alias: 股票价格
    tool_type: builtin
    enabled: true

# 验证规则
verification_rules:
  - json_format_check
  - required_fields_check
  - financial_data_accuracy

# 元数据
tags:
  - financial
  - analysis
  - investment
author: system
```

---

## 3. 工具定义模型

```python
# etf_common/agent_framework/definitions/tool_definition.py

from enum import Enum
from typing import Dict, Any, Optional, List, Callable
from pydantic import BaseModel, Field


class ToolCategory(str, Enum):
    """工具分类"""
    
    # 文件系统工具（核心）
    FILE_SYSTEM = "file_system"          # ls, read, write, edit
    BASH = "bash"                        # 执行 shell 命令
    CODE_EXECUTION = "code_execution"    # 执行代码
    
    # 搜索工具
    DOCUMENT_SEARCH = "document_search"
    NEWS_SEARCH = "news_search"
    ANNOUNCEMENT_SEARCH = "announcement_search"
    RESEARCH_REPORT_SEARCH = "research_report_search"
    
    # 数据工具
    STOCK_DATA = "stock_data"
    FINANCIAL_DATA = "financial_data"
    MARKET_DATA = "market_data"
    
    # 分析工具
    TECHNICAL_ANALYSIS = "technical_analysis"
    FUNDAMENTAL_ANALYSIS = "fundamental_analysis"
    
    # 生成工具
    REPORT_GENERATION = "report_generation"
    CHART_GENERATION = "chart_generation"
    
    # 外部服务
    MCP = "mcp"
    EXTERNAL_API = "external_api"


class ToolDefinition(BaseModel):
    """工具定义"""
    
    tool_id: str = Field(description="工具唯一 ID")
    name: str = Field(description="工具名称")
    alias: str = Field(description="工具别名，用于 @引用")
    description: str = Field(description="工具描述")
    category: ToolCategory = Field(description="工具分类")
    
    # 输入输出定义
    input_schema: Dict[str, Any] = Field(description="输入参数 JSON Schema")
    output_schema: Dict[str, Any] = Field(description="输出结果 JSON Schema")
    
    # 执行配置
    is_async: bool = Field(default=True, description="是否异步执行")
    timeout: int = Field(default=30, description="超时时间（秒）")
    retry_count: int = Field(default=3, description="重试次数")
    
    # 权限和限制
    requires_auth: bool = Field(default=False, description="是否需要认证")
    rate_limit: Optional[int] = Field(default=None, description="速率限制（次/分钟）")
    
    # 示例
    examples: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="使用示例"
    )
    
    def to_function_schema(self) -> Dict[str, Any]:
        """转换为 OpenAI Function Calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.tool_id,
                "description": self.description,
                "parameters": self.input_schema
            }
        }
    
    def to_prompt_description(self) -> str:
        """生成用于 Prompt 的工具描述"""
        params_desc = []
        if "properties" in self.input_schema:
            for name, prop in self.input_schema["properties"].items():
                required = name in self.input_schema.get("required", [])
                params_desc.append(
                    f"  - {name}: {prop.get('description', '')} "
                    f"{'(必需)' if required else '(可选)'}"
                )
        
        return f"""**@{self.alias}** - {self.name}
{self.description}
参数：
{chr(10).join(params_desc) if params_desc else '  无参数'}
"""
```

---

## 4. 工作流定义模型

```python
# etf_common/agent_framework/definitions/workflow_definition.py

from enum import Enum
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """节点类型"""
    
    START = "start"                    # 开始节点
    END = "end"                        # 结束节点
    AGENT = "agent"                    # Agent 执行节点
    CONDITION = "condition"            # 条件分支
    PARALLEL = "parallel"              # 并行执行
    LOOP = "loop"                      # 循环
    HUMAN_IN_LOOP = "human_in_loop"    # 人工介入
    SUB_WORKFLOW = "sub_workflow"      # 子工作流


class DataMapping(BaseModel):
    """数据映射配置 - 节点间数据传递"""
    
    source_node: str = Field(description="源节点 ID")
    source_field: str = Field(description="源字段路径，如 'output.stocks'")
    target_field: str = Field(description="目标字段路径，如 'input.stock_list'")
    transform: Optional[str] = Field(
        default=None,
        description="转换表达式，如 'json.loads' 或 'lambda x: x[:5]'"
    )
    required: bool = Field(default=True, description="是否必需")


class WorkflowNode(BaseModel):
    """工作流节点定义"""
    
    node_id: str = Field(description="节点 ID")
    name: str = Field(description="节点名称")
    node_type: NodeType = Field(description="节点类型")
    description: Optional[str] = Field(default=None, description="节点描述")
    
    # === Agent 配置（当 node_type == AGENT 时）===
    agent_id: Optional[str] = Field(
        default=None,
        description="关联的 Agent ID"
    )
    
    # === 指令覆盖（可覆盖 Agent 默认配置）===
    background_override: Optional[str] = Field(
        default=None,
        description="背景指令覆盖"
    )
    output_override: Optional[str] = Field(
        default=None,
        description="输出指令覆盖"
    )
    user_override: Optional[str] = Field(
        default=None,
        description="用户指令覆盖"
    )
    
    # === 模型覆盖 ===
    model_override: Optional[str] = Field(
        default=None,
        description="模型覆盖"
    )
    
    # === 工具配置 ===
    additional_tools: List[str] = Field(
        default_factory=list,
        description="额外的工具引用"
    )
    disabled_tools: List[str] = Field(
        default_factory=list,
        description="禁用的工具"
    )
    
    # === 输入映射 ===
    input_mappings: List[DataMapping] = Field(
        default_factory=list,
        description="输入数据映射"
    )
    
    # === 上下文引用 ===
    context_refs: List[str] = Field(
        default_factory=list,
        description="上下文引用，如 ['#定义突破标准']"
    )
    
    # === 条件配置（当 node_type == CONDITION 时）===
    condition_expression: Optional[str] = Field(
        default=None,
        description="条件表达式，如 'state.score >= 0.7'"
    )
    
    # === 并行配置（当 node_type == PARALLEL 时）===
    parallel_nodes: List[str] = Field(
        default_factory=list,
        description="并行执行的节点 ID 列表"
    )
    
    # === 执行配置 ===
    timeout: int = Field(default=300, description="超时时间（秒）")
    retry_count: int = Field(default=3, description="重试次数")
    continue_on_error: bool = Field(default=False, description="错误时是否继续")


class WorkflowEdge(BaseModel):
    """工作流边（连接）"""
    
    from_node: str = Field(description="源节点 ID")
    to_node: str = Field(description="目标节点 ID")
    condition: Optional[str] = Field(
        default=None,
        description="条件表达式"
    )
    priority: int = Field(default=0, description="优先级")


class WorkflowDefinition(BaseModel):
    """完整的工作流定义"""
    
    workflow_id: str = Field(description="工作流 ID")
    name: str = Field(description="工作流名称")
    description: str = Field(description="工作流描述")
    version: str = Field(default="1.0.0", description="版本号")
    
    # === 节点和边 ===
    nodes: List[WorkflowNode] = Field(description="节点列表")
    edges: List[WorkflowEdge] = Field(description="边列表")
    
    # === 入口和出口 ===
    entry_node: str = Field(description="入口节点 ID")
    exit_nodes: List[str] = Field(description="出口节点 ID 列表")
    
    # === 全局配置 ===
    global_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="全局上下文"
    )
    global_tools: List[str] = Field(
        default_factory=list,
        description="全局工具"
    )
    
    # === 工作空间配置 ===
    workspace_path: Optional[str] = Field(
        default=None,
        description="工作空间路径"
    )
    
    # === 元数据 ===
    tags: List[str] = Field(default_factory=list)
    author: str = Field(default="system")
    created_at: Optional[str] = Field(default=None)
    
    def get_node(self, node_id: str) -> Optional[WorkflowNode]:
        """获取节点"""
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None
    
    def get_next_nodes(self, node_id: str) -> List[str]:
        """获取后继节点"""
        next_nodes = []
        for edge in self.edges:
            if edge.from_node == node_id:
                next_nodes.append((edge.to_node, edge.condition, edge.priority))
        # 按优先级排序
        next_nodes.sort(key=lambda x: x[2], reverse=True)
        return [n[0] for n in next_nodes]
    
    def validate(self) -> List[str]:
        """验证工作流定义"""
        errors = []
        node_ids = {n.node_id for n in self.nodes}
        
        # 检查入口节点
        if self.entry_node not in node_ids:
            errors.append(f"入口节点 {self.entry_node} 不存在")
        
        # 检查出口节点
        for exit_node in self.exit_nodes:
            if exit_node not in node_ids:
                errors.append(f"出口节点 {exit_node} 不存在")
        
        # 检查边的有效性
        for edge in self.edges:
            if edge.from_node not in node_ids:
                errors.append(f"边的源节点 {edge.from_node} 不存在")
            if edge.to_node not in node_ids:
                errors.append(f"边的目标节点 {edge.to_node} 不存在")
        
        return errors
```

---

## 5. 引用解析器

```python
# etf_common/agent_framework/definitions/reference_resolver.py

import re
from typing import Dict, Any, List, Optional, Tuple
from .tool_definition import ToolDefinition


class ReferenceResolver:
    """
    引用解析器
    
    支持两种引用语法：
    - @工具名：解析为工具定义和调用
    - #上下文名：解析为上下文数据
    """
    
    def __init__(
        self,
        tool_registry: "ToolRegistry",
        context_store: Dict[str, str] = None
    ):
        self.tool_registry = tool_registry
        self.context_store = context_store or {}
    
    def resolve_tool_references(
        self,
        prompt: str,
        allowed_tools: List[str] = None
    ) -> Tuple[str, List[ToolDefinition]]:
        """
        解析 prompt 中的 @工具名 引用
        
        Args:
            prompt: 原始 prompt
            allowed_tools: 允许使用的工具别名列表
            
        Returns:
            (解析后的 prompt, 使用的工具定义列表)
        """
        used_tools = []
        
        # 查找所有 @xxx 引用
        pattern = r'@(\S+)'
        matches = re.findall(pattern, prompt)
        
        for alias in matches:
            tool_def = self.tool_registry.get_by_alias(alias)
            
            if tool_def is None:
                continue
            
            # 检查是否在允许列表中
            if allowed_tools and alias not in allowed_tools:
                continue
            
            if tool_def not in used_tools:
                used_tools.append(tool_def)
        
        return prompt, used_tools
    
    def resolve_context_references(
        self,
        prompt: str
    ) -> Tuple[str, Dict[str, str]]:
        """
        解析 prompt 中的 #上下文名 引用
        
        Args:
            prompt: 原始 prompt
            
        Returns:
            (解析后的 prompt, 解析的上下文字典)
        """
        resolved_context = {}
        
        # 查找所有 #xxx 引用
        pattern = r'#(\S+)'
        matches = re.findall(pattern, prompt)
        
        for ref_name in matches:
            if ref_name in self.context_store:
                resolved_context[f"#{ref_name}"] = self.context_store[ref_name]
        
        return prompt, resolved_context
    
    def inject_tool_descriptions(
        self,
        prompt: str,
        tools: List[ToolDefinition]
    ) -> str:
        """
        将工具描述注入到 prompt 中
        
        Args:
            prompt: 原始 prompt
            tools: 工具定义列表
            
        Returns:
            注入工具描述后的 prompt
        """
        if not tools:
            return prompt
        
        tool_descriptions = "\n\n".join([
            t.to_prompt_description() for t in tools
        ])
        
        # 在 prompt 末尾添加工具描述
        return f"""{prompt}

---

## 可用工具详细说明

{tool_descriptions}
"""
    
    def update_context(self, key: str, value: str):
        """更新上下文存储"""
        self.context_store[key] = value
    
    def get_context(self, key: str) -> Optional[str]:
        """获取上下文"""
        return self.context_store.get(key)
```


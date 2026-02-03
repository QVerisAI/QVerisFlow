"""
工具定义模型

提供工具的结构化定义，包括工具类别、输入输出 Schema、
执行配置等。
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class ToolCategory(str, Enum):
    """工具分类（来自设计文档 05_tools.md）"""

    # === 系统和执行工具 ===
    SYSTEM = "system"  # 系统/Shell 工具
    FILE_SYSTEM = "file_system"  # 文件系统操作
    BASH = "bash"  # Bash 命令执行
    CODE_EXECUTION = "code_execution"  # 代码执行

    # === 搜索类工具 ===
    AGENTIC_SEARCH = "agentic_search"  # Agent化搜索（如 Perplexity）
    SEMANTIC_SEARCH = "semantic_search"  # 语义搜索
    WEB_SEARCH = "web_search"  # 网页搜索

    # === 金融数据工具 ===
    STOCK_DATA = "stock_data"  # 股票数据
    FINANCIAL_DATA = "financial_data"  # 财务数据
    NEWS_DATA = "news_data"  # 新闻数据
    RESEARCH_DATA = "research_data"  # 研报数据
    ANNOUNCEMENT_DATA = "announcement_data"  # 公告数据

    # === 分析类工具 ===
    TECHNICAL_ANALYSIS = "technical_analysis"  # 技术分析
    FUNDAMENTAL_ANALYSIS = "fundamental_analysis"  # 基本面分析
    RISK_ANALYSIS = "risk_analysis"  # 风险分析

    # === 生成类工具 ===
    REPORT_GENERATION = "report_generation"  # 报告生成
    CHART_GENERATION = "chart_generation"  # 图表生成

    # === 特殊工具 ===
    MCP = "mcp"  # MCP 协议工具
    SUB_AGENT = "sub_agent"  # 子 Agent

    # === 远程工具 ===
    QVERIS = "qveris"  # QVeris 远程工具
    DYNAMIC = "dynamic"  # 动态发现的工具
    DEVELOPMENT = "development"  # 开发工具（Bash 等）


class ToolReferenceType(str, Enum):
    """工具引用类型"""

    BUILTIN = "builtin"  # 内置工具
    CUSTOM = "custom"  # 自定义工具
    MCP = "mcp"  # MCP 协议工具
    APP = "app"  # 应用工具
    EXTERNAL_API = "external_api"  # 外部 API
    QVERIS = "qveris"  # QVeris 远程工具


class ToolReference(BaseModel):
    """工具引用配置"""

    tool_id: str = Field(description="工具ID")
    alias: str = Field(description="工具别名，用于 @引用，如 '公告搜索'")
    tool_type: ToolReferenceType = Field(description="工具类型")
    parameters: Optional[Dict[str, Any]] = Field(
        default=None, description="工具参数覆盖"
    )
    enabled: bool = Field(default=True, description="是否启用")


class ToolDefinition(BaseModel):
    """
    工具定义

    完整的工具元数据定义，包括名称、描述、分类、
    输入输出 Schema、执行配置等。
    """

    tool_id: str = Field(description="工具唯一ID")
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
    cost_estimate: float = Field(default=0.0, description="估算成本")

    # 实现配置
    implementation_type: str = Field(
        default="custom", description="实现类型：builtin, custom, mcp, external_api"
    )
    implementation_config: Optional[Dict[str, Any]] = Field(
        default=None, description="实现配置（MCP server info, API endpoint 等）"
    )

    # 示例
    examples: List[Dict[str, Any]] = Field(default_factory=list, description="使用示例")

    # 元数据
    tags: List[str] = Field(default_factory=list, description="标签")
    is_active: bool = Field(default=True, description="是否激活")
    version: str = Field(default="1.0.0", description="版本号")

    # === QVeris 远程工具字段 ===
    qveris_tool_id: Optional[str] = Field(
        default=None, description="QVeris 工具 ID（仅 QVeris 远程工具）"
    )
    qveris_search_id: Optional[str] = Field(
        default=None, description="关联的 QVeris 搜索 ID"
    )
    weighted_success_rate: Optional[float] = Field(
        default=None, description="加权成功率（0-1），用于工具选择"
    )
    avg_execution_time: Optional[float] = Field(
        default=None, description="平均执行时间（秒），用于性能评估"
    )
    provider: Optional[str] = Field(default=None, description="工具提供者/来源")
    is_remote: bool = Field(default=False, description="是否为远程工具")

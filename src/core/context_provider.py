"""
统一的运行时上下文提供器

提供工作流和 Agent 执行所需的各类上下文信息：
- 时间上下文：当前时间、日期、季度等
- 领域知识：从配置文件读取的业务领域特定信息
- 模型能力：可用模型的能力矩阵
- 数据时效性：数据缓存和延迟信息
- 执行进度：工作流执行状态

设计原则：
- 领域知识等配置化内容从 config/app_config.yaml 读取，不硬编码
- 提供统一的 format_for_prompt() 方法生成可直接注入 prompt 的文本
- 支持按需组合不同类型的上下文
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from src.utils.logger import get_logger

logger = get_logger()

# 尝试导入 pytz，如果不可用则使用标准库
try:
    import pytz

    HAS_PYTZ = True
except ImportError:
    HAS_PYTZ = False
    logger.warning("pytz 未安装，将使用本地时区")


class RuntimeContextProvider:
    """
    统一的运行时上下文提供器

    领域知识从 config/app_config.yaml 的 domains 配置项读取，
    便于维护和扩展，无需修改代码。

    使用示例：
        provider = RuntimeContextProvider(
            timezone="Asia/Shanghai",
            domain="financial",
        )

        # 获取完整的 prompt 上下文
        context_prompt = provider.format_for_prompt()

        # 只获取时间上下文
        time_ctx = provider.get_time_context()
    """

    def __init__(
        self,
        timezone: str = "Asia/Shanghai",
        domain: str = "general",
        data_cache_ttl: int = 3600,
        execution_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ):
        """
        初始化上下文提供器

        Args:
            timezone: 时区，默认 Asia/Shanghai
            domain: 业务领域，如 financial, healthcare, scientific, legal, general
            data_cache_ttl: 数据缓存 TTL（秒），用于时效性提示
            execution_id: 执行 ID
            workflow_id: 工作流 ID
        """
        self.timezone = timezone
        self.domain = domain
        self.data_cache_ttl = data_cache_ttl
        self.execution_id = execution_id
        self.workflow_id = workflow_id
        self._config = None
        self._models_config = None

    @property
    def config(self) -> Dict[str, Any]:
        """延迟加载配置"""
        if self._config is None:
            try:
                from src.config import get_app_config_loader

                loader = get_app_config_loader()
                self._config = loader.load()
            except Exception as e:
                logger.warning(f"加载配置失败: {e}，使用空配置")
                self._config = {}
        return self._config

    @property
    def models_config(self) -> Dict[str, Any]:
        """获取模型配置"""
        if self._models_config is None:
            self._models_config = self.config.get("models", {})
        return self._models_config

    def get_time_context(self) -> Dict[str, str]:
        """
        获取时间上下文

        Returns:
            包含当前时间各种格式的字典
        """
        if HAS_PYTZ:
            try:
                tz = pytz.timezone(self.timezone)
                now = datetime.now(tz)
            except Exception:
                now = datetime.now()
        else:
            now = datetime.now()

        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        return {
            "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "current_date": now.strftime("%Y年%m月%d日"),
            "current_date_iso": now.strftime("%Y-%m-%d"),
            "current_weekday": weekdays[now.weekday()],
            "current_quarter": f"{now.year}年Q{(now.month - 1) // 3 + 1}",
            "current_year": str(now.year),
            "current_month": str(now.month),
            "current_month_name": f"{now.month}月",
            "timezone": self.timezone,
        }

    def get_domain_context(self, domain: str = None) -> Dict[str, Any]:
        """
        从配置文件获取领域知识上下文

        Args:
            domain: 领域名称，默认使用初始化时的 domain

        Returns:
            领域配置字典
        """
        domain = domain or self.domain
        domains_config = self.config.get("domains", {})

        # 优先返回指定领域，否则返回 general
        domain_info = domains_config.get(domain)
        if domain_info:
            return domain_info

        # 返回 general 或空字典
        return domains_config.get("general", {})

    def get_data_freshness_context(self) -> Dict[str, Any]:
        """
        获取数据时效性上下文

        Returns:
            数据时效性信息字典
        """
        minutes = self.data_cache_ttl // 60
        hours = self.data_cache_ttl // 3600

        if hours >= 1:
            delay_desc = f"{hours} 小时"
        else:
            delay_desc = f"{minutes} 分钟"

        return {
            "cache_ttl_seconds": self.data_cache_ttl,
            "cache_ttl_minutes": minutes,
            "cache_ttl_hours": hours,
            "freshness_warning": f"数据可能有 {delay_desc} 延迟",
        }

    def get_model_capabilities_context(self) -> Dict[str, Any]:
        """
        获取模型能力矩阵

        Returns:
            模型能力信息字典
        """
        capabilities_matrix = {}

        for model_name, model_config in self.models_config.items():
            if isinstance(model_config, dict):
                capabilities_matrix[model_name] = {
                    "type": model_config.get("type", "language"),
                    "capabilities": model_config.get("capabilities", []),
                    "cost_tier": model_config.get("cost_tier", "medium"),
                    "max_tokens": model_config.get("max_tokens", 4096),
                }

        return capabilities_matrix

    def format_time_prompt(self) -> str:
        """
        格式化时间上下文为 prompt 文本

        Returns:
            可直接注入 prompt 的时间上下文文本
        """
        ctx = self.get_time_context()
        freshness = self.get_data_freshness_context()

        return f"""## 当前执行环境
- 当前时间: {ctx['current_datetime']} ({ctx['timezone']})
- 当前日期: {ctx['current_date']}，{ctx['current_weekday']}
- 当前季度: {ctx['current_quarter']}
- 数据时效性: {freshness['freshness_warning']}
- **重要**: 在查询数据、搜索信息时，请基于上述当前时间确定查询的时间范围。例如，如果需要查询"最近一个季度"的数据，应该明确指定为 {ctx['current_quarter']}。"""

    def format_domain_prompt(self, domain: str = None) -> str:
        """
        格式化领域知识为 prompt 文本（从配置文件读取）

        Args:
            domain: 领域名称

        Returns:
            可直接注入 prompt 的领域知识文本
        """
        domain_info = self.get_domain_context(domain)
        if not domain_info:
            return ""

        parts = [f"## 业务领域: {domain_info.get('name', self.domain)}"]

        if domain_info.get("description"):
            parts.append(f"- 描述: {domain_info['description']}")

        if domain_info.get("data_sources"):
            sources = domain_info["data_sources"]
            if isinstance(sources, list) and sources:
                parts.append(f"- 数据来源: {', '.join(sources)}")
            elif sources:
                parts.append(f"- 数据来源: {sources}")

        if domain_info.get("timeliness"):
            timeliness = domain_info["timeliness"]
            if isinstance(timeliness, dict):
                parts.append("- 数据时效性:")
                for k, v in timeliness.items():
                    parts.append(f"  - {k}: {v}")
            else:
                parts.append(f"- 数据时效性: {timeliness}")

        if domain_info.get("terminology"):
            terms = domain_info["terminology"]
            if isinstance(terms, list) and terms:
                parts.append(f"- 术语规范: {', '.join(terms)}")
            elif terms:
                parts.append(f"- 术语规范: {terms}")

        if domain_info.get("compliance"):
            compliance = domain_info["compliance"]
            if isinstance(compliance, list) and compliance:
                parts.append("- 合规要求:")
                for item in compliance:
                    parts.append(f"  - {item}")

        if domain_info.get("data_format"):
            data_format = domain_info["data_format"]
            if isinstance(data_format, dict):
                parts.append("- 数据格式规范:")
                for k, v in data_format.items():
                    parts.append(f"  - {k}: {v}")

        return "\n".join(parts)

    def format_model_capabilities_prompt(self) -> str:
        """
        格式化模型能力矩阵为 prompt 文本

        Returns:
            可直接注入 prompt 的模型能力矩阵文本
        """
        capabilities = self.get_model_capabilities_context()
        if not capabilities:
            return ""

        # 构建表格
        lines = [
            "## 可用模型能力矩阵",
            "",
            "| 模型 | 类型 | 推理 | 编程 | 视觉 | 长文本 | 深度思考 | 成本 |",
            "|------|------|------|------|------|--------|----------|------|",
        ]

        capability_names = [
            "reasoning",
            "coding",
            "vision",
            "long_context",
            "deep_thinking",
        ]

        for model_name, info in capabilities.items():
            caps = info.get("capabilities", [])
            row = [
                model_name,
                info.get("type", "-"),
            ]
            for cap in capability_names:
                row.append("✓" if cap in caps else "✗")
            row.append(info.get("cost_tier", "-"))
            lines.append("| " + " | ".join(row) + " |")

        # 添加选择建议
        lines.extend(
            [
                "",
                "**模型选择建议:**",
                "- 需要图像理解: 选择 type=multimodal 且有 vision 能力的模型",
                "- 需要深度推理: 选择有 deep_thinking 能力的模型",
                "- 简单数据收集: 选择 cost_tier=low 的模型以降低成本",
                "- 长文档处理: 选择有 long_context 能力的模型",
            ]
        )

        return "\n".join(lines)

    def format_execution_context(
        self,
        node_index: int = None,
        total_nodes: int = None,
        completed_nodes: int = None,
    ) -> str:
        """
        格式化执行进度上下文

        Args:
            node_index: 当前节点索引
            total_nodes: 总节点数
            completed_nodes: 已完成节点数

        Returns:
            执行进度上下文文本
        """
        parts = ["## 执行进度"]

        if self.workflow_id:
            parts.append(f"- 工作流 ID: {self.workflow_id}")

        if self.execution_id:
            parts.append(f"- 执行 ID: {self.execution_id}")

        if total_nodes is not None:
            if node_index is not None:
                parts.append(f"- 当前节点: {node_index + 1} / {total_nodes}")
            if completed_nodes is not None:
                progress = (
                    (completed_nodes / total_nodes * 100) if total_nodes > 0 else 0
                )
                parts.append(
                    f"- 完成进度: {progress:.0f}% ({completed_nodes}/{total_nodes})"
                )

        return "\n".join(parts) if len(parts) > 1 else ""

    def format_for_prompt(
        self,
        include_time: bool = True,
        include_domain: bool = True,
        include_model_capabilities: bool = False,
        include_execution_context: bool = False,
        node_index: int = None,
        total_nodes: int = None,
        completed_nodes: int = None,
    ) -> str:
        """
        格式化完整的上下文 prompt

        Args:
            include_time: 是否包含时间上下文
            include_domain: 是否包含领域知识
            include_model_capabilities: 是否包含模型能力矩阵
            include_execution_context: 是否包含执行进度
            node_index: 当前节点索引（用于执行进度）
            total_nodes: 总节点数
            completed_nodes: 已完成节点数

        Returns:
            完整的上下文 prompt 文本
        """
        parts = []

        if include_time:
            parts.append(self.format_time_prompt())

        if include_domain:
            domain_prompt = self.format_domain_prompt()
            if domain_prompt:
                parts.append(domain_prompt)

        if include_model_capabilities:
            model_prompt = self.format_model_capabilities_prompt()
            if model_prompt:
                parts.append(model_prompt)

        if include_execution_context:
            exec_prompt = self.format_execution_context(
                node_index=node_index,
                total_nodes=total_nodes,
                completed_nodes=completed_nodes,
            )
            if exec_prompt:
                parts.append(exec_prompt)

        return "\n\n".join(parts)

    def get_runtime_context_dict(self) -> Dict[str, Any]:
        """
        获取运行时上下文字典（用于注入到 workflow context）

        Returns:
            可注入到执行上下文的字典
        """
        time_ctx = self.get_time_context()

        return {
            "_runtime": {
                "current_time": time_ctx["current_datetime"],
                "current_date": time_ctx["current_date_iso"],
                "current_quarter": time_ctx["current_quarter"],
                "timezone": self.timezone,
                "domain": self.domain,
                "data_cache_ttl": self.data_cache_ttl,
                "execution_id": self.execution_id,
                "workflow_id": self.workflow_id,
            }
        }


def extract_schema_constraints(schema: Dict[str, Any]) -> str:
    """
    从 JSON Schema 提取人类可读的约束描述

    Args:
        schema: JSON Schema 字典

    Returns:
        人类可读的约束描述文本
    """
    if not schema or not isinstance(schema, dict):
        return "无特殊约束"

    constraints = []
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])

    for prop, spec in properties.items():
        if not isinstance(spec, dict):
            continue

        prop_constraints = []

        # 必填字段标记
        is_required = prop in required_fields

        # 类型约束
        prop_type = spec.get("type", "")

        # 枚举约束
        if "enum" in spec:
            enum_values = spec["enum"]
            if len(enum_values) <= 5:
                prop_constraints.append(f"只能是 {enum_values} 之一")
            else:
                prop_constraints.append(
                    f"只能是 {enum_values[:3]}... 等 {len(enum_values)} 个值之一"
                )

        # 数值范围约束
        if "minimum" in spec:
            prop_constraints.append(f"最小值 {spec['minimum']}")
        if "maximum" in spec:
            prop_constraints.append(f"最大值 {spec['maximum']}")
        if "exclusiveMinimum" in spec:
            prop_constraints.append(f"大于 {spec['exclusiveMinimum']}")
        if "exclusiveMaximum" in spec:
            prop_constraints.append(f"小于 {spec['exclusiveMaximum']}")

        # 字符串长度约束
        if "minLength" in spec:
            prop_constraints.append(f"最小长度 {spec['minLength']}")
        if "maxLength" in spec:
            prop_constraints.append(f"最大长度 {spec['maxLength']}")

        # 格式约束
        if "pattern" in spec:
            prop_constraints.append(f"格式正则: {spec['pattern']}")
        if "format" in spec:
            format_desc = {
                "date": "日期格式 (YYYY-MM-DD)",
                "date-time": "日期时间格式 (ISO 8601)",
                "email": "邮箱格式",
                "uri": "URL 格式",
                "uuid": "UUID 格式",
            }.get(spec["format"], spec["format"])
            prop_constraints.append(f"格式: {format_desc}")

        # 数组约束
        if "minItems" in spec:
            prop_constraints.append(f"最少 {spec['minItems']} 项")
        if "maxItems" in spec:
            prop_constraints.append(f"最多 {spec['maxItems']} 项")

        # 默认值
        if "default" in spec:
            prop_constraints.append(f"默认值: {spec['default']}")

        if prop_constraints:
            required_mark = " (必填)" if is_required else ""
            constraints.append(
                f"- {prop}{required_mark}: {'; '.join(prop_constraints)}"
            )
        elif is_required:
            constraints.append(f"- {prop} (必填)")

    return "\n".join(constraints) if constraints else "无特殊约束"


def format_tool_with_quality_metrics(
    tool_name: str,
    tool_id: str,
    description: str,
    success_rate: float = None,
    avg_execution_time: float = None,
    input_schema: Dict[str, Any] = None,
    cache_ttl: int = 3600,
) -> str:
    """
    格式化工具信息，包含质量指标帮助 Agent 做选择

    Args:
        tool_name: 工具名称
        tool_id: 工具 ID
        description: 工具描述
        success_rate: 历史成功率 (0-1)
        avg_execution_time: 平均执行时间（秒）
        input_schema: 输入 JSON Schema
        cache_ttl: 数据缓存 TTL（秒）

    Returns:
        格式化的工具信息文本
    """
    parts = [
        f"**工具**: {tool_name} (`{tool_id}`)",
        f"**描述**: {description}",
    ]

    # 质量指标
    quality_parts = []
    if success_rate is not None:
        quality_parts.append(f"历史成功率: {success_rate:.1%}")
    if avg_execution_time is not None:
        quality_parts.append(f"平均响应时间: {avg_execution_time:.1f}秒")

    if quality_parts:
        parts.append(f"**质量指标**: {', '.join(quality_parts)}")

    # 数据时效性
    if cache_ttl:
        minutes = cache_ttl // 60
        parts.append(f"**数据时效性**: 数据可能有 {minutes} 分钟延迟")

    # 参数约束
    if input_schema:
        constraints = extract_schema_constraints(input_schema)
        if constraints != "无特殊约束":
            parts.append(f"**参数约束**:\n{constraints}")

    return "\n".join(parts)


# 便捷函数
def get_runtime_context_provider(
    timezone: str = "Asia/Shanghai",
    domain: str = "general",
    **kwargs,
) -> RuntimeContextProvider:
    """
    获取上下文提供器实例

    Args:
        timezone: 时区
        domain: 业务领域
        **kwargs: 其他参数

    Returns:
        RuntimeContextProvider 实例
    """
    return RuntimeContextProvider(
        timezone=timezone,
        domain=domain,
        **kwargs,
    )


def get_current_time_context() -> str:
    """
    快捷方法：获取当前时间上下文 prompt

    Returns:
        时间上下文 prompt 文本
    """
    return RuntimeContextProvider().format_time_prompt()

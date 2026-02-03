"""
Meta Agent

能够创建和优化其他 Agent 的元智能体。
支持：
- 根据任务描述生成新的 Agent 定义
- 基于执行反馈优化 Agent 提示
- 少样本学习和参考 Agent 模式提取
- 自动生成多 Agent 工作流

增强特性：
- 工作流自动生成
- 多 Agent 协作编排
- Agent 性能监控集成
"""

from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime, timedelta
import json

from ..definitions import (
    AgentDefinition,
    ModelConfig,
    BackgroundInstruction,
    OutputInstruction,
    UserInstruction,
    PromptStructure,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    DataMapping,
)
from ..registry import AgentRegistry
from ..config import get_model_registry
from ..tools import ToolRegistry
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from .performance_monitor import AgentPerformanceMonitor

logger = get_logger()


class MetaAgent:
    """
    元智能体

    能够创建和优化其他 Agent 的特殊智能体。
    通过 LLM 生成和改进 Agent 定义。

    核心能力：
    1. 从任务描述创建新 Agent
    2. 从执行反馈优化现有 Agent
    3. 从成功案例学习和提取模式
    4. 自动生成多 Agent 工作流

    用法:
        meta = MetaAgent(llm_client, agent_registry)

        # 创建新 Agent
        new_agent = await meta.create_agent(
            task_description="创建一个能够分析股票数据的 Agent",
            reference_agents=["data_analyst", "financial_expert"],
        )

        # 优化现有 Agent
        optimized_agent = await meta.optimize_prompt(
            agent_id="stock_analyzer",
            feedback_history=[
                {"task": "分析苹果股票", "success": False, "feedback": "缺少财务指标分析"},
                {"task": "分析微软股票", "success": True},
            ]
        )

        # 生成工作流
        workflow = await meta.generate_workflow(
            task_description="端到端的股票分析报告生成",
            available_agents=["data_collector", "analyzer", "report_writer"],
        )
    """

    def __init__(
        self,
        llm_client: Any,
        agent_registry: Optional[AgentRegistry] = None,
        tool_registry: Optional[ToolRegistry] = None,
        performance_monitor: Optional["AgentPerformanceMonitor"] = None,
        model: str = None,
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ):
        """
        初始化 Meta Agent

        Args:
            llm_client: LLM 客户端
            agent_registry: Agent 注册表（用于查找参考 Agent）
            tool_registry: 工具注册表（用于获取可用工具列表）
            performance_monitor: Agent 性能监控器（可选）
            model: 使用的模型名称
            temperature: 生成温度
            max_tokens: 最大生成 token 数
        """
        self.llm_client = llm_client
        self.agent_registry = agent_registry or AgentRegistry.get_default()
        self.tool_registry = tool_registry
        self.performance_monitor = performance_monitor
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def create_agent(
        self,
        task_description: str,
        reference_agents: List[str] = None,
        tools: List[str] = None,
        constraints: Dict[str, Any] = None,
    ) -> AgentDefinition:
        """
        根据任务描述创建新的 Agent 定义

        Args:
            task_description: 任务描述
            reference_agents: 参考 Agent ID 列表（用于少样本学习）
            tools: 可用的工具 ID 列表
            constraints: 约束条件（如最大迭代次数、模型限制等）

        Returns:
            新创建的 AgentDefinition
        """
        # 收集参考 Agent 信息
        reference_examples = []
        if reference_agents:
            for ref_id in reference_agents:
                ref_agent = self.agent_registry.get_definition(ref_id)
                if ref_agent:
                    reference_examples.append(self._format_agent_example(ref_agent))

        # 构建生成提示
        prompt = self._build_creation_prompt(
            task_description=task_description,
            reference_examples=reference_examples,
            tools=tools,
            constraints=constraints,
        )

        # 调用 LLM 生成（启用 JSON 优化和重试机制）
        response = await self._call_llm(prompt, expect_json=True)

        # 解析响应为 AgentDefinition
        agent_def = self._parse_agent_definition(response)

        logger.info(f"Meta Agent 创建了新 Agent: {agent_def.agent_id}")

        return agent_def

    async def optimize_prompt(
        self,
        agent_id: str,
        feedback_history: List[Dict[str, Any]],
        optimization_focus: str = "overall",
    ) -> AgentDefinition:
        """
        基于执行反馈优化 Agent 提示

        Args:
            agent_id: 待优化的 Agent ID
            feedback_history: 执行反馈历史，每条包含：
                - task: 任务描述
                - success: 是否成功
                - feedback: 具体反馈（可选）
                - result: 执行结果（可选）
            optimization_focus: 优化重点（overall、precision、speed、robustness）

        Returns:
            优化后的 AgentDefinition
        """
        # 获取原始 Agent 定义
        original_agent = self.agent_registry.get_definition(agent_id)
        if not original_agent:
            raise ValueError(f"Agent {agent_id} 不存在")

        # 分析反馈模式
        analysis = self._analyze_feedback(feedback_history)

        # 构建优化提示
        prompt = self._build_optimization_prompt(
            original_agent=original_agent,
            feedback_history=feedback_history,
            analysis=analysis,
            optimization_focus=optimization_focus,
        )

        # 调用 LLM 生成优化建议（启用 JSON 优化和重试机制）
        response = await self._call_llm(prompt, expect_json=True)

        # 应用优化
        optimized_agent = self._apply_optimization(original_agent, response)

        # 更新版本
        optimized_agent.version = self._increment_version(original_agent.version)

        logger.info(
            f"Meta Agent 优化了 Agent {agent_id}: "
            f"v{original_agent.version} -> v{optimized_agent.version}"
        )

        return optimized_agent

    async def suggest_improvements(
        self,
        agent_id: str,
        execution_logs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        分析执行日志并提出改进建议

        Args:
            agent_id: Agent ID
            execution_logs: 执行日志列表

        Returns:
            改进建议，包含：
            - summary: 总结
            - issues: 发现的问题
            - suggestions: 改进建议
            - priority: 优先级排序
        """
        agent = self.agent_registry.get_definition(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} 不存在")

        # 构建提示配置摘要
        prompt_config = {
            "background": {
                "role": agent.background_instruction.role_description,
                "capability": agent.background_instruction.core_capability,
                "context": agent.background_instruction.task_context,
            },
            "output": {
                "format": agent.output_instruction.format_type,
                "requirements": (
                    agent.output_instruction.format_requirements[:3]
                    if agent.output_instruction.format_requirements
                    else []
                ),
            },
            "user_instruction": {
                "template": (
                    agent.user_instruction.template[:200]
                    if agent.user_instruction.template
                    else "无"
                ),
            },
        }

        prompt = f"""分析以下 Agent 的执行日志，并提供改进建议。

## Agent 信息
- ID: {agent.agent_id}
- 名称: {agent.name}
- 描述: {agent.description}

## 当前提示配置
{json.dumps(prompt_config, ensure_ascii=False, indent=2)}

## 执行日志（最近 10 条）
{json.dumps(execution_logs[-10:], ensure_ascii=False, indent=2)}

## 请提供
1. 执行模式分析
2. 发现的问题和风险
3. 具体改进建议（按优先级排序）

请使用以下 JSON 格式输出：
```json
{{
    "summary": "执行分析总结...",
    "issues": [
        {{"severity": "high|medium|low", "description": "问题描述", "impact": "影响说明"}}
    ],
    "suggestions": [
        {{"priority": 1, "category": "prompt|tool|config", "description": "建议内容", "expected_improvement": "预期改善"}}
    ],
    "metrics": {{
        "success_rate": 0.8,
        "avg_iterations": 3.5,
        "common_failures": ["原因1", "原因2"]
    }}
}}
```"""

        response = await self._call_llm(prompt, expect_json=True)
        return self._parse_suggestions(response)

    def _build_creation_prompt(
        self,
        task_description: str,
        reference_examples: List[str],
        tools: List[str] = None,
        constraints: Dict[str, Any] = None,
    ) -> str:
        """构建 Agent 创建提示"""
        examples_text = (
            "\n\n".join(reference_examples) if reference_examples else "无参考示例"
        )
        
        # 获取真实可用的工具列表
        available_tools_info = self._get_available_tools_info()
        
        # 用户指定的工具偏好（如果有）
        if tools:
            tools_preference = f"用户建议的工具: {', '.join(tools)}\n（请从下方实际可用工具中选择匹配的工具，如果建议的工具不存在，请使用 QVeris 工具动态发现）"
        else:
            tools_preference = "无特定工具偏好，请根据任务需求从可用工具中选择"
        
        constraints_text = (
            json.dumps(constraints, ensure_ascii=False, indent=2)
            if constraints
            else "无特殊约束"
        )
        
        # 获取可用模型信息
        available_models_info = self._get_available_models_info()
        
        # 分析任务复杂度并推荐模型
        suggested_model = self._suggest_model_for_task(task_description, tools)

        return f"""你是一个专业的 Agent 设计专家。请根据以下任务描述，设计一个高效的 Agent。

## 任务描述
{task_description}

## 参考示例
{examples_text}

## Framework 可用工具列表
{available_tools_info}

## 工具选择偏好
{tools_preference}

## 工具选择指南
1. **只能使用上述列出的工具**，不要虚构不存在的工具（如 "Web Scraper"、"Financial API" 等）
2. **外部数据获取**：如果任务需要获取外部数据（金融数据、新闻、网页内容等），必须使用：
   - `qveris_search_tools`: 搜索可用的远程工具
   - `qveris_execute_tool`: 执行找到的工具
3. **文件操作**：使用 file_* 系列工具
4. **命令执行**：使用 bash_execute_safe
5. **无需外部数据**：如果任务只需要 LLM 分析/生成，tool_references 可以为空数组

## 约束条件
{constraints_text}

## 可用模型列表
{available_models_info}

## 模型选择建议
推荐模型: **{suggested_model}**

模型选择指南：
- **简单任务**（数据收集、格式化、简单查询）: 使用 `qwen-plus` 或 `glm-4-air`（低成本）
- **中等任务**（分析、总结、多步骤处理）: 使用 `deepseek-v3` 或 `qwen-max`
- **复杂任务**（深度推理、规划、复杂决策）: 使用 `deepseek-r1`
- **多模态任务**（涉及图像理解）: 使用 `gpt-4o` 或 `qwen-vl-max-latest`

请根据任务需求在 llm_config.model_name 中选择最合适的模型。

## 输出要求
请生成完整的 Agent 定义，严格使用以下 JSON 格式：

```json
{{
    "agent_id": "唯一标识符_使用下划线命名",
    "name": "Agent 技术名称（英文 CamelCase，如 DataCollectorAgent）",
    "display_name": "用户友好的中文显示名称（如：数据收集器、趋势分析师、报告生成器）",
    "description": "Agent 描述",
    "version": "1.0.0",
    "execution_type": "executor",
    "domain_type": "data_integration",
    "background_instruction": {{
        "role_description": "角色描述，如：你是一位资深分析师...",
        "core_capability": "核心能力描述，如：你的核心能力是...",
        "task_context": "任务上下文，如：在本任务中，你需要..."
    }},
    "output_instruction": {{
        "format_type": "json",
        "format_requirements": ["输出格式要求1", "输出格式要求2"],
        "quality_standards": ["质量标准1", "质量标准2"],
        "example_output": "可选的示例输出"
    }},
    "user_instruction": {{
        "task_description": "用户任务描述模板，可包含 {{task}} 等占位符",
        "tool_references": [],
        "context_references": []
    }},
    "llm_config": {{
        "model_name": "{suggested_model}",
        "temperature": 0.3,
        "max_tokens": 8000,
        "max_iterations": 10
    }},
    "tool_references": [
        {{"tool_id": "qveris_search_tools", "alias": "搜索工具", "tool_type": "qveris", "enabled": true}},
        {{"tool_id": "qveris_execute_tool", "alias": "执行工具", "tool_type": "qveris", "enabled": true}}
    ],
    "output_schema": {{
        "type": "object",
        "properties": {{
            "result": {{"type": "string"}}
        }}
    }}
}}
```

注意事项：
1. agent_id 应该简洁、有意义，使用下划线命名
2. **重要**: display_name 必须是简洁、易懂的中文名称（如"数据收集器"、"趋势分析师"），让普通用户能理解这个 Agent 的作用
3. background_instruction 必须包含 role_description、core_capability、task_context 三个字段
3. output_instruction 必须包含 format_type、format_requirements 字段
4. user_instruction 必须包含 task_description 字段
5. **重要**: tool_references 中的 tool_id 必须是上方「Framework 可用工具列表」中列出的工具
6. **重要**: tool_type 只能是以下值之一: "builtin", "qveris", "custom", "mcp", "app", "external_api"
   - 文件操作工具(file_*)和命令执行工具(bash_*)使用 "builtin"
   - QVeris 远程工具使用 "qveris"
7. 对于需要外部数据的任务，必须包含 qveris_search_tools 和 qveris_execute_tool
8. 如果任务不需要任何工具（纯 LLM 分析），tool_references 应为空数组 []
9. **重要**: llm_config.model_name 必须从可用模型列表中选择
10. **重要**: execution_type 只能是以下值之一:
    - "executor": 执行智能体，快速执行直接输出（推荐用于数据收集、报告生成等）
    - "reasoning_executor": 推理执行智能体，需要深度思考（推荐用于复杂分析）
    - "deep_search": 深度搜索，多轮搜索信息聚合
    - "flow_agent": 流程智能体，工作流编排
11. **重要**: domain_type 只能是以下值之一:
    - "data_integration": 数据集成/收集（推荐用于数据采集任务）
    - "financial_analysis": 金融分析
    - "data_verification": 数据验证
    - "risk_assessment": 风险评估
    - "signal_detection": 信号检测
    - "report_generation": 报告生成
    - "general": 通用（其他任务）"""

    def _build_optimization_prompt(
        self,
        original_agent: AgentDefinition,
        feedback_history: List[Dict[str, Any]],
        analysis: Dict[str, Any],
        optimization_focus: str,
    ) -> str:
        """构建 Agent 优化提示"""
        original_def = (
            original_agent.model_dump()
            if hasattr(original_agent, "model_dump")
            else vars(original_agent)
        )

        return f"""你是一个专业的 Agent 优化专家。请根据执行反馈，优化以下 Agent 的提示配置。

## 当前 Agent 定义
```json
{json.dumps(original_def, ensure_ascii=False, indent=2, default=str)}
```

## 执行反馈历史
{json.dumps(feedback_history, ensure_ascii=False, indent=2)}

## 反馈分析
- 成功率: {analysis.get('success_rate', 0):.1%}
- 常见失败原因: {analysis.get('common_failures', [])}
- 需要改进的领域: {analysis.get('improvement_areas', [])}

## 优化重点
{optimization_focus}

## 输出要求
请输出优化后的 prompt 配置，使用以下 JSON 格式：

```json
{{
    "prompt": {{
        "background_instruction": "优化后的背景指令...",
        "output_instruction": "优化后的输出指令...",
        "user_instruction_template": "优化后的用户指令模板..."
    }},
    "optimization_notes": "优化说明，解释做了哪些改进及原因",
    "expected_improvements": ["预期改善1", "预期改善2"]
}}
```

优化建议：
1. 针对失败案例加强相关指令
2. 使提示更清晰、更具体
3. 添加必要的约束和检查点
4. 优化输出格式规范"""

    def _get_available_tools_info(self) -> str:
        """
        获取可用工具信息的格式化文本
        
        Returns:
            工具信息的格式化字符串，包含工具 ID、名称和描述
        """
        if not self.tool_registry:
            return self._get_default_tools_info()
        
        try:
            tools_list = self.tool_registry.list_all()
            
            if not tools_list:
                return self._get_default_tools_info()
            
            lines = ["以下是 Framework 中实际可用的工具：\n"]
            
            # 按类别分组显示工具
            builtin_tools = []
            qveris_tools = []
            other_tools = []
            
            for tool in tools_list:
                if not tool.get("is_active", True):
                    continue
                    
                tool_id = tool.get("tool_id", "")
                name = tool.get("name", tool_id)
                category = tool.get("category", "general")
                
                # 获取工具定义以获取描述
                tool_def = self.tool_registry.get(tool_id)
                description = tool_def.description if tool_def else ""
                
                tool_info = f"  - **{tool_id}** ({name}): {description}"
                
                if "qveris" in tool_id.lower() or category == "qveris":
                    qveris_tools.append(tool_info)
                elif category in ["file", "shell", "builtin"]:
                    builtin_tools.append(tool_info)
                else:
                    other_tools.append(tool_info)
            
            if builtin_tools:
                lines.append("### 内置工具 (builtin)")
                lines.extend(builtin_tools)
                lines.append("")
            
            if qveris_tools:
                lines.append("### QVeris 远程工具接口 (qveris)")
                lines.extend(qveris_tools)
                lines.append("\n**重要**: 对于需要外部数据（金融数据、新闻、API 调用等）的任务，")
                lines.append("应使用 `qveris_search_tools` 搜索可用工具，然后用 `qveris_execute_tool` 执行。")
                lines.append("不要虚构工具名称，而是通过 QVeris 动态发现和使用远程工具。")
                lines.append("")
            
            if other_tools:
                lines.append("### 其他工具")
                lines.extend(other_tools)
                lines.append("")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.warning(f"获取工具信息失败: {e}")
            return self._get_default_tools_info()
    
    def _get_default_tools_info(self) -> str:
        """返回默认的工具信息（当 tool_registry 不可用时）"""
        return """以下是 Framework 中常用的工具：

### 内置工具 (builtin)
  - **file_ls**: 列出目录内容
  - **file_read**: 读取文件内容
  - **file_write**: 写入文件
  - **file_edit**: 编辑文件（查找替换）
  - **file_append**: 追加内容到文件
  - **bash_execute**: 执行 Bash 命令
  - **bash_execute_safe**: 安全执行 Bash 命令

### QVeris 远程工具接口 (qveris)
  - **qveris_search_tools**: 搜索 QVeris 平台上的远程工具
  - **qveris_execute_tool**: 执行通过搜索找到的远程工具
  - **qveris_get_tool_info**: 获取工具的详细信息

**重要**: 对于需要外部数据（金融数据、新闻、API 调用等）的任务，
应使用 `qveris_search_tools` 搜索可用工具，然后用 `qveris_execute_tool` 执行。
不要虚构工具名称（如 "Web Scraper"、"Financial API"），而是通过 QVeris 动态发现和使用远程工具。
"""
    
    def _validate_tool_references(
        self, 
        tool_references: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        验证并修正工具引用
        
        检查 tool_references 中的工具是否真实存在于 ToolRegistry 中，
        对于不存在的工具给出警告并尝试修正。
        同时修正无效的 tool_type 值。
        
        Args:
            tool_references: 原始的工具引用列表
            
        Returns:
            验证/修正后的工具引用列表
        """
        if not tool_references:
            return []
        
        validated_refs = []
        known_tool_ids = set()
        
        # 有效的 tool_type 枚举值
        valid_tool_types = {"builtin", "custom", "mcp", "app", "external_api", "qveris"}
        
        # tool_type 映射表，将常见的无效值映射为有效值
        tool_type_mapping = {
            "filesystem": "builtin",
            "system": "builtin",
            "file": "builtin",
            "bash": "builtin",
            "shell": "builtin",
            "command": "builtin",
            "api": "external_api",
            "external": "external_api",
            "remote": "qveris",
        }
        
        # 获取已知工具 ID
        if self.tool_registry:
            try:
                tools_list = self.tool_registry.list_all()
                known_tool_ids = {t.get("tool_id") for t in tools_list}
            except Exception as e:
                logger.warning(f"获取工具列表失败: {e}")
        
        # 如果没有 tool_registry，使用默认工具列表
        if not known_tool_ids:
            known_tool_ids = {
                "file_ls", "file_read", "file_write", "file_edit", "file_append",
                "bash_execute", "bash_execute_safe",
                "qveris_search_tools", "qveris_execute_tool", "qveris_get_tool_info"
            }
        
        for ref in tool_references:
            tool_id = ref.get("tool_id", "")
            
            # 修正 tool_type
            tool_type = ref.get("tool_type", "builtin")
            if tool_type not in valid_tool_types:
                # 尝试从映射表中获取正确的 tool_type
                mapped_type = tool_type_mapping.get(tool_type.lower(), "builtin")
                logger.info(f"修正工具 '{tool_id}' 的 tool_type: '{tool_type}' -> '{mapped_type}'")
                ref["tool_type"] = mapped_type
            
            if tool_id in known_tool_ids:
                # 工具存在，保留
                validated_refs.append(ref)
            else:
                # 工具不存在，尝试映射或给出警告
                mapped_tool = self._map_unknown_tool(tool_id, ref.get("alias", ""))
                if mapped_tool:
                    logger.info(f"工具 '{tool_id}' 不存在，已映射为 '{mapped_tool}'")
                    ref["tool_id"] = mapped_tool
                    ref["alias"] = ref.get("alias", tool_id)  # 保留原别名
                    validated_refs.append(ref)
                else:
                    logger.warning(
                        f"工具 '{tool_id}' 不存在于 ToolRegistry 中，已移除。"
                        f"建议使用 qveris_search_tools 搜索相关工具。"
                    )
        
        # 如果移除了所有工具，至少添加 QVeris 工具以便动态发现
        if not validated_refs and tool_references:
            logger.info("所有指定工具均不存在，添加 QVeris 工具以支持动态工具发现")
            validated_refs = [
                {
                    "tool_id": "qveris_search_tools",
                    "alias": "搜索工具",
                    "tool_type": "qveris",
                    "enabled": True
                },
                {
                    "tool_id": "qveris_execute_tool",
                    "alias": "执行工具",
                    "tool_type": "qveris",
                    "enabled": True
                }
            ]
        
        return validated_refs
    
    def _map_unknown_tool(self, tool_id: str, alias: str) -> Optional[str]:
        """
        尝试将未知工具映射到已知工具
        
        Args:
            tool_id: 工具 ID
            alias: 工具别名
            
        Returns:
            映射后的工具 ID，如果无法映射则返回 None
        """
        # QVeris 工具不应被映射到其他工具
        # 如果 QVeris 工具未注册，返回 None 触发回退逻辑
        if tool_id.startswith("qveris_"):
            logger.warning(
                f"QVeris 工具 '{tool_id}' 未注册，请确保已调用 "
                f"QVerisToolAdapter.register_meta_tools(tool_registry)"
            )
            return None
        
        tool_lower = tool_id.lower()
        alias_lower = alias.lower() if alias else ""
        combined = f"{tool_lower} {alias_lower}"
        
        # 文件相关工具映射
        if any(kw in combined for kw in ["file", "read", "write", "edit"]):
            if "read" in combined:
                return "file_read"
            elif "write" in combined:
                return "file_write"
            elif "edit" in combined:
                return "file_edit"
            elif "ls" in combined or "list" in combined:
                return "file_ls"
        
        # Shell 相关工具映射 (排除 qveris_execute_tool)
        if any(kw in combined for kw in ["bash", "shell", "command", "terminal"]):
            return "bash_execute_safe"
        
        # 外部数据/API 相关 - 映射到 QVeris
        if any(kw in combined for kw in [
            "api", "web", "scraper", "crawler", "fetch", "http", "request",
            "financial", "stock", "news", "data", "search", "query"
        ]):
            # 这类工具应该通过 QVeris 动态发现
            return None  # 返回 None，让调用者决定添加 QVeris 工具
        
        return None

    def _normalize_enum_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        规范化枚举字段值
        
        将 LLM 生成的无效枚举值映射到有效值，避免 Pydantic 验证失败。
        
        Args:
            data: Agent 定义数据字典
            
        Returns:
            规范化后的数据字典
        """
        # 有效的 domain_type 枚举值
        valid_domain_types = {
            "financial_analysis", "data_integration", "data_verification",
            "risk_assessment", "signal_detection", "report_generation", "general"
        }
        
        # domain_type 映射表 - 将常见的无效值映射到有效值
        domain_mapping = {
            # 数据收集相关
            "financial_data_collection": "data_integration",
            "data_collection": "data_integration",
            "data_collector": "data_integration",
            "collector": "data_integration",
            "data_gathering": "data_integration",
            "information_gathering": "data_integration",
            # 分析相关
            "analysis": "financial_analysis",
            "analyzer": "financial_analysis",
            "financial_analyzer": "financial_analysis",
            "investment_analysis": "financial_analysis",
            # 报告相关
            "report": "report_generation",
            "reporting": "report_generation",
            "report_writer": "report_generation",
            # 验证相关
            "verification": "data_verification",
            "validator": "data_verification",
            # 风险相关
            "risk": "risk_assessment",
            "risk_analysis": "risk_assessment",
        }
        
        # 有效的 execution_type 枚举值
        valid_execution_types = {
            "executor", "reasoning_executor", "deep_search", "flow_agent"
        }
        
        # execution_type 映射表
        execution_mapping = {
            "agent": "executor",
            "simple": "executor",
            "basic": "executor",
            "reasoner": "reasoning_executor",
            "reasoning": "reasoning_executor",
            "thinker": "reasoning_executor",
            "search": "deep_search",
            "searcher": "deep_search",
            "workflow": "flow_agent",
            "orchestrator": "flow_agent",
        }
        
        # 规范化 domain_type
        if "domain_type" in data:
            domain_type = data["domain_type"]
            if domain_type not in valid_domain_types:
                # 尝试从映射表中获取正确的值
                mapped_type = domain_mapping.get(domain_type.lower())
                if mapped_type:
                    logger.info(
                        f"修正 domain_type: '{domain_type}' -> '{mapped_type}'"
                    )
                    data["domain_type"] = mapped_type
                else:
                    # 无法映射，使用默认值
                    logger.warning(
                        f"无效的 domain_type '{domain_type}'，使用默认值 'general'"
                    )
                    data["domain_type"] = "general"
        
        # 规范化 execution_type
        if "execution_type" in data:
            execution_type = data["execution_type"]
            if execution_type not in valid_execution_types:
                # 尝试从映射表中获取正确的值
                mapped_type = execution_mapping.get(execution_type.lower())
                if mapped_type:
                    logger.info(
                        f"修正 execution_type: '{execution_type}' -> '{mapped_type}'"
                    )
                    data["execution_type"] = mapped_type
                else:
                    # 无法映射，使用默认值
                    logger.warning(
                        f"无效的 execution_type '{execution_type}'，使用默认值 'executor'"
                    )
                    data["execution_type"] = "executor"
        
        return data

    def _get_available_models_info(self) -> str:
        """获取可用模型信息的格式化文本"""
        try:
            model_registry = get_model_registry()
            models_info = model_registry.get_models_info()
            
            if not models_info:
                return "暂无可用模型配置"
            
            lines = []
            for model in models_info:
                caps = ", ".join(model.get("capabilities", []))
                cost = model.get("cost_tier", "unknown")
                max_tokens = model.get("max_tokens", "N/A")
                lines.append(
                    f"- **{model['name']}** (类型: {model['type']}, 成本: {cost}, "
                    f"最大tokens: {max_tokens}, 能力: {caps})"
                )
            
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"获取模型信息失败: {e}")
            return "模型信息不可用，请使用默认模型 qwen-plus"

    def _suggest_model_for_task(
        self, 
        task_description: str, 
        tools: List[str] = None
    ) -> str:
        """根据任务描述推荐合适的模型"""
        try:
            model_registry = get_model_registry()
            
            # 分析任务复杂度
            complexity = self._analyze_task_complexity(task_description)
            
            # 确定所需能力
            required_capabilities = self._determine_required_capabilities(
                task_description, tools
            )
            
            # 使用 ModelRegistry 的智能选择
            return model_registry.select_model(
                task_complexity=complexity,
                required_capabilities=required_capabilities,
                prefer_low_cost=True,
            )
        except Exception as e:
            logger.warning(f"模型选择失败，使用默认模型: {e}")
            return "qwen-plus"

    def _analyze_task_complexity(self, task_description: str) -> str:
        """
        分析任务复杂度
        
        Returns:
            复杂度级别: "simple", "medium", "complex", "multimodal"
        """
        desc_lower = task_description.lower()
        
        # 多模态任务
        multimodal_keywords = ["图像", "图片", "视觉", "image", "vision", "看图", "识别图"]
        if any(kw in desc_lower for kw in multimodal_keywords):
            return "multimodal"
        
        # 复杂任务关键词
        complex_keywords = [
            "深度分析", "推理", "规划", "决策", "评估", "策略",
            "comprehensive", "analysis", "reasoning", "planning",
            "多步骤", "复杂", "深入", "全面评估"
        ]
        if any(kw in desc_lower for kw in complex_keywords):
            return "complex"
        
        # 简单任务关键词
        simple_keywords = [
            "收集", "获取", "查询", "列出", "格式化", "转换",
            "collect", "fetch", "query", "list", "format", "convert",
            "简单", "基本"
        ]
        if any(kw in desc_lower for kw in simple_keywords):
            return "simple"
        
        # 默认为中等复杂度
        return "medium"

    def _determine_required_capabilities(
        self, 
        task_description: str, 
        tools: List[str] = None
    ) -> List[str]:
        """确定任务所需的模型能力"""
        capabilities = []
        desc_lower = task_description.lower()
        
        # 推理能力
        if any(kw in desc_lower for kw in ["分析", "推理", "判断", "评估", "analysis"]):
            capabilities.append("reasoning")
        
        # 编码能力
        if any(kw in desc_lower for kw in ["代码", "编程", "开发", "code", "programming"]):
            capabilities.append("coding")
        
        # 长上下文能力
        if any(kw in desc_lower for kw in ["长文", "大量数据", "全面", "comprehensive"]):
            capabilities.append("long_context")
        
        # 视觉能力
        if any(kw in desc_lower for kw in ["图像", "图片", "视觉", "image", "vision"]):
            capabilities.append("vision")
        
        # 如果没有特殊能力需求，默认需要推理
        if not capabilities:
            capabilities.append("reasoning")
        
        return capabilities

    def _format_agent_example(self, agent: AgentDefinition) -> str:
        """格式化 Agent 为示例文本"""
        # 提取背景指令摘要
        bg = agent.background_instruction
        bg_summary = f"{bg.role_description[:100]}..." if bg.role_description else "无"

        # 提取输出指令摘要
        out = agent.output_instruction
        out_summary = f"格式: {out.format_type}" if out else "无"

        return f"""### 参考 Agent: {agent.name}
- ID: {agent.agent_id}
- 描述: {agent.description}
- 背景指令: {bg_summary}
- 输出指令: {out_summary}
- 工具: {[t.tool_id for t in agent.tool_references]}"""

    def _analyze_feedback(
        self, feedback_history: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """分析反馈历史"""
        if not feedback_history:
            return {"success_rate": 0, "common_failures": [], "improvement_areas": []}

        successes = sum(1 for f in feedback_history if f.get("success"))
        success_rate = successes / len(feedback_history)

        # 收集失败原因
        failures = [
            f.get("feedback", "未知原因")
            for f in feedback_history
            if not f.get("success")
        ]

        return {
            "success_rate": success_rate,
            "total_executions": len(feedback_history),
            "common_failures": failures[:5],
            "improvement_areas": self._identify_improvement_areas(feedback_history),
        }

    def _identify_improvement_areas(
        self, feedback_history: List[Dict[str, Any]]
    ) -> List[str]:
        """识别需要改进的领域"""
        areas = []

        # 分析失败模式
        failed_tasks = [f for f in feedback_history if not f.get("success")]

        if len(failed_tasks) > len(feedback_history) * 0.3:
            areas.append("提高整体成功率")

        # 检查是否有重复失败
        failure_feedbacks = [f.get("feedback", "") for f in failed_tasks]
        if len(set(failure_feedbacks)) < len(failure_feedbacks) * 0.5:
            areas.append("解决重复性失败问题")

        return areas

    async def _call_llm(self, prompt: str, expect_json: bool = False) -> str:
        """调用 LLM
        
        Args:
            prompt: 提示词
            expect_json: 是否期望 JSON 响应（启用 UnifiedLLMClient 的自动优化和重试机制）
        
        Returns:
            LLM 响应内容
        """
        # 优先使用 UnifiedLLMClient 的 call 方法（支持 JSON 优化和重试）
        if hasattr(self.llm_client, "call"):
            import inspect
            if inspect.iscoroutinefunction(self.llm_client.call):
                messages = [{"role": "user", "content": prompt}]
                # 传入 response_format 触发 JSON 优化和相关重试机制
                response_format = {"type": "json_object"} if expect_json else None
                response = await self.llm_client.call(
                    messages,
                    response_format=response_format,
                )
                
                if isinstance(response, dict):
                    return response.get("content", response.get("text", str(response)))
                if hasattr(response, "content"):
                    return response.content
                return str(response)
        
        # 回退：使用 LangChain 的 ainvoke 方法
        if hasattr(self.llm_client, "ainvoke"):
            try:
                from langchain_core.messages import HumanMessage

                messages = [HumanMessage(content=prompt)]
                response = await self.llm_client.ainvoke(messages)

                if hasattr(response, "content"):
                    return response.content
                return str(response)
            except ImportError:
                pass  # 继续尝试其他方法
        
        # 尝试使用 invoke 方法（同步版本）
        if hasattr(self.llm_client, "invoke"):
            try:
                from langchain_core.messages import HumanMessage

                messages = [HumanMessage(content=prompt)]
                response = self.llm_client.invoke(messages)

                if hasattr(response, "content"):
                    return response.content
                return str(response)
            except ImportError:
                pass

        # 尝试使用自定义的 generate 方法（非 LangChain）
        if hasattr(self.llm_client, "generate"):
            import inspect

            sig = inspect.signature(self.llm_client.generate)
            params = list(sig.parameters.keys())

            # 如果 generate 方法接受 prompt 参数
            if "prompt" in params or len(params) == 0:
                kwargs = {"prompt": prompt}
                if "temperature" in params:
                    kwargs["temperature"] = self.temperature
                if "max_tokens" in params:
                    kwargs["max_tokens"] = self.max_tokens
                if self.model and "model" in params:
                    kwargs["model"] = self.model

                if inspect.iscoroutinefunction(self.llm_client.generate):
                    response = await self.llm_client.generate(**kwargs)
                else:
                    response = self.llm_client.generate(**kwargs)

                if isinstance(response, dict):
                    return response.get("content", response.get("text", str(response)))
                if hasattr(response, "content"):
                    return response.content
                return str(response)

        # 尝试直接调用（某些客户端支持 __call__）
        if callable(self.llm_client):
            response = self.llm_client(prompt)
            if hasattr(response, "content"):
                return response.content
            return str(response)

        raise ValueError(
            "不支持的 LLM 客户端类型，请确保客户端具有 ainvoke, invoke, 或 generate 方法"
        )

    def _parse_agent_definition(self, response: str) -> AgentDefinition:
        """解析 LLM 响应为 AgentDefinition"""
        import re

        # 提取 JSON
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)

            # 确保基本字段存在
            if "agent_id" not in data:
                data["agent_id"] = (
                    f"auto_generated_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )

            if "name" not in data:
                data["name"] = data["agent_id"].replace("_", " ").title()

            # 确保 display_name 存在，如果没有则使用 name
            if "display_name" not in data or not data["display_name"]:
                data["display_name"] = data.get("name", "智能助手")

            if "description" not in data:
                data["description"] = "由 Meta Agent 自动生成"

            # 确保 prompt 结构字段存在
            if "background_instruction" not in data:
                # 尝试从旧格式 prompt 字段迁移
                if "prompt" in data and isinstance(data["prompt"], dict):
                    old_prompt = data.pop("prompt")
                    data["background_instruction"] = {
                        "role_description": old_prompt.get(
                            "background_instruction", "你是一个智能助手"
                        ),
                        "core_capability": "根据用户需求完成任务",
                        "task_context": "在本任务中完成用户指定的工作",
                    }
                    data["output_instruction"] = {
                        "format_type": "json",
                        "format_requirements": [
                            old_prompt.get("output_instruction", "输出 JSON 格式")
                        ],
                    }
                    data["user_instruction"] = {
                        "template": old_prompt.get(
                            "user_instruction_template", "请完成以下任务：{task}"
                        ),
                    }
                else:
                    data["background_instruction"] = {
                        "role_description": "你是一个智能助手",
                        "core_capability": "根据用户需求完成任务",
                        "task_context": "在本任务中完成用户指定的工作",
                    }

            if "output_instruction" not in data:
                data["output_instruction"] = {
                    "format_type": "json",
                    "format_requirements": ["输出 JSON 格式"],
                }

            if "user_instruction" not in data:
                data["user_instruction"] = {
                    "task_description": "请完成以下任务：{task}",
                }
            elif "user_instruction" in data:
                # 确保使用正确的字段名（兼容 template 和 task_description）
                ui = data["user_instruction"]
                if "template" in ui and "task_description" not in ui:
                    ui["task_description"] = ui.pop("template")
                if "task_description" not in ui:
                    ui["task_description"] = "请完成以下任务：{task}"
                
                # 处理 user_instruction.tool_references - 应为字符串列表
                if "tool_references" in ui and isinstance(ui["tool_references"], list):
                    normalized_refs = []
                    for ref in ui["tool_references"]:
                        if isinstance(ref, str):
                            normalized_refs.append(ref)
                        elif isinstance(ref, dict):
                            # LLM 可能生成字典，转换为工具别名字符串
                            alias = ref.get("alias", ref.get("tool_id", ""))
                            if alias:
                                normalized_refs.append(f"@{alias}" if not alias.startswith("@") else alias)
                    ui["tool_references"] = normalized_refs
                
                # 处理 user_instruction.context_references - 应为字符串列表
                if "context_references" in ui and isinstance(ui["context_references"], list):
                    normalized_ctx = []
                    for ref in ui["context_references"]:
                        if isinstance(ref, str):
                            normalized_ctx.append(ref)
                        elif isinstance(ref, dict):
                            # 转换为引用字符串
                            ref_id = ref.get("reference", ref.get("id", ""))
                            if ref_id:
                                normalized_ctx.append(f"#{ref_id}" if not ref_id.startswith("#") else ref_id)
                    ui["context_references"] = normalized_ctx

            # 处理 tool_references 中缺失的字段并验证工具存在性
            if "tool_references" in data:
                for i, tool_ref in enumerate(data["tool_references"]):
                    if "alias" not in tool_ref:
                        tool_ref["alias"] = tool_ref.get("tool_id", f"tool_{i}")
                    if "tool_type" not in tool_ref:
                        tool_ref["tool_type"] = "builtin"
                
                # 验证并修正工具引用
                data["tool_references"] = self._validate_tool_references(
                    data["tool_references"]
                )

            # 处理 llm_config 字段名转换
            if "model_config" in data and "llm_config" not in data:
                data["llm_config"] = data.pop("model_config")

            # 规范化枚举字段（domain_type, execution_type）
            data = self._normalize_enum_fields(data)

            return AgentDefinition(**data)

        except json.JSONDecodeError as e:
            logger.error(f"解析 Agent 定义失败: {e}")
            raise ValueError(f"无法解析 LLM 响应为 Agent 定义: {e}")
        except Exception as e:
            logger.error(f"创建 AgentDefinition 失败: {e}")
            raise ValueError(f"无法创建 AgentDefinition: {e}")

    def _apply_optimization(
        self,
        original: AgentDefinition,
        optimization_response: str,
    ) -> AgentDefinition:
        """应用优化到 Agent 定义"""
        import re

        # 提取 JSON
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", optimization_response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = optimization_response

        try:
            optimization = json.loads(json_str)

            # 创建副本
            optimized_data = (
                original.model_dump()
                if hasattr(original, "model_dump")
                else vars(original).copy()
            )

            # 应用 prompt 优化
            if "prompt" in optimization:
                optimized_data["prompt"] = PromptStructure(**optimization["prompt"])

            return AgentDefinition(**optimized_data)

        except Exception as e:
            logger.warning(f"应用优化失败，返回原始定义: {e}")
            return original

    def _parse_suggestions(self, response: str) -> Dict[str, Any]:
        """解析改进建议响应"""
        import re

        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return {
                "summary": response,
                "issues": [],
                "suggestions": [],
                "metrics": {},
            }

    def _increment_version(self, version: str) -> str:
        """递增版本号"""
        try:
            parts = version.split(".")
            parts[-1] = str(int(parts[-1]) + 1)
            return ".".join(parts)
        except Exception:
            return "1.0.1"

    # ========== 工作流生成 ==========

    async def generate_workflow(
        self,
        task_description: str,
        available_agents: List[str],
        constraints: Optional[Dict[str, Any]] = None,
        include_error_handling: bool = True,
    ) -> WorkflowDefinition:
        """
        根据任务描述自动生成多 Agent 工作流

        分析任务需求，选择合适的 Agent，设计执行顺序和数据流。

        Args:
            task_description: 工作流任务描述
            available_agents: 可用的 Agent ID 列表
            constraints: 约束条件（如并行限制、超时等）
            include_error_handling: 是否包含错误处理节点

        Returns:
            生成的 WorkflowDefinition

        用法:
            ```python
            workflow = await meta.generate_workflow(
                task_description="生成一份完整的股票分析报告",
                available_agents=["data_fetcher", "technical_analyzer", "fundamental_analyzer", "report_generator"],
                constraints={"max_parallel": 2, "timeout": 300},
            )
            ```
        """
        # 收集可用 Agent 的信息
        agent_infos = []
        for agent_id in available_agents:
            agent = self.agent_registry.get_definition(agent_id)
            if agent:
                agent_infos.append(
                    {
                        "id": agent.agent_id,
                        "name": agent.name,
                        "description": agent.description,
                        "capabilities": self._extract_capabilities(agent),
                    }
                )

        if not agent_infos:
            raise ValueError("没有找到可用的 Agent")

        # 构建工作流生成提示
        prompt = self._build_workflow_generation_prompt(
            task_description=task_description,
            agent_infos=agent_infos,
            constraints=constraints,
            include_error_handling=include_error_handling,
        )

        # 调用 LLM 生成（启用 JSON 优化和重试机制）
        response = await self._call_llm(prompt, expect_json=True)

        # 解析响应为 WorkflowDefinition
        workflow = self._parse_workflow_definition(response)

        logger.info(f"Meta Agent 生成了工作流: {workflow.workflow_id}")

        return workflow

    def _build_workflow_generation_prompt(
        self,
        task_description: str,
        agent_infos: List[Dict[str, Any]],
        constraints: Optional[Dict[str, Any]],
        include_error_handling: bool,
    ) -> str:
        """构建工作流生成提示"""
        agents_text = json.dumps(agent_infos, ensure_ascii=False, indent=2)
        constraints_text = (
            json.dumps(constraints, ensure_ascii=False, indent=2)
            if constraints
            else "无特殊约束"
        )

        return f"""你是一个专业的多 Agent 工作流设计专家。请根据任务描述和可用 Agent，设计一个高效的工作流。

## 任务描述
{task_description}

## 可用 Agent
{agents_text}

## 约束条件
{constraints_text}

## 是否包含错误处理
{"是" if include_error_handling else "否"}

## 设计原则
1. 合理拆分任务，每个 Agent 负责其擅长的部分
2. 设计清晰的数据流，确保每个节点的输入来源明确
3. 可并行的任务应该并行执行
4. 考虑错误处理和重试机制
5. 设置合理的超时时间
6. **重要 - 数据血缘设计**：
   - `dependencies` 用于控制执行顺序（节点 B 必须在节点 A 之后执行）
   - `context_refs` 用于声明数据引用（节点 B 需要节点 A 的输出数据，但不改变执行顺序）
   - 报告生成类节点通常需要同时引用：分析节点的结论 + 数据收集节点的原始数据
   - 例如：report_generator 依赖 analyzer 执行，但也需要 data_collector 的原始数据作为证据支撑

## 输出要求
请生成完整的工作流定义，严格使用以下 JSON 格式：

```json
{{
    "workflow_id": "唯一标识符",
    "name": "工作流名称",
    "description": "工作流描述",
    "version": "1.0.0",
    "entry_node": "start",
    "exit_nodes": ["end"],
    "nodes": [
        {{
            "node_id": "start",
            "name": "开始节点",
            "node_type": "start"
        }},
        {{
            "node_id": "data_collector",
            "name": "数据采集节点",
            "node_type": "agent",
            "agent_id": "数据采集 Agent ID",
            "dependencies": ["start"],
            "context_refs": [],
            "config": {{"timeout": 90}}
        }},
        {{
            "node_id": "analyzer",
            "name": "分析节点",
            "node_type": "agent",
            "agent_id": "分析 Agent ID",
            "dependencies": ["data_collector"],
            "context_refs": [],
            "config": {{"timeout": 120}}
        }},
        {{
            "node_id": "report_generator",
            "name": "报告生成节点",
            "node_type": "agent",
            "agent_id": "报告生成 Agent ID",
            "dependencies": ["analyzer"],
            "context_refs": ["data_collector"],
            "config": {{"timeout": 90}}
        }},
        {{
            "node_id": "end",
            "name": "结束节点",
            "node_type": "end",
            "dependencies": ["report_generator"]
        }}
    ],
    "edges": [
        {{"from_node": "start", "to_node": "data_collector"}},
        {{"from_node": "data_collector", "to_node": "analyzer"}},
        {{"from_node": "analyzer", "to_node": "report_generator"}},
        {{"from_node": "report_generator", "to_node": "end"}}
    ],
    "global_config": {{
        "max_parallel": 3,
        "default_timeout": 120
    }}
}}
```

关键要求：
1. 每个 node 必须包含 node_id、name、node_type 三个字段
2. node_type 只能是: start, end, agent, parallel, condition, loop, human_in_loop
3. 必须有一个 start 节点和至少一个 end 节点
4. entry_node 应设为 start 节点的 ID
5. exit_nodes 应包含所有 end 节点的 ID
6. agent 类型节点必须指定 agent_id
7. dependencies 数组表示该节点依赖的前置节点（控制执行顺序）
8. **context_refs 数组表示该节点需要引用的其他节点输出（仅获取数据，不影响执行顺序）**
9. edges 定义节点间的连接关系
10. **报告/总结/输出类节点必须通过 context_refs 引用原始数据节点，确保最终输出包含详实的事实依据**"""

    def _extract_capabilities(self, agent: AgentDefinition) -> List[str]:
        """从 Agent 定义中提取能力关键词"""
        capabilities = []

        # 从工具引用提取
        for tool_ref in agent.tool_references:
            if tool_ref.enabled:
                capabilities.append(f"tool:{tool_ref.tool_id}")

        # 从描述中提取关键词
        keywords = ["分析", "生成", "搜索", "计算", "转换", "验证", "聚合"]
        description = agent.description.lower()
        for kw in keywords:
            if kw in description:
                capabilities.append(kw)

        return capabilities

    def _parse_workflow_definition(self, response: str) -> WorkflowDefinition:
        """解析 LLM 响应为 WorkflowDefinition"""
        import re
        from ..definitions.workflow_definition import NodeType

        # 提取 JSON
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)

            # 确保必需字段存在
            if "workflow_id" not in data:
                data["workflow_id"] = (
                    f"auto_workflow_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )

            if "name" not in data:
                data["name"] = "自动生成的工作流"

            # 转换节点，确保每个节点有必需字段
            nodes = []
            for i, node_data in enumerate(data.get("nodes", [])):
                # 确保 name 字段存在
                if "name" not in node_data:
                    node_data["name"] = node_data.get("node_id", f"node_{i}")

                # 确保 node_type 是有效的枚举值
                node_type_str = node_data.get("node_type", "agent")
                valid_types = [
                    "start",
                    "end",
                    "agent",
                    "condition",
                    "parallel",
                    "loop",
                    "human_in_loop",
                ]
                if node_type_str not in valid_types:
                    node_type_str = "agent"
                node_data["node_type"] = node_type_str

                nodes.append(WorkflowNode(**node_data))

            # 转换边
            edges = []
            for edge_data in data.get("edges", []):
                edges.append(WorkflowEdge(**edge_data))

            # 转换数据映射
            data_mappings = []
            for mapping_data in data.get("data_mappings", []):
                data_mappings.append(DataMapping(**mapping_data))

            # 确定入口和出口节点
            entry_node = data.get("entry_node")
            if not entry_node:
                # 查找 start 类型节点
                for node in nodes:
                    if node.node_type == NodeType.START:
                        entry_node = node.node_id
                        break
                if not entry_node and nodes:
                    entry_node = nodes[0].node_id

            exit_nodes = data.get("exit_nodes", [])
            if not exit_nodes:
                # 查找 end 类型节点
                for node in nodes:
                    if node.node_type == NodeType.END:
                        exit_nodes.append(node.node_id)
                if not exit_nodes and nodes:
                    exit_nodes = [nodes[-1].node_id]

            return WorkflowDefinition(
                workflow_id=data["workflow_id"],
                name=data["name"],
                description=data.get("description", ""),
                version=data.get("version", "1.0.0"),
                entry_node=entry_node,
                exit_nodes=exit_nodes,
                nodes=nodes,
                edges=edges,
                data_mappings=data_mappings,
                global_config=data.get("global_config", {}),
            )

        except json.JSONDecodeError as e:
            logger.error(f"解析工作流定义失败: {e}")
            raise ValueError(f"无法解析 LLM 响应为工作流定义: {e}")
        except Exception as e:
            logger.error(f"创建 WorkflowDefinition 失败: {e}")
            raise ValueError(f"无法创建 WorkflowDefinition: {e}")

    async def optimize_workflow(
        self,
        workflow: WorkflowDefinition,
        execution_history: List[Dict[str, Any]],
        optimization_goal: str = "latency",
    ) -> WorkflowDefinition:
        """
        基于执行历史优化工作流

        Args:
            workflow: 原始工作流定义
            execution_history: 执行历史记录
            optimization_goal: 优化目标 (latency, reliability, cost)

        Returns:
            优化后的工作流定义
        """
        # 分析执行历史
        analysis = self._analyze_workflow_execution(execution_history)

        prompt = f"""你是一个工作流优化专家。请根据执行历史，优化以下工作流。

## 当前工作流
```json
{json.dumps(workflow.model_dump() if hasattr(workflow, 'model_dump') else vars(workflow), ensure_ascii=False, indent=2, default=str)}
```

## 执行分析
- 平均执行时间: {analysis.get('avg_duration', 'N/A')}
- 成功率: {analysis.get('success_rate', 'N/A')}
- 瓶颈节点: {analysis.get('bottlenecks', [])}
- 常见失败点: {analysis.get('failure_points', [])}

## 优化目标
{optimization_goal}

## 输出要求
请输出优化后的工作流定义（JSON 格式），并说明优化理由。
"""

        response = await self._call_llm(prompt, expect_json=True)
        return self._parse_workflow_definition(response)

    def _analyze_workflow_execution(
        self, execution_history: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """分析工作流执行历史"""
        if not execution_history:
            return {}

        # 计算基本统计
        durations = [
            e.get("duration", 0) for e in execution_history if e.get("duration")
        ]
        successes = sum(1 for e in execution_history if e.get("success"))

        # 找出瓶颈节点
        node_durations = {}
        for execution in execution_history:
            for node_id, node_result in execution.get("node_results", {}).items():
                if node_id not in node_durations:
                    node_durations[node_id] = []
                node_durations[node_id].append(node_result.get("duration", 0))

        bottlenecks = sorted(
            node_durations.items(),
            key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0,
            reverse=True,
        )[:3]

        return {
            "avg_duration": sum(durations) / len(durations) if durations else 0,
            "success_rate": successes / len(execution_history),
            "bottlenecks": [b[0] for b in bottlenecks],
            "failure_points": self._find_failure_points(execution_history),
        }

    def _find_failure_points(
        self, execution_history: List[Dict[str, Any]]
    ) -> List[str]:
        """找出常见失败点"""
        failure_counts = {}
        for execution in execution_history:
            if not execution.get("success"):
                failed_node = execution.get("failed_node", "unknown")
                failure_counts[failed_node] = failure_counts.get(failed_node, 0) + 1

        return sorted(
            failure_counts.keys(), key=lambda x: failure_counts[x], reverse=True
        )[:3]

    # ========== 性能监控集成 ==========

    async def monitor_agent_performance(
        self,
        agent_id: str,
        time_window: timedelta = timedelta(hours=24),
    ) -> Dict[str, Any]:
        """
        监控 Agent 性能

        如果配置了性能监控器，使用监控器；否则从注册表获取基本统计。

        Args:
            agent_id: Agent ID
            time_window: 监控时间窗口

        Returns:
            性能报告
        """
        if self.performance_monitor:
            return await self.performance_monitor.generate_report(agent_id, time_window)

        # 基本性能统计（从注册表获取）
        agent = self.agent_registry.get_definition(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} 不存在")

        return {
            "agent_id": agent_id,
            "agent_name": agent.name,
            "status": "active",
            "message": "性能监控器未配置，无法获取详细指标",
        }

    async def check_agent_health(
        self,
        agent_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        检查 Agent 健康状态

        Args:
            agent_ids: 要检查的 Agent ID 列表（None 表示所有）

        Returns:
            健康状态报告
        """
        if agent_ids is None:
            agent_ids = [a.agent_id for a in self.agent_registry.list_all()]

        health_report = {
            "timestamp": datetime.now().isoformat(),
            "agents": {},
            "overall_status": "healthy",
        }

        for agent_id in agent_ids:
            try:
                if self.performance_monitor:
                    metrics = await self.performance_monitor.collect_metrics(agent_id)
                    alerts = await self.performance_monitor.check_alerts(agent_id)

                    status = "healthy"
                    if any(a.severity == "critical" for a in alerts):
                        status = "critical"
                        health_report["overall_status"] = "critical"
                    elif any(a.severity == "warning" for a in alerts):
                        status = "warning"
                        if health_report["overall_status"] == "healthy":
                            health_report["overall_status"] = "warning"

                    health_report["agents"][agent_id] = {
                        "status": status,
                        "metrics": (
                            metrics.to_dict()
                            if hasattr(metrics, "to_dict")
                            else metrics
                        ),
                        "alerts": [
                            a.to_dict() if hasattr(a, "to_dict") else a for a in alerts
                        ],
                    }
                else:
                    health_report["agents"][agent_id] = {
                        "status": "unknown",
                        "message": "性能监控器未配置",
                    }
            except Exception as e:
                health_report["agents"][agent_id] = {
                    "status": "error",
                    "error": str(e),
                }
                health_report["overall_status"] = "warning"

        return health_report

    # ========== 交互式构建器集成 ==========

    def create_interactive_builder(
        self,
        callback: Optional[Any] = None,
        storage_path: Optional[str] = None,
        max_iterations: int = 3,
    ) -> "InteractiveWorkflowBuilder":
        """
        创建交互式工作流构建器
        
        Args:
            callback: 用户交互回调实现，如果为 None 则使用 CLIInteractionCallback
            storage_path: 存储路径，用于保存检查点和迭代历史
            max_iterations: 每步最大迭代次数
            
        Returns:
            InteractiveWorkflowBuilder 实例
            
        示例:
            ```python
            builder = meta_agent.create_interactive_builder()
            workflow = await builder.start_interactive_session(
                task_description="对比亚迪进行投资分析",
                interaction_level=InteractionLevel.MODERATE,
            )
            ```
        """
        from .interactive_builder import (
            InteractiveWorkflowBuilder,
            CLIInteractionCallback,
        )
        from pathlib import Path
        
        if callback is None:
            callback = CLIInteractionCallback()
        
        path = Path(storage_path) if storage_path else None
        
        return InteractiveWorkflowBuilder(
            meta_agent=self,
            callback=callback,
            storage_path=path,
            max_iterations_per_step=max_iterations,
        )


# 导出
__all__ = ["MetaAgent"]

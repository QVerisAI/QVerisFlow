"""
智能路由器

根据任务描述和要求，智能选择合适的 Agent 或工作流。
"""

from typing import List, Dict, Any, Optional
from enum import Enum

from ..definitions import AgentDefinition, AgentDomainType, AgentExecutionType
from src.utils.logger import get_logger

logger = get_logger()


class RoutingStrategy(str, Enum):
    """路由策略"""

    # 基础策略
    EXACT_MATCH = "exact_match"  # 精确匹配
    CAPABILITY_MATCH = "capability_match"  # 能力匹配

    # 智能策略
    LLM_ROUTING = "llm_routing"  # LLM 智能路由
    ENSEMBLE = "ensemble"  # 集成多个 Agent

    # 优化策略
    COST_OPTIMIZED = "cost_optimized"  # 成本优化
    LATENCY_OPTIMIZED = "latency_optimized"  # 延迟优化


class SmartRouter:
    """
    智能路由器

    支持多种路由策略，根据任务选择合适的 Agent
    """

    def __init__(
        self,
        agent_registry: Any,  # AgentRegistry
        tool_registry: Any,  # ToolRegistry
        default_strategy: RoutingStrategy = RoutingStrategy.CAPABILITY_MATCH,
    ):
        self.agent_registry = agent_registry
        self.tool_registry = tool_registry
        self.default_strategy = default_strategy

        # LLM 路由器（可选）
        self._llm_router = None

    async def route(
        self,
        task_description: str,
        required_capabilities: Optional[List[str]] = None,
        required_tools: Optional[List[str]] = None,
        domain: Optional[AgentDomainType] = None,
        execution_type: Optional[AgentExecutionType] = None,
        strategy: Optional[RoutingStrategy] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[AgentDefinition]:
        """
        智能路由到合适的 Agent

        Args:
            task_description: 任务描述
            required_capabilities: 必需的能力
            required_tools: 必需的工具（@引用）
            domain: 限定领域
            execution_type: 限定执行类型
            strategy: 路由策略
            context: 上下文信息

        Returns:
            匹配的 Agent 定义列表
        """
        strategy = strategy or self.default_strategy

        # 1. 初步筛选
        candidates = self._filter_candidates(
            domain=domain, execution_type=execution_type, required_tools=required_tools
        )

        if not candidates:
            logger.warning("⚠️ 未找到符合条件的 Agent")
            return []

        # 2. 根据策略选择
        if strategy == RoutingStrategy.EXACT_MATCH:
            return candidates[:1]  # 返回第一个匹配

        elif strategy == RoutingStrategy.CAPABILITY_MATCH:
            return self._match_by_capability(candidates, required_capabilities)

        elif strategy == RoutingStrategy.LLM_ROUTING:
            return await self._llm_route(candidates, task_description, context)

        elif strategy == RoutingStrategy.ENSEMBLE:
            return self._select_ensemble(candidates, task_description)

        elif strategy == RoutingStrategy.COST_OPTIMIZED:
            return self._optimize_by_cost(candidates)

        elif strategy == RoutingStrategy.LATENCY_OPTIMIZED:
            return self._optimize_by_latency(candidates)

        return candidates

    def _filter_candidates(
        self,
        domain: Optional[AgentDomainType],
        execution_type: Optional[AgentExecutionType],
        required_tools: Optional[List[str]],
    ) -> List[AgentDefinition]:
        """初步筛选候选 Agent"""

        all_agents = list(self.agent_registry._definitions.values())
        candidates = all_agents

        # 按领域筛选
        if domain:
            candidates = [a for a in candidates if a.domain_type == domain]

        # 按执行类型筛选
        if execution_type:
            candidates = [a for a in candidates if a.execution_type == execution_type]

        # 按工具筛选
        if required_tools:

            def has_all_tools(agent: AgentDefinition) -> bool:
                agent_tools = {t.alias for t in agent.tool_references}
                return all(
                    tool.replace("@", "") in agent_tools for tool in required_tools
                )

            candidates = [a for a in candidates if has_all_tools(a)]

        return candidates

    def _match_by_capability(
        self,
        candidates: List[AgentDefinition],
        required_capabilities: Optional[List[str]],
    ) -> List[AgentDefinition]:
        """按能力匹配"""
        if not required_capabilities:
            return candidates

        # 简化实现：匹配描述中包含能力关键词的 Agent
        matched = []
        for agent in candidates:
            description_lower = agent.description.lower()
            if any(cap.lower() in description_lower for cap in required_capabilities):
                matched.append(agent)

        return matched if matched else candidates

    async def _llm_route(
        self,
        candidates: List[AgentDefinition],
        task_description: str,
        context: Optional[Dict[str, Any]],
    ) -> List[AgentDefinition]:
        """使用 LLM 智能路由"""

        if not self._llm_router:
            # 回退到能力匹配
            logger.warning("LLM 路由器未配置，回退到能力匹配")
            return self._match_by_capability(candidates, None)

        # 构建候选描述
        candidates_desc = "\n".join(
            [f"- {a.agent_id}: {a.name} - {a.description}" for a in candidates]
        )

        prompt = f"""任务描述：{task_description}

可用的 Agent：
{candidates_desc}

请选择最适合处理该任务的 Agent，返回其 agent_id。
如果需要多个 Agent 协作，按优先级列出。
"""

        try:
            # 调用 LLM
            response = await self._llm_router.invoke(prompt)
            selected_ids = self._parse_llm_response(response)

            return [a for a in candidates if a.agent_id in selected_ids]

        except Exception as e:
            logger.error(f"LLM 路由失败: {e}")
            return candidates

    def _select_ensemble(
        self, candidates: List[AgentDefinition], task_description: str
    ) -> List[AgentDefinition]:
        """选择集成执行的 Agent 组合"""

        # 按执行类型分组，每组选一个最匹配的
        by_type = {}
        for agent in candidates:
            exec_type = agent.execution_type
            if exec_type not in by_type:
                by_type[exec_type] = []
            by_type[exec_type].append(agent)

        selected = []
        for agents in by_type.values():
            # 每种类型选择第一个
            selected.append(agents[0])

        return selected

    def _optimize_by_cost(
        self, candidates: List[AgentDefinition]
    ) -> List[AgentDefinition]:
        """按成本优化"""
        # 简化实现：选择 max_tokens 较小的
        return sorted(candidates, key=lambda a: a.llm_config.max_tokens)

    def _optimize_by_latency(
        self, candidates: List[AgentDefinition]
    ) -> List[AgentDefinition]:
        """按延迟优化"""
        # 简化实现：选择 max_iterations 较小的
        return sorted(candidates, key=lambda a: a.llm_config.max_iterations)

    def _parse_llm_response(self, response: str) -> List[str]:
        """解析 LLM 响应，提取 agent_id"""
        # 简化实现：提取所有类似 agent_id 的字符串
        import re

        pattern = r"[a-z_]+(?:_agent|_analyzer|_generator)?"
        matches = re.findall(pattern, response.lower())
        return matches[:3]  # 最多返回 3 个

# 工作流编排与智能路由

## 1. 设计理念

工作流编排层负责：
- **多 Agent 协作**：编排多个 Agent 完成复杂任务
- **智能路由**：根据任务特征选择最合适的 Agent
- **并行执行**：支持子 Agent 并行，提高效率
- **数据流转**：管理节点间的数据传递

```
┌─────────────────────────────────────────────────────────────┐
│                      编排层架构                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   工作流引擎                          │   │
│  │  ┌───────────────────────────────────────────────┐   │   │
│  │  │  YAML 定义 ──▶ DAG 构建 ──▶ 执行调度            │   │   │
│  │  └───────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   智能路由器                          │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐  │   │
│  │  │能力匹配  │  │LLM路由  │  │成本优化  │  │延迟优化│  │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                 子 Agent 管理器                       │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │   │
│  │  │ 并行执行器   │  │ 上下文隔离   │  │ 结果聚合    │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 工作流引擎

```python
# etf_common/agent_framework/orchestration/workflow_engine.py

from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import asyncio
from enum import Enum

from ..definitions import WorkflowDefinition, WorkflowNode, NodeType, DataMapping
from ..core import BaseAgent, AgentState
from ..workspace import AgentWorkspace, WorkspaceConfig
from ..registry import AgentRegistry


class NodeStatus(str, Enum):
    """节点执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowState:
    """工作流执行状态"""
    
    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self.node_states: Dict[str, NodeStatus] = {}
        self.node_outputs: Dict[str, Any] = {}
        self.node_errors: Dict[str, str] = {}
        self.global_context: Dict[str, Any] = {}
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
    
    def set_node_status(self, node_id: str, status: NodeStatus):
        self.node_states[node_id] = status
    
    def set_node_output(self, node_id: str, output: Any):
        self.node_outputs[node_id] = output
    
    def get_node_output(self, node_id: str) -> Any:
        return self.node_outputs.get(node_id)
    
    def is_completed(self, node_id: str) -> bool:
        return self.node_states.get(node_id) == NodeStatus.COMPLETED


class WorkflowEngine:
    """
    工作流引擎
    
    支持：
    - DAG 工作流执行
    - 条件分支
    - 并行节点
    - 数据映射
    - 错误处理
    """
    
    def __init__(
        self,
        agent_registry: AgentRegistry,
        base_workspace_path: str = "./workspaces"
    ):
        self.agent_registry = agent_registry
        self.base_workspace_path = base_workspace_path
        self._node_executors: Dict[NodeType, Callable] = {
            NodeType.START: self._execute_start_node,
            NodeType.END: self._execute_end_node,
            NodeType.AGENT: self._execute_agent_node,
            NodeType.CONDITION: self._execute_condition_node,
            NodeType.PARALLEL: self._execute_parallel_node,
        }
    
    async def execute(
        self,
        workflow: WorkflowDefinition,
        initial_input: Dict[str, Any] = None,
        task_id: str = None
    ) -> Dict[str, Any]:
        """
        执行工作流
        
        Args:
            workflow: 工作流定义
            initial_input: 初始输入数据
            task_id: 任务 ID
            
        Returns:
            工作流执行结果
        """
        # 验证工作流
        errors = workflow.validate()
        if errors:
            raise ValueError(f"工作流定义错误: {errors}")
        
        # 初始化状态
        task_id = task_id or f"{workflow.workflow_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        state = WorkflowState(workflow.workflow_id)
        state.started_at = datetime.now()
        state.global_context = {
            **(workflow.global_context or {}),
            "initial_input": initial_input or {}
        }
        
        # 创建工作空间
        workspace = AgentWorkspace(WorkspaceConfig(
            base_path=self.base_workspace_path,
            task_id=task_id
        ))
        
        # 写入初始输入
        if initial_input:
            workspace.write_task(
                task_description=initial_input.get("task", ""),
                input_data=initial_input
            )
        
        try:
            # 从入口节点开始执行
            await self._execute_from_node(
                workflow=workflow,
                state=state,
                workspace=workspace,
                node_id=workflow.entry_node
            )
            
            state.completed_at = datetime.now()
            
            # 收集结果
            return {
                "workflow_id": workflow.workflow_id,
                "task_id": task_id,
                "success": all(
                    state.node_states.get(exit_id) == NodeStatus.COMPLETED
                    for exit_id in workflow.exit_nodes
                ),
                "node_outputs": state.node_outputs,
                "duration": (state.completed_at - state.started_at).total_seconds()
            }
            
        except Exception as e:
            state.completed_at = datetime.now()
            return {
                "workflow_id": workflow.workflow_id,
                "task_id": task_id,
                "success": False,
                "error": str(e),
                "node_outputs": state.node_outputs
            }
    
    async def _execute_from_node(
        self,
        workflow: WorkflowDefinition,
        state: WorkflowState,
        workspace: AgentWorkspace,
        node_id: str
    ):
        """从指定节点开始执行"""
        node = workflow.get_node(node_id)
        if not node:
            raise ValueError(f"节点 {node_id} 不存在")
        
        # 检查是否已执行
        if state.is_completed(node_id):
            return
        
        # 执行节点
        state.set_node_status(node_id, NodeStatus.RUNNING)
        
        try:
            executor = self._node_executors.get(node.node_type)
            if not executor:
                raise ValueError(f"不支持的节点类型: {node.node_type}")
            
            output = await executor(
                node=node,
                workflow=workflow,
                state=state,
                workspace=workspace
            )
            
            state.set_node_output(node_id, output)
            state.set_node_status(node_id, NodeStatus.COMPLETED)
            
            # 更新全局上下文（用于 #引用）
            state.global_context[node_id] = output
            
        except Exception as e:
            state.node_errors[node_id] = str(e)
            if node.continue_on_error:
                state.set_node_status(node_id, NodeStatus.FAILED)
            else:
                raise
        
        # 执行后继节点
        next_nodes = workflow.get_next_nodes(node_id)
        for next_id in next_nodes:
            # 检查条件
            edge = next(
                (e for e in workflow.edges 
                 if e.from_node == node_id and e.to_node == next_id),
                None
            )
            
            if edge and edge.condition:
                if not self._evaluate_condition(edge.condition, state):
                    continue
            
            await self._execute_from_node(workflow, state, workspace, next_id)
    
    async def _execute_start_node(
        self,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        state: WorkflowState,
        workspace: AgentWorkspace
    ) -> Dict[str, Any]:
        """执行开始节点"""
        return {"status": "started"}
    
    async def _execute_end_node(
        self,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        state: WorkflowState,
        workspace: AgentWorkspace
    ) -> Dict[str, Any]:
        """执行结束节点"""
        return {"status": "completed", "outputs": state.node_outputs}
    
    async def _execute_agent_node(
        self,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        state: WorkflowState,
        workspace: AgentWorkspace
    ) -> Dict[str, Any]:
        """执行 Agent 节点"""
        # 获取 Agent 定义
        agent_def = self.agent_registry.get_definition(node.agent_id)
        if not agent_def:
            raise ValueError(f"Agent {node.agent_id} 未注册")
        
        # 应用覆盖配置
        if node.background_override:
            agent_def.background_instruction.task_context = node.background_override
        if node.user_override:
            agent_def.user_instruction.task_description = node.user_override
        if node.model_override:
            agent_def.model_config.model_name = node.model_override
        
        # 解析输入映射
        input_data = self._resolve_input_mappings(node.input_mappings, state)
        
        # 解析上下文引用
        resolved_context = {}
        for ref in node.context_refs:
            ref_key = ref.replace("#", "")
            if ref_key in state.global_context:
                resolved_context[ref] = state.global_context[ref_key]
        
        # 创建子工作空间
        sub_workspace = workspace.create_sub_workspace(node.node_id)
        sub_workspace.write_task(
            task_description=agent_def.user_instruction.task_description,
            input_data=input_data
        )
        
        # 创建并执行 Agent
        agent = self.agent_registry.create_agent(
            agent_id=node.agent_id,
            workspace=sub_workspace,
            config={"resolved_context": resolved_context}
        )
        
        result = await agent.run()
        
        return result
    
    async def _execute_condition_node(
        self,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        state: WorkflowState,
        workspace: AgentWorkspace
    ) -> Dict[str, Any]:
        """执行条件节点"""
        condition_result = self._evaluate_condition(
            node.condition_expression,
            state
        )
        return {"condition": node.condition_expression, "result": condition_result}
    
    async def _execute_parallel_node(
        self,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        state: WorkflowState,
        workspace: AgentWorkspace
    ) -> Dict[str, Any]:
        """执行并行节点"""
        parallel_tasks = []
        
        for parallel_node_id in node.parallel_nodes:
            parallel_tasks.append(
                self._execute_from_node(
                    workflow=workflow,
                    state=state,
                    workspace=workspace,
                    node_id=parallel_node_id
                )
            )
        
        await asyncio.gather(*parallel_tasks, return_exceptions=True)
        
        return {
            "parallel_nodes": node.parallel_nodes,
            "completed": [
                nid for nid in node.parallel_nodes
                if state.is_completed(nid)
            ]
        }
    
    def _resolve_input_mappings(
        self,
        mappings: List[DataMapping],
        state: WorkflowState
    ) -> Dict[str, Any]:
        """解析输入映射"""
        result = {}
        
        for mapping in mappings:
            source_output = state.get_node_output(mapping.source_node)
            if source_output is None:
                if mapping.required:
                    raise ValueError(f"源节点 {mapping.source_node} 无输出")
                continue
            
            # 获取源字段值
            value = self._get_nested_value(source_output, mapping.source_field)
            
            # 应用转换
            if mapping.transform:
                value = self._apply_transform(value, mapping.transform)
            
            # 设置目标字段
            self._set_nested_value(result, mapping.target_field, value)
        
        return result
    
    def _evaluate_condition(
        self,
        expression: str,
        state: WorkflowState
    ) -> bool:
        """评估条件表达式"""
        # 构建评估上下文
        eval_context = {
            "state": state,
            "outputs": state.node_outputs,
            "context": state.global_context
        }
        
        try:
            return eval(expression, {"__builtins__": {}}, eval_context)
        except Exception:
            return False
    
    @staticmethod
    def _get_nested_value(obj: Dict, path: str) -> Any:
        """获取嵌套字段值"""
        keys = path.split(".")
        value = obj
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value
    
    @staticmethod
    def _set_nested_value(obj: Dict, path: str, value: Any):
        """设置嵌套字段值"""
        keys = path.split(".")
        for key in keys[:-1]:
            obj = obj.setdefault(key, {})
        obj[keys[-1]] = value
    
    @staticmethod
    def _apply_transform(value: Any, transform: str) -> Any:
        """应用转换"""
        import json
        
        transforms = {
            "json.loads": json.loads,
            "json.dumps": lambda x: json.dumps(x, ensure_ascii=False),
            "str": str,
            "int": int,
            "float": float,
            "list": list,
        }
        
        if transform in transforms:
            return transforms[transform](value)
        
        # Lambda 表达式
        if transform.startswith("lambda"):
            func = eval(transform)
            return func(value)
        
        return value
```

---

## 3. 智能路由器

```python
# etf_common/agent_framework/orchestration/smart_router.py

from typing import List, Dict, Any, Optional
from enum import Enum

from ..definitions import AgentDefinition, AgentDomainType, AgentExecutionType
from ..registry import AgentRegistry
from ..tools import ToolRegistry


class RoutingStrategy(str, Enum):
    """路由策略"""
    
    EXACT_MATCH = "exact_match"              # 精确匹配
    CAPABILITY_MATCH = "capability_match"    # 能力匹配
    LLM_ROUTING = "llm_routing"              # LLM 智能路由
    ENSEMBLE = "ensemble"                    # 集成多个 Agent
    COST_OPTIMIZED = "cost_optimized"        # 成本优化
    LATENCY_OPTIMIZED = "latency_optimized"  # 延迟优化


class SmartRouter:
    """
    智能路由器
    
    根据任务特征选择最合适的 Agent
    """
    
    def __init__(
        self,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        llm_client: Any = None,
        default_strategy: RoutingStrategy = RoutingStrategy.CAPABILITY_MATCH
    ):
        self.agent_registry = agent_registry
        self.tool_registry = tool_registry
        self.llm_client = llm_client
        self.default_strategy = default_strategy
    
    async def route(
        self,
        task_description: str,
        required_capabilities: List[str] = None,
        required_tools: List[str] = None,
        domain: AgentDomainType = None,
        execution_type: AgentExecutionType = None,
        strategy: RoutingStrategy = None,
        context: Dict[str, Any] = None
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
            匹配的 Agent 定义列表（按优先级排序）
        """
        strategy = strategy or self.default_strategy
        
        # 1. 初步筛选
        candidates = self._filter_candidates(
            domain=domain,
            execution_type=execution_type,
            required_tools=required_tools
        )
        
        if not candidates:
            return []
        
        # 2. 根据策略选择
        if strategy == RoutingStrategy.EXACT_MATCH:
            return candidates[:1]
        
        elif strategy == RoutingStrategy.CAPABILITY_MATCH:
            return self._match_by_capability(
                candidates, required_capabilities, task_description
            )
        
        elif strategy == RoutingStrategy.LLM_ROUTING:
            return await self._llm_route(
                candidates, task_description, context
            )
        
        elif strategy == RoutingStrategy.ENSEMBLE:
            return self._select_ensemble(candidates, task_description)
        
        elif strategy == RoutingStrategy.COST_OPTIMIZED:
            return self._optimize_by_cost(candidates)
        
        elif strategy == RoutingStrategy.LATENCY_OPTIMIZED:
            return self._optimize_by_latency(candidates)
        
        return candidates
    
    def _filter_candidates(
        self,
        domain: AgentDomainType = None,
        execution_type: AgentExecutionType = None,
        required_tools: List[str] = None
    ) -> List[AgentDefinition]:
        """初步筛选候选 Agent"""
        all_agents = self.agent_registry.list_all_definitions()
        candidates = list(all_agents)
        
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
                    tool.replace("@", "") in agent_tools 
                    for tool in required_tools
                )
            candidates = [a for a in candidates if has_all_tools(a)]
        
        return candidates
    
    def _match_by_capability(
        self,
        candidates: List[AgentDefinition],
        required_capabilities: List[str],
        task_description: str
    ) -> List[AgentDefinition]:
        """按能力匹配"""
        if not required_capabilities:
            return candidates
        
        # 计算匹配分数
        scored = []
        for agent in candidates:
            score = 0
            agent_text = f"{agent.description} {agent.background_instruction.core_capability}"
            
            for cap in required_capabilities:
                if cap.lower() in agent_text.lower():
                    score += 1
            
            # 检查任务关键词匹配
            task_words = set(task_description.lower().split())
            agent_words = set(agent_text.lower().split())
            overlap = len(task_words & agent_words)
            score += overlap * 0.1
            
            scored.append((agent, score))
        
        # 按分数排序
        scored.sort(key=lambda x: x[1], reverse=True)
        return [a for a, _ in scored]
    
    async def _llm_route(
        self,
        candidates: List[AgentDefinition],
        task_description: str,
        context: Dict[str, Any] = None
    ) -> List[AgentDefinition]:
        """使用 LLM 智能路由"""
        if not self.llm_client:
            return self._match_by_capability(candidates, None, task_description)
        
        # 构建候选描述
        candidates_desc = "\n".join([
            f"- {a.agent_id}: {a.name}\n  描述: {a.description}\n  能力: {a.background_instruction.core_capability[:200]}"
            for a in candidates
        ])
        
        prompt = f"""作为智能路由器，请选择最适合处理以下任务的 Agent。

## 任务描述
{task_description}

## 可用的 Agent
{candidates_desc}

## 上下文
{context if context else '无'}

请返回最适合的 Agent ID 列表（JSON 格式），按优先级排序：
["agent_id_1", "agent_id_2", ...]

如果只需要一个 Agent，只返回一个。如果任务复杂需要多个协作，可返回多个。
"""
        
        response = await self.llm_client.generate(prompt)
        
        try:
            import json
            selected_ids = json.loads(response)
            return [a for a in candidates if a.agent_id in selected_ids]
        except:
            return candidates[:1]
    
    def _select_ensemble(
        self,
        candidates: List[AgentDefinition],
        task_description: str
    ) -> List[AgentDefinition]:
        """选择集成执行的 Agent 组合"""
        # 按执行类型分组，每组选一个最匹配的
        by_type: Dict[AgentExecutionType, List[AgentDefinition]] = {}
        
        for agent in candidates:
            exec_type = agent.execution_type
            if exec_type not in by_type:
                by_type[exec_type] = []
            by_type[exec_type].append(agent)
        
        # 每种类型选择第一个
        selected = []
        for agents in by_type.values():
            selected.append(agents[0])
        
        return selected
    
    def _optimize_by_cost(
        self,
        candidates: List[AgentDefinition]
    ) -> List[AgentDefinition]:
        """按成本优化选择"""
        # 简单实现：优先选择非 online 模式
        return sorted(
            candidates,
            key=lambda a: (
                1 if a.model_config.enable_online else 0,
                a.model_config.max_tokens
            )
        )
    
    def _optimize_by_latency(
        self,
        candidates: List[AgentDefinition]
    ) -> List[AgentDefinition]:
        """按延迟优化选择"""
        # 简单实现：优先选择迭代次数少的
        return sorted(
            candidates,
            key=lambda a: a.model_config.max_iterations
        )
```

---

## 4. 子 Agent 管理器

```python
# etf_common/agent_framework/orchestration/sub_agent_manager.py

from typing import Dict, Any, List, Type
import asyncio
from datetime import datetime

from ..core import BaseAgent
from ..workspace import AgentWorkspace, WorkspaceConfig


class SubAgentManager:
    """
    子 Agent 管理器
    
    负责：
    - 子 Agent 创建和生命周期管理
    - 并行执行
    - 上下文隔离
    - 结果聚合
    """
    
    def __init__(
        self,
        parent_workspace: AgentWorkspace,
        max_parallel: int = 5
    ):
        self.parent_workspace = parent_workspace
        self.max_parallel = max_parallel
        self.active_sub_agents: Dict[str, BaseAgent] = {}
        self.results: Dict[str, Any] = {}
        self.semaphore = asyncio.Semaphore(max_parallel)
    
    async def spawn(
        self,
        agent_class: Type[BaseAgent],
        task_description: str,
        input_data: Dict[str, Any] = None,
        sub_task_id: str = None,
        **agent_kwargs
    ) -> Dict[str, Any]:
        """
        启动子 Agent
        
        Args:
            agent_class: Agent 类
            task_description: 任务描述
            input_data: 输入数据
            sub_task_id: 子任务 ID
            **agent_kwargs: Agent 构造参数
            
        Returns:
            子 Agent 执行结果
        """
        sub_task_id = sub_task_id or f"sub_{datetime.now().strftime('%H%M%S')}_{len(self.active_sub_agents)}"
        
        async with self.semaphore:
            # 创建隔离的工作空间
            sub_workspace = self.parent_workspace.create_sub_workspace(sub_task_id)
            
            # 写入任务
            sub_workspace.write_task(task_description, input_data)
            
            # 创建子 Agent
            sub_agent = agent_class(
                workspace=sub_workspace,
                **agent_kwargs
            )
            
            self.active_sub_agents[sub_task_id] = sub_agent
            
            try:
                result = await sub_agent.run()
                self.results[sub_task_id] = result
                return result
            finally:
                del self.active_sub_agents[sub_task_id]
    
    async def spawn_parallel(
        self,
        tasks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        并行启动多个子 Agent
        
        Args:
            tasks: 任务列表，每个任务包含：
                - class: Agent 类
                - task: 任务描述
                - data: 输入数据（可选）
                - id: 子任务 ID（可选）
                
        Returns:
            所有子 Agent 的结果列表
        """
        async def run_task(task: Dict, index: int):
            return await self.spawn(
                agent_class=task["class"],
                task_description=task["task"],
                input_data=task.get("data"),
                sub_task_id=task.get("id", f"parallel_{index}"),
                **task.get("kwargs", {})
            )
        
        results = await asyncio.gather(
            *[run_task(task, i) for i, task in enumerate(tasks)],
            return_exceptions=True
        )
        
        return [
            r if not isinstance(r, Exception) else {"error": str(r)}
            for r in results
        ]
    
    async def spawn_with_retry(
        self,
        agent_class: Type[BaseAgent],
        task_description: str,
        input_data: Dict[str, Any] = None,
        max_retries: int = 3,
        **agent_kwargs
    ) -> Dict[str, Any]:
        """带重试的子 Agent 启动"""
        last_error = None
        
        for attempt in range(max_retries):
            try:
                result = await self.spawn(
                    agent_class=agent_class,
                    task_description=task_description,
                    input_data=input_data,
                    sub_task_id=f"retry_{attempt}",
                    **agent_kwargs
                )
                
                if result.get("success"):
                    return result
                
                last_error = result.get("error", "Unknown error")
                
            except Exception as e:
                last_error = str(e)
        
        return {
            "success": False,
            "error": f"重试 {max_retries} 次后仍失败: {last_error}"
        }
    
    def aggregate_results(
        self,
        aggregation_type: str = "merge"
    ) -> Dict[str, Any]:
        """
        聚合所有子 Agent 结果
        
        Args:
            aggregation_type: 聚合类型
                - "merge": 合并所有结果
                - "best": 选择最佳结果
                - "vote": 投票选择
                
        Returns:
            聚合后的结果
        """
        if not self.results:
            return {"success": False, "error": "无子 Agent 结果"}
        
        if aggregation_type == "merge":
            merged = {"success": True, "sub_results": {}}
            for task_id, result in self.results.items():
                merged["sub_results"][task_id] = result
                if not result.get("success", True):
                    merged["success"] = False
            return merged
        
        elif aggregation_type == "best":
            # 选择得分最高的结果
            best = max(
                self.results.values(),
                key=lambda r: r.get("summary", {}).get("verification", {}).get("score", 0)
            )
            return best
        
        return {"results": self.results}
```

---

## 5. YAML 工作流配置示例

```yaml
# workflows/financial_analysis.yaml

workflow_id: financial_analysis_v1
name: 金融分析工作流
description: 完整的公司投资价值分析流程
version: 1.0.0

# 全局配置
global:
  default_model: deepseek/deepseek-v3
  workspace_path: ./workspaces/financial_analysis

# 节点定义
nodes:
  - node_id: start
    name: 开始
    node_type: start

  - node_id: gather_info
    name: 信息收集
    node_type: parallel
    parallel_nodes:
      - gather_financial
      - gather_news
      - gather_research

  - node_id: gather_financial
    name: 财务数据收集
    node_type: agent
    agent_id: data_collector
    user_override: |
      收集目标公司的财务数据，包括最近4个季度的财务报表
    tools:
      - 财务数据

  - node_id: gather_news
    name: 新闻收集
    node_type: agent
    agent_id: news_collector
    user_override: |
      收集目标公司最近30天的相关新闻
    tools:
      - 新闻搜索

  - node_id: gather_research
    name: 研报收集
    node_type: agent
    agent_id: research_collector
    user_override: |
      收集目标公司的最新研究报告
    tools:
      - 研报搜索

  - node_id: analyze
    name: 综合分析
    node_type: agent
    agent_id: financial_analyst
    input_mappings:
      - source_node: gather_financial
        source_field: output.data
        target_field: input.financial_data
      - source_node: gather_news
        source_field: output.results
        target_field: input.news
      - source_node: gather_research
        source_field: output.results
        target_field: input.research
    context_refs:
      - "#gather_financial"
      - "#gather_news"
      - "#gather_research"

  - node_id: risk_check
    name: 风险检查
    node_type: condition
    condition_expression: "outputs['analyze'].get('risk_level') == '高'"

  - node_id: risk_analysis
    name: 风险深度分析
    node_type: agent
    agent_id: risk_analyst
    input_mappings:
      - source_node: analyze
        source_field: output.risk_analysis
        target_field: input.preliminary_risk

  - node_id: generate_report
    name: 生成报告
    node_type: agent
    agent_id: report_generator
    execution_type: markdown_generator
    context_refs:
      - "#analyze"
      - "#risk_analysis"

  - node_id: end
    name: 结束
    node_type: end

# 边定义
edges:
  - from_node: start
    to_node: gather_info

  - from_node: gather_info
    to_node: analyze

  - from_node: analyze
    to_node: risk_check

  - from_node: risk_check
    to_node: risk_analysis
    condition: "True"  # 高风险时执行

  - from_node: risk_check
    to_node: generate_report
    condition: "False"  # 非高风险直接生成报告

  - from_node: risk_analysis
    to_node: generate_report

  - from_node: generate_report
    to_node: end
```

---

## 6. 流式执行 (Streaming Execution)

### 6.1 设计目标

流式执行允许实时推送工作流执行事件，提供更好的用户体验和执行可见性。

| 功能 | 描述 |
|------|------|
| **实时事件推送** | 节点开始/完成/失败等事件 |
| **进度追踪** | 实时显示执行进度 |
| **增量输出** | 支持 Agent 输出的流式返回 |
| **异步回调** | 通过回调函数处理事件 |

### 6.2 核心实现

```python
# src/orchestration/workflow_engine.py

from typing import AsyncGenerator, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum


class ExecutionEventType(str, Enum):
    """执行事件类型"""
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_SKIPPED = "node_skipped"
    PROGRESS_UPDATE = "progress_update"
    CHECKPOINT_CREATED = "checkpoint_created"


@dataclass
class ExecutionEvent:
    """执行事件"""
    event_type: ExecutionEventType
    workflow_id: str
    node_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


EventCallback = Callable[[ExecutionEvent], Awaitable[None]]


class WorkflowEngine:
    """
    工作流引擎（增强版）
    
    支持：
    - 流式执行和事件推送
    - 运行时干预
    - 多模型支持
    - 上下文文件复制
    """
    
    def __init__(
        self,
        agent_registry: AgentRegistry,
        base_workspace_path: str = "./workspaces",
        event_callback: Optional[EventCallback] = None,
    ):
        self.agent_registry = agent_registry
        self.base_workspace_path = base_workspace_path
        self.event_callback = event_callback
        
        # 运行时控制
        self._pause_requested = False
        self._skip_nodes: Set[str] = set()
        self._node_input_overrides: Dict[str, Dict] = {}
        self._injected_context: Dict[str, Any] = {}
    
    async def execute_with_streaming(
        self,
        workflow: WorkflowDefinition,
        initial_input: Dict[str, Any] = None,
        task_id: str = None,
    ) -> AsyncGenerator[ExecutionEvent, None]:
        """
        流式执行工作流
        
        Args:
            workflow: 工作流定义
            initial_input: 初始输入
            task_id: 任务 ID
            
        Yields:
            执行事件流
        """
        # 发送工作流开始事件
        yield ExecutionEvent(
            event_type=ExecutionEventType.WORKFLOW_STARTED,
            workflow_id=workflow.workflow_id,
            data={"task_id": task_id, "input": initial_input},
        )
        
        try:
            # 拓扑排序获取执行顺序
            execution_order = self._topological_sort(workflow)
            total_nodes = len(execution_order)
            completed_nodes = 0
            
            state = WorkflowState(workflow.workflow_id)
            state.global_context = initial_input or {}
            
            for node_id in execution_order:
                # 检查暂停请求
                while self._pause_requested:
                    await asyncio.sleep(0.1)
                
                # 检查是否跳过
                if node_id in self._skip_nodes:
                    yield ExecutionEvent(
                        event_type=ExecutionEventType.NODE_SKIPPED,
                        workflow_id=workflow.workflow_id,
                        node_id=node_id,
                    )
                    continue
                
                node = workflow.get_node(node_id)
                
                # 发送节点开始事件
                yield ExecutionEvent(
                    event_type=ExecutionEventType.NODE_STARTED,
                    workflow_id=workflow.workflow_id,
                    node_id=node_id,
                    data={"node_name": node.name, "node_type": node.node_type},
                )
                
                try:
                    # 执行节点
                    result = await self._execute_node_with_context(
                        node=node,
                        workflow=workflow,
                        state=state,
                    )
                    
                    state.set_node_output(node_id, result)
                    state.set_node_status(node_id, NodeStatus.COMPLETED)
                    completed_nodes += 1
                    
                    # 发送节点完成事件
                    yield ExecutionEvent(
                        event_type=ExecutionEventType.NODE_COMPLETED,
                        workflow_id=workflow.workflow_id,
                        node_id=node_id,
                        data={
                            "result": result,
                            "duration_ms": result.get("duration_ms", 0),
                        },
                    )
                    
                    # 发送进度更新
                    yield ExecutionEvent(
                        event_type=ExecutionEventType.PROGRESS_UPDATE,
                        workflow_id=workflow.workflow_id,
                        data={
                            "completed": completed_nodes,
                            "total": total_nodes,
                            "progress": completed_nodes / total_nodes,
                        },
                    )
                    
                except Exception as e:
                    state.set_node_status(node_id, NodeStatus.FAILED)
                    state.node_errors[node_id] = str(e)
                    
                    yield ExecutionEvent(
                        event_type=ExecutionEventType.NODE_FAILED,
                        workflow_id=workflow.workflow_id,
                        node_id=node_id,
                        data={"error": str(e)},
                    )
                    
                    if not node.continue_on_error:
                        raise
            
            # 发送工作流完成事件
            yield ExecutionEvent(
                event_type=ExecutionEventType.WORKFLOW_COMPLETED,
                workflow_id=workflow.workflow_id,
                data={
                    "node_outputs": state.node_outputs,
                    "success": True,
                },
            )
            
        except Exception as e:
            yield ExecutionEvent(
                event_type=ExecutionEventType.WORKFLOW_FAILED,
                workflow_id=workflow.workflow_id,
                data={"error": str(e)},
            )
    
    async def _execute_node_with_context(
        self,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        state: WorkflowState,
    ) -> Dict[str, Any]:
        """执行节点（支持上下文文件复制）"""
        # 检查输入覆盖
        input_override = self._node_input_overrides.get(node.node_id, {})
        
        # 注入上下文
        if self._injected_context:
            state.global_context.update(self._injected_context)
        
        # 复制上游节点的 context 文件
        await self._copy_upstream_context(node, workflow, state)
        
        # 根据 Agent 的 llm_config 动态创建 LLM 客户端
        llm_client = self._create_llm_client_for_node(node)
        
        # 执行节点
        start_time = datetime.now()
        result = await self._execute_node(
            node=node,
            workflow=workflow,
            state=state,
            input_override=input_override,
            llm_client=llm_client,
        )
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        result["duration_ms"] = duration_ms
        return result
    
    async def _copy_upstream_context(
        self,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        state: WorkflowState,
    ):
        """复制上游节点的 context 文件到当前节点工作空间"""
        # 找到所有上游节点
        upstream_nodes = self._get_upstream_nodes(node.node_id, workflow)
        
        for upstream_id in upstream_nodes:
            upstream_workspace_path = f"{self.base_workspace_path}/{upstream_id}"
            current_workspace_path = f"{self.base_workspace_path}/{node.node_id}"
            
            # 复制 context 目录
            context_source = Path(upstream_workspace_path) / "context"
            if context_source.exists():
                context_dest = Path(current_workspace_path) / "context" / upstream_id
                shutil.copytree(context_source, context_dest, dirs_exist_ok=True)
    
    def _topological_sort(self, workflow: WorkflowDefinition) -> List[str]:
        """拓扑排序获取执行顺序"""
        # ... 实现拓扑排序 ...
        pass
```

### 6.3 使用示例

```python
from orchestration import WorkflowEngine, ExecutionEventType

# 创建工作流引擎
engine = WorkflowEngine(agent_registry)

# 流式执行
async for event in engine.execute_with_streaming(
    workflow=workflow_def,
    initial_input={"company": "贵州茅台"},
):
    if event.event_type == ExecutionEventType.NODE_STARTED:
        print(f"开始执行节点: {event.node_id}")
    elif event.event_type == ExecutionEventType.NODE_COMPLETED:
        print(f"节点完成: {event.node_id}, 耗时: {event.data['duration_ms']}ms")
    elif event.event_type == ExecutionEventType.PROGRESS_UPDATE:
        print(f"进度: {event.data['progress']:.1%}")
```

---

## 7. 运行时干预机制

### 7.1 设计目标

运行时干预允许在工作流执行过程中进行控制和调整。

| 功能 | 描述 |
|------|------|
| **暂停/恢复** | 暂停工作流执行，稍后恢复 |
| **跳过节点** | 跳过特定节点的执行 |
| **修改输入** | 动态修改节点的输入数据 |
| **注入上下文** | 在运行时注入额外上下文 |

### 7.2 核心实现

```python
class WorkflowEngine:
    """工作流引擎（运行时干预）"""
    
    # === 暂停/恢复 ===
    
    def pause(self):
        """请求暂停执行"""
        self._pause_requested = True
    
    def resume(self):
        """恢复执行"""
        self._pause_requested = False
    
    def is_paused(self) -> bool:
        """检查是否暂停"""
        return self._pause_requested
    
    # === 跳过节点 ===
    
    def skip_node(self, node_id: str):
        """标记节点跳过"""
        self._skip_nodes.add(node_id)
    
    def unskip_node(self, node_id: str):
        """取消跳过标记"""
        self._skip_nodes.discard(node_id)
    
    def get_skipped_nodes(self) -> Set[str]:
        """获取跳过的节点列表"""
        return self._skip_nodes.copy()
    
    # === 修改输入 ===
    
    def override_node_input(
        self,
        node_id: str,
        input_data: Dict[str, Any],
        merge: bool = True,
    ):
        """
        覆盖节点输入
        
        Args:
            node_id: 节点 ID
            input_data: 输入数据
            merge: 是否与原输入合并
        """
        if merge and node_id in self._node_input_overrides:
            self._node_input_overrides[node_id].update(input_data)
        else:
            self._node_input_overrides[node_id] = input_data
    
    def clear_node_input_override(self, node_id: str):
        """清除节点输入覆盖"""
        self._node_input_overrides.pop(node_id, None)
    
    # === 注入上下文 ===
    
    def inject_context(self, key: str, value: Any):
        """注入上下文"""
        self._injected_context[key] = value
    
    def inject_contexts(self, contexts: Dict[str, Any]):
        """批量注入上下文"""
        self._injected_context.update(contexts)
    
    def clear_injected_context(self):
        """清除注入的上下文"""
        self._injected_context.clear()
    
    # === 检查点 ===
    
    async def create_checkpoint(
        self,
        state: WorkflowState,
        name: str = None,
    ) -> WorkflowCheckpoint:
        """
        创建检查点
        
        Args:
            state: 当前工作流状态
            name: 检查点名称
            
        Returns:
            检查点对象
        """
        checkpoint = WorkflowCheckpoint(
            checkpoint_id=f"{state.workflow_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            workflow_id=state.workflow_id,
            name=name or f"检查点_{len(state.checkpoints) + 1}",
            node_states=state.node_states.copy(),
            node_outputs=state.node_outputs.copy(),
            global_context=state.global_context.copy(),
            created_at=datetime.now(),
        )
        
        state.checkpoints.append(checkpoint)
        return checkpoint
    
    async def restore_from_checkpoint(
        self,
        state: WorkflowState,
        checkpoint_id: str,
    ) -> bool:
        """
        从检查点恢复
        
        Args:
            state: 工作流状态
            checkpoint_id: 检查点 ID
            
        Returns:
            是否成功恢复
        """
        checkpoint = next(
            (c for c in state.checkpoints if c.checkpoint_id == checkpoint_id),
            None
        )
        
        if not checkpoint:
            return False
        
        state.node_states = checkpoint.node_states.copy()
        state.node_outputs = checkpoint.node_outputs.copy()
        state.global_context = checkpoint.global_context.copy()
        
        return True
```

### 7.3 使用示例

```python
import asyncio
from orchestration import WorkflowEngine

engine = WorkflowEngine(agent_registry)

# 启动执行（在后台）
async def run_workflow():
    async for event in engine.execute_with_streaming(workflow, input_data):
        handle_event(event)

task = asyncio.create_task(run_workflow())

# 运行时干预
await asyncio.sleep(5)
engine.pause()  # 暂停执行

# 修改某个节点的输入
engine.override_node_input(
    "analysis_node",
    {"additional_data": "补充信息"}
)

# 跳过某个节点
engine.skip_node("optional_node")

# 注入额外上下文
engine.inject_context("user_feedback", "请更详细地分析风险")

# 恢复执行
engine.resume()

# 等待完成
await task
```

---

## 8. 多模型支持

### 8.1 设计目标

支持在同一工作流中使用不同的 LLM 模型，根据 Agent 配置动态选择。

### 8.2 实现方式

```python
class WorkflowEngine:
    """工作流引擎（多模型支持）"""
    
    def __init__(self, ...):
        # LLM 客户端缓存
        self._llm_clients: Dict[str, Any] = {}
    
    def _create_llm_client_for_node(
        self,
        node: WorkflowNode,
    ) -> Any:
        """
        根据节点配置创建 LLM 客户端
        
        支持：
        - 按 Agent 定义的 model_config
        - 按节点级别的 model_override
        - 客户端复用（缓存）
        """
        # 获取 Agent 定义
        agent_def = self.agent_registry.get_definition(node.agent_id)
        
        # 确定模型配置
        model_name = node.model_override or agent_def.model_config.model_name
        temperature = agent_def.model_config.temperature
        max_tokens = agent_def.model_config.max_tokens
        
        # 构建缓存键
        cache_key = f"{model_name}_{temperature}_{max_tokens}"
        
        # 复用或创建客户端
        if cache_key not in self._llm_clients:
            self._llm_clients[cache_key] = self._create_client(
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        
        return self._llm_clients[cache_key]
    
    def _create_client(
        self,
        model_name: str,
        temperature: float,
        max_tokens: int,
    ) -> Any:
        """创建 LLM 客户端"""
        # 根据模型名称选择客户端类型
        if model_name.startswith("claude"):
            from utils.claude_client import ClaudeClient
            return ClaudeClient(
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            from utils.llm_client import UnifiedLLMClient
            return UnifiedLLMClient(
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )
```

### 8.3 配置示例

```yaml
# 工作流中不同节点使用不同模型
nodes:
  - node_id: quick_analysis
    agent_id: fast_analyzer
    model_override: "claude-3-haiku"  # 快速但便宜
    
  - node_id: deep_analysis
    agent_id: deep_analyzer
    model_override: "claude-sonnet-4-20250514"  # 深度分析
    
  - node_id: report_generation
    agent_id: report_writer
    # 使用 Agent 定义中的默认模型
```


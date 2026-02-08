"""
工作流引擎

负责工作流的执行和管理，支持：
- DAG（有向无环图）工作流执行
- 节点并行执行
- 条件分支
- 错误处理和重试
- 检查点恢复
"""

from typing import Dict, Any, Optional, List, Set, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from pathlib import Path
import asyncio
import shutil
import uuid

from src.utils.logger import get_logger

from ..definitions import WorkflowDefinition, WorkflowNode, NodeType, ModelConfig
from ..registry import AgentRegistry
from ..tools import ToolRegistry
from ..workspace import AgentWorkspace, WorkspaceConfig
from ..config import get_model_registry
from ..core.context_provider import RuntimeContextProvider
from ..exceptions import (
    WorkflowError,
    WorkflowNodeError,
    WorkflowCycleError,
)
from ..interfaces.workflow import (
    IWorkflowEngine,
    IWorkflowResult,
    WorkflowStatus,
)
from .execution_fsm import (
    ExecutionFSM,
    ExecutionState,
    ExecutionEvent,
    InvalidTransitionError,
)
from ..utils.safe_eval import safe_eval_condition, safe_eval_expression
from .events import (
    ExecutionEventType,
    EXECUTION_EVENT_TYPES,
    EventSequenceGenerator,
    generate_event_id,
)

logger = get_logger()

# 事件历史缓存的最大大小（每个工作流）
MAX_EVENT_HISTORY_SIZE = 100


class StreamBatcher:
    """将流式 token 按间隔或最小字符数批量发送，避免前端收到过于频繁的事件"""

    def __init__(
        self,
        flush_callback: Callable[[str, str], Awaitable[None]],
        interval: float = 0.1,
        min_chars: int = 20,
    ):
        self._flush_callback = flush_callback
        self._interval = interval
        self._min_chars = min_chars
        self._buffer: Dict[str, str] = {}  # type -> accumulated content
        self._last_flush: Dict[str, float] = {}
        self._flush_task: Optional[asyncio.Task] = None

    async def add(self, chunk_type: str, content: str) -> None:
        if not content:
            return
        self._buffer[chunk_type] = self._buffer.get(chunk_type, "") + content
        self._last_flush[chunk_type] = asyncio.get_event_loop().time()
        if len(self._buffer[chunk_type]) >= self._min_chars:
            await self._flush(chunk_type)

    async def _flush(self, chunk_type: str) -> None:
        text = self._buffer.pop(chunk_type, "")
        self._last_flush.pop(chunk_type, None)
        if text:
            await self._flush_callback(chunk_type, text)

    async def flush_all(self) -> None:
        for chunk_type in list(self._buffer.keys()):
            await self._flush(chunk_type)


@dataclass
class NodeExecutionResult:
    """节点执行结果"""

    node_id: str
    status: str  # "success", "failed", "skipped"
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class WorkflowResult:
    """工作流执行结果"""

    workflow_id: str
    status: WorkflowStatus
    node_results: Dict[str, NodeExecutionResult] = field(default_factory=dict)
    final_output: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    total_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "node_results": {
                k: {
                    "node_id": v.node_id,
                    "status": v.status,
                    "output": v.output,
                    "error": v.error,
                    "duration_ms": v.duration_ms,
                }
                for k, v in self.node_results.items()
            },
            "final_output": self.final_output,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_ms": self.total_duration_ms,
        }


@dataclass
class WorkflowCheckpoint:
    """工作流检查点"""

    checkpoint_id: str
    workflow_id: str
    workflow_definition_id: str
    status: WorkflowStatus
    node_results: Dict[str, NodeExecutionResult]
    node_outputs: Dict[str, Any]
    pending_nodes: List[str]
    context: Dict[str, Any]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "workflow_id": self.workflow_id,
            "workflow_definition_id": self.workflow_definition_id,
            "status": self.status.value,
            "node_results": {
                k: {
                    "node_id": v.node_id,
                    "status": v.status,
                    "output": v.output,
                    "error": v.error,
                    "duration_ms": v.duration_ms,
                    "started_at": v.started_at,
                    "completed_at": v.completed_at,
                }
                for k, v in self.node_results.items()
            },
            "node_outputs": self.node_outputs,
            "pending_nodes": self.pending_nodes,
            "context": self.context,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowCheckpoint":
        node_results = {}
        for k, v in data.get("node_results", {}).items():
            node_results[k] = NodeExecutionResult(
                node_id=v["node_id"],
                status=v["status"],
                output=v.get("output"),
                error=v.get("error"),
                duration_ms=v.get("duration_ms", 0.0),
                started_at=v.get("started_at"),
                completed_at=v.get("completed_at"),
            )

        return cls(
            checkpoint_id=data["checkpoint_id"],
            workflow_id=data["workflow_id"],
            workflow_definition_id=data["workflow_definition_id"],
            status=WorkflowStatus(data["status"]),
            node_results=node_results,
            node_outputs=data.get("node_outputs", {}),
            pending_nodes=data.get("pending_nodes", []),
            context=data.get("context", {}),
            created_at=data["created_at"],
        )


class WorkflowEngine(IWorkflowEngine):
    """
    工作流引擎

    支持 DAG 工作流的执行，包括：
    - Agent 节点执行
    - 工具节点执行
    - 并行节点执行
    - 条件分支
    - 聚合节点
    - 检查点保存和恢复
    """

    def __init__(
        self,
        agent_registry: Optional[AgentRegistry] = None,
        tool_registry: Optional[ToolRegistry] = None,
        llm_client: Any = None,
        workspace_base_path: str = "/tmp/agent_workflows",
        auto_checkpoint: bool = True,
        checkpoint_interval: int = 1,  # 每执行几个节点保存一次检查点
        app_workflow_config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化工作流引擎

        Args:
            agent_registry: Agent 注册表
            tool_registry: 工具注册表
            llm_client: LLM 客户端
            workspace_base_path: 工作空间基础路径
            auto_checkpoint: 是否自动保存检查点
            checkpoint_interval: 检查点保存间隔（节点数）
            app_workflow_config: 应用层工作流配置（来自 app_config.yaml 的 workflow 部分）
        """
        self.agent_registry = agent_registry or AgentRegistry.get_default()
        self.tool_registry = tool_registry or ToolRegistry.get_default()
        self.llm_client = llm_client  # 默认 LLM 客户端（向后兼容）
        self.workspace_base_path = workspace_base_path
        self.auto_checkpoint = auto_checkpoint
        self.checkpoint_interval = checkpoint_interval

        # 应用层工作流配置（从 app_config.yaml 加载）
        self._app_workflow_config = app_workflow_config or {}

        # 运行中的工作流状态（通过 FSM 管理）
        self._execution_fsms: Dict[str, ExecutionFSM] = {}
        self._workflow_results: Dict[str, WorkflowResult] = {}

        # 工作流定义缓存（用于恢复）
        self._workflow_definitions: Dict[str, WorkflowDefinition] = {}

        # LLM 客户端缓存（按模型名缓存）
        self._llm_client_cache: Dict[str, Any] = {}

        # === 流式执行支持 ===
        # 跳过节点: workflow_id -> Set[node_id]
        self._skip_nodes: Dict[str, Set[str]] = {}
        # 节点输入修改: workflow_id -> {node_id: new_input}
        self._modified_inputs: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # 注入的上下文: workflow_id -> context
        self._injected_context: Dict[str, Dict[str, Any]] = {}
        # 事件回调: workflow_id -> callback
        self._event_callbacks: Dict[str, Callable] = {}

        # === 事件追踪支持 ===
        # 事件序列号生成器
        self._event_sequence = EventSequenceGenerator()
        # 事件历史缓存: workflow_id -> List[event]
        self._event_history: Dict[str, List[Dict[str, Any]]] = {}

    def _get_or_create_llm_client(self, llm_config: ModelConfig) -> Any:
        """
        根据 Agent 的 llm_config 获取或创建对应的 LLM 客户端

        优先级：
        1. 如果 llm_config.model_name 在 ModelRegistry 中配置，使用对应配置创建客户端
        2. 否则回退到 WorkflowEngine 的默认 llm_client

        Args:
            llm_config: Agent 定义中的模型配置

        Returns:
            LLM 客户端实例
        """
        model_name = llm_config.model_name if llm_config else None

        # 如果没有指定模型名，使用默认客户端
        if not model_name:
            if self.llm_client:
                return self.llm_client
            # 使用 ModelRegistry 的默认模型
            model_name = get_model_registry().get_default_model()

        # 检查缓存
        if model_name in self._llm_client_cache:
            return self._llm_client_cache[model_name]

        # 尝试从 ModelRegistry 创建客户端
        try:
            model_registry = get_model_registry()
            client = model_registry.create_client(
                model_name=model_name,
                client_type="langchain",
                use_cache=False,  # 我们自己管理缓存
            )
            self._llm_client_cache[model_name] = client
            logger.info(f"✅ 为 Agent 创建 LLM 客户端: {model_name}")
            return client
        except ValueError as e:
            # 模型未配置，回退到默认客户端
            logger.warning(f"模型 {model_name} 未配置，使用默认客户端: {e}")
            if self.llm_client:
                return self.llm_client
            # 使用 ModelRegistry 的默认模型
            default_model = model_registry.get_default_model()
            client = model_registry.create_client(default_model, "langchain")
            self._llm_client_cache[model_name] = client
            return client

    async def execute(
        self,
        workflow_definition: WorkflowDefinition,
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> WorkflowResult:
        """
        执行工作流

        Args:
            workflow_definition: 工作流定义
            initial_context: 初始上下文

        Returns:
            工作流执行结果
        """
        workflow_id = f"{workflow_definition.workflow_id}_{uuid.uuid4().hex[:8]}"
        started_at = datetime.now()

        logger.info(f"开始执行工作流: {workflow_id}")

        # 创建 FSM 并启动
        fsm = ExecutionFSM(workflow_id)
        self._execution_fsms[workflow_id] = fsm
        fsm.transition_sync(ExecutionEvent.START)

        # 初始化结果
        result = WorkflowResult(
            workflow_id=workflow_id,
            status=WorkflowStatus.RUNNING,
            started_at=started_at.isoformat(),
        )

        self._workflow_results[workflow_id] = result

        try:
            # 验证工作流（检查循环依赖）
            self._validate_workflow(workflow_definition)

            # 获取工作流的配置
            domain = getattr(workflow_definition, "domain", "general")
            timezone = getattr(workflow_definition, "timezone", "Asia/Shanghai")
            runtime_context_injection = getattr(
                workflow_definition, "runtime_context_injection", True
            )

            # 初始化基础上下文
            context = {
                "workflow_id": workflow_id,
                "global_context": workflow_definition.global_context or {},
                **(initial_context or {}),
            }

            # 根据配置决定是否注入运行时上下文
            total_nodes = len(workflow_definition.nodes)
            if runtime_context_injection:
                # 创建运行时上下文提供器
                context_provider = RuntimeContextProvider(
                    domain=domain,
                    timezone=timezone,
                    workflow_id=workflow_id,
                    execution_id=workflow_id,
                )

                # 获取并注入运行时上下文
                runtime_context = context_provider.get_runtime_context_dict()
                runtime_context["_runtime"]["total_nodes"] = total_nodes
                runtime_context["_runtime"]["started_at"] = datetime.now().isoformat()
                context.update(runtime_context)
            else:
                # 即使不注入完整运行时上下文，也提供基本的进度信息
                context["_runtime"] = {
                    "total_nodes": total_nodes,
                    "started_at": datetime.now().isoformat(),
                }

            # 构建 DAG 并获取拓扑排序
            execution_order = self._topological_sort(workflow_definition)

            # 按拓扑顺序执行节点
            node_outputs: Dict[str, Any] = {}
            nodes_executed = 0

            # 保存工作流定义用于恢复
            self._workflow_definitions[workflow_definition.workflow_id] = (
                workflow_definition
            )

            for node_index, node_id in enumerate(execution_order):
                # 检查取消标志（通过 FSM）
                if fsm.state == ExecutionState.CANCELLED:
                    result.status = WorkflowStatus.CANCELLED
                    result.error = "工作流被取消"
                    break

                # 检查暂停标志（通过 FSM）— 非流式路径也支持暂停
                if fsm.state == ExecutionState.PAUSED:
                    await fsm.pause_event.wait()
                    # 唤醒后检查是否在暂停期间被取消
                    if fsm.state == ExecutionState.CANCELLED:
                        result.status = WorkflowStatus.CANCELLED
                        result.error = "工作流被取消"
                        break

                node = self._get_node(workflow_definition, node_id)
                if not node:
                    continue

                # 更新运行时上下文：当前节点进度
                if "_runtime" in context:
                    context["_runtime"]["current_node_index"] = node_index
                    context["_runtime"]["current_node_id"] = node_id
                    context["_runtime"]["completed_nodes"] = nodes_executed
                    if total_nodes > 0:
                        context["_runtime"]["progress_percentage"] = round(
                            nodes_executed / total_nodes * 100, 1
                        )

                # 检查依赖是否都已完成
                dependencies_met = self._check_dependencies(node, result.node_results)

                if not dependencies_met:
                    result.node_results[node_id] = NodeExecutionResult(
                        node_id=node_id, status="skipped", error="依赖节点未成功完成"
                    )
                    continue

                # 执行节点
                node_result = await self._execute_node(
                    node=node,
                    context=context,
                    node_outputs=node_outputs,
                    workflow_definition=workflow_definition,
                )

                result.node_results[node_id] = node_result
                nodes_executed += 1

                if node_result.status == "success":
                    node_outputs[node_id] = node_result.output
                elif node_result.status == "failed":
                    # 节点失败，检查是否继续
                    if not workflow_definition.continue_on_error:
                        result.status = WorkflowStatus.FAILED
                        result.error = f"节点 {node_id} 执行失败: {node_result.error}"
                        break

                # 自动保存检查点
                if (
                    self.auto_checkpoint
                    and nodes_executed % self.checkpoint_interval == 0
                ):
                    remaining_nodes = [
                        n
                        for n in execution_order
                        if n not in result.node_results
                        or result.node_results[n].status
                        not in ("success", "failed", "skipped")
                    ]
                    if remaining_nodes:  # 还有未完成的节点才保存检查点
                        await self._save_checkpoint(
                            workflow_id=workflow_id,
                            workflow_definition=workflow_definition,
                            result=result,
                            node_outputs=node_outputs,
                            pending_nodes=remaining_nodes,
                            context=context,
                        )

            # 确定最终状态
            if result.status == WorkflowStatus.RUNNING:
                # 检查是否所有必需节点都成功
                exit_node_id = workflow_definition.exit_point
                if exit_node_id and exit_node_id in result.node_results:
                    exit_result = result.node_results[exit_node_id]
                    if exit_result.status == "success":
                        result.status = WorkflowStatus.COMPLETED
                        result.final_output = exit_result.output
                    else:
                        result.status = WorkflowStatus.FAILED
                        result.error = f"出口节点 {exit_node_id} 未成功完成"
                else:
                    # 所有节点执行完成
                    result.status = WorkflowStatus.COMPLETED
                    # 收集所有输出
                    result.final_output = node_outputs

        except WorkflowCycleError as e:
            result.status = WorkflowStatus.FAILED
            result.error = str(e)
        except Exception as e:
            result.status = WorkflowStatus.FAILED
            result.error = f"工作流执行异常: {str(e)}"
            logger.exception(f"工作流 {workflow_id} 执行异常")

        finally:
            # 更新 FSM 到终态（如果尚未到达终态）
            if not fsm.is_terminal:
                if result.status == WorkflowStatus.COMPLETED:
                    fsm.transition_sync(ExecutionEvent.COMPLETE)
                elif result.status == WorkflowStatus.FAILED:
                    fsm.transition_sync(ExecutionEvent.FAIL)
                elif result.status == WorkflowStatus.CANCELLED:
                    try:
                        fsm.transition_sync(ExecutionEvent.STOP)
                    except InvalidTransitionError:
                        pass  # 可能已经被外部取消

            # 清理
            completed_at = datetime.now()
            result.completed_at = completed_at.isoformat()
            result.total_duration_ms = (
                completed_at - started_at
            ).total_seconds() * 1000

            self._workflow_results[workflow_id] = result

        logger.info(
            f"工作流 {workflow_id} 执行完成: {result.status.value}, "
            f"耗时 {result.total_duration_ms:.2f}ms"
        )

        return result

    async def cancel(self, workflow_id: str) -> bool:
        """取消工作流执行"""
        fsm = self._execution_fsms.get(workflow_id)
        if fsm and fsm.can_transition(ExecutionEvent.STOP):
            try:
                await fsm.transition(ExecutionEvent.STOP)
                return True
            except InvalidTransitionError:
                return False
        return False

    # ========== 流式执行支持 ==========

    async def execute_with_streaming(
        self,
        workflow_definition: WorkflowDefinition,
        initial_context: Optional[Dict[str, Any]] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> WorkflowResult:
        """
        执行工作流并实时推送事件

        与 execute() 类似，但会在执行过程中通过回调推送事件。

        Args:
            workflow_definition: 工作流定义
            initial_context: 初始上下文
            event_callback: 事件回调函数，接收事件字典

        Returns:
            工作流执行结果
        """
        workflow_id = f"{workflow_definition.workflow_id}_{uuid.uuid4().hex[:8]}"
        started_at = datetime.now()

        logger.info(f"开始流式执行工作流: {workflow_id}")

        # 创建 FSM 并启动
        fsm = ExecutionFSM(workflow_id)
        self._execution_fsms[workflow_id] = fsm
        fsm.transition_sync(ExecutionEvent.START)

        # 注册事件回调
        if event_callback:
            self._event_callbacks[workflow_id] = event_callback

        # 初始化控制状态
        self._skip_nodes[workflow_id] = set()
        self._modified_inputs[workflow_id] = {}
        self._injected_context[workflow_id] = {}

        # 推送工作流开始事件
        await self._emit_event(
            workflow_id,
            {
                "event_type": "workflow_started",
                "workflow_id": workflow_id,
                "timestamp": started_at.isoformat(),
                "data": {
                    "total_nodes": len(workflow_definition.nodes),
                    "workflow_name": workflow_definition.name,
                },
            },
        )

        # 初始化结果
        result = WorkflowResult(
            workflow_id=workflow_id,
            status=WorkflowStatus.RUNNING,
            started_at=started_at.isoformat(),
        )

        self._workflow_results[workflow_id] = result

        # Initialize variables before try block so they're accessible in finally
        context: Dict[str, Any] = {
            "workflow_id": workflow_id,
            "global_context": workflow_definition.global_context or {},
            **(initial_context or {}),
        }
        node_outputs: Dict[str, Any] = {}

        try:
            # 验证工作流
            self._validate_workflow(workflow_definition)

            # 构建 DAG 并获取拓扑排序
            execution_order = self._topological_sort(workflow_definition)

            # 保存工作流定义用于恢复
            self._workflow_definitions[workflow_definition.workflow_id] = (
                workflow_definition
            )

            # 按拓扑顺序执行节点
            nodes_executed = 0
            total_nodes = len(execution_order)

            for node_id in execution_order:
                # 检查取消标志（通过 FSM）
                if fsm.state == ExecutionState.CANCELLED:
                    result.status = WorkflowStatus.CANCELLED
                    result.error = "工作流被取消"

                    # 构建已完成节点的结果数据（用于前端持久化显示）
                    node_name_map = {
                        node.node_id: node.name for node in workflow_definition.nodes
                    }
                    cancelled_node_results = {}
                    for nid, nr in result.node_results.items():
                        output_summary, output_narrative, output_highlights = (
                            self._extract_narrative_fields(
                                nr.output if isinstance(nr.output, dict) else None
                            )
                        )
                        output_preview = self._truncate_output(
                            nr.output, max_length=100
                        )
                        if isinstance(output_preview, dict):
                            output_preview = str(output_preview)[:100]
                        # 使用用户可见输出（与 node_completed 事件保持一致）
                        user_facing_output = self._extract_user_facing_output(nr.output)
                        cancelled_node_results[nid] = {
                            "node_name": node_name_map.get(nid, nid),
                            "status": nr.status,
                            "duration_ms": nr.duration_ms,
                            "output": user_facing_output,
                            "output_preview": output_preview,
                            "output_summary": output_summary,
                            "output_narrative": output_narrative,
                            "output_highlights": output_highlights,
                            "error": nr.error,
                        }

                    await self._emit_event(
                        workflow_id,
                        {
                            "event_type": "workflow_cancelled",
                            "workflow_id": workflow_id,
                            "timestamp": datetime.now().isoformat(),
                            "data": {
                                "status": "cancelled",
                                "node_results": cancelled_node_results,
                                "total_duration_ms": (
                                    datetime.now() - started_at
                                ).total_seconds()
                                * 1000,
                                "nodes_completed": len(
                                    [
                                        r
                                        for r in result.node_results.values()
                                        if r.status == "success"
                                    ]
                                ),
                                "total_nodes": len(execution_order),
                            },
                        },
                    )
                    break

                # 检查暂停标志（通过 FSM）
                if fsm.state == ExecutionState.PAUSED:
                    await self._emit_event(
                        workflow_id,
                        {
                            "event_type": "workflow_paused",
                            "workflow_id": workflow_id,
                            "timestamp": datetime.now().isoformat(),
                        },
                    )
                    # 等待恢复（或取消）
                    await fsm.pause_event.wait()
                    # 关键修复：唤醒后先检查是否在暂停期间被取消
                    # 避免先发 workflow_resumed 再发 workflow_cancelled 的事件闪烁
                    if fsm.state == ExecutionState.CANCELLED:
                        result.status = WorkflowStatus.CANCELLED
                        result.error = "工作流在暂停期间被取消"
                        break
                    await self._emit_event(
                        workflow_id,
                        {
                            "event_type": "workflow_resumed",
                            "workflow_id": workflow_id,
                            "timestamp": datetime.now().isoformat(),
                        },
                    )

                # 合并注入的上下文
                if self._injected_context.get(workflow_id):
                    context.update(self._injected_context[workflow_id])
                    self._injected_context[workflow_id] = {}

                node = self._get_node(workflow_definition, node_id)
                if not node:
                    continue

                # 检查是否需要跳过
                if node_id in self._skip_nodes.get(workflow_id, set()):
                    result.node_results[node_id] = NodeExecutionResult(
                        node_id=node_id,
                        status="skipped",
                        error="用户请求跳过",
                    )
                    await self._emit_event(
                        workflow_id,
                        {
                            "event_type": "node_skipped",
                            "workflow_id": workflow_id,
                            "node_id": node_id,
                            "node_name": node.name,
                            "timestamp": datetime.now().isoformat(),
                        },
                    )
                    continue

                # 检查依赖是否都已完成
                dependencies_met = self._check_dependencies(node, result.node_results)

                if not dependencies_met:
                    result.node_results[node_id] = NodeExecutionResult(
                        node_id=node_id,
                        status="skipped",
                        error="依赖节点未成功完成",
                    )
                    continue

                # 推送节点开始事件
                node_start_time = datetime.now()
                await self._emit_event(
                    workflow_id,
                    {
                        "event_type": "node_started",
                        "workflow_id": workflow_id,
                        "node_id": node_id,
                        "node_name": node.name,
                        "timestamp": node_start_time.isoformat(),
                        "data": {
                            "progress": nodes_executed / total_nodes * 100,
                        },
                    },
                )

                # 检查是否有修改的输入
                modified_input = self._modified_inputs.get(workflow_id, {}).get(node_id)

                # 执行节点
                node_result = await self._execute_node(
                    node=node,
                    context=context,
                    node_outputs=node_outputs,
                    workflow_definition=workflow_definition,
                    workflow_id=workflow_id,  # 传递 workflow_id 用于事件
                    modified_input=modified_input,
                )

                result.node_results[node_id] = node_result
                nodes_executed += 1

                # 推送节点完成事件
                if node_result.status == "success":
                    node_outputs[node_id] = node_result.output
                    out_summary, out_narrative, out_highlights = (
                        self._extract_narrative_fields(node_result.output)
                    )
                    # 提取用户可见的输出（过滤技术字段）
                    user_facing_output = self._extract_user_facing_output(
                        node_result.output
                    )
                    data_payload = {
                        "duration_ms": node_result.duration_ms,
                        "output_preview": self._truncate_output(user_facing_output),
                        "output_summary": out_summary
                        or self._generate_output_summary(user_facing_output),
                        "output": user_facing_output,
                    }
                    if out_narrative is not None:
                        data_payload["output_narrative"] = out_narrative
                    if out_highlights is not None:
                        data_payload["output_highlights"] = out_highlights
                    await self._emit_event(
                        workflow_id,
                        {
                            "event_type": "node_completed",
                            "workflow_id": workflow_id,
                            "node_id": node_id,
                            "node_name": node.name,
                            "timestamp": datetime.now().isoformat(),
                            "data": data_payload,
                        },
                    )
                elif node_result.status == "failed":
                    await self._emit_event(
                        workflow_id,
                        {
                            "event_type": "node_failed",
                            "workflow_id": workflow_id,
                            "node_id": node_id,
                            "node_name": node.name,
                            "timestamp": datetime.now().isoformat(),
                            "data": {
                                "error": node_result.error,
                            },
                        },
                    )

                    if not workflow_definition.continue_on_error:
                        result.status = WorkflowStatus.FAILED
                        result.error = f"节点 {node_id} 执行失败: {node_result.error}"
                        break

                # 推送进度更新
                await self._emit_event(
                    workflow_id,
                    {
                        "event_type": "progress_update",
                        "workflow_id": workflow_id,
                        "timestamp": datetime.now().isoformat(),
                        "data": {
                            "nodes_completed": nodes_executed,
                            "total_nodes": total_nodes,
                            "progress": nodes_executed / total_nodes * 100,
                        },
                    },
                )

            # 确定最终状态
            if result.status == WorkflowStatus.RUNNING:
                exit_node_id = workflow_definition.exit_point
                if exit_node_id and exit_node_id in result.node_results:
                    exit_result = result.node_results[exit_node_id]
                    if exit_result.status == "success":
                        result.status = WorkflowStatus.COMPLETED
                        result.final_output = exit_result.output
                    else:
                        result.status = WorkflowStatus.FAILED
                        result.error = f"出口节点 {exit_node_id} 未成功完成"
                else:
                    result.status = WorkflowStatus.COMPLETED
                    result.final_output = node_outputs

        except WorkflowCycleError as e:
            result.status = WorkflowStatus.FAILED
            result.error = str(e)
        except Exception as e:
            result.status = WorkflowStatus.FAILED
            result.error = f"工作流执行异常: {str(e)}"
            logger.exception(f"工作流 {workflow_id} 执行异常")

        finally:
            # 更新 FSM 到终态（如果尚未到达终态）
            if not fsm.is_terminal:
                if result.status == WorkflowStatus.COMPLETED:
                    fsm.transition_sync(ExecutionEvent.COMPLETE)
                elif result.status == WorkflowStatus.FAILED:
                    fsm.transition_sync(ExecutionEvent.FAIL)
                elif result.status == WorkflowStatus.CANCELLED:
                    try:
                        fsm.transition_sync(ExecutionEvent.STOP)
                    except InvalidTransitionError:
                        pass  # 可能已经被外部取消

            # 清理
            completed_at = datetime.now()
            result.completed_at = completed_at.isoformat()
            result.total_duration_ms = (
                completed_at - started_at
            ).total_seconds() * 1000

            self._workflow_results[workflow_id] = result

            # 构建节点结果列表（用于前端持久化显示）
            # 从 workflow_definition 获取节点名称映射
            node_name_map = {
                node.node_id: node.name for node in workflow_definition.nodes
            }
            node_results_for_event = {}
            for node_id, node_result in result.node_results.items():
                # 从节点输出中提取摘要信息
                output_summary, output_narrative, output_highlights = (
                    self._extract_narrative_fields(
                        node_result.output
                        if isinstance(node_result.output, dict)
                        else None
                    )
                )
                # 生成输出预览
                output_preview = self._truncate_output(
                    node_result.output, max_length=100
                )
                if isinstance(output_preview, dict):
                    output_preview = str(output_preview)[:100]

                # 使用用户可见输出（与 node_completed 事件保持一致）
                user_facing_output = self._extract_user_facing_output(
                    node_result.output
                )

                node_results_for_event[node_id] = {
                    "node_name": node_name_map.get(node_id, node_id),
                    "status": node_result.status,
                    "duration_ms": node_result.duration_ms,
                    "output": user_facing_output,
                    "output_preview": output_preview,
                    "output_summary": output_summary,
                    "output_narrative": output_narrative,
                    "output_highlights": output_highlights,
                    "error": node_result.error,
                }

            # 推送完成事件
            if result.status == WorkflowStatus.COMPLETED:
                final_out = result.final_output
                final_summary, final_narrative, final_highlights = (
                    self._extract_narrative_fields(
                        final_out if isinstance(final_out, dict) else None
                    )
                )
                data_payload = {
                    "status": "completed",
                    "total_duration_ms": result.total_duration_ms,
                    "nodes_completed": len(
                        [
                            r
                            for r in result.node_results.values()
                            if r.status == "success"
                        ]
                    ),
                    "total_nodes": len(result.node_results),
                    "final_output": result.final_output,
                    "node_results": node_results_for_event,  # 添加节点结果用于持久化
                }
                if final_narrative is not None:
                    data_payload["final_narrative"] = final_narrative
                if final_highlights is not None:
                    data_payload["final_highlights"] = final_highlights
                if final_summary is not None and final_narrative is None:
                    data_payload["final_narrative"] = final_summary
                await self._emit_event(
                    workflow_id,
                    {
                        "event_type": "workflow_completed",
                        "workflow_id": workflow_id,
                        "status": "completed",
                        "timestamp": completed_at.isoformat(),
                        "data": data_payload,
                    },
                )
            elif result.status == WorkflowStatus.FAILED:
                await self._emit_event(
                    workflow_id,
                    {
                        "event_type": "workflow_failed",
                        "workflow_id": workflow_id,
                        "status": "failed",  # 添加明确的 status 字段
                        "timestamp": completed_at.isoformat(),
                        "data": {
                            "status": "failed",  # 同时在 data 中也添加
                            "error": result.error,
                            "failed_node": next(
                                (
                                    k
                                    for k, v in result.node_results.items()
                                    if v.status == "failed"
                                ),
                                None,
                            ),
                            "node_results": node_results_for_event,  # 添加节点结果用于持久化
                            "total_duration_ms": result.total_duration_ms,
                            "nodes_completed": len(
                                [
                                    r
                                    for r in result.node_results.values()
                                    if r.status == "success"
                                ]
                            ),
                            "total_nodes": len(result.node_results),
                        },
                    },
                )

            # 清理控制状态
            self._cleanup_streaming_state(workflow_id)

            # Save final checkpoint with completed status for execution history
            try:
                await self._save_checkpoint(
                    workflow_id=workflow_id,
                    workflow_definition=workflow_definition,
                    result=result,
                    node_outputs=node_outputs,
                    pending_nodes=[],  # No pending nodes after completion
                    context=context,
                )
                logger.debug(f"工作流 {workflow_id} 最终检查点已保存")
            except Exception as ckpt_error:
                logger.warning(f"保存最终检查点失败: {ckpt_error}")

        logger.info(
            f"工作流 {workflow_id} 流式执行完成: {result.status.value}, "
            f"耗时 {result.total_duration_ms:.2f}ms"
        )

        return result

    async def _emit_event(self, workflow_id: str, event: Dict[str, Any]) -> None:
        """
        推送事件到回调

        自动添加事件元数据：
        - event_id: 唯一事件 ID
        - sequence: 事件序列号（用于检测丢失和保证顺序）

        Args:
            workflow_id: 工作流 ID
            event: 事件数据
        """
        # 添加事件元数据（向后兼容，不覆盖已有字段）
        if "event_id" not in event:
            event["event_id"] = generate_event_id()
        if "sequence" not in event:
            event["sequence"] = self._event_sequence.next(workflow_id)

        event_type = event.get("event_type", "unknown")
        node_id = event.get("node_id", "")
        sequence = event.get("sequence", 0)

        # 增强日志追踪
        logger.debug(
            f"[事件发送] workflow={workflow_id}, type={event_type}, "
            f"node={node_id}, seq={sequence}, event_id={event.get('event_id')}"
        )

        # 缓存事件历史（用于重放）
        if workflow_id not in self._event_history:
            self._event_history[workflow_id] = []
        history = self._event_history[workflow_id]
        history.append(event.copy())
        # 限制历史大小，移除最早的事件
        if len(history) > MAX_EVENT_HISTORY_SIZE:
            self._event_history[workflow_id] = history[-MAX_EVENT_HISTORY_SIZE:]

        # 推送事件到回调
        callback = self._event_callbacks.get(workflow_id)
        if callback:
            try:
                await callback(event)
            except Exception as e:
                logger.warning(
                    f"事件回调失败: type={event_type}, node={node_id}, "
                    f"seq={sequence}, error={e}"
                )
        else:
            logger.debug(f"[事件发送] 无回调注册: workflow={workflow_id}")

    def get_event_history(
        self, workflow_id: str, since_sequence: int = 0
    ) -> List[Dict[str, Any]]:
        """
        获取事件历史（用于重放或补发）

        Args:
            workflow_id: 工作流 ID
            since_sequence: 从指定序列号之后开始（不包含该序列号）

        Returns:
            事件列表，按序列号升序排列
        """
        history = self._event_history.get(workflow_id, [])
        if since_sequence > 0:
            return [e for e in history if e.get("sequence", 0) > since_sequence]
        return list(history)

    def clear_event_history(self, workflow_id: str) -> None:
        """
        清理工作流的事件历史和序列号

        在工作流执行完成后调用，释放内存。

        Args:
            workflow_id: 工作流 ID
        """
        if workflow_id in self._event_history:
            del self._event_history[workflow_id]
        self._event_sequence.reset(workflow_id)
        logger.debug(f"[事件清理] workflow={workflow_id} 事件历史已清理")

    def _truncate_output(self, output: Any, max_length: int = 500) -> Any:
        """截断输出用于预览，保留结构化信息"""
        if output is None:
            return None

        if isinstance(output, str):
            if len(output) > max_length:
                return output[:max_length] + "..."
            return output

        if isinstance(output, dict):
            # 提取关键字段用于摘要
            summary_fields = [
                "recommendation",
                "summary",
                "result",
                "conclusion",
                "建议",
                "摘要",
                "结果",
                "结论",
                "answer",
                "答案",
            ]
            for field in summary_fields:
                if field in output:
                    value = output[field]
                    if isinstance(value, str):
                        return (
                            f"{field}: {value[:max_length]}"
                            if len(value) > max_length
                            else f"{field}: {value}"
                        )
                    return {field: value}

            # 返回简化的 dict 预览
            preview = {}
            for k, v in list(output.items())[:5]:
                if isinstance(v, str):
                    preview[k] = v[:100] + "..." if len(v) > 100 else v
                elif isinstance(v, (dict, list)):
                    preview[k] = f"[{type(v).__name__}]"
                else:
                    preview[k] = v
            return preview

        if isinstance(output, list):
            if len(output) > 10:
                return f"[{len(output)} 项]"
            return output[:5] if len(output) > 5 else output

        return output

    def _extract_narrative_fields(self, output: Any) -> tuple:
        """从 agent 输出中提取 summary / narrative / highlights（标准输出格式）"""
        if output is None or not isinstance(output, dict):
            return (None, None, None)
        # Agent.run() 返回 { result: { summary, narrative, data, highlights }, ... }，优先从 result 取
        inner = (
            output.get("result") if isinstance(output.get("result"), dict) else output
        )
        summary = inner.get("summary")
        narrative = inner.get("narrative")
        highlights = inner.get("highlights")
        if not isinstance(summary, str):
            summary = None
        if not isinstance(narrative, str):
            narrative = None
        if not isinstance(highlights, list):
            highlights = None
        else:
            highlights = [str(h) for h in highlights]
        return (summary, narrative, highlights)

    # 技术字段黑名单（对用户无意义）
    _TECHNICAL_FIELDS = {
        "agent_id",
        "task_id",
        "workspace_path",
        "_workspace_path",
        "duration_ms",
        "success",
        "verification_score",
        "iterations",
    }

    def _extract_user_facing_output(self, output: Any) -> Any:
        """
        提取用户关心的输出数据，过滤技术字段

        从 Agent 输出中提取用户真正需要的数据，过滤掉
        agent_id, task_id, workspace_path 等技术元数据
        """
        if not isinstance(output, dict):
            return output

        # 优先使用 result 字段（Agent 标准输出格式）
        result = output.get("result")
        if isinstance(result, dict):
            # 如果 result 有 data 字段，优先返回结构化的用户数据
            data = result.get("data")
            if data is not None:
                user_output = {
                    "summary": result.get("summary"),
                    "narrative": result.get("narrative"),
                    "data": data,
                    "highlights": result.get("highlights"),
                }
                # 保留 data_format 字段，供前端报告渲染使用
                if result.get("data_format"):
                    user_output["data_format"] = result["data_format"]
                # 保留 output_files 字段，供前端展示完整的输出文件列表
                if result.get("output_files"):
                    user_output["output_files"] = result["output_files"]
                return user_output
            # 否则返回整个 result（已经是用户数据）
            return result

        # 过滤技术字段
        return {
            k: v
            for k, v in output.items()
            if k.lower() not in self._TECHNICAL_FIELDS and not k.startswith("_")
        }

    def _generate_output_summary(self, output: Any) -> str:
        """生成输出的一句话摘要"""
        if output is None:
            return "无输出"

        if isinstance(output, str):
            trimmed = output.strip()
            if not trimmed:
                return "空输出"
            # 取第一行或前80个字符
            first_line = trimmed.split("\n")[0]
            if len(first_line) > 80:
                return first_line[:77] + "..."
            return first_line

        if isinstance(output, (int, float)):
            return f"结果: {output}"

        if isinstance(output, bool):
            return "成功" if output else "失败"

        if isinstance(output, list):
            return f"返回 {len(output)} 项结果"

        if isinstance(output, dict):
            # 智能提取关键信息
            highlight_fields = ["recommendation", "suggestion", "建议", "推荐"]
            for field in highlight_fields:
                if field in output:
                    value = output[field]
                    if isinstance(value, str):
                        return (
                            f"建议: {value[:60]}..."
                            if len(value) > 60
                            else f"建议: {value}"
                        )
                    return f"建议: {value}"

            summary_fields = [
                "summary",
                "conclusion",
                "result",
                "摘要",
                "结论",
                "结果",
                "answer",
                "答案",
            ]
            for field in summary_fields:
                if field in output:
                    value = str(output[field])
                    return value[:80] + "..." if len(value) > 80 else value

            error_fields = ["error", "exception", "错误", "异常"]
            for field in error_fields:
                if field in output:
                    return f"错误: {output[field]}"

            # 返回字段数量
            keys = list(output.keys())
            if not keys:
                return "空对象"
            if len(keys) <= 3:
                return ", ".join(keys)
            return f"包含 {len(keys)} 个字段"

        return str(output)[:80]

    def _cleanup_streaming_state(self, workflow_id: str) -> None:
        """清理流式执行的辅助状态（FSM 本身保留用于后续查询）

        Args:
            workflow_id: 工作流 ID
        """
        if workflow_id in self._skip_nodes:
            del self._skip_nodes[workflow_id]
        if workflow_id in self._modified_inputs:
            del self._modified_inputs[workflow_id]
        if workflow_id in self._injected_context:
            del self._injected_context[workflow_id]
        if workflow_id in self._event_callbacks:
            del self._event_callbacks[workflow_id]

    # ========== 运行时干预方法 ==========

    async def pause(self, workflow_id: str) -> bool:
        """
        暂停工作流执行

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否成功
        """
        fsm = self._execution_fsms.get(workflow_id)
        if not fsm or not fsm.can_transition(ExecutionEvent.PAUSE):
            return False

        try:
            await fsm.transition(ExecutionEvent.PAUSE)
            logger.info(f"工作流 {workflow_id} 已暂停")
            return True
        except InvalidTransitionError:
            return False

    async def resume_execution(self, workflow_id: str) -> bool:
        """
        恢复工作流执行

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否成功
        """
        fsm = self._execution_fsms.get(workflow_id)
        if not fsm or not fsm.can_transition(ExecutionEvent.RESUME):
            return False

        try:
            await fsm.transition(ExecutionEvent.RESUME)
            logger.info(f"工作流 {workflow_id} 已恢复")
            return True
        except InvalidTransitionError:
            return False

    def is_paused(self, workflow_id: str) -> bool:
        """
        检查工作流是否处于暂停状态

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否处于暂停状态
        """
        fsm = self._execution_fsms.get(workflow_id)
        return fsm.is_paused if fsm else False

    def is_running(self, workflow_id: str) -> bool:
        """
        检查工作流是否正在运行

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否正在运行
        """
        fsm = self._execution_fsms.get(workflow_id)
        return fsm.is_running if fsm else False

    def get_fsm(self, workflow_id: str) -> Optional[ExecutionFSM]:
        """
        获取指定工作流的执行状态机

        Args:
            workflow_id: 工作流 ID

        Returns:
            ExecutionFSM 实例，如果不存在则返回 None
        """
        return self._execution_fsms.get(workflow_id)

    async def skip_node(self, workflow_id: str, node_id: str) -> bool:
        """
        跳过指定节点

        Args:
            workflow_id: 工作流 ID
            node_id: 节点 ID

        Returns:
            是否成功
        """
        fsm = self._execution_fsms.get(workflow_id)
        if not fsm or fsm.is_terminal:
            return False

        if workflow_id not in self._skip_nodes:
            self._skip_nodes[workflow_id] = set()

        self._skip_nodes[workflow_id].add(node_id)
        logger.info(f"工作流 {workflow_id} 将跳过节点 {node_id}")
        return True

    async def modify_node_input(
        self, workflow_id: str, node_id: str, new_input: Dict[str, Any]
    ) -> bool:
        """
        修改即将执行的节点输入

        Args:
            workflow_id: 工作流 ID
            node_id: 节点 ID
            new_input: 新的输入数据

        Returns:
            是否成功
        """
        fsm = self._execution_fsms.get(workflow_id)
        if not fsm or fsm.is_terminal:
            return False

        if workflow_id not in self._modified_inputs:
            self._modified_inputs[workflow_id] = {}

        self._modified_inputs[workflow_id][node_id] = new_input
        logger.info(f"工作流 {workflow_id} 节点 {node_id} 输入已修改")
        return True

    async def inject_context(self, workflow_id: str, context: Dict[str, Any]) -> bool:
        """
        注入额外上下文

        Args:
            workflow_id: 工作流 ID
            context: 要注入的上下文

        Returns:
            是否成功
        """
        fsm = self._execution_fsms.get(workflow_id)
        if not fsm or fsm.is_terminal:
            return False

        if workflow_id not in self._injected_context:
            self._injected_context[workflow_id] = {}

        self._injected_context[workflow_id].update(context)
        logger.info(f"工作流 {workflow_id} 已注入额外上下文")
        return True

    async def get_status(self, workflow_id: str) -> WorkflowStatus:
        """获取工作流状态"""
        fsm = self._execution_fsms.get(workflow_id)
        if not fsm:
            return WorkflowStatus.PENDING
        # Map ExecutionState to WorkflowStatus
        state_map = {
            ExecutionState.IDLE: WorkflowStatus.PENDING,
            ExecutionState.RUNNING: WorkflowStatus.RUNNING,
            ExecutionState.PAUSED: WorkflowStatus.PAUSED,
            ExecutionState.COMPLETED: WorkflowStatus.COMPLETED,
            ExecutionState.FAILED: WorkflowStatus.FAILED,
            ExecutionState.CANCELLED: WorkflowStatus.CANCELLED,
        }
        return state_map.get(fsm.state, WorkflowStatus.PENDING)

    async def resume(
        self, workflow_id: str, checkpoint_id: Optional[str] = None
    ) -> WorkflowResult:
        """
        从检查点恢复工作流执行

        Args:
            workflow_id: 工作流 ID
            checkpoint_id: 检查点 ID（可选，默认使用最新检查点）

        Returns:
            工作流执行结果
        """
        logger.info(f"恢复工作流: {workflow_id}, 检查点: {checkpoint_id or '最新'}")

        # 加载检查点
        checkpoint = await self._load_checkpoint(workflow_id, checkpoint_id)
        if not checkpoint:
            raise WorkflowError(
                f"找不到工作流 {workflow_id} 的检查点",
                workflow_id=workflow_id,
            )

        # 获取工作流定义
        workflow_def = self._workflow_definitions.get(checkpoint.workflow_definition_id)
        if not workflow_def:
            # 尝试从检查点目录加载
            workflow_def = await self._load_workflow_definition(
                checkpoint.workflow_definition_id
            )
            if not workflow_def:
                raise WorkflowError(
                    f"找不到工作流定义: {checkpoint.workflow_definition_id}",
                    workflow_id=workflow_id,
                )

        # 创建 FSM 并启动
        fsm = ExecutionFSM(workflow_id)
        self._execution_fsms[workflow_id] = fsm
        fsm.transition_sync(ExecutionEvent.START)

        # 恢复执行状态
        started_at = datetime.now()
        result = WorkflowResult(
            workflow_id=workflow_id,
            status=WorkflowStatus.RUNNING,
            node_results=checkpoint.node_results.copy(),
            started_at=started_at.isoformat(),
        )

        self._workflow_results[workflow_id] = result

        try:
            # 恢复上下文和节点输出
            context = checkpoint.context.copy()
            node_outputs = checkpoint.node_outputs.copy()
            pending_nodes = checkpoint.pending_nodes.copy()

            # 获取完整的执行顺序
            full_order = self._topological_sort(workflow_def)

            # 过滤出待执行的节点（按拓扑顺序）
            execution_order = [n for n in full_order if n in pending_nodes]

            logger.info(f"恢复执行，待执行节点: {execution_order}")

            nodes_executed = 0
            for node_id in execution_order:
                # 检查取消标志（通过 FSM）
                if fsm.state == ExecutionState.CANCELLED:
                    result.status = WorkflowStatus.CANCELLED
                    result.error = "工作流被取消"
                    break

                # 检查暂停标志（通过 FSM）
                if fsm.state == ExecutionState.PAUSED:
                    await fsm.pause_event.wait()
                    if fsm.state == ExecutionState.CANCELLED:
                        result.status = WorkflowStatus.CANCELLED
                        result.error = "工作流在暂停期间被取消"
                        break

                node = self._get_node(workflow_def, node_id)
                if not node:
                    continue

                # 检查依赖
                dependencies_met = self._check_dependencies(node, result.node_results)
                if not dependencies_met:
                    result.node_results[node_id] = NodeExecutionResult(
                        node_id=node_id,
                        status="skipped",
                        error="依赖节点未成功完成",
                    )
                    continue

                # 执行节点
                node_result = await self._execute_node(
                    node=node,
                    context=context,
                    node_outputs=node_outputs,
                    workflow_definition=workflow_def,
                )

                result.node_results[node_id] = node_result
                nodes_executed += 1

                if node_result.status == "success":
                    node_outputs[node_id] = node_result.output
                elif node_result.status == "failed":
                    if not workflow_def.continue_on_error:
                        result.status = WorkflowStatus.FAILED
                        result.error = f"节点 {node_id} 执行失败: {node_result.error}"
                        break

                # 自动保存检查点
                if (
                    self.auto_checkpoint
                    and nodes_executed % self.checkpoint_interval == 0
                ):
                    remaining_nodes = [
                        n
                        for n in execution_order
                        if n not in result.node_results
                        or result.node_results[n].status not in ("success", "failed")
                    ]
                    await self._save_checkpoint(
                        workflow_id=workflow_id,
                        workflow_definition=workflow_def,
                        result=result,
                        node_outputs=node_outputs,
                        pending_nodes=remaining_nodes,
                        context=context,
                    )

            # 确定最终状态
            if result.status == WorkflowStatus.RUNNING:
                exit_node_id = workflow_def.primary_exit
                if exit_node_id and exit_node_id in result.node_results:
                    exit_result = result.node_results[exit_node_id]
                    if exit_result.status == "success":
                        result.status = WorkflowStatus.COMPLETED
                        result.final_output = exit_result.output
                    else:
                        result.status = WorkflowStatus.FAILED
                        result.error = f"出口节点 {exit_node_id} 未成功完成"
                else:
                    result.status = WorkflowStatus.COMPLETED
                    result.final_output = node_outputs

        except Exception as e:
            result.status = WorkflowStatus.FAILED
            result.error = f"工作流恢复执行异常: {str(e)}"
            logger.exception(f"工作流 {workflow_id} 恢复执行异常")

        finally:
            # 更新 FSM 到终态（如果尚未到达终态）
            if not fsm.is_terminal:
                if result.status == WorkflowStatus.COMPLETED:
                    fsm.transition_sync(ExecutionEvent.COMPLETE)
                elif result.status == WorkflowStatus.FAILED:
                    fsm.transition_sync(ExecutionEvent.FAIL)
                elif result.status == WorkflowStatus.CANCELLED:
                    try:
                        fsm.transition_sync(ExecutionEvent.STOP)
                    except InvalidTransitionError:
                        pass

            completed_at = datetime.now()
            result.completed_at = completed_at.isoformat()
            result.total_duration_ms = (
                completed_at - started_at
            ).total_seconds() * 1000

            self._workflow_results[workflow_id] = result

        logger.info(f"工作流 {workflow_id} 恢复执行完成: {result.status.value}")
        return result

    async def _save_checkpoint(
        self,
        workflow_id: str,
        workflow_definition: WorkflowDefinition,
        result: WorkflowResult,
        node_outputs: Dict[str, Any],
        pending_nodes: List[str],
        context: Dict[str, Any],
    ) -> str:
        """
        保存工作流检查点

        Args:
            workflow_id: 工作流 ID
            workflow_definition: 工作流定义
            result: 当前执行结果
            node_outputs: 节点输出
            pending_nodes: 待执行节点
            context: 执行上下文

        Returns:
            检查点 ID
        """
        import json
        from pathlib import Path

        checkpoint_id = (
            f"ckpt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )

        checkpoint = WorkflowCheckpoint(
            checkpoint_id=checkpoint_id,
            workflow_id=workflow_id,
            workflow_definition_id=workflow_definition.workflow_id,
            status=result.status,
            node_results=result.node_results,
            node_outputs=node_outputs,
            pending_nodes=pending_nodes,
            context=context,
            created_at=datetime.now().isoformat(),
        )

        # 保存到工作空间
        checkpoint_dir = Path(self.workspace_base_path) / workflow_id / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        checkpoint_file = checkpoint_dir / f"{checkpoint_id}.json"
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(
                checkpoint.to_dict(), f, ensure_ascii=False, indent=2, default=str
            )

        # 保存工作流定义（用于恢复）
        self._workflow_definitions[workflow_definition.workflow_id] = (
            workflow_definition
        )

        # 同时保存定义到文件
        definition_file = checkpoint_dir.parent / "workflow_definition.json"
        with open(definition_file, "w", encoding="utf-8") as f:
            json.dump(
                workflow_definition.model_dump(mode="json"),
                f,
                ensure_ascii=False,
                indent=2,
            )

        # 更新最新检查点索引
        latest_file = checkpoint_dir / "latest.txt"
        with open(latest_file, "w") as f:
            f.write(checkpoint_id)

        logger.debug(f"检查点已保存: {checkpoint_id}")
        return checkpoint_id

    async def _load_checkpoint(
        self,
        workflow_id: str,
        checkpoint_id: Optional[str] = None,
    ) -> Optional[WorkflowCheckpoint]:
        """
        加载工作流检查点

        Args:
            workflow_id: 工作流 ID
            checkpoint_id: 检查点 ID（可选，默认加载最新）

        Returns:
            检查点数据
        """
        import json
        from pathlib import Path

        checkpoint_dir = Path(self.workspace_base_path) / workflow_id / "checkpoints"

        if not checkpoint_dir.exists():
            return None

        # 确定检查点 ID
        if not checkpoint_id:
            latest_file = checkpoint_dir / "latest.txt"
            if latest_file.exists():
                checkpoint_id = latest_file.read_text().strip()
            else:
                # 查找最新的检查点文件
                checkpoint_files = sorted(
                    checkpoint_dir.glob("ckpt_*.json"), reverse=True
                )
                if checkpoint_files:
                    checkpoint_id = checkpoint_files[0].stem
                else:
                    return None

        checkpoint_file = checkpoint_dir / f"{checkpoint_id}.json"
        if not checkpoint_file.exists():
            return None

        with open(checkpoint_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        return WorkflowCheckpoint.from_dict(data)

    async def _load_workflow_definition(
        self,
        workflow_definition_id: str,
    ) -> Optional[WorkflowDefinition]:
        """
        从文件加载工作流定义

        Args:
            workflow_definition_id: 工作流定义 ID

        Returns:
            工作流定义
        """
        import json
        from pathlib import Path

        # 尝试在所有工作流目录中查找
        base_path = Path(self.workspace_base_path)
        if not base_path.exists():
            return None

        for workflow_dir in base_path.iterdir():
            if not workflow_dir.is_dir():
                continue

            definition_file = workflow_dir / "workflow_definition.json"
            if definition_file.exists():
                with open(definition_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if data.get("workflow_id") == workflow_definition_id:
                    return WorkflowDefinition(**data)

        return None

    async def list_checkpoints(self, workflow_id: str) -> List[Dict[str, Any]]:
        """
        列出工作流的所有检查点

        Args:
            workflow_id: 工作流 ID

        Returns:
            检查点信息列表
        """
        import json
        from pathlib import Path

        checkpoint_dir = Path(self.workspace_base_path) / workflow_id / "checkpoints"

        if not checkpoint_dir.exists():
            return []

        checkpoints = []
        for checkpoint_file in sorted(checkpoint_dir.glob("ckpt_*.json"), reverse=True):
            try:
                with open(checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                checkpoints.append(
                    {
                        "checkpoint_id": data.get("checkpoint_id"),
                        "status": data.get("status"),
                        "created_at": data.get("created_at"),
                        "pending_nodes": len(data.get("pending_nodes", [])),
                        "completed_nodes": len(data.get("node_results", {})),
                    }
                )
            except Exception as e:
                logger.warning(f"读取检查点失败: {checkpoint_file}, {e}")

        return checkpoints

    def _validate_workflow(self, workflow_def: WorkflowDefinition) -> None:
        """验证工作流，检查循环依赖"""
        # 构建邻接表
        graph: Dict[str, List[str]] = {}
        for edge in workflow_def.edges:
            if edge.from_node not in graph:
                graph[edge.from_node] = []
            graph[edge.from_node].append(edge.to_node)

        # DFS 检测环
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def has_cycle(node: str, path: List[str]) -> Optional[List[str]]:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    result = has_cycle(neighbor, path + [neighbor])
                    if result:
                        return result
                elif neighbor in rec_stack:
                    # 发现环
                    cycle_start = path.index(neighbor) if neighbor in path else 0
                    return path[cycle_start:] + [neighbor]

            rec_stack.remove(node)
            return None

        for node in workflow_def.nodes:
            if node.node_id not in visited:
                cycle = has_cycle(node.node_id, [node.node_id])
                if cycle:
                    raise WorkflowCycleError(
                        workflow_id=workflow_def.workflow_id, cycle_nodes=cycle
                    )

    def _topological_sort(self, workflow_def: WorkflowDefinition) -> List[str]:
        """拓扑排序获取执行顺序"""
        # 构建入度表和邻接表
        in_degree: Dict[str, int] = {node.node_id: 0 for node in workflow_def.nodes}
        graph: Dict[str, List[str]] = {node.node_id: [] for node in workflow_def.nodes}

        for edge in workflow_def.edges:
            graph[edge.from_node].append(edge.to_node)
            in_degree[edge.to_node] += 1

        # Kahn 算法
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            # 可以在这里实现优先级排序
            node_id = queue.pop(0)
            result.append(node_id)

            for neighbor in graph[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def _get_node(
        self, workflow_def: WorkflowDefinition, node_id: str
    ) -> Optional[WorkflowNode]:
        """获取节点定义"""
        for node in workflow_def.nodes:
            if node.node_id == node_id:
                return node
        return None

    def _check_dependencies(
        self, node: WorkflowNode, node_results: Dict[str, NodeExecutionResult]
    ) -> bool:
        """检查节点依赖是否满足"""
        for dep_id in node.dependencies:
            if dep_id not in node_results:
                return False
            if node_results[dep_id].status != "success":
                return False
        return True

    async def _execute_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
        node_outputs: Dict[str, Any],
        workflow_definition: WorkflowDefinition,
        workflow_id: Optional[str] = None,
        modified_input: Optional[Dict[str, Any]] = None,
    ) -> NodeExecutionResult:
        """执行单个节点"""
        started_at = datetime.now()

        logger.debug(f"执行节点: {node.node_id} ({node.node_type.value})")

        try:
            # 准备节点输入
            node_input = self._prepare_node_input(
                node=node,
                context=context,
                node_outputs=node_outputs,
            )

            # 应用修改的输入
            if modified_input:
                node_input.update(modified_input)
                logger.info(f"节点 {node.node_id} 应用了修改的输入")

            # 根据节点类型执行
            if node.node_type == NodeType.START:
                # 开始节点：直接传递上下文
                output = {"status": "started", "context": node_input}

            elif node.node_type == NodeType.END:
                # 结束节点：汇总所有输出
                output = {"status": "completed", "final_output": node_input}

            elif node.node_type == NodeType.AGENT:
                output = await self._execute_agent_node(
                    node, node_input, context, workflow_definition
                )

            elif node.node_type == NodeType.PARALLEL:
                output = await self._execute_parallel_node(
                    node, node_input, context, node_outputs, workflow_definition
                )

            elif node.node_type == NodeType.CONDITION:
                output = await self._execute_conditional_node(
                    node, node_input, context, node_outputs
                )

            elif node.node_type == NodeType.LOOP:
                output = await self._execute_loop_node(
                    node, node_input, context, node_outputs, workflow_definition
                )

            elif node.node_type == NodeType.HUMAN_IN_LOOP:
                output = await self._execute_human_input_node(node, node_input, context)

            else:
                raise ValueError(f"未知节点类型: {node.node_type}")

            completed_at = datetime.now()
            duration_ms = (completed_at - started_at).total_seconds() * 1000

            return NodeExecutionResult(
                node_id=node.node_id,
                status="success",
                output=output,
                duration_ms=duration_ms,
                started_at=started_at.isoformat(),
                completed_at=completed_at.isoformat(),
            )

        except Exception as e:
            completed_at = datetime.now()
            duration_ms = (completed_at - started_at).total_seconds() * 1000

            logger.error(f"节点 {node.node_id} 执行失败: {e}")

            return NodeExecutionResult(
                node_id=node.node_id,
                status="failed",
                error=str(e),
                duration_ms=duration_ms,
                started_at=started_at.isoformat(),
                completed_at=completed_at.isoformat(),
            )

    def _prepare_node_input(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
        node_outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """准备节点输入

        数据来源优先级：
        1. context: 全局上下文
        2. config: 节点配置
        3. input_mappings: 显式字段映射
        4. dependencies: 直接依赖节点的输出 (dep_{node_id})
        5. context_refs: 引用节点的输出 (ref_{node_id}) - 不影响执行顺序
        6. _upstream_workspace_paths: 上游节点的工作空间路径（用于复制 context 文件）
        """
        node_input = {
            "context": context,
            "config": node.config or {},
        }

        # 收集上游节点的工作空间路径（用于复制 context 文件）
        upstream_workspace_paths = {}

        # 应用数据映射
        if node.input_mappings:
            for mapping in node.input_mappings:
                source_value = node_outputs.get(mapping.source_node, {})
                if isinstance(source_value, dict):
                    value = source_value.get(mapping.source_field)
                    # 收集工作空间路径
                    if "_workspace_path" in source_value:
                        upstream_workspace_paths[mapping.source_node] = source_value[
                            "_workspace_path"
                        ]
                else:
                    value = source_value
                node_input[mapping.target_field] = value

        # 从依赖节点获取输出（执行顺序依赖）
        for dep_id in node.dependencies:
            if dep_id in node_outputs:
                node_input[f"dep_{dep_id}"] = node_outputs[dep_id]
                # 收集工作空间路径
                if (
                    isinstance(node_outputs[dep_id], dict)
                    and "_workspace_path" in node_outputs[dep_id]
                ):
                    upstream_workspace_paths[dep_id] = node_outputs[dep_id][
                        "_workspace_path"
                    ]

        # 从 context_refs 引用节点获取输出（数据引用，不影响执行顺序）
        # 用于获取非直接依赖节点的数据，如 report_generator 需要 data_collector 的原始数据
        if node.context_refs:
            for ref_id in node.context_refs:
                if ref_id in node_outputs:
                    node_input[f"ref_{ref_id}"] = node_outputs[ref_id]
                    logger.debug(
                        f"节点 {node.node_id} 通过 context_refs 引用了 {ref_id} 的输出"
                    )
                    # 收集工作空间路径
                    if (
                        isinstance(node_outputs[ref_id], dict)
                        and "_workspace_path" in node_outputs[ref_id]
                    ):
                        upstream_workspace_paths[ref_id] = node_outputs[ref_id][
                            "_workspace_path"
                        ]
                else:
                    logger.warning(
                        f"节点 {node.node_id} 的 context_refs 引用了不存在的节点: {ref_id}"
                    )

        # 添加上游工作空间路径到输入（供 _execute_agent_node 使用）
        if upstream_workspace_paths:
            node_input["_upstream_workspace_paths"] = upstream_workspace_paths
            logger.debug(
                f"节点 {node.node_id} 将从以下上游节点复制 context 文件: {list(upstream_workspace_paths.keys())}"
            )

        return node_input

    async def _execute_agent_node(
        self,
        node: WorkflowNode,
        node_input: Dict[str, Any],
        context: Dict[str, Any],
        workflow_definition=None,
    ) -> Any:
        """执行 Agent 节点"""
        # 优先从节点直接字段获取，其次从 config 获取
        agent_ref = node.agent_id or (
            node.config.get("agent_id") if node.config else None
        )
        if not agent_ref:
            raise ValueError(f"Agent 节点 {node.node_id} 缺少 agent_id 配置")

        # 获取 Agent 定义，用于确定 LLM 配置
        agent_definition = self.agent_registry.get_definition(agent_ref)
        if not agent_definition:
            raise ValueError(f"Agent {agent_ref} 未在注册表中找到")

        # --- Resolve data_format ---
        # Priority: agent output_instruction.data_format
        #         > WorkflowDefinition.default_data_format
        #         > app_config.yaml workflow.default_data_format
        #         > system default ("json")
        agent_data_format = getattr(
            agent_definition.output_instruction, "data_format", "json"
        )
        if agent_data_format == "json":
            # Agent 未显式设置，尝试从工作流定义继承
            resolved_format = "json"
            if workflow_definition is not None:
                wf_default = getattr(workflow_definition, "default_data_format", "json")
                if wf_default and wf_default != "json":
                    resolved_format = wf_default

            # 工作流定义也没设置，回退到应用配置
            if resolved_format == "json":
                app_default = self._app_workflow_config.get(
                    "default_data_format", "json"
                )
                if app_default and app_default != "json":
                    resolved_format = app_default

            # 如果解析出非 json 格式，克隆并修改 agent 定义
            if resolved_format != "json":
                agent_definition = agent_definition.model_copy(deep=True)
                agent_definition.output_instruction.data_format = resolved_format

        # 根据 Agent 的 llm_config 动态创建 LLM 客户端
        llm_client = self._get_or_create_llm_client(agent_definition.llm_config)

        # 创建工作空间
        workspace_config = WorkspaceConfig(
            base_path=self.workspace_base_path,
            task_id=f"{context['workflow_id']}_{node.node_id}",
        )
        workspace = AgentWorkspace(workspace_config)

        # === 复制上游节点的 context 文件到当前工作空间 ===
        # 这解决了下游 Agent 无法读取上游 Agent 产生的 context 文件的问题
        upstream_workspace_paths = node_input.get("_upstream_workspace_paths", {})
        copied_files_count = 0

        for upstream_node_id, upstream_ws_path in upstream_workspace_paths.items():
            upstream_context_dir = Path(upstream_ws_path) / "context"
            if upstream_context_dir.exists():
                # 复制上游 context 目录中的所有文件
                for src_file in upstream_context_dir.iterdir():
                    if src_file.is_file():
                        # 目标路径：context/{upstream_node_id}_{filename} 或直接 context/{filename}
                        # 使用 upstream_node_id 前缀避免文件名冲突
                        dest_file = (
                            workspace.context_dir
                            / f"{upstream_node_id}_{src_file.name}"
                        )
                        try:
                            shutil.copy2(src_file, dest_file)
                            copied_files_count += 1
                        except Exception as e:
                            logger.warning(
                                f"复制上游 context 文件失败: {src_file} -> {dest_file}: {e}"
                            )

                # 同时创建不带前缀的软链接或复制，便于直接引用
                # 如果同名文件已存在则跳过（优先使用较早节点的文件）
                for src_file in upstream_context_dir.iterdir():
                    if src_file.is_file():
                        dest_file_direct = workspace.context_dir / src_file.name
                        if not dest_file_direct.exists():
                            try:
                                shutil.copy2(src_file, dest_file_direct)
                            except Exception as e:
                                logger.warning(
                                    f"复制上游 context 文件失败: {src_file} -> {dest_file_direct}: {e}"
                                )

        if copied_files_count > 0:
            logger.info(
                f"节点 {node.node_id} 从上游节点复制了 {copied_files_count} 个 context 文件"
            )

        # 创建并运行 Agent
        agent = self.agent_registry.create_agent(
            agent_id=agent_ref,
            workspace=workspace,
            tool_registry=self.tool_registry,
            llm_client=llm_client,
        )

        # 构建任务描述：优先级顺序
        # 1. node_input 中的 task_description
        # 2. node.config 中的 task
        # 3. context 中的 task
        # 4. 默认任务描述
        task_description = None

        if "task_description" in node_input and node_input["task_description"]:
            task_description = node_input["task_description"]
        elif node.config and node.config.get("task"):
            task_description = node.config.get("task")
        elif context.get("task"):
            task_description = context.get("task")

        # 如果仍然没有任务描述，构建一个默认的
        if not task_description:
            task_description = f"执行工作流节点 '{node.name}' (ID: {node.node_id})"
            # 添加上下文信息
            if context.get("company"):
                task_description += f"\n目标公司: {context.get('company')}"
            if context.get("ticker"):
                task_description += f"\n股票代码: {context.get('ticker')}"
            # 添加输入数据摘要
            if node_input:
                input_summary = ", ".join(
                    f"{k}={v}" for k, v in list(node_input.items())[:5]
                )
                task_description += f"\n输入参数: {input_summary}"

        # 创建进度回调函数，用于发送节点执行中间状态
        workflow_id = context.get("workflow_id", "")

        async def progress_callback(status) -> None:
            """发送节点进度事件；支持字符串（兼容）或结构化 dict（node_activity）"""
            if isinstance(status, dict):
                await self._emit_event(
                    workflow_id,
                    {
                        "event_type": "node_activity",
                        "workflow_id": workflow_id,
                        "node_id": node.node_id,
                        "node_name": node.name,
                        "timestamp": datetime.now().isoformat(),
                        "data": status,
                    },
                )
            else:
                await self._emit_event(
                    workflow_id,
                    {
                        "event_type": "node_progress",
                        "workflow_id": workflow_id,
                        "node_id": node.node_id,
                        "node_name": node.name,
                        "status": str(status),
                        "timestamp": datetime.now().isoformat(),
                    },
                )

        async def _emit_stream(chunk_type: str, content: str) -> None:
            event_type = "node_thinking" if chunk_type == "reasoning" else "node_stream"
            await self._emit_event(
                workflow_id,
                {
                    "event_type": event_type,
                    "workflow_id": workflow_id,
                    "node_id": node.node_id,
                    "node_name": node.name,
                    "timestamp": datetime.now().isoformat(),
                    "data": {"content": content},
                },
            )

        batcher = StreamBatcher(_emit_stream, interval=0.1, min_chars=20)

        async def stream_callback(chunk: Dict[str, Any]) -> None:
            ctype = chunk.get("type", "content")
            content = chunk.get("content", "") or ""
            if ctype in ("reasoning", "content") and content:
                await batcher.add(ctype, content)

        result = await agent.run(
            task_description=task_description,
            input_data=node_input.get("input_data", node_input),
            progress_callback=progress_callback,
            stream_callback=stream_callback,
        )
        await batcher.flush_all()

        # 在结果中添加工作空间路径，供下游节点使用
        if isinstance(result, dict):
            result["_workspace_path"] = str(workspace.root)
        else:
            result = {"output": result, "_workspace_path": str(workspace.root)}

        return result

    async def _execute_tool_node(
        self,
        node: WorkflowNode,
        node_input: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        """执行工具节点"""
        tool_id = node.config.get("tool_id") if node.config else None
        if not tool_id:
            raise ValueError(f"工具节点 {node.node_id} 缺少 tool_id 配置")

        tool_params = node.config.get("params", {}) if node.config else {}
        # 合并输入参数
        tool_params.update(node_input.get("tool_params", {}))

        result = await self.tool_registry.execute(
            tool_id=tool_id,
            params=tool_params,
            context=context,
        )

        return result

    async def _execute_parallel_node(
        self,
        node: WorkflowNode,
        node_input: Dict[str, Any],
        context: Dict[str, Any],
        node_outputs: Dict[str, Any],
        workflow_definition: WorkflowDefinition,
    ) -> Any:
        """执行并行节点"""
        parallel_node_ids = node.config.get("parallel_nodes", []) if node.config else []

        if not parallel_node_ids:
            return {}

        # 并行执行所有子节点
        tasks = []
        for sub_node_id in parallel_node_ids:
            sub_node = self._get_node(workflow_definition, sub_node_id)
            if sub_node:
                tasks.append(
                    self._execute_node(
                        node=sub_node,
                        context=context,
                        node_outputs=node_outputs,
                        workflow_definition=workflow_definition,
                    )
                )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 整理结果
        parallel_outputs = {}
        for i, result in enumerate(results):
            sub_node_id = parallel_node_ids[i]
            if isinstance(result, Exception):
                parallel_outputs[sub_node_id] = {"error": str(result)}
            elif isinstance(result, NodeExecutionResult):
                parallel_outputs[sub_node_id] = result.output
                # 更新 node_outputs 供后续节点使用
                node_outputs[sub_node_id] = result.output

        return parallel_outputs

    async def _execute_conditional_node(
        self,
        node: WorkflowNode,
        node_input: Dict[str, Any],
        context: Dict[str, Any],
        node_outputs: Dict[str, Any],
    ) -> Any:
        """执行条件节点"""
        condition = node.config.get("condition") if node.config else None

        if not condition:
            return {"branch": "default", "value": None}

        # 简单的条件评估
        # 支持: "output.field == value" 格式
        try:
            # 安全的条件评估（简化版）
            condition_result = self._evaluate_condition(
                condition, node_input, node_outputs
            )

            branch = "true" if condition_result else "false"
            return {"branch": branch, "condition_result": condition_result}

        except Exception as e:
            logger.warning(f"条件评估失败: {e}")
            return {"branch": "error", "error": str(e)}

    def _evaluate_condition(
        self,
        condition: str,
        node_input: Dict[str, Any],
        node_outputs: Dict[str, Any],
    ) -> bool:
        """
        使用安全表达式评估器评估条件

        支持的表达式格式:
        - "node_id.field == value"
        - "score >= 0.7"
        - "status == 'success' and score > 0.5"

        Args:
            condition: 条件表达式
            node_input: 当前节点输入
            node_outputs: 所有节点输出

        Returns:
            条件评估结果
        """
        # 构建评估上下文
        context = {
            "input": node_input,
            "outputs": node_outputs,
            **node_outputs,  # 允许直接引用节点 ID
        }

        # 使用安全评估器
        return safe_eval_condition(condition, context, default=False)

    async def _execute_aggregator_node(
        self,
        node: WorkflowNode,
        node_input: Dict[str, Any],
        context: Dict[str, Any],
        node_outputs: Dict[str, Any],
    ) -> Any:
        """执行聚合节点"""
        source_nodes = node.config.get("source_nodes", []) if node.config else []
        aggregation_type = (
            node.config.get("aggregation_type", "list") if node.config else "list"
        )

        # 收集所有源节点的输出
        collected = []
        for source_id in source_nodes:
            if source_id in node_outputs:
                collected.append(
                    {"node_id": source_id, "output": node_outputs[source_id]}
                )

        # 根据聚合类型处理
        if aggregation_type == "list":
            return collected
        elif aggregation_type == "merge":
            merged = {}
            for item in collected:
                if isinstance(item["output"], dict):
                    merged.update(item["output"])
            return merged
        elif aggregation_type == "first":
            return collected[0]["output"] if collected else None
        elif aggregation_type == "last":
            return collected[-1]["output"] if collected else None
        else:
            return collected

    async def _execute_human_input_node(
        self,
        node: WorkflowNode,
        node_input: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        """执行人工输入节点"""
        # 在实际实现中，这会暂停工作流等待人工输入
        # 目前返回占位符
        prompt = node.config.get("prompt", "请输入") if node.config else "请输入"

        logger.info(f"人工输入节点 {node.node_id}: {prompt}")

        # 检查是否有预设的测试输入
        if "human_input" in node_input:
            return node_input["human_input"]

        return {
            "status": "waiting_for_input",
            "prompt": prompt,
            "node_id": node.node_id,
        }

    async def _execute_loop_node(
        self,
        node: WorkflowNode,
        node_input: Dict[str, Any],
        context: Dict[str, Any],
        node_outputs: Dict[str, Any],
        workflow_definition: WorkflowDefinition,
    ) -> Any:
        """执行循环节点"""
        config = node.config or {}
        max_iterations = config.get("max_iterations", 10)
        condition = config.get("condition", "false")
        loop_body = config.get("loop_body", [])  # 循环体内的节点ID列表

        results = []
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # 评估条件
            eval_context = {
                **context,
                "iteration": iteration,
                "results": results,
                "node_input": node_input,
            }

            should_continue = safe_eval_condition(condition, eval_context)
            if not should_continue:
                break

            # 执行循环体中的节点（如果有）
            if loop_body:
                iteration_output = {}
                for body_node_id in loop_body:
                    body_node = next(
                        (
                            n
                            for n in workflow_definition.nodes
                            if n.node_id == body_node_id
                        ),
                        None,
                    )
                    if body_node:
                        body_result = await self._execute_node(
                            body_node, context, node_outputs, workflow_definition
                        )
                        if body_result.status == "success":
                            iteration_output[body_node_id] = body_result.output
                results.append(iteration_output)
            else:
                results.append({"iteration": iteration})

        return {
            "iterations": iteration,
            "results": results,
            "completed": iteration < max_iterations,
        }

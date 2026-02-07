"""
对话式工作流构建器

使用 LLM Dialogue Agent 提供智能自然语言驱动的工作流构建接口。
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable, Awaitable
from datetime import datetime
from enum import Enum
from pathlib import Path

from src.utils.logger import get_logger
from src.definitions import WorkflowDefinition, AgentDefinition

from .interactive_builder import (
    InteractiveWorkflowBuilder,
    InteractionStage,
    UserInteractionCallback,
    UserFeedback,
    UserAction,
    IterationManager,
    WorkflowPlan,
    AgentSpec,
)
from .workflow_operations import WorkflowOperationTools, OperationResult
from .dialogue_agent import DialogueAgent, DialogueResponse
from src.orchestration.events import FRONTEND_EXECUTION_EVENTS, is_execution_event

logger = get_logger()


class SessionMode(Enum):
    """会话模式"""

    IDLE = "idle"  # 空闲状态
    BUILDING = "building"  # 构建中
    EXECUTING = "executing"  # 执行中
    COMPLETED = "completed"  # 已完成


@dataclass
class Message:
    """对话消息"""

    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    message_type: str = "text"  # text, execution_event, workflow_update, error
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        # 处理 timestamp 可能是 datetime 对象或字符串的情况
        timestamp_str = (
            self.timestamp.isoformat()
            if isinstance(self.timestamp, datetime)
            else str(self.timestamp)
        )
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": timestamp_str,
            "message_type": self.message_type,
            "data": self.data,
        }


@dataclass
class ConversationResponse:
    """对话响应"""

    message: str
    workflow_state: Optional[Dict[str, Any]] = None
    suggested_actions: List[str] = field(default_factory=list)
    highlighted_nodes: List[str] = field(default_factory=list)
    data: Optional[Dict[str, Any]] = None
    workflow_changed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "workflow_state": self.workflow_state,
            "suggested_actions": self.suggested_actions,
            "highlighted_nodes": self.highlighted_nodes,
            "data": self.data,
            "workflow_changed": self.workflow_changed,
        }


class AutoApproveCallback(UserInteractionCallback):
    """
    自动批准回调（用于对话式构建）

    这个回调不会阻塞等待用户输入，而是通过对话历史来获取反馈。
    """

    def __init__(
        self,
        on_progress: Optional[
            Callable[[InteractionStage, float, str, Optional[Dict]], Awaitable[None]]
        ] = None,
    ):
        self.on_progress = on_progress
        self._pending_feedback: Optional[UserFeedback] = None

    def set_feedback(self, feedback: UserFeedback) -> None:
        """设置下一次的反馈"""
        self._pending_feedback = feedback

    async def request_plan_review(
        self,
        plan: WorkflowPlan,
        iteration: int,
    ) -> UserFeedback:
        """请求规划审查 - 在对话模式下自动批准"""
        if self._pending_feedback:
            feedback = self._pending_feedback
            self._pending_feedback = None
            return feedback
        return UserFeedback(action=UserAction.APPROVE)

    async def request_agent_review(
        self,
        agent: AgentDefinition,
        spec: AgentSpec,
        iteration: int,
    ) -> UserFeedback:
        """请求 Agent 审查 - 在对话模式下自动批准"""
        if self._pending_feedback:
            feedback = self._pending_feedback
            self._pending_feedback = None
            return feedback
        return UserFeedback(action=UserAction.APPROVE)

    async def request_workflow_review(
        self,
        workflow: WorkflowDefinition,
        agents: List[AgentDefinition],
        iteration: int,
    ) -> UserFeedback:
        """请求工作流审查 - 在对话模式下自动批准"""
        if self._pending_feedback:
            feedback = self._pending_feedback
            self._pending_feedback = None
            return feedback
        return UserFeedback(action=UserAction.APPROVE)

    async def display_progress(
        self,
        stage: InteractionStage,
        progress: float,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """显示进度"""
        if self.on_progress:
            await self.on_progress(stage, progress, message, details)

    async def display_diff(
        self,
        before: str,
        after: str,
        title: str = "变更对比",
    ) -> None:
        """显示差异（由对话式构建器处理）"""
        pass


class ConversationalWorkflowBuilder:
    """
    对话式工作流构建器

    使用 LLM Dialogue Agent 实现智能对话式工作流构建。
    支持自然语言驱动的工作流创建、修改、执行和干预。
    """

    def __init__(
        self,
        meta_agent: Any,
        tool_registry: Any,
        llm_client: Any,
        workflow_engine: Optional[Any] = None,
        storage_path: Optional[Path] = None,
        session_id: Optional[str] = None,
    ):
        """
        初始化对话式构建器

        Args:
            meta_agent: MetaAgent 实例
            tool_registry: 工具注册表
            llm_client: LLM 客户端
            workflow_engine: 工作流引擎（可选）
            storage_path: 存储路径
            session_id: 会话 ID（可选，如果不提供则生成新的）
        """
        self.meta_agent = meta_agent
        self.tool_registry = tool_registry
        self.llm_client = llm_client
        self.workflow_engine = workflow_engine
        self.storage_path = storage_path or Path("./workspaces/conversational")

        # 工作流操作工具
        self.operations = WorkflowOperationTools(
            meta_agent=meta_agent,
            storage_path=str(self.storage_path),
            tool_registry=tool_registry,
        )

        # 对话 Agent
        self.dialogue_agent = DialogueAgent(
            llm_client=llm_client,
            operations=self.operations,
        )

        # 自动批准回调
        self._auto_callback = AutoApproveCallback(on_progress=self._handle_progress)

        # 对话历史
        self.conversation_history: List[Message] = []

        # 会话状态 - 使用传入的 session_id 或生成新的
        self.session_id = session_id or (
            f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )
        self.mode = SessionMode.IDLE
        self.current_execution_id: Optional[str] = None

        # 事件回调（用于实时推送到前端）
        self.on_workflow_update: Optional[Callable[[Dict], Awaitable[None]]] = None
        self.on_message: Optional[Callable[[Message], Awaitable[None]]] = None
        self.on_execution_event: Optional[Callable[[Dict], Awaitable[None]]] = None
        self.on_generation_progress: Optional[Callable[[Dict], Awaitable[None]]] = None

        # 设置进度回调
        self.operations.set_progress_callback(self._handle_agent_generation_progress)

        # 确保存储路径存在
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # 标记是否已初始化（异步加载会话历史后设置为 True）
        self._initialized = False

    async def _handle_progress(
        self,
        stage: InteractionStage,
        progress: float,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """处理进度更新"""
        if self.on_message:
            await self.on_message(
                Message(
                    role="system",
                    content=message,
                    message_type="progress",
                    data={
                        "stage": stage.value,
                        "progress": progress,
                        "details": details,
                    },
                )
            )

    async def _handle_agent_generation_progress(self, event: Dict[str, Any]) -> None:
        """处理 Agent 生成进度事件、批准消息事件和工作流执行事件"""
        event_type = event.get("type") or event.get(
            "event_type", "agent_generation_progress"
        )

        # 增强日志追踪
        event_id = event.get("event_id", "")
        sequence = event.get("sequence", 0)
        node_id = event.get("node_id", "")
        logger.debug(
            f"[事件接收] type={event_type}, node={node_id}, "
            f"seq={sequence}, event_id={event_id}"
        )

        # ========== 处理工作流执行事件 ==========
        # 使用统一的事件类型常量，避免遗漏
        if event_type in FRONTEND_EXECUTION_EVENTS:
            await self._handle_execution_event(event)
            return

        # ========== 处理批准开始消息（approval_started）==========
        if event_type == "approval_started":
            if self.on_message:
                await self.on_message(
                    Message(
                        role="assistant",
                        content=event.get("message", "已批准，正在处理..."),
                        message_type="status",
                        data={
                            "type": "approval_started",
                            "stage": event.get("stage", ""),
                        },
                    )
                )
            return

        # ========== 处理 Agent 生成进度 ==========
        display_name = event.get("display_name", event.get("agent_name", "Agent"))
        current = event.get("current", 0)
        total = event.get("total", 1)
        status = event.get("status", "generating")

        # 推送进度消息到聊天面板
        if self.on_message:
            message_text = event.get("message", f"正在生成 {display_name}...")
            await self.on_message(
                Message(
                    role="system",
                    content=message_text,
                    message_type="progress",
                    data={
                        "type": "agent_generation_progress",
                        "current": current,
                        "total": total,
                        "agent_name": event.get("agent_name"),
                        "display_name": display_name,
                        "status": status,
                        "progress": current / total if total > 0 else 0,
                    },
                )
            )

        # 推送专用生成进度事件
        if self.on_generation_progress:
            await self.on_generation_progress(event)

        # 同时推送工作流更新（以便画布实时显示）
        if status == "completed" and self.on_workflow_update:
            await self.on_workflow_update(self._get_workflow_state())

    async def _handle_execution_event(self, event: Dict[str, Any]) -> None:
        """处理工作流执行事件"""
        event_type = event.get("type") or event.get("event_type", "")
        event_id = event.get("event_id", "")
        sequence = event.get("sequence", 0)
        node_id = event.get("node_id", "")

        # 增强日志追踪
        logger.debug(
            f"[执行事件处理] type={event_type}, node={node_id}, "
            f"seq={sequence}, event_id={event_id}"
        )

        # 更新会话模式
        if event_type in ["execution_started", "workflow_started"]:
            self.mode = SessionMode.EXECUTING
            # 推送工作流状态更新（mode 变为 executing）
            if self.on_workflow_update:
                await self.on_workflow_update(self._get_workflow_state())

        elif event_type in ["execution_completed", "workflow_completed"]:
            self.mode = SessionMode.COMPLETED
            # 推送工作流状态更新（mode 变为 completed）
            if self.on_workflow_update:
                await self.on_workflow_update(self._get_workflow_state())

            # 保存执行摘要到对话历史（用于页面刷新后恢复卡片）
            summary_message = self._build_execution_summary_message(event)
            if summary_message:
                self.conversation_history.append(summary_message)
                await self._save_to_database()
                logger.debug(f"执行摘要已保存到对话历史: {event.get('workflow_id')}")

        elif event_type in ["execution_failed", "workflow_failed"]:
            self.mode = SessionMode.BUILDING  # 失败后回到构建模式，允许重试
            if self.on_workflow_update:
                await self.on_workflow_update(self._get_workflow_state())

            # 保存失败摘要到对话历史
            summary_message = self._build_execution_summary_message(
                event, is_failed=True
            )
            if summary_message:
                self.conversation_history.append(summary_message)
                await self._save_to_database()
                logger.debug(
                    f"执行失败摘要已保存到对话历史: {event.get('workflow_id')}"
                )

        elif event_type == "workflow_cancelled":
            self.mode = SessionMode.BUILDING  # 取消后回到构建模式
            if self.on_workflow_update:
                await self.on_workflow_update(self._get_workflow_state())

            # 保存取消摘要到对话历史
            summary_message = self._build_execution_summary_message(
                event, is_cancelled=True
            )
            if summary_message:
                self.conversation_history.append(summary_message)
                await self._save_to_database()
                logger.debug(
                    f"执行取消摘要已保存到对话历史: {event.get('workflow_id')}"
                )

        # 推送执行事件到前端
        if self.on_execution_event:
            await self.on_execution_event(event)

        # 同时推送为消息（便于对话框显示）
        if self.on_message:
            message_content = self._format_execution_message(event)
            if message_content:
                await self.on_message(
                    Message(
                        role="system",
                        content=message_content,
                        message_type="execution_event",
                        data=event,
                    )
                )

    def _format_execution_message(self, event: Dict[str, Any]) -> Optional[str]:
        """格式化执行事件为消息文本。仅对完成/失败返回消息，其余由进度卡片展示。"""
        event_type = event.get("type") or event.get("event_type", "")
        data = event.get("data", {})

        # 执行开始：不发消息，卡片出现即表示开始
        if event_type in ("execution_started", "workflow_started"):
            return None

        # 执行完成：发送结论（使用 final_narrative）
        if event_type in ("execution_completed", "workflow_completed"):
            narrative = data.get("final_narrative")
            return narrative if isinstance(narrative, str) else None

        # 节点完成：不发消息，卡片内展示
        if event_type == "node_completed":
            return None

        if event_type in ("node_started", "node_skipped", "progress_update"):
            return None

        # 失败事件：保留通知
        if event_type == "node_failed":
            node_name = event.get("node_name") or event.get("node_id") or "节点"
            error = data.get("error") or event.get("error", "未知错误")
            return f"[{node_name}] 执行失败: {error}"

        if event_type in ("execution_failed", "workflow_failed"):
            error = data.get("error") or event.get("error", "未知错误")
            return f"工作流执行失败: {error}"

        return None

    def _build_execution_summary_message(
        self, event: Dict[str, Any], is_failed: bool = False, is_cancelled: bool = False
    ) -> Optional[Message]:
        """
        构建执行摘要消息，用于持久化到对话历史

        该消息将在页面刷新后通过消息同步机制恢复，使 ExecutionSummaryCard 能够正确渲染。

        Args:
            event: 执行完成/失败/取消事件
            is_failed: 是否为失败事件
            is_cancelled: 是否为取消事件

        Returns:
            执行摘要消息，或 None（如果无法构建）
        """
        data = event.get("data", {})

        # 获取执行 ID 和工作流信息
        execution_id = event.get("workflow_id") or event.get("execution_id")
        if not execution_id:
            logger.warning("无法构建执行摘要消息：缺少 execution_id")
            return None

        # 获取工作流名称（从 operations 或事件数据中获取）
        workflow_name = "工作流"
        current_workflow = self.operations.get_current_workflow()
        if current_workflow:
            workflow_name = current_workflow.get("name", workflow_name)

        # 获取工作流 ID
        workflow_id = execution_id  # 通常 execution_id 就是 workflow_id

        # 构建节点结果列表（从事件数据中提取）
        node_results = []
        event_node_results = data.get("node_results", {})
        if isinstance(event_node_results, dict):
            for node_id, node_result in event_node_results.items():
                if isinstance(node_result, dict):
                    raw_output = node_result.get("output")

                    # --- 清洗 fullOutput：从原始 agent 输出中提取用户可见部分 ---
                    # 原始结构: {agent_id, task_id, success, result: {summary, narrative, data, highlights, data_format}, ...}
                    # 清洗后:   {summary, narrative, data, highlights, data_format}
                    user_output = raw_output
                    data_format = None
                    if isinstance(raw_output, dict):
                        inner = raw_output.get("result")
                        if isinstance(inner, dict) and (
                            "data" in inner or "summary" in inner
                        ):
                            user_output = {
                                "summary": inner.get("summary"),
                                "narrative": inner.get("narrative"),
                                "data": inner.get("data"),
                                "highlights": inner.get("highlights"),
                            }
                            if inner.get("data_format"):
                                user_output["data_format"] = inner["data_format"]
                                data_format = inner["data_format"]
                        else:
                            # 没有 result 嵌套，直接从顶层取
                            data_format = raw_output.get("data_format")

                    # --- 规范化 status：后端 "success" -> 前端 "completed" ---
                    raw_status = node_result.get("status", "completed")
                    status = "completed" if raw_status == "success" else raw_status

                    # --- outputPreview 强制字符串化 ---
                    preview = node_result.get("output_preview")
                    if preview is not None and not isinstance(preview, str):
                        preview = str(preview)[:200]

                    node_entry = {
                        "nodeId": node_id,
                        "nodeName": node_result.get("node_name", node_id),
                        "status": status,
                        "durationMs": node_result.get("duration_ms", 0),
                        "outputPreview": preview,
                        "outputSummary": node_result.get("output_summary"),
                        "outputNarrative": node_result.get("output_narrative"),
                        "outputHighlights": node_result.get("output_highlights"),
                        "fullOutput": user_output,
                        "error": node_result.get("error"),
                    }
                    if data_format:
                        node_entry["dataFormat"] = data_format
                    node_results.append(node_entry)

        # 计算节点统计
        nodes_completed = data.get(
            "nodes_completed",
            len([r for r in node_results if r.get("status") == "completed"]),
        )
        nodes_failed = data.get(
            "nodes_failed",
            len([r for r in node_results if r.get("status") == "failed"]),
        )
        total_nodes = data.get("total_nodes", len(node_results))

        # 确定执行状态
        if is_cancelled:
            status = "cancelled"
        elif is_failed:
            status = "failed"
        else:
            status = "completed"

        # 构建与前端 ExecutionSummary 类型兼容的数据结构
        summary_data = {
            "type": "execution_summary",
            "executionId": execution_id,
            "workflowId": workflow_id,
            "workflowName": workflow_name,
            "status": status,
            "totalDurationMs": data.get("total_duration_ms", 0),
            "nodesCompleted": nodes_completed,
            "nodesFailed": nodes_failed,
            "totalNodes": total_nodes,
            "startedAt": data.get("started_at", datetime.now().isoformat()),
            "completedAt": data.get("completed_at") or datetime.now().isoformat(),
            "nodeResults": node_results,
            "finalOutput": data.get("final_output"),
            "finalNarrative": data.get("final_narrative"),
            "finalHighlights": data.get("final_highlights"),
        }

        # 如果是失败事件，添加错误信息
        if is_failed:
            summary_data["error"] = data.get("error") or event.get("error", "未知错误")

        # 确定消息内容
        if is_cancelled:
            content = "工作流已停止"
        elif is_failed:
            content = "工作流执行失败"
        else:
            content = "工作流执行完成"

        return Message(
            role="assistant",
            content=content,
            message_type="execution_summary",
            data=summary_data,
        )

    async def process_message(self, user_message: str) -> ConversationResponse:
        """
        处理用户消息

        使用 DialogueAgent 进行智能对话和工具调用。

        Args:
            user_message: 用户输入的自然语言

        Returns:
            对话响应
        """
        # 1. 记录用户消息
        user_msg = Message(role="user", content=user_message)
        self.conversation_history.append(user_msg)

        # 2. 通过 DialogueAgent 处理消息
        try:
            dialogue_response = await self.dialogue_agent.process_message(user_message)

            # 更新会话模式
            if dialogue_response.workflow_changed:
                self.mode = SessionMode.BUILDING

            # 3. 记录助手回复（如果有消息内容）
            # 注意：执行工作流时返回空消息，因为状态更新通过执行事件实时推送
            if dialogue_response.message:
                assistant_msg = Message(
                    role="assistant",
                    content=dialogue_response.message,
                    data=dialogue_response.data,
                )
                self.conversation_history.append(assistant_msg)

                # 4. 推送消息
                if self.on_message:
                    await self.on_message(assistant_msg)

            # 5. 推送工作流更新
            workflow_state = None
            if dialogue_response.workflow_changed:
                workflow_state = self._get_workflow_state()
                if self.on_workflow_update:
                    await self.on_workflow_update(workflow_state)

            # 6. 获取建议操作
            suggested_actions = self._get_suggested_actions()

            # 7. 持久化对话历史
            self.save_conversation_history()

            return ConversationResponse(
                message=dialogue_response.message,
                workflow_state=workflow_state,
                suggested_actions=suggested_actions,
                data=dialogue_response.data,
                workflow_changed=dialogue_response.workflow_changed,
            )

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            error_msg = Message(
                role="assistant",
                content=f"处理请求时出错: {str(e)}",
                message_type="error",
            )
            self.conversation_history.append(error_msg)
            if self.on_message:
                await self.on_message(error_msg)

            # 持久化对话历史（包括错误消息）
            self.save_conversation_history()

            return ConversationResponse(
                message=error_msg.content,
                workflow_changed=False,
            )

    def _get_workflow_state(self) -> Dict[str, Any]:
        """获取工作流状态（用于前端渲染）"""
        current_stage = self.operations.get_current_stage()

        state = {
            "mode": self.mode.value,
            "stage": current_stage,
            "agents": [],
            "nodes": [],
            "edges": [],
            "checkpoints": [],
            "agentDefinitions": {},  # 完整的 AgentDefinition 数据
            "availableModels": self._get_available_models(),  # 可用模型列表
        }

        # 获取已生成的 draft_agents (完整的 AgentDefinition)
        draft_agents = self.operations.get_draft_agents()
        draft_agent_map = {}
        for agent_def in draft_agents:
            # ========== 改进：使用多种 key 确保匹配成功 ==========
            agent_id = agent_def.get("agent_id", "")
            name = agent_def.get("name", "")
            display_name = agent_def.get("display_name", "")

            if agent_id:
                draft_agent_map[agent_id] = agent_def
            if name:
                draft_agent_map[name] = agent_def
                # 处理空格替换的情况
                draft_agent_map[name.replace(" ", "_")] = agent_def
            if display_name:
                draft_agent_map[display_name] = agent_def

        # ========== 改进：只要有 draft_agents 就认为已生成（支持加载模式）==========
        # 原条件要求 current_stage in ["agent", "workflow"]，但加载已保存工作流时 stage 可能不满足
        has_generated_agents = len(draft_agents) > 0

        # 获取规划中的 agent specs
        plan_agents = self.operations.get_current_agents()

        # 从 WorkflowDefinition 获取 node_id 映射（用于执行事件匹配）
        # 映射：多种 key -> workflow_node_id（增加匹配成功率）
        workflow_node_ids = {}
        # ========== 关键修复：从 WorkflowDefinition 获取节点依赖关系 ==========
        # 用于在 plan_agents 没有 dependencies 时（如加载已保存的工作流），从工作流定义获取依赖
        workflow_node_dependencies = (
            {}
        )  # node_id/agent_id/name -> dependencies (node_ids)
        current_workflow = self.operations.get_current_workflow()
        if current_workflow and "nodes" in current_workflow:
            for wf_node in current_workflow["nodes"]:
                agent_id = wf_node.get("agent_id")
                node_id = wf_node.get("node_id")
                name = wf_node.get("name")
                dependencies = wf_node.get("dependencies", [])
                if node_id:
                    # node_id 本身也作为 key（执行事件直接使用 node_id）
                    workflow_node_ids[node_id] = node_id
                    workflow_node_dependencies[node_id] = dependencies
                    # 使用 agent_id 作为 key
                    if agent_id:
                        workflow_node_ids[agent_id] = node_id
                        workflow_node_dependencies[agent_id] = dependencies
                    # 使用 name 作为备用 key
                    if name:
                        workflow_node_ids[name] = node_id
                        workflow_node_dependencies[name] = dependencies
                        # 处理空格替换的情况
                        workflow_node_ids[name.replace(" ", "_")] = node_id
                        workflow_node_dependencies[name.replace(" ", "_")] = (
                            dependencies
                        )

        # 构建 agents 列表和节点
        name_to_id = {}
        for i, agent in enumerate(plan_agents):
            name = agent.get("name", f"Agent_{i}")
            # 使用 or 确保空字符串也会回退到 name
            display_name = agent.get("display_name") or name
            node_id = f"agent_{name.replace(' ', '_')}"
            name_to_id[name] = node_id

            # ========== 改进：尝试多种 key 匹配 AgentDefinition ==========
            agent_id_from_plan = agent.get("agent_id", name.replace(" ", "_"))
            agent_def = (
                draft_agent_map.get(name)
                or draft_agent_map.get(agent_id_from_plan)
                or draft_agent_map.get(display_name)
                or draft_agent_map.get(name.replace(" ", "_"))
            )

            # 根据是否有完整定义来决定状态
            if has_generated_agents and agent_def:
                node_status = "pending"
                node_type = "agent"

                # 将完整的 AgentDefinition 加入 state（使用多种 key 确保前端能匹配）
                state["agentDefinitions"][name] = agent_def
                # 同时使用 agent_id 作为 key（前端可能通过 agentId 查找）
                actual_agent_id = agent_def.get("agent_id")
                if actual_agent_id and actual_agent_id != name:
                    state["agentDefinitions"][actual_agent_id] = agent_def

                # 使用生成后的完整信息，注意使用 or 处理空字符串
                state["agents"].append(
                    {
                        "agentId": agent_def.get("agent_id") or name.replace(" ", "_"),
                        "name": agent_def.get("name") or name,
                        "displayName": agent_def.get("display_name")
                        or display_name
                        or name,
                        "description": agent_def.get("description")
                        or agent.get("task", ""),
                        "domainType": agent_def.get("domain_type") or "general",
                        "executionType": agent_def.get("execution_type") or "default",
                        "tools": [
                            t.get("alias") or t.get("tool_id")
                            for t in agent_def.get("tool_references", [])
                        ],
                    }
                )

                # 获取工具信息
                tools = [
                    t.get("alias") or t.get("tool_id")
                    for t in agent_def.get("tool_references", [])
                ]
            else:
                node_status = "preview"
                node_type = "preview"
                tools = agent.get("suggested_tools", [])

                state["agents"].append(
                    {
                        "agentId": name.replace(" ", "_"),
                        "name": name,
                        "displayName": display_name,
                        "description": agent.get("task", ""),
                        "domainType": agent.get("domain_type", "general"),
                    }
                )

            # 获取 workflow node_id（用于执行事件匹配）
            # 尝试多种方式查找，以处理 agent_id 不匹配的情况
            agent_id = (
                agent_def.get("agent_id") if agent_def else name.replace(" ", "_")
            )
            workflow_node_id = (
                workflow_node_ids.get(agent_id)  # 优先用 agent_id
                or workflow_node_ids.get(name)  # 其次用 name
                or workflow_node_ids.get(display_name)  # 再次用 display_name
                or workflow_node_ids.get(name.replace(" ", "_"))  # 最后用处理过的 name
            )

            # 确定要显示的名称：优先使用 agent_def 的 display_name，否则用 display_name
            final_display_name = (
                (agent_def.get("display_name") if agent_def else None)
                or display_name
                or name
            )

            # ========== 关键修复：获取节点依赖关系 ==========
            # 优先从 plan_agents 获取，其次从 WorkflowDefinition 获取
            node_dependencies = agent.get("dependencies", [])
            if not node_dependencies:
                # 尝试从 workflow_node_dependencies 获取
                node_dependencies = (
                    workflow_node_dependencies.get(agent_id)
                    or workflow_node_dependencies.get(name)
                    or workflow_node_dependencies.get(name.replace(" ", "_"))
                    or []
                )

            state["nodes"].append(
                {
                    "nodeId": node_id,
                    "workflowNodeId": workflow_node_id,  # WorkflowDefinition 中的 node_id，用于匹配执行事件
                    "agentId": agent_id,
                    "name": name,
                    "displayName": final_display_name,
                    "nodeType": node_type,
                    "description": (agent_def.get("description") if agent_def else None)
                    or agent.get("task", ""),
                    "tools": tools,
                    "dependencies": node_dependencies,
                    "status": node_status,
                }
            )

        # 生成边
        # 首先从 plan_agents 获取依赖关系
        edges_added = set()  # 用于去重
        for agent in plan_agents:
            name = agent.get("name", "")
            deps = agent.get("dependencies", [])
            target_id = name_to_id.get(name)

            if target_id:
                for dep in deps:
                    source_id = name_to_id.get(dep)
                    if source_id:
                        edge_key = f"{source_id}->{target_id}"
                        if edge_key not in edges_added:
                            state["edges"].append(
                                {
                                    "source": source_id,
                                    "target": target_id,
                                    "edgeType": "dependency",
                                }
                            )
                            edges_added.add(edge_key)

        # ========== 关键修复：如果 plan_agents 没有生成边，从 WorkflowDefinition 获取 ==========
        # 这种情况发生在加载已保存的工作流时，因为 AgentDefinition 不包含 dependencies
        if not state["edges"] and workflow_node_dependencies:
            # 构建 workflow_node_id -> frontend_node_id 的映射
            wf_node_to_frontend = {}
            for node in state["nodes"]:
                wf_node_id = node.get("workflowNodeId")
                frontend_id = node.get("nodeId")
                agent_id = node.get("agentId")
                node_name = node.get("name")
                if wf_node_id:
                    wf_node_to_frontend[wf_node_id] = frontend_id
                if agent_id:
                    wf_node_to_frontend[agent_id] = frontend_id
                if node_name:
                    wf_node_to_frontend[node_name] = frontend_id
                    wf_node_to_frontend[node_name.replace(" ", "_")] = frontend_id

            # 从 workflow_node_dependencies 生成边
            for key, deps in workflow_node_dependencies.items():
                target_id = wf_node_to_frontend.get(key)
                if target_id and deps:
                    for dep in deps:
                        source_id = wf_node_to_frontend.get(dep)
                        if source_id:
                            edge_key = f"{source_id}->{target_id}"
                            if edge_key not in edges_added:
                                state["edges"].append(
                                    {
                                        "source": source_id,
                                        "target": target_id,
                                        "edgeType": "dependency",
                                    }
                                )
                                edges_added.add(edge_key)

        # 检查点
        checkpoints = self.operations.get_checkpoints()
        for ckpt in checkpoints[-5:]:
            state["checkpoints"].append(
                {
                    "checkpoint_id": ckpt.get("checkpoint_id"),
                    "label": ckpt.get("label"),
                    "timestamp": ckpt.get("timestamp"),
                }
            )

        # 可用工具列表
        state["availableTools"] = self.operations.get_available_tools()

        return state

    def _get_available_models(self) -> List[Dict[str, Any]]:
        """获取可用的 LLM 模型列表（从配置文件读取）"""
        try:
            from src.config import get_model_registry

            model_registry = get_model_registry()
            models_info = model_registry.get_models_info()

            # 转换为前端需要的格式
            result = []
            for model in models_info:
                result.append(
                    {
                        "value": model.get("name", ""),  # 模型标识符
                        "label": model.get(
                            "model_name", model.get("name", "")
                        ),  # 显示名称
                        "type": model.get("type", "language"),
                        "capabilities": model.get("capabilities", []),
                        "costTier": model.get("cost_tier", "medium"),
                        "maxTokens": model.get("max_tokens", 4096),
                    }
                )
            return result
        except Exception as e:
            logger.warning(f"获取可用模型列表失败: {e}")
            # 返回空列表，前端会显示当前配置的模型
            return []

    def _get_suggested_actions(self) -> List[str]:
        """获取建议的操作"""
        stage = self.operations.get_current_stage()
        agents = self.operations.get_current_agents()
        status = self.operations.get_execution_status()

        suggestions = []

        if stage == "idle":
            suggestions.append("创建工作流")
        elif stage == "plan":
            suggestions.append("确认规划")
            suggestions.append("修改规划")
            suggestions.append("重新生成")
        elif stage == "agent":
            suggestions.append("确认 Agents")
            suggestions.append("添加 Agent")
            suggestions.append("修改 Agent")
        elif stage == "workflow":
            suggestions.append("确认工作流")
            suggestions.append("执行工作流")
            suggestions.append("保存工作流")

        if agents:
            suggestions.append("回滚")

        if status.get("is_executing"):
            suggestions = ["暂停执行", "停止执行"]

        return suggestions

    def get_session_info(self) -> Dict[str, Any]:
        """获取会话信息"""
        return {
            "session_id": self.session_id,
            "mode": self.mode.value,
            "stage": self.operations.get_current_stage(),
            "message_count": len(self.conversation_history),
            "has_plan": self.operations.get_current_plan() is not None,
            "agent_count": len(self.operations.get_current_agents()),
            "has_workflow": self.operations.get_current_workflow() is not None,
            "checkpoint_count": len(self.operations.get_checkpoints()),
        }

    def _get_conversation_file_path(self) -> Path:
        """获取对话历史存储文件路径（用于文件备份）"""
        return self.storage_path / "conversation_history.json"

    async def _save_to_file(self) -> None:
        """保存到本地文件（作为备份）- 异步执行"""
        try:
            file_path = self._get_conversation_file_path()
            history_data = {
                "session_id": self.session_id,
                "mode": self.mode.value,
                "messages": [msg.to_dict() for msg in self.conversation_history],
                "saved_at": datetime.now().isoformat(),
            }

            def _sync_write():
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(history_data, f, ensure_ascii=False, indent=2)

            await asyncio.to_thread(_sync_write)
            logger.debug(
                f"对话历史已保存到文件: {len(self.conversation_history)} 条消息"
            )
        except Exception as e:
            logger.error(f"保存对话历史到文件失败: {e}")

    async def _load_from_file(self) -> bool:
        """从本地文件加载 - 异步执行"""
        try:
            file_path = self._get_conversation_file_path()
            if not file_path.exists():
                return False

            def _sync_read():
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)

            history_data = await asyncio.to_thread(_sync_read)

            self.conversation_history = [
                Message(
                    role=msg["role"],
                    content=msg["content"],
                    timestamp=msg.get("timestamp", ""),
                    message_type=msg.get("message_type", "text"),
                    data=msg.get("data"),
                )
                for msg in history_data.get("messages", [])
            ]

            mode_str = history_data.get("mode", "idle")
            try:
                self.mode = SessionMode(mode_str)
                # 服务重启后，执行状态不可恢复（执行任务已丢失），重置为 building
                if self.mode == SessionMode.EXECUTING:
                    self.mode = SessionMode.BUILDING
                    logger.info(
                        "执行状态无法恢复（服务已重启），已重置为 building 模式"
                    )
            except ValueError:
                self.mode = SessionMode.IDLE

            logger.info(
                f"对话历史已从文件恢复: {len(self.conversation_history)} 条消息, 模式: {self.mode.value}"
            )
            return True
        except Exception as e:
            logger.error(f"从文件加载对话历史失败: {e}")
            return False

    def save_conversation_history(self) -> None:
        """持久化对话历史（优先数据库，同时备份到文件）"""
        import os

        # 始终保存到文件作为备份（在后台异步执行）
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在运行中的事件循环中创建任务
                asyncio.create_task(self._save_to_file())
            else:
                loop.run_until_complete(self._save_to_file())
        except RuntimeError:
            # 没有事件循环，同步执行
            self._save_to_file_sync()

        # 如果启用了数据库，异步保存到数据库
        if os.getenv("ENABLE_POSTGRES", "false").lower() == "true":
            try:
                # 在已有事件循环中运行
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 创建任务，异步执行
                    asyncio.create_task(self._save_to_database())
                else:
                    loop.run_until_complete(self._save_to_database())
            except RuntimeError:
                # 没有事件循环，跳过数据库保存
                logger.debug("没有事件循环，跳过数据库保存")

    def _save_to_file_sync(self) -> None:
        """同步保存到文件（备用方法）"""
        try:
            file_path = self._get_conversation_file_path()
            history_data = {
                "session_id": self.session_id,
                "mode": self.mode.value,
                "messages": [msg.to_dict() for msg in self.conversation_history],
                "saved_at": datetime.now().isoformat(),
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)
            logger.debug(
                f"对话历史已保存到文件(同步): {len(self.conversation_history)} 条消息"
            )
        except Exception as e:
            logger.error(f"保存对话历史到文件失败: {e}")

    async def _save_to_database(self) -> bool:
        """异步保存到数据库"""
        try:
            from src.services import create_session_service

            service = await create_session_service()
            if not service:
                logger.debug("数据库服务未启用，跳过保存")
                return False

            # 准备消息数据
            messages = [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": (
                        msg.timestamp.isoformat()
                        if isinstance(msg.timestamp, datetime)
                        else str(msg.timestamp)
                    ),
                    "message_type": msg.message_type,
                    "data": msg.data,
                }
                for msg in self.conversation_history
            ]

            # 获取任务描述
            task_description = ""
            if self.operations and hasattr(self.operations, "_task_description"):
                task_description = self.operations._task_description or ""

            # 保存到数据库（使用完整的 session_id）
            result = await service.save_conversation_history(
                session_id=self.session_id,
                messages=messages,
                mode=self.mode.value,
                task_description=task_description,
            )

            if result:
                logger.debug(
                    f"对话历史已保存到数据库: {self.session_id}, {len(messages)} 条消息"
                )
            return result

        except Exception as e:
            logger.error(f"保存对话历史到数据库失败: {e}")
            import traceback

            logger.debug(f"详细错误: {traceback.format_exc()}")
            return False

    def load_conversation_history(self) -> bool:
        """从持久化存储加载对话历史（优先数据库）

        Returns:
            是否成功加载
        """
        import os

        # 如果启用了数据库，优先从数据库加载
        if os.getenv("ENABLE_POSTGRES", "false").lower() == "true":
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在运行中的循环里，创建新的future
                    future = asyncio.ensure_future(self._load_from_database())
                    # 这里不能直接等待，需要在外部处理
                    # 暂时回退到文件加载
                    return self._load_from_file_sync()
                else:
                    result = loop.run_until_complete(self._load_from_database())
                    if result:
                        return True
            except RuntimeError:
                pass

        # 回退到文件加载
        return self._load_from_file_sync()

    def _load_from_file_sync(self) -> bool:
        """同步从本地文件加载（备用方法）"""
        try:
            file_path = self._get_conversation_file_path()
            if not file_path.exists():
                return False

            with open(file_path, "r", encoding="utf-8") as f:
                history_data = json.load(f)

            self.conversation_history = [
                Message(
                    role=msg["role"],
                    content=msg["content"],
                    timestamp=msg.get("timestamp", ""),
                    message_type=msg.get("message_type", "text"),
                    data=msg.get("data"),
                )
                for msg in history_data.get("messages", [])
            ]

            mode_str = history_data.get("mode", "idle")
            try:
                self.mode = SessionMode(mode_str)
                # 服务重启后，执行状态不可恢复（执行任务已丢失），重置为 building
                if self.mode == SessionMode.EXECUTING:
                    self.mode = SessionMode.BUILDING
                    logger.info(
                        "执行状态无法恢复（服务已重启），已重置为 building 模式"
                    )
            except ValueError:
                self.mode = SessionMode.IDLE

            logger.info(
                f"对话历史已从文件恢复(同步): {len(self.conversation_history)} 条消息, 模式: {self.mode.value}"
            )
            return True
        except Exception as e:
            logger.error(f"从文件加载对话历史失败: {e}")
            return False

    async def _load_from_database(self) -> bool:
        """异步从数据库加载"""
        try:
            from src.services import create_session_service

            service = await create_session_service()
            if not service:
                logger.debug("数据库服务未启用，跳过加载")
                return False

            # 从数据库加载（使用完整的 session_id）
            history_data = await service.load_conversation_history(self.session_id)

            if not history_data:
                logger.debug(f"数据库中没有找到会话历史: {self.session_id}")
                return False

            # 恢复对话历史
            messages = history_data.get("messages", [])
            self.conversation_history = [
                Message(
                    role=msg["role"],
                    content=msg["content"],
                    timestamp=msg.get("timestamp", ""),
                    message_type=msg.get("message_type", "text"),
                    data=msg.get("data"),
                )
                for msg in messages
            ]

            # 恢复会话模式
            mode_str = history_data.get("mode", "idle")
            try:
                self.mode = SessionMode(mode_str)
                # 服务重启后，执行状态不可恢复（执行任务已丢失），重置为 building
                if self.mode == SessionMode.EXECUTING:
                    self.mode = SessionMode.BUILDING
                    logger.info(
                        "执行状态无法恢复（服务已重启），已重置为 building 模式"
                    )
            except ValueError:
                self.mode = SessionMode.IDLE

            logger.info(
                f"对话历史已从数据库恢复: session_id={self.session_id}, {len(self.conversation_history)} 条消息, 模式: {self.mode.value}"
            )
            return True

        except Exception as e:
            logger.error(f"从数据库加载对话历史失败: {e}")
            import traceback

            logger.debug(f"详细错误: {traceback.format_exc()}")
            return False

    async def load_conversation_history_async(self) -> bool:
        """异步加载对话历史（推荐在异步环境中使用）

        Returns:
            是否成功加载
        """
        import os

        # 如果启用了数据库，优先从数据库加载
        if os.getenv("ENABLE_POSTGRES", "false").lower() == "true":
            result = await self._load_from_database()
            if result:
                return True

        # 回退到文件加载（异步）
        return await self._load_from_file()

    async def save_conversation_history_async(self) -> None:
        """异步保存对话历史（推荐在异步环境中使用）"""
        import os

        # 始终保存到文件作为备份（异步）
        await self._save_to_file()

        # 如果启用了数据库，保存到数据库
        if os.getenv("ENABLE_POSTGRES", "false").lower() == "true":
            await self._save_to_database()

    def clear_session(self) -> None:
        """清除会话"""
        self.conversation_history.clear()
        self.dialogue_agent.clear_history()
        self.mode = SessionMode.IDLE
        # 重新初始化操作工具
        self.operations = WorkflowOperationTools(
            meta_agent=self.meta_agent,
            storage_path=str(self.storage_path),
            tool_registry=self.tool_registry,
        )
        self.operations.set_progress_callback(self._handle_agent_generation_progress)
        self.dialogue_agent.ops = self.operations

    async def init_dependencies(self) -> None:
        """
        异步初始化依赖（用于延迟初始化）

        在异步环境中调用此方法来加载会话历史（优先从数据库）。
        """
        if self._initialized:
            return

        # 尝试异步加载会话历史（优先数据库）
        loaded = await self.load_conversation_history_async()
        if loaded:
            logger.info(
                f"已从数据库恢复会话状态: session_id={self.session_id}, messages={len(self.conversation_history)}"
            )

        self._initialized = True

    # ========== 向后兼容的辅助属性 ==========

    @property
    def builder(self) -> Optional[InteractiveWorkflowBuilder]:
        """获取底层 builder（向后兼容）"""
        return self.operations.builder

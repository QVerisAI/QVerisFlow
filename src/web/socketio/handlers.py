"""
Socket.IO 事件处理器

复用 WebSocketHandler 的业务逻辑，适配 Socket.IO 事件模型。
核心改进：所有长时间操作使用 asyncio.create_task() 异步执行，不阻塞事件循环。
"""

import asyncio
import time
import json
from datetime import datetime
from typing import Dict, Any, Optional, Set
from pathlib import Path

import socketio

from src.web.websocket.handlers import WSMessageType, WSMessage
from src.web.socketio.manager import SocketIOConnectionManager
from src.utils.logger import get_logger
from src.evolution.conversational_builder import (
    ConversationalWorkflowBuilder,
    Message,
)

logger = get_logger()


class SocketIOHandler:
    """
    Socket.IO 会话处理器

    核心改进：
    1. 所有长任务异步执行 - 使用 create_task() 不阻塞事件循环
    2. Socket.IO 内置心跳 - 无需手动实现
    3. 复用原有 ConversationalWorkflowBuilder 业务逻辑
    """

    def __init__(
        self,
        sio: socketio.AsyncServer,
        manager: SocketIOConnectionManager,
        sid: str,
        session_id: str,
        builder: ConversationalWorkflowBuilder,
    ):
        self.sio = sio
        self.manager = manager
        self.sid = sid
        self.session_id = session_id
        self.builder = builder

        # 后台任务管理
        self._background_tasks: Set[asyncio.Task] = set()
        self._is_closing = False

        # 设置回调
        self._setup_callbacks()

    def _setup_callbacks(self) -> None:
        """设置业务逻辑回调"""
        self.builder.on_message = self._on_builder_message
        self.builder.on_workflow_update = self._on_workflow_update
        self.builder.on_execution_event = self._on_execution_event
        self.builder.on_generation_progress = self._on_generation_progress

    async def _on_builder_message(self, message: Message) -> None:
        """构建器消息回调"""
        msg_dict = message.to_dict()

        # 检查是否是进度类消息（不应缓存，重发无意义）
        msg_data = msg_dict.get("data", {})
        msg_type = msg_data.get("type", "") if isinstance(msg_data, dict) else ""
        is_progress_message = (
            msg_type
            in {
                "agent_generation_progress",
                "execution_event",
                "progress_update",
                "node_progress",
                "node_thinking",
                "node_stream",
                "node_activity",
            }
            or msg_dict.get("message_type") == "progress"
        )

        await self.emit(
            WSMessageType.CHAT_MESSAGE.value, msg_dict, queue=not is_progress_message
        )

    async def _on_workflow_update(self, state: Dict[str, Any]) -> None:
        """工作流更新回调"""
        await self.emit(WSMessageType.WORKFLOW_UPDATE.value, state)

    async def _on_execution_event(self, event: Dict[str, Any]) -> None:
        """执行事件回调 - 不缓存（实时状态重发无意义）"""
        event_type = event.get("type") or event.get("event_type", "")
        event_id = event.get("event_id", "")
        sequence = event.get("sequence", 0)
        node_id = event.get("node_id", "")
        logger.debug(
            f"[事件推送] type={event_type}, node={node_id}, "
            f"seq={sequence}, event_id={event_id}, sid={self.sid}"
        )
        await self.emit(WSMessageType.EXECUTION_EVENT.value, event, queue=False)

    async def _on_generation_progress(self, event: Dict[str, Any]) -> None:
        """Agent 生成进度回调 - 不缓存（实时状态重发无意义）"""
        await self.emit(
            WSMessageType.AGENT_GENERATION_PROGRESS.value, event, queue=False
        )

    async def emit(
        self, event: str, payload: Dict[str, Any], queue: bool = True
    ) -> None:
        """发送事件到客户端

        Args:
            event: 事件类型
            payload: 消息内容
            queue: 是否在断连时缓存消息（进度类消息应设为 False）
        """
        if self._is_closing:
            return

        message = {
            "type": event,
            "payload": payload,
            # 使用 UTC 时间，确保时间戳准确（Z 后缀表示 UTC）
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }

        if queue:
            await self.manager.send_personal_message(self.session_id, message)
        else:
            await self.manager.send_immediate(self.session_id, message)

    # ==================== 事件处理器 ====================

    async def handle_chat_message(self, data: Dict[str, Any]) -> None:
        """处理聊天消息 - 【核心】异步执行"""
        payload = data.get("payload", {})
        content = payload.get("content", "")

        if not content.strip():
            return

        # 在后台执行，不阻塞事件循环
        task = asyncio.create_task(self._process_chat_background(content))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _process_chat_background(self, content: str) -> None:
        """【后台】处理聊天消息 - 可能耗时数分钟到数小时"""
        try:
            response = await self.builder.process_message(content)

            # 发送建议操作
            if response and response.suggested_actions:
                await self.emit(
                    WSMessageType.SUGGESTED_ACTIONS.value,
                    {"actions": response.suggested_actions},
                )

            # 高亮节点
            if response and response.highlighted_nodes:
                await self.emit(
                    WSMessageType.NODE_HIGHLIGHT.value,
                    {"nodes": response.highlighted_nodes},
                )

        except asyncio.CancelledError:
            logger.info(f"任务被取消: {self.session_id}")
        except Exception as e:
            logger.error(f"处理消息失败: {e}", exc_info=True)
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_user_action(self, data: Dict[str, Any]) -> None:
        """处理用户操作"""
        payload = data.get("payload", {})
        action = payload.get("action", "")
        params = payload.get("params", {})

        # 长时间操作异步执行
        if action in ["execute", "approve", "regenerate"]:
            task = asyncio.create_task(self._execute_action_background(action, params))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        else:
            # 快速操作也异步执行，但不需要后台任务管理
            await self._handle_quick_action(action, params)

    async def _execute_action_background(self, action: str, params: Dict) -> None:
        """【后台】执行操作"""
        try:
            # 将快捷操作转换为对话消息
            action_messages = {
                "approve": "确认",
                "rollback": "撤销",
                "execute": "执行",
                "pause": "暂停",
                "resume": "继续",
                "stop": "停止",
                "save": "保存",
                "regenerate": "重新生成",
            }

            if action in action_messages:
                message = action_messages[action]
                if params:
                    message += f" {json.dumps(params, ensure_ascii=False)}"

                response = await self.builder.process_message(message)

                if response and response.suggested_actions:
                    await self.emit(
                        WSMessageType.SUGGESTED_ACTIONS.value,
                        {"actions": response.suggested_actions},
                    )
        except Exception as e:
            logger.error(f"操作执行失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def _handle_quick_action(self, action: str, params: Dict) -> None:
        """处理快速操作"""
        try:
            action_messages = {
                "pause": "暂停",
                "resume": "继续",
                "stop": "停止",
                "rollback": "撤销",
                "save": "保存",
            }

            if action in action_messages:
                message = action_messages[action]
                if params:
                    message += f" {json.dumps(params, ensure_ascii=False)}"

                response = await self.builder.process_message(message)

                if response and response.suggested_actions:
                    await self.emit(
                        WSMessageType.SUGGESTED_ACTIONS.value,
                        {"actions": response.suggested_actions},
                    )
        except Exception as e:
            logger.error(f"快速操作失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_update_agent(self, data: Dict[str, Any]) -> None:
        """处理 Agent 更新"""
        payload = data.get("payload", {})
        agent_name = payload.get("agent_name", "")
        updates = payload.get("updates", {})

        if not agent_name:
            await self.emit(
                WSMessageType.ERROR.value, {"error": "缺少 agent_name 参数"}
            )
            return

        # 异步执行
        task = asyncio.create_task(self._update_agent_background(agent_name, updates))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _update_agent_background(self, agent_name: str, updates: Dict) -> None:
        """【后台】更新 Agent"""
        try:
            result = await self.builder.operations.update_agent_definition(
                agent_name=agent_name,
                updates=updates,
            )

            if result.success:
                await self.emit(
                    WSMessageType.AGENT_UPDATED.value,
                    {
                        "agent_name": agent_name,
                        "message": result.message,
                        "data": result.data,
                    },
                )

                if result.workflow_changed:
                    await self._on_workflow_update(self.builder._get_workflow_state())
            else:
                await self.emit(WSMessageType.ERROR.value, {"error": result.message})
        except Exception as e:
            logger.error(f"更新 Agent 失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_optimize_prompt(self, data: Dict[str, Any]) -> None:
        """处理 Prompt 优化请求"""
        payload = data.get("payload", {})
        agent_name = payload.get("agent_name", "")
        field = payload.get("field", "")
        current_value = payload.get("current_value", "")
        optimization_goal = payload.get("optimization_goal")

        if not agent_name or not field:
            await self.emit(
                WSMessageType.ERROR.value, {"error": "缺少 agent_name 或 field 参数"}
            )
            return

        task = asyncio.create_task(
            self._optimize_prompt_background(
                agent_name, field, current_value, optimization_goal
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _optimize_prompt_background(
        self,
        agent_name: str,
        field: str,
        current_value: str,
        optimization_goal: Optional[str],
    ) -> None:
        """【后台】优化 Prompt"""
        try:
            result = await self.builder.operations.optimize_agent_prompt(
                agent_name=agent_name,
                field=field,
                current_value=current_value,
                optimization_goal=optimization_goal,
            )

            if result.success:
                await self.emit(
                    WSMessageType.AGENT_UPDATED.value,
                    {
                        "agent_name": agent_name,
                        "message": result.message,
                        "data": result.data,
                        "is_optimization": True,
                    },
                )
            else:
                await self.emit(WSMessageType.ERROR.value, {"error": result.message})
        except Exception as e:
            logger.error(f"优化 Prompt 失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_load_workflow(self, data: Dict[str, Any]) -> None:
        """加载工作流 - 异步执行"""
        task = asyncio.create_task(self._load_workflow_background(data))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _load_workflow_background(self, data: Dict[str, Any]) -> None:
        """【后台】加载工作流 - 与原 WebSocket 处理器逻辑一致"""
        try:
            payload = data.get("payload", {})
            workflow_id = payload.get("workflow_id", "")
            workflow_db_id = payload.get("workflow_db_id", "")

            if not workflow_id and not workflow_db_id:
                await self.emit(
                    WSMessageType.ERROR.value,
                    {"error": "缺少 workflow_id 或 workflow_db_id 参数"},
                )
                return

            from src.services import WorkflowService, AgentService
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import (
                WorkflowDefinitionRepository,
                WorkflowExecutionRepository,
                AgentRepository,
            )
            from src.storage.config import PostgreSQLConfig
            from src.definitions import WorkflowDefinition, AgentDefinition
            from src.evolution.interactive_builder import InteractionStage
            import os

            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            try:
                workflow_repo = WorkflowDefinitionRepository(db._session_factory)
                execution_repo = WorkflowExecutionRepository(db._session_factory)
                agent_repo = AgentRepository(db._session_factory)
                service = WorkflowService(workflow_repo, execution_repo)
                agent_service = AgentService(agent_repo)

                workflow_detail = None
                execution_history = []

                # 优先按数据库主键加载（零歧义）
                if workflow_db_id:
                    workflow_detail = await service.get_workflow_by_id(workflow_db_id)
                    if workflow_detail:
                        execution_history = await execution_repo.get_by_workflow(
                            workflow_definition_id=workflow_detail.id,
                            limit=10,
                        )
                else:
                    # 兼容旧流程：按 workflow_id 加载
                    workflow_detail = await service.get_workflow(workflow_id)
                    if workflow_detail:
                        execution_history = await service.get_execution_history(
                            workflow_detail.workflow_id, limit=10
                        )

                if not workflow_detail:
                    await self.emit(
                        WSMessageType.ERROR.value,
                        {"error": f"工作流不存在: {workflow_db_id or workflow_id}"},
                    )
                    return

                # 将工作流加载到构建器
                definition = workflow_detail.definition
                workflow = WorkflowDefinition(**definition)

                # ========== 关键：加载工作流引用的 Agents ==========
                # 从工作流节点中提取所有 agent_id
                agent_ids = set()
                for node in workflow.nodes:
                    if node.agent_id:
                        agent_ids.add(node.agent_id)
                    # 也检查 config 中的 agent_id（兼容旧格式）
                    if node.config and node.config.get("agent_id"):
                        agent_ids.add(node.config.get("agent_id"))

                # 从数据库加载这些 Agents 并注册到 AgentRegistry
                loaded_agents = []
                loaded_agent_db_ids = {}  # agent_id -> 数据库 ID 映射
                for agent_id in agent_ids:
                    try:
                        agent_model = await agent_repo.get_by_agent_id(agent_id)
                        if agent_model and agent_model.definition_json:
                            # 从数据库记录构建 AgentDefinition
                            agent_def = AgentDefinition(**agent_model.definition_json)
                            loaded_agents.append(agent_def)
                            # 保存数据库 ID 用于后续更新
                            loaded_agent_db_ids[agent_id] = agent_model.id

                            # 注册到 AgentRegistry（用于执行时查找）
                            if not self.builder.meta_agent.agent_registry.get_definition(
                                agent_id
                            ):
                                self.builder.meta_agent.agent_registry.register_definition(
                                    agent_def
                                )
                                logger.info(f"已注册 Agent 到 Registry: {agent_id}")
                        else:
                            logger.warning(f"Agent 不存在于数据库: {agent_id}")
                    except Exception as agent_error:
                        logger.warning(f"加载 Agent {agent_id} 失败: {agent_error}")

                # 使用 operations 管理底层 builder
                ops = self.builder.operations
                if ops.builder:
                    ops.builder.draft_workflow = workflow
                    # 设置加载的 agents 到 draft_agents
                    ops.builder.draft_agents = loaded_agents
                    # ========== 关键：设置 current_stage 为 WORKFLOW ==========
                    ops.builder.current_stage = InteractionStage.WORKFLOW
                    # 保存数据库 ID 用于后续更新
                    ops.builder.loaded_workflow_db_id = workflow_detail.id
                    ops.builder.loaded_agent_db_ids = loaded_agent_db_ids
                else:
                    # 初始化构建器
                    from src.evolution.interactive_builder import (
                        InteractiveWorkflowBuilder,
                    )

                    ops._builder = InteractiveWorkflowBuilder(
                        meta_agent=self.builder.meta_agent,
                        callback=None,
                        storage_path=self.builder.storage_path,
                    )
                    ops._builder.draft_workflow = workflow
                    ops._builder.draft_agents = loaded_agents
                    ops._builder.current_stage = InteractionStage.WORKFLOW
                    ops._builder.loaded_workflow_db_id = workflow_detail.id
                    ops._builder.loaded_agent_db_ids = loaded_agent_db_ids

                ops._task_description = workflow.description or workflow.name

                logger.info(
                    f"工作流加载完成: {workflow.name}, "
                    f"已加载 {len(loaded_agents)}/{len(agent_ids)} 个 Agents"
                )

                # 格式化执行历史
                def _normalize_status(raw_status):
                    if raw_status in ("completed", "success"):
                        return "success"
                    return raw_status

                history_list = []
                for h in execution_history:
                    if hasattr(h, "to_dict"):
                        node_results = h.node_results or {}
                        nodes_completed = sum(
                            1
                            for r in node_results.values()
                            if isinstance(r, dict) and r.get("status") == "completed"
                        )
                        history_list.append(
                            {
                                "id": h.id,
                                "execution_id": h.execution_id,
                                "status": _normalize_status(h.status),
                                "started_at": (
                                    h.started_at.isoformat() if h.started_at else None
                                ),
                                "completed_at": (
                                    h.completed_at.isoformat()
                                    if h.completed_at
                                    else None
                                ),
                                "nodes_completed": nodes_completed,
                                "total_nodes": len(node_results),
                            }
                        )

                # 发送成功响应
                await self.emit(
                    WSMessageType.WORKFLOW_LOADED.value,
                    {
                        "id": workflow_detail.id,
                        "workflow_id": workflow.workflow_id,
                        "name": workflow.name,
                        "description": workflow.description or "",
                        "version": workflow.version or "1.0.0",
                        "message": f"工作流 '{workflow.name}' 加载成功",
                        "execution_history": history_list,
                    },
                )

                # 发送工作流状态更新
                await self._on_workflow_update(self.builder._get_workflow_state())

            finally:
                await db.close()

        except Exception as e:
            logger.error(f"加载工作流失败: {e}", exc_info=True)
            await self.emit(
                WSMessageType.ERROR.value, {"error": f"加载工作流失败: {str(e)}"}
            )

    async def handle_save_workflow(self, data: Dict[str, Any]) -> None:
        """保存工作流"""
        task = asyncio.create_task(self._save_workflow_background(data))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _save_workflow_background(self, data: Dict[str, Any]) -> None:
        """【后台】保存工作流"""
        try:
            payload = data.get("payload", {})
            name = payload.get("name", "")
            description = payload.get("description", "")
            tags = payload.get("tags", [])

            if not name:
                await self.emit(WSMessageType.ERROR.value, {"error": "缺少工作流名称"})
                return

            result = await self.builder.operations.save_workflow(
                name=name,
                description=description,
                tags=tags,
            )

            if result.success:
                await self.emit(
                    WSMessageType.WORKFLOW_SAVED.value,
                    {
                        "id": result.data.get("id", ""),
                        "workflow_id": result.data.get("workflow_id", ""),
                        "name": name,
                        "message": result.message,
                    },
                )
            else:
                await self.emit(WSMessageType.ERROR.value, {"error": result.message})
        except Exception as e:
            logger.error(f"保存工作流失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_list_workflows(self, data: Dict[str, Any]) -> None:
        """列出工作流"""
        try:
            from src.services import WorkflowService
            from src.services.workflow_service import WorkflowFilters
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import (
                WorkflowDefinitionRepository,
                WorkflowExecutionRepository,
            )
            from src.storage.config import PostgreSQLConfig
            import os

            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            try:
                workflow_repo = WorkflowDefinitionRepository(db._session_factory)
                execution_repo = WorkflowExecutionRepository(db._session_factory)
                service = WorkflowService(workflow_repo, execution_repo)

                payload = data.get("payload", {})
                filters = WorkflowFilters(
                    is_active=payload.get("is_active"),
                    tags=payload.get("tags"),
                    query=payload.get("query"),
                    limit=payload.get("limit", 50),
                    offset=payload.get("offset", 0),
                )

                workflows = await service.list_workflows(filters)

                # 将 WorkflowSummary 对象转换为字典
                await self.emit(
                    WSMessageType.WORKFLOWS_LIST.value,
                    {
                        "workflows": [
                            {
                                "id": w.id,
                                "workflow_id": w.workflow_id,
                                "name": w.name,
                                "description": w.description,
                                "version": w.version,
                                "status": w.status,
                                "node_count": w.node_count,
                                "edge_count": w.edge_count,
                                "tags": w.tags,
                                "author": w.author,
                                "created_at": w.created_at,
                                "updated_at": w.updated_at,
                            }
                            for w in workflows
                        ],
                        "total": len(workflows),
                    },
                )
            finally:
                await db.close()
        except Exception as e:
            logger.error(f"列出工作流失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_delete_workflow(self, data: Dict[str, Any]) -> None:
        """删除工作流"""
        try:
            payload = data.get("payload", {})
            workflow_id = payload.get("workflow_id", "")
            workflow_db_id = payload.get("workflow_db_id", "")

            if not workflow_id and not workflow_db_id:
                await self.emit(
                    WSMessageType.ERROR.value,
                    {"error": "缺少 workflow_id 或 workflow_db_id"},
                )
                return

            from src.services import WorkflowService
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import (
                WorkflowDefinitionRepository,
                WorkflowExecutionRepository,
            )
            from src.storage.config import PostgreSQLConfig
            import os

            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            try:
                workflow_repo = WorkflowDefinitionRepository(db._session_factory)
                execution_repo = WorkflowExecutionRepository(db._session_factory)
                service = WorkflowService(workflow_repo, execution_repo)

                result = False
                if workflow_db_id:
                    # 优先使用数据库主键删除（零歧义）
                    result = await service.delete_workflow_by_id(workflow_db_id)
                elif workflow_id:
                    # 兼容旧流程：按 workflow_id 删除
                    result = await service.delete_workflow(workflow_id)

                if result:
                    await self.emit(
                        WSMessageType.WORKFLOW_DELETED.value,
                        {
                            "workflow_id": workflow_id or "",
                            "workflow_db_id": workflow_db_id or "",
                            "message": f"工作流已删除: {workflow_db_id or workflow_id}",
                        },
                    )
                else:
                    await self.emit(
                        WSMessageType.ERROR.value,
                        {"error": f"工作流不存在: {workflow_db_id or workflow_id}"},
                    )
            finally:
                await db.close()
        except Exception as e:
            logger.error(f"删除工作流失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_list_agents(self, data: Dict[str, Any]) -> None:
        """列出可用 Agent"""
        try:
            from src.services import AgentService
            from src.services.agent_service import AgentFilters
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import AgentRepository
            from src.storage.config import PostgreSQLConfig
            import os

            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            try:
                agent_repo = AgentRepository(db._session_factory)
                service = AgentService(agent_repo)

                payload = data.get("payload", {})
                filters = AgentFilters(
                    status=payload.get("status"),
                    domain_type=payload.get("domain_type"),
                    execution_type=payload.get("execution_type"),
                    tags=payload.get("tags"),
                    query=payload.get("query"),
                    is_template=payload.get("is_template"),
                    limit=payload.get("limit", 50),
                    offset=payload.get("offset", 0),
                )

                agents = await service.list_agents(filters)

                # 将 AgentSummary 对象转换为字典
                await self.emit(
                    WSMessageType.AGENTS_LIST.value,
                    {
                        "agents": [
                            {
                                "id": a.id,
                                "agent_id": a.agent_id,
                                "name": a.name,
                                "description": a.description,
                                "version": a.version,
                                "status": a.status,
                                "domain_type": a.domain_type,
                                "execution_type": a.execution_type,
                                "model_name": a.model_name,
                                "tags": a.tags,
                                "is_template": a.is_template,
                                "created_at": a.created_at,
                                "updated_at": a.updated_at,
                            }
                            for a in agents
                        ],
                        "total": len(agents),
                    },
                )
            finally:
                await db.close()
        except Exception as e:
            logger.error(f"列出 Agent 失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_reuse_agent(self, data: Dict[str, Any]) -> None:
        """复用 Agent"""
        task = asyncio.create_task(self._reuse_agent_background(data))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _reuse_agent_background(self, data: Dict[str, Any]) -> None:
        """【后台】复用 Agent"""
        try:
            payload = data.get("payload", {})
            agent_id = payload.get("agent_id", "")
            agent_db_id = payload.get("agent_db_id", "")
            node_id = payload.get("node_id", "")

            if not agent_id and not agent_db_id:
                await self.emit(
                    WSMessageType.ERROR.value, {"error": "缺少 agent_id 或 agent_db_id"}
                )
                return

            from src.services import AgentService
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import AgentRepository
            from src.storage.config import PostgreSQLConfig
            from src.definitions import AgentDefinition
            import os

            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            try:
                agent_repo = AgentRepository(db._session_factory)
                service = AgentService(agent_repo)

                agent_model = None
                target_id = agent_db_id

                if agent_db_id:
                    # 优先按数据库主键加载
                    agent_model = await agent_repo.get_by_id(agent_db_id)
                    target_id = agent_db_id
                elif agent_id:
                    # 兼容旧流程：按 agent_id 加载
                    agent_model = await agent_repo.get_by_agent_id(agent_id)
                    if agent_model:
                        target_id = agent_model.id

                if not agent_model or not agent_model.definition_json:
                    await self.emit(
                        WSMessageType.ERROR.value,
                        {"error": f"Agent 不存在: {agent_db_id or agent_id}"},
                    )
                    return

                agent_def = AgentDefinition(**agent_model.definition_json)

                # 添加到 builder - 使用 operations.builder
                ops = self.builder.operations
                if ops.builder:
                    ops.builder.draft_agents.append(agent_def)
                    if not hasattr(ops.builder, "loaded_agent_db_ids"):
                        ops.builder.loaded_agent_db_ids = {}
                    ops.builder.loaded_agent_db_ids[agent_def.agent_id] = target_id

                # 注册到 AgentRegistry（用于执行时查找）
                if not self.builder.meta_agent.agent_registry.get_definition(
                    agent_def.agent_id
                ):
                    self.builder.meta_agent.agent_registry.register_definition(
                        agent_def
                    )
                    logger.info(f"已注册 Agent 到 Registry: {agent_def.agent_id}")

                await self.emit(
                    WSMessageType.AGENT_REUSED.value,
                    {
                        "agent_id": agent_def.agent_id,
                        "name": agent_def.name,
                        "message": f"Agent '{agent_def.name}' 已添加到工作流",
                    },
                )

                # 更新工作流状态
                await self._on_workflow_update(self.builder._get_workflow_state())
            finally:
                await db.close()
        except Exception as e:
            logger.error(f"复用 Agent 失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_get_agent_templates(self, data: Dict[str, Any]) -> None:
        """获取 Agent 模板"""
        try:
            from src.services import AgentService
            from src.services.agent_service import AgentFilters
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import AgentRepository
            from src.storage.config import PostgreSQLConfig
            import os

            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            try:
                agent_repo = AgentRepository(db._session_factory)
                service = AgentService(agent_repo)

                payload = data.get("payload", {})
                filters = AgentFilters(
                    is_template=True,
                    domain_type=payload.get("domain_type"),
                    limit=payload.get("limit", 50),
                )
                templates = await service.list_agents(filters)

                # 将 AgentSummary 对象转换为字典
                await self.emit(
                    WSMessageType.AGENT_TEMPLATES.value,
                    {
                        "templates": [
                            {
                                "id": t.id,
                                "agent_id": t.agent_id,
                                "name": t.name,
                                "description": t.description,
                                "version": t.version,
                                "status": t.status,
                                "domain_type": t.domain_type,
                                "execution_type": t.execution_type,
                                "model_name": t.model_name,
                                "tags": t.tags,
                                "is_template": t.is_template,
                                "created_at": t.created_at,
                                "updated_at": t.updated_at,
                            }
                            for t in templates
                        ],
                        "total": len(templates),
                    },
                )
            finally:
                await db.close()
        except Exception as e:
            logger.error(f"获取 Agent 模板失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_get_execution_history(self, data: Dict[str, Any]) -> None:
        """获取执行历史"""
        try:
            payload = data.get("payload", {})
            limit = payload.get("limit", 10)

            result = await self.builder.operations.get_execution_history(limit=limit)

            if result.success:
                await self.emit(
                    WSMessageType.EXECUTION_HISTORY.value,
                    {
                        "history": result.data.get("history", []),
                        "message": result.message,
                    },
                )
            else:
                await self.emit(WSMessageType.ERROR.value, {"error": result.message})
        except Exception as e:
            logger.error(f"获取执行历史失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_get_execution_detail(self, data: Dict[str, Any]) -> None:
        """获取执行详情"""
        try:
            payload = data.get("payload", {})
            execution_id = payload.get("execution_id", "")

            if not execution_id:
                await self.emit(
                    WSMessageType.ERROR.value, {"error": "缺少 execution_id"}
                )
                return

            result = await self.builder.operations.get_execution_detail(execution_id)

            if result.success:
                await self.emit(
                    WSMessageType.EXECUTION_DETAIL.value,
                    {
                        "executionId": execution_id,
                        "detail": result.data,
                        "message": result.message,
                    },
                )
            else:
                await self.emit(WSMessageType.ERROR.value, {"error": result.message})
        except Exception as e:
            logger.error(f"获取执行详情失败: {e}")
            await self.emit(WSMessageType.ERROR.value, {"error": str(e)})

    async def handle_sync_messages(self, data: Dict[str, Any]) -> None:
        """同步消息历史"""
        try:
            payload = data.get("payload", {})
            client_count = payload.get("client_message_count", 0)

            server_count = len(self.builder.conversation_history)

            if client_count < server_count:
                missing_messages = self.builder.conversation_history[client_count:]
                logger.info(
                    f"同步缺失消息: 客户端={client_count}, 服务端={server_count}, 同步={len(missing_messages)}条"
                )

                for msg in missing_messages:
                    await self.emit(WSMessageType.CHAT_MESSAGE.value, msg.to_dict())
            else:
                logger.debug(
                    f"消息已同步: 客户端={client_count}, 服务端={server_count}"
                )
        except Exception as e:
            logger.error(f"同步消息失败: {e}")

    async def handle_subscribe(self, data: Dict[str, Any]) -> None:
        """订阅频道"""
        payload = data.get("payload", {})
        channel = payload.get("channel", "")
        if channel:
            await self.manager.subscribe(self.session_id, channel)

    async def handle_unsubscribe(self, data: Dict[str, Any]) -> None:
        """取消订阅"""
        payload = data.get("payload", {})
        channel = payload.get("channel", "")
        if channel:
            await self.manager.unsubscribe(self.session_id, channel)

    async def cleanup(self) -> None:
        """清理资源"""
        self._is_closing = True

        # 取消所有后台任务
        for task in self._background_tasks:
            task.cancel()

        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

        self._background_tasks.clear()
        logger.info(f"Handler 清理完成: {self.session_id}")


# 会话管理器（复用原有的 session_manager）
from src.web.websocket.handlers import session_manager

__all__ = ["SocketIOHandler", "session_manager"]

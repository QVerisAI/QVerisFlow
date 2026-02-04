"""
WebSocket 消息处理器

处理前后端之间的 WebSocket 消息。
"""

from enum import Enum
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass
from datetime import datetime
import json
import asyncio

try:
    from fastapi import WebSocket
except ImportError:
    WebSocket = Any

from src.utils.logger import get_logger
from src.evolution.conversational_builder import (
    ConversationalWorkflowBuilder,
    Message,
    ConversationResponse,
)

from .manager import ConnectionManager, manager as global_manager

logger = get_logger()


class WSMessageType(Enum):
    """WebSocket 消息类型"""

    # 双向
    CHAT_MESSAGE = "chat_message"

    # Client -> Server
    USER_ACTION = "user_action"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    UPDATE_AGENT = "update_agent"  # 更新 Agent 配置
    OPTIMIZE_PROMPT = "optimize_prompt"  # 优化 Prompt
    GET_EXECUTION_HISTORY = "get_execution_history"  # 获取执行历史
    GET_EXECUTION_DETAIL = "get_execution_detail"  # 获取执行详情
    SYNC_MESSAGES = "sync_messages"  # 同步缺失的消息（增量同步）

    # 工作流管理 (Client -> Server)
    LOAD_WORKFLOW = "load_workflow"  # 加载工作流
    SAVE_WORKFLOW = "save_workflow"  # 保存工作流
    LIST_WORKFLOWS = "list_workflows"  # 列出工作流
    DELETE_WORKFLOW = "delete_workflow"  # 删除工作流

    # Agent 管理 (Client -> Server)
    LIST_AGENTS = "list_agents"  # 列出可用 Agent
    REUSE_AGENT = "reuse_agent"  # 复用 Agent
    GET_AGENT_TEMPLATES = "get_agent_templates"  # 获取 Agent 模板

    # Server -> Client
    WORKFLOW_UPDATE = "workflow_update"
    NODE_HIGHLIGHT = "node_highlight"
    PROGRESS_UPDATE = "progress_update"
    EXECUTION_EVENT = "execution_event"
    CHECKPOINT_CREATED = "checkpoint"
    SUGGESTED_ACTIONS = "suggestions"
    ERROR = "error"
    CONNECTED = "connected"
    EXECUTION_HISTORY = "execution_history"  # 执行历史响应
    EXECUTION_DETAIL = "execution_detail"  # 执行详情响应

    # 工作流管理响应 (Server -> Client)
    WORKFLOW_LOADED = "workflow_loaded"  # 工作流已加载
    WORKFLOW_SAVED = "workflow_saved"  # 工作流已保存
    WORKFLOWS_LIST = "workflows_list"  # 工作流列表
    WORKFLOW_DELETED = "workflow_deleted"  # 工作流已删除

    # Agent 管理响应 (Server -> Client)
    AGENTS_LIST = "agents_list"  # Agent 列表
    AGENT_REUSED = "agent_reused"  # Agent 已复用
    AGENT_TEMPLATES = "agent_templates"  # Agent 模板列表

    # Agent 生成相关
    AGENT_GENERATION_PROGRESS = "agent_generation_progress"  # Agent 生成进度
    AGENT_UPDATED = "agent_updated"  # Agent 配置更新

    # 心跳
    PING = "ping"
    PONG = "pong"


@dataclass
class WSMessage:
    """WebSocket 消息"""

    type: WSMessageType
    payload: Dict[str, Any]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WSMessage":
        return cls(
            type=WSMessageType(data.get("type", "chat_message")),
            payload=data.get("payload", {}),
            timestamp=data.get("timestamp", ""),
        )


class WebSocketHandler:
    """
    WebSocket 消息处理器

    处理单个 WebSocket 连接的消息循环。
    """

    def __init__(
        self,
        websocket: WebSocket,
        session_id: str,
        builder: ConversationalWorkflowBuilder,
        connection_manager: Optional[ConnectionManager] = None,
    ):
        """
        初始化处理器

        Args:
            websocket: WebSocket 连接
            session_id: 会话 ID
            builder: 对话式构建器
            connection_manager: 连接管理器
        """
        self.websocket = websocket
        self.session_id = session_id
        self.builder = builder
        self.manager = connection_manager or global_manager

        # 设置构建器回调
        self._setup_callbacks()

    def _setup_callbacks(self) -> None:
        """设置构建器回调"""
        self.builder.on_message = self._on_builder_message
        self.builder.on_workflow_update = self._on_workflow_update
        self.builder.on_execution_event = self._on_execution_event
        self.builder.on_generation_progress = self._on_generation_progress

    def _clear_callbacks(self) -> None:
        """清除构建器回调，防止连接关闭后继续发送消息"""
        # 不再清除回调，因为我们现在有消息队列机制
        # 让回调继续发送消息，断连后会自动缓存
        # 这样重连后可以收到缓存的消息
        pass

    def _is_connection_active(self) -> bool:
        """检查连接是否活跃"""
        return self.manager.is_connected(self.session_id)

    async def _on_builder_message(self, message: Message) -> None:
        """构建器消息回调"""
        ws_message = WSMessage(
            type=WSMessageType.CHAT_MESSAGE,
            payload=message.to_dict(),
        )
        # 对于进度类消息使用立即发送以确保实时性
        if message.message_type in ("progress", "status"):
            await self._send_message_immediate(ws_message)
        else:
            await self._send_message(ws_message)

    async def _on_workflow_update(self, state: Dict[str, Any]) -> None:
        """工作流更新回调"""
        await self._send_message(
            WSMessage(
                type=WSMessageType.WORKFLOW_UPDATE,
                payload=state,
            )
        )

    async def _on_execution_event(self, event: Dict[str, Any]) -> None:
        """执行事件回调"""
        await self._send_message(
            WSMessage(
                type=WSMessageType.EXECUTION_EVENT,
                payload=event,
            )
        )

    async def _on_generation_progress(self, event: Dict[str, Any]) -> None:
        """Agent 生成进度回调 - 使用立即发送确保实时性"""
        await self._send_message_immediate(
            WSMessage(
                type=WSMessageType.AGENT_GENERATION_PROGRESS,
                payload=event,
            )
        )

    async def _send_message(self, message: WSMessage) -> None:
        """发送消息（自动处理断连缓存）"""
        await self.manager.send_personal_message(
            self.session_id,
            message.to_dict(),
            queue_on_disconnect=True,  # 断连时自动缓存
        )

    async def _send_message_immediate(self, message: WSMessage) -> None:
        """立即发送消息（用于进度更新等需要实时性的消息）"""
        success = await self.manager.send_immediate(
            self.session_id,
            message.to_dict(),
        )
        # 如果立即发送失败，回退到普通发送（会缓存）
        if not success:
            await self._send_message(message)

    async def handle_connection(self) -> None:
        """
        处理 WebSocket 连接

        主消息循环：接收消息 -> 处理 -> 发送响应
        """
        # 检查是否是重连（有历史对话记录）
        has_history = len(self.builder.conversation_history) > 0
        history_count = len(self.builder.conversation_history)

        # 发送连接成功消息，包含历史消息数量供前端决定是否需要同步
        await self._send_message(
            WSMessage(
                type=WSMessageType.CONNECTED,
                payload={
                    "session_id": self.session_id,
                    "message": (
                        "连接成功，欢迎使用对话式工作流构建器！"
                        if not has_history
                        else "重新连接成功，已恢复会话状态！"
                    ),
                    "is_reconnect": has_history,
                    "history_count": history_count,  # 告知前端历史消息总数
                    "mode": self.builder.mode.value,  # 告知当前会话模式
                },
            )
        )

        # 发送初始工作流状态
        initial_state = self.builder._get_workflow_state()
        if initial_state:
            await self._send_message(
                WSMessage(
                    type=WSMessageType.WORKFLOW_UPDATE,
                    payload=initial_state,
                )
            )

        # 重连时不再自动发送全部历史消息
        # 前端会根据本地消息数量与 history_count 对比，按需请求缺失的消息
        # 这避免了重复消息导致的 UI 闪动问题
        if has_history:
            logger.info(f"会话历史: {history_count} 条消息（前端可按需请求同步）")

        try:
            while True:
                # 接收消息
                data = await self.websocket.receive_json()

                # 解析消息
                try:
                    message = WSMessage.from_dict(data)
                    await self._handle_message(message)
                except Exception as e:
                    logger.error(f"处理消息失败: {e}")
                    await self._send_message(
                        WSMessage(
                            type=WSMessageType.ERROR,
                            payload={"error": str(e)},
                        )
                    )

        except Exception as e:
            # 正常的连接关闭不需要记录为错误
            error_str = str(e).lower()
            if any(
                keyword in error_str
                for keyword in ["disconnect", "closed", "connection"]
            ):
                logger.debug(f"WebSocket 连接关闭: {self.session_id} - {e}")
            else:
                logger.info(f"WebSocket 连接关闭: {self.session_id} - {e}")
        finally:
            # 不清除回调，让消息继续缓存（重连后可以恢复）
            self._clear_callbacks()
            # 断开连接（但不会影响 session 的生命周期）
            await self.manager.disconnect(self.session_id)

    async def _handle_message(self, message: WSMessage) -> None:
        """处理接收到的消息"""
        logger.debug(f"收到消息: {message.type.value}")

        if message.type == WSMessageType.CHAT_MESSAGE:
            await self._handle_chat_message(message.payload)

        elif message.type == WSMessageType.USER_ACTION:
            await self._handle_user_action(message.payload)

        elif message.type == WSMessageType.UPDATE_AGENT:
            await self._handle_update_agent(message.payload)

        elif message.type == WSMessageType.OPTIMIZE_PROMPT:
            await self._handle_optimize_prompt(message.payload)

        elif message.type == WSMessageType.SUBSCRIBE:
            channel = message.payload.get("channel", "")
            await self.manager.subscribe(self.session_id, channel)

        elif message.type == WSMessageType.UNSUBSCRIBE:
            channel = message.payload.get("channel", "")
            await self.manager.unsubscribe(self.session_id, channel)

        elif message.type == WSMessageType.GET_EXECUTION_HISTORY:
            await self._handle_get_execution_history(message.payload)

        elif message.type == WSMessageType.GET_EXECUTION_DETAIL:
            await self._handle_get_execution_detail(message.payload)

        elif message.type == WSMessageType.SYNC_MESSAGES:
            await self._handle_sync_messages(message.payload)

        # 工作流管理
        elif message.type == WSMessageType.LOAD_WORKFLOW:
            await self._handle_load_workflow(message.payload)

        elif message.type == WSMessageType.SAVE_WORKFLOW:
            await self._handle_save_workflow(message.payload)

        elif message.type == WSMessageType.LIST_WORKFLOWS:
            await self._handle_list_workflows(message.payload)

        elif message.type == WSMessageType.DELETE_WORKFLOW:
            await self._handle_delete_workflow(message.payload)

        # Agent 管理
        elif message.type == WSMessageType.LIST_AGENTS:
            await self._handle_list_agents(message.payload)

        elif message.type == WSMessageType.REUSE_AGENT:
            await self._handle_reuse_agent(message.payload)

        elif message.type == WSMessageType.GET_AGENT_TEMPLATES:
            await self._handle_get_agent_templates(message.payload)

        elif message.type == WSMessageType.PING:
            # 心跳响应
            await self._send_message(
                WSMessage(
                    type=WSMessageType.PONG,
                    payload={"timestamp": message.payload.get("timestamp", "")},
                )
            )

        else:
            logger.warning(f"未知消息类型: {message.type}")

    async def _handle_chat_message(self, payload: Dict[str, Any]) -> None:
        """处理对话消息"""
        user_message = payload.get("content", "")

        if not user_message.strip():
            return

        try:
            # 处理消息并获取响应
            response = await self.builder.process_message(user_message)

            # 发送响应（process_message 已通过回调发送）
            # 这里发送额外的元信息

            # 发送建议操作
            if response.suggested_actions:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.SUGGESTED_ACTIONS,
                        payload={"actions": response.suggested_actions},
                    )
                )

            # 高亮节点
            if response.highlighted_nodes:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.NODE_HIGHLIGHT,
                        payload={"nodes": response.highlighted_nodes},
                    )
                )

        except Exception as e:
            logger.error(f"处理对话消息失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"处理失败: {str(e)}"},
                )
            )

    async def _handle_user_action(self, payload: Dict[str, Any]) -> None:
        """处理用户快捷操作"""
        action = payload.get("action", "")
        params = payload.get("params", {})

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

            # 发送建议操作
            if response.suggested_actions:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.SUGGESTED_ACTIONS,
                        payload={"actions": response.suggested_actions},
                    )
                )
        else:
            logger.warning(f"未知操作: {action}")

    async def _handle_update_agent(self, payload: Dict[str, Any]) -> None:
        """处理 Agent 更新请求"""
        agent_name = payload.get("agent_name", "")
        updates = payload.get("updates", {})

        if not agent_name:
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": "缺少 agent_name 参数"},
                )
            )
            return

        try:
            # 调用 operations 更新 Agent
            result = await self.builder.operations.update_agent_definition(
                agent_name=agent_name,
                updates=updates,
            )

            if result.success:
                # 发送更新成功的响应
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.AGENT_UPDATED,
                        payload={
                            "agent_name": agent_name,
                            "message": result.message,
                            "data": result.data,
                        },
                    )
                )

                # 发送工作流更新
                if result.workflow_changed:
                    await self._on_workflow_update(self.builder._get_workflow_state())
            else:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.ERROR,
                        payload={"error": result.message},
                    )
                )

        except Exception as e:
            logger.error(f"更新 Agent 失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"更新失败: {str(e)}"},
                )
            )

    async def _handle_optimize_prompt(self, payload: Dict[str, Any]) -> None:
        """处理 Prompt 优化请求"""
        agent_name = payload.get("agent_name", "")
        field = payload.get("field", "")
        current_value = payload.get("current_value", "")
        optimization_goal = payload.get("optimization_goal")

        if not agent_name or not field:
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": "缺少 agent_name 或 field 参数"},
                )
            )
            return

        try:
            # 调用 operations 优化 prompt
            result = await self.builder.operations.optimize_agent_prompt(
                agent_name=agent_name,
                field=field,
                current_value=current_value,
                optimization_goal=optimization_goal,
            )

            if result.success:
                # 发送优化结果
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.AGENT_UPDATED,
                        payload={
                            "agent_name": agent_name,
                            "message": result.message,
                            "data": result.data,
                            "is_optimization": True,
                        },
                    )
                )
            else:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.ERROR,
                        payload={"error": result.message},
                    )
                )

        except Exception as e:
            logger.error(f"优化 Prompt 失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"优化失败: {str(e)}"},
                )
            )

    async def _handle_get_execution_history(self, payload: Dict[str, Any]) -> None:
        """处理获取执行历史请求"""
        limit = payload.get("limit", 10)

        try:
            result = await self.builder.operations.get_execution_history(limit=limit)

            if result.success:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.EXECUTION_HISTORY,
                        payload={
                            "history": result.data.get("history", []),
                            "message": result.message,
                        },
                    )
                )
            else:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.ERROR,
                        payload={"error": result.message},
                    )
                )

        except Exception as e:
            logger.error(f"获取执行历史失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"获取执行历史失败: {str(e)}"},
                )
            )

    async def _handle_get_execution_detail(self, payload: Dict[str, Any]) -> None:
        """处理获取执行详情请求"""
        execution_id = payload.get("execution_id", "")

        if not execution_id:
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": "缺少 execution_id 参数"},
                )
            )
            return

        try:
            result = await self.builder.operations.get_execution_detail(execution_id)

            if result.success:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.EXECUTION_DETAIL,
                        payload={
                            "executionId": execution_id,
                            "detail": result.data,
                            "message": result.message,
                        },
                    )
                )
            else:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.ERROR,
                        payload={"error": result.message},
                    )
                )

        except Exception as e:
            logger.error(f"获取执行详情失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"获取执行详情失败: {str(e)}"},
                )
            )

    async def _handle_sync_messages(self, payload: Dict[str, Any]) -> None:
        """
        处理消息同步请求（增量同步）

        前端发送已有的消息数量，后端只返回缺失的消息。
        这避免了重连时发送全部历史消息导致的 UI 闪动。

        Args:
            payload: {
                "client_message_count": int,  # 前端当前消息数量
            }
        """
        client_count = payload.get("client_message_count", 0)

        # 确保从数据库加载最新的消息
        await self._ensure_messages_loaded()

        server_count = len(self.builder.conversation_history)

        # 如果客户端消息少于服务端，发送缺失的消息
        if client_count < server_count:
            missing_messages = self.builder.conversation_history[client_count:]
            logger.info(
                f"同步缺失消息: 客户端={client_count}, 服务端={server_count}, 同步={len(missing_messages)}条"
            )

            for msg in missing_messages:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.CHAT_MESSAGE,
                        payload=msg.to_dict(),
                    )
                )
        else:
            logger.debug(f"消息已同步: 客户端={client_count}, 服务端={server_count}")

    async def _ensure_messages_loaded(self) -> None:
        """确保消息从数据库加载（如果数据库可用）"""
        import os

        if os.getenv("ENABLE_POSTGRES", "false").lower() != "true":
            return

        # 如果 builder 还没初始化，先初始化
        if not self.builder._initialized:
            await self.builder.init_dependencies()

    # ==================== 工作流管理 ====================

    async def _handle_load_workflow(self, payload: Dict[str, Any]) -> None:
        """处理加载工作流请求"""
        workflow_id = payload.get("workflow_id", "")

        if not workflow_id:
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": "缺少 workflow_id 参数"},
                )
            )
            return

        try:
            from src.services import WorkflowService
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import (
                WorkflowDefinitionRepository,
                WorkflowExecutionRepository,
            )
            from src.storage.config import PostgreSQLConfig
            from src.definitions import WorkflowDefinition
            import os

            # 获取服务
            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            workflow_repo = WorkflowDefinitionRepository(db._session_factory)
            execution_repo = WorkflowExecutionRepository(db._session_factory)
            service = WorkflowService(workflow_repo, execution_repo)

            # 获取工作流
            workflow_detail = await service.get_workflow(workflow_id)
            await db.close()

            if not workflow_detail:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.ERROR,
                        payload={"error": f"工作流不存在: {workflow_id}"},
                    )
                )
                return

            # 将工作流加载到构建器
            definition = workflow_detail.definition
            workflow = WorkflowDefinition(**definition)

            if self.builder.builder:
                self.builder.builder.draft_workflow = workflow
            else:
                # 初始化构建器
                from src.evolution.interactive_builder import InteractiveWorkflowBuilder
                from src.evolution.conversational_builder import AutoApproveCallback

                self.builder.builder = InteractiveWorkflowBuilder(
                    meta_agent=self.builder.meta_agent,
                    callback=AutoApproveCallback(),
                    storage_path=self.builder.storage_path,
                )
                self.builder.builder.draft_workflow = workflow

            # 发送成功响应
            await self._send_message(
                WSMessage(
                    type=WSMessageType.WORKFLOW_LOADED,
                    payload={
                        "workflow_id": workflow_id,
                        "name": workflow_detail.name,
                        "description": workflow_detail.description,
                        "message": f"已加载工作流: {workflow_detail.name}",
                    },
                )
            )

            # 发送工作流更新
            await self._on_workflow_update(self.builder._get_workflow_state())

        except Exception as e:
            logger.error(f"加载工作流失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"加载失败: {str(e)}"},
                )
            )

    async def _handle_save_workflow(self, payload: Dict[str, Any]) -> None:
        """处理保存工作流请求"""
        name = payload.get("name", "")
        description = payload.get("description", "")
        tags = payload.get("tags", [])

        if not name:
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": "缺少 name 参数"},
                )
            )
            return

        if not self.builder.builder or not self.builder.builder.draft_workflow:
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": "没有可保存的工作流"},
                )
            )
            return

        try:
            from src.services import WorkflowService
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import (
                WorkflowDefinitionRepository,
                WorkflowExecutionRepository,
            )
            from src.storage.config import PostgreSQLConfig
            import os

            # 更新工作流名称和描述
            self.builder.builder.draft_workflow.name = name
            self.builder.builder.draft_workflow.description = description

            # 获取服务
            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            workflow_repo = WorkflowDefinitionRepository(db._session_factory)
            execution_repo = WorkflowExecutionRepository(db._session_factory)
            service = WorkflowService(workflow_repo, execution_repo)

            # 保存工作流
            workflow_data = self.builder.builder.draft_workflow.model_dump(mode="json")
            workflow_data["tags"] = tags

            workflow_detail = await service.create_workflow_from_dict(
                workflow_data=workflow_data,
                author="websocket",
            )
            await db.close()

            # 发送成功响应
            await self._send_message(
                WSMessage(
                    type=WSMessageType.WORKFLOW_SAVED,
                    payload={
                        "id": workflow_detail.id,
                        "workflow_id": workflow_detail.workflow_id,
                        "name": workflow_detail.name,
                        "message": f"工作流已保存: {workflow_detail.name}",
                    },
                )
            )

        except Exception as e:
            logger.error(f"保存工作流失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"保存失败: {str(e)}"},
                )
            )

    async def _handle_list_workflows(self, payload: Dict[str, Any]) -> None:
        """处理列出工作流请求"""
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

            # 获取服务
            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            workflow_repo = WorkflowDefinitionRepository(db._session_factory)
            execution_repo = WorkflowExecutionRepository(db._session_factory)
            service = WorkflowService(workflow_repo, execution_repo)

            # 获取工作流列表
            filters = WorkflowFilters(
                is_active=payload.get("is_active"),
                tags=payload.get("tags"),
                query=payload.get("query"),
                limit=payload.get("limit", 50),
                offset=payload.get("offset", 0),
            )

            workflows = await service.list_workflows(filters)
            await db.close()

            # 发送响应
            await self._send_message(
                WSMessage(
                    type=WSMessageType.WORKFLOWS_LIST,
                    payload={
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
            )

        except Exception as e:
            logger.error(f"列出工作流失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"获取工作流列表失败: {str(e)}"},
                )
            )

    async def _handle_delete_workflow(self, payload: Dict[str, Any]) -> None:
        """处理删除工作流请求"""
        workflow_id = payload.get("workflow_id", "")

        if not workflow_id:
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": "缺少 workflow_id 参数"},
                )
            )
            return

        try:
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

            workflow_repo = WorkflowDefinitionRepository(db._session_factory)
            execution_repo = WorkflowExecutionRepository(db._session_factory)
            service = WorkflowService(workflow_repo, execution_repo)

            result = await service.delete_workflow(workflow_id)
            await db.close()

            if result:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.WORKFLOW_DELETED,
                        payload={
                            "workflow_id": workflow_id,
                            "message": f"工作流已删除: {workflow_id}",
                        },
                    )
                )
            else:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.ERROR,
                        payload={"error": f"工作流不存在: {workflow_id}"},
                    )
                )

        except Exception as e:
            logger.error(f"删除工作流失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"删除失败: {str(e)}"},
                )
            )

    # ==================== Agent 管理 ====================

    async def _handle_list_agents(self, payload: Dict[str, Any]) -> None:
        """处理列出 Agent 请求"""
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

            agent_repo = AgentRepository(db._session_factory)
            service = AgentService(agent_repo)

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
            await db.close()

            await self._send_message(
                WSMessage(
                    type=WSMessageType.AGENTS_LIST,
                    payload={
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
            )

        except Exception as e:
            logger.error(f"列出 Agent 失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"获取 Agent 列表失败: {str(e)}"},
                )
            )

    async def _handle_reuse_agent(self, payload: Dict[str, Any]) -> None:
        """处理复用 Agent 请求"""
        agent_id = payload.get("agent_id", "")
        node_id = payload.get("node_id")  # 可选：指定添加到哪个节点

        if not agent_id:
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": "缺少 agent_id 参数"},
                )
            )
            return

        try:
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

            agent_repo = AgentRepository(db._session_factory)
            service = AgentService(agent_repo)

            agent_detail = await service.get_agent(agent_id)
            await db.close()

            if not agent_detail:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.ERROR,
                        payload={"error": f"Agent 不存在: {agent_id}"},
                    )
                )
                return

            # 将 Agent 添加到当前工作流
            if self.builder.builder and self.builder.builder.draft_workflow:
                # 从数据库定义创建 AgentDefinition
                agent_def = AgentDefinition(**agent_detail.definition)

                # 添加到工作流的 agents 字典
                self.builder.builder.draft_workflow.agents[agent_id] = agent_def

                # 发送成功响应
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.AGENT_REUSED,
                        payload={
                            "agent_id": agent_id,
                            "name": agent_detail.name,
                            "message": f"已复用 Agent: {agent_detail.name}",
                        },
                    )
                )

                # 发送工作流更新
                await self._on_workflow_update(self.builder._get_workflow_state())
            else:
                await self._send_message(
                    WSMessage(
                        type=WSMessageType.ERROR,
                        payload={"error": "请先创建工作流"},
                    )
                )

        except Exception as e:
            logger.error(f"复用 Agent 失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"复用失败: {str(e)}"},
                )
            )

    async def _handle_get_agent_templates(self, payload: Dict[str, Any]) -> None:
        """处理获取 Agent 模板请求"""
        try:
            from src.services import AgentService
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

            agent_repo = AgentRepository(db._session_factory)
            service = AgentService(agent_repo)

            templates = await service.get_templates(
                domain_type=payload.get("domain_type"),
                limit=payload.get("limit", 50),
            )
            await db.close()

            await self._send_message(
                WSMessage(
                    type=WSMessageType.AGENT_TEMPLATES,
                    payload={
                        "templates": [
                            {
                                "id": t.id,
                                "agent_id": t.agent_id,
                                "name": t.name,
                                "description": t.description,
                                "version": t.version,
                                "domain_type": t.domain_type,
                                "execution_type": t.execution_type,
                                "model_name": t.model_name,
                                "tags": t.tags,
                            }
                            for t in templates
                        ],
                        "total": len(templates),
                    },
                )
            )

        except Exception as e:
            logger.error(f"获取 Agent 模板失败: {e}")
            await self._send_message(
                WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": f"获取模板失败: {str(e)}"},
                )
            )


class SessionManager:
    """
    会话管理器

    管理多个构建会话。
    """

    def __init__(self):
        # session_id -> ConversationalWorkflowBuilder
        self.sessions: Dict[str, ConversationalWorkflowBuilder] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self, session_id: str, builder: ConversationalWorkflowBuilder
    ) -> None:
        """创建会话"""
        async with self._lock:
            self.sessions[session_id] = builder

    async def get_session(
        self, session_id: str
    ) -> Optional[ConversationalWorkflowBuilder]:
        """获取会话"""
        return self.sessions.get(session_id)

    async def remove_session(self, session_id: str) -> None:
        """移除会话"""
        async with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]

    def list_sessions(self) -> list:
        """列出所有会话"""
        return [
            {
                "session_id": sid,
                "mode": builder.mode.value,
                "message_count": len(builder.conversation_history),
            }
            for sid, builder in self.sessions.items()
        ]


# 全局会话管理器
session_manager = SessionManager()

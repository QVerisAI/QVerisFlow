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
        self.builder.on_message = None
        self.builder.on_workflow_update = None
        self.builder.on_execution_event = None
        self.builder.on_generation_progress = None
    
    async def _on_builder_message(self, message: Message) -> None:
        """构建器消息回调"""
        await self._send_message(WSMessage(
            type=WSMessageType.CHAT_MESSAGE,
            payload=message.to_dict(),
        ))
    
    async def _on_workflow_update(self, state: Dict[str, Any]) -> None:
        """工作流更新回调"""
        await self._send_message(WSMessage(
            type=WSMessageType.WORKFLOW_UPDATE,
            payload=state,
        ))
    
    async def _on_execution_event(self, event: Dict[str, Any]) -> None:
        """执行事件回调"""
        await self._send_message(WSMessage(
            type=WSMessageType.EXECUTION_EVENT,
            payload=event,
        ))
    
    async def _on_generation_progress(self, event: Dict[str, Any]) -> None:
        """Agent 生成进度回调"""
        await self._send_message(WSMessage(
            type=WSMessageType.AGENT_GENERATION_PROGRESS,
            payload=event,
        ))
    
    async def _send_message(self, message: WSMessage) -> None:
        """发送消息"""
        await self.manager.send_personal_message(
            self.session_id,
            message.to_dict(),
        )
    
    async def handle_connection(self) -> None:
        """
        处理 WebSocket 连接
        
        主消息循环：接收消息 -> 处理 -> 发送响应
        """
        # 检查是否是重连（有历史对话记录）
        has_history = len(self.builder.conversation_history) > 0
        
        # 发送连接成功消息
        await self._send_message(WSMessage(
            type=WSMessageType.CONNECTED,
            payload={
                "session_id": self.session_id,
                "message": "连接成功，欢迎使用对话式工作流构建器！" if not has_history else "重新连接成功，已恢复会话状态！",
                "is_reconnect": has_history,
            },
        ))
        
        # 发送初始工作流状态
        initial_state = self.builder._get_workflow_state()
        if initial_state:
            await self._send_message(WSMessage(
                type=WSMessageType.WORKFLOW_UPDATE,
                payload=initial_state,
            ))
        
        # 如果是重连，发送历史对话记录
        if has_history:
            logger.info(f"恢复会话历史: {len(self.builder.conversation_history)} 条消息")
            for msg in self.builder.conversation_history:
                await self._send_message(WSMessage(
                    type=WSMessageType.CHAT_MESSAGE,
                    payload=msg.to_dict(),
                ))
        
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
                    await self._send_message(WSMessage(
                        type=WSMessageType.ERROR,
                        payload={"error": str(e)},
                    ))
                    
        except Exception as e:
            logger.info(f"WebSocket 连接关闭: {e}")
        finally:
            # 清除回调，防止后续消息发送尝试
            self._clear_callbacks()
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
        
        elif message.type == WSMessageType.PING:
            # 心跳响应
            await self._send_message(WSMessage(
                type=WSMessageType.PONG,
                payload={"timestamp": message.payload.get("timestamp", "")},
            ))
        
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
                await self._send_message(WSMessage(
                    type=WSMessageType.SUGGESTED_ACTIONS,
                    payload={"actions": response.suggested_actions},
                ))
            
            # 高亮节点
            if response.highlighted_nodes:
                await self._send_message(WSMessage(
                    type=WSMessageType.NODE_HIGHLIGHT,
                    payload={"nodes": response.highlighted_nodes},
                ))
                
        except Exception as e:
            logger.error(f"处理对话消息失败: {e}")
            await self._send_message(WSMessage(
                type=WSMessageType.ERROR,
                payload={"error": f"处理失败: {str(e)}"},
            ))
    
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
                await self._send_message(WSMessage(
                    type=WSMessageType.SUGGESTED_ACTIONS,
                    payload={"actions": response.suggested_actions},
                ))
        else:
            logger.warning(f"未知操作: {action}")
    
    async def _handle_update_agent(self, payload: Dict[str, Any]) -> None:
        """处理 Agent 更新请求"""
        agent_name = payload.get("agent_name", "")
        updates = payload.get("updates", {})
        
        if not agent_name:
            await self._send_message(WSMessage(
                type=WSMessageType.ERROR,
                payload={"error": "缺少 agent_name 参数"},
            ))
            return
        
        try:
            # 调用 operations 更新 Agent
            result = await self.builder.operations.update_agent_definition(
                agent_name=agent_name,
                updates=updates,
            )
            
            if result.success:
                # 发送更新成功的响应
                await self._send_message(WSMessage(
                    type=WSMessageType.AGENT_UPDATED,
                    payload={
                        "agent_name": agent_name,
                        "message": result.message,
                        "data": result.data,
                    },
                ))
                
                # 发送工作流更新
                if result.workflow_changed:
                    await self._on_workflow_update(self.builder._get_workflow_state())
            else:
                await self._send_message(WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": result.message},
                ))
                
        except Exception as e:
            logger.error(f"更新 Agent 失败: {e}")
            await self._send_message(WSMessage(
                type=WSMessageType.ERROR,
                payload={"error": f"更新失败: {str(e)}"},
            ))
    
    async def _handle_optimize_prompt(self, payload: Dict[str, Any]) -> None:
        """处理 Prompt 优化请求"""
        agent_name = payload.get("agent_name", "")
        field = payload.get("field", "")
        current_value = payload.get("current_value", "")
        optimization_goal = payload.get("optimization_goal")
        
        if not agent_name or not field:
            await self._send_message(WSMessage(
                type=WSMessageType.ERROR,
                payload={"error": "缺少 agent_name 或 field 参数"},
            ))
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
                await self._send_message(WSMessage(
                    type=WSMessageType.AGENT_UPDATED,
                    payload={
                        "agent_name": agent_name,
                        "message": result.message,
                        "data": result.data,
                        "is_optimization": True,
                    },
                ))
            else:
                await self._send_message(WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": result.message},
                ))
                
        except Exception as e:
            logger.error(f"优化 Prompt 失败: {e}")
            await self._send_message(WSMessage(
                type=WSMessageType.ERROR,
                payload={"error": f"优化失败: {str(e)}"},
            ))
    
    async def _handle_get_execution_history(self, payload: Dict[str, Any]) -> None:
        """处理获取执行历史请求"""
        limit = payload.get("limit", 10)
        
        try:
            result = await self.builder.operations.get_execution_history(limit=limit)
            
            if result.success:
                await self._send_message(WSMessage(
                    type=WSMessageType.EXECUTION_HISTORY,
                    payload={
                        "history": result.data.get("history", []),
                        "message": result.message,
                    },
                ))
            else:
                await self._send_message(WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": result.message},
                ))
                
        except Exception as e:
            logger.error(f"获取执行历史失败: {e}")
            await self._send_message(WSMessage(
                type=WSMessageType.ERROR,
                payload={"error": f"获取执行历史失败: {str(e)}"},
            ))
    
    async def _handle_get_execution_detail(self, payload: Dict[str, Any]) -> None:
        """处理获取执行详情请求"""
        execution_id = payload.get("execution_id", "")
        
        if not execution_id:
            await self._send_message(WSMessage(
                type=WSMessageType.ERROR,
                payload={"error": "缺少 execution_id 参数"},
            ))
            return
        
        try:
            result = await self.builder.operations.get_execution_detail(execution_id)
            
            if result.success:
                await self._send_message(WSMessage(
                    type=WSMessageType.EXECUTION_DETAIL,
                    payload={
                        "executionId": execution_id,
                        "detail": result.data,
                        "message": result.message,
                    },
                ))
            else:
                await self._send_message(WSMessage(
                    type=WSMessageType.ERROR,
                    payload={"error": result.message},
                ))
                
        except Exception as e:
            logger.error(f"获取执行详情失败: {e}")
            await self._send_message(WSMessage(
                type=WSMessageType.ERROR,
                payload={"error": f"获取执行详情失败: {str(e)}"},
            ))


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
        self,
        session_id: str,
        builder: ConversationalWorkflowBuilder
    ) -> None:
        """创建会话"""
        async with self._lock:
            self.sessions[session_id] = builder
    
    async def get_session(
        self,
        session_id: str
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

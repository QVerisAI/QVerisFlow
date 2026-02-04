"""
WebSocket 连接管理器

管理 WebSocket 连接的生命周期和消息广播。
"""

from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import asyncio
import json
import time

try:
    from fastapi import WebSocket, WebSocketDisconnect
except ImportError:
    WebSocket = Any
    WebSocketDisconnect = Exception

from src.utils.logger import get_logger

logger = get_logger()


class ConnectionState(Enum):
    """连接状态"""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"


@dataclass
class ConnectionInfo:
    """连接信息"""

    websocket: WebSocket
    session_id: str
    user_id: Optional[str] = None
    connected_at: datetime = field(default_factory=datetime.now)
    subscriptions: Set[str] = field(default_factory=set)
    state: ConnectionState = ConnectionState.CONNECTED
    last_activity: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "connected_at": self.connected_at.isoformat(),
            "subscriptions": list(self.subscriptions),
            "state": self.state.value,
        }

    def is_active(self) -> bool:
        """检查连接是否活跃"""
        return self.state == ConnectionState.CONNECTED


class ConnectionManager:
    """
    WebSocket 连接管理器

    功能：
    - 管理多个 WebSocket 连接
    - 支持按会话 ID 或用户 ID 发送消息
    - 支持频道订阅和广播
    - 支持连接状态跟踪和自动清理
    """

    def __init__(self):
        # 活跃连接：session_id -> ConnectionInfo
        self.active_connections: Dict[str, ConnectionInfo] = {}

        # 频道订阅：channel -> Set[session_id]
        self.channels: Dict[str, Set[str]] = {}

        # 锁，用于并发控制
        self._lock = asyncio.Lock()

        # 消息队列：session_id -> List[message]（用于断连期间缓存消息）
        self._message_queues: Dict[str, List[Dict[str, Any]]] = {}

        # 最大队列长度
        self._max_queue_size = 100

    async def connect(
        self, websocket: WebSocket, session_id: str, user_id: Optional[str] = None
    ) -> ConnectionInfo:
        """
        接受新的 WebSocket 连接

        Args:
            websocket: WebSocket 连接
            session_id: 会话 ID
            user_id: 用户 ID（可选）

        Returns:
            连接信息
        """
        await websocket.accept()

        async with self._lock:
            # 如果已有旧连接，先标记为断开（而不是直接删除）
            if session_id in self.active_connections:
                old_conn = self.active_connections[session_id]
                old_conn.state = ConnectionState.DISCONNECTED
                logger.debug(f"替换旧连接: session_id={session_id}")

            conn_info = ConnectionInfo(
                websocket=websocket,
                session_id=session_id,
                user_id=user_id,
                state=ConnectionState.CONNECTED,
                last_activity=time.time(),
            )
            self.active_connections[session_id] = conn_info

        logger.info(f"WebSocket 连接已建立: session_id={session_id}")

        # 发送队列中的缓存消息
        await self._flush_message_queue(session_id)

        return conn_info

    async def _flush_message_queue(self, session_id: str) -> None:
        """发送缓存的消息队列"""
        if session_id not in self._message_queues:
            return

        queue = self._message_queues.pop(session_id, [])
        if queue:
            logger.info(f"发送缓存消息: session_id={session_id}, count={len(queue)}")
            for msg in queue:
                await self.send_personal_message(session_id, msg)

    async def disconnect(self, session_id: str) -> None:
        """
        断开 WebSocket 连接

        Args:
            session_id: 会话 ID
        """
        async with self._lock:
            if session_id in self.active_connections:
                conn_info = self.active_connections[session_id]

                # 先标记状态，防止其他任务继续发送
                conn_info.state = ConnectionState.DISCONNECTED

                # 延迟删除，给正在进行的操作一些时间完成
                # 但不在锁内等待

            if session_id in self.active_connections:
                conn_info = self.active_connections.pop(session_id)

                # 从所有频道中移除
                for channel in list(conn_info.subscriptions):
                    if channel in self.channels:
                        self.channels[channel].discard(session_id)

                logger.info(f"WebSocket 连接已断开: session_id={session_id}")

    async def subscribe(self, session_id: str, channel: str) -> bool:
        """
        订阅频道

        Args:
            session_id: 会话 ID
            channel: 频道名称

        Returns:
            是否成功
        """
        async with self._lock:
            if session_id not in self.active_connections:
                return False

            # 添加到频道
            if channel not in self.channels:
                self.channels[channel] = set()
            self.channels[channel].add(session_id)

            # 更新连接订阅列表
            self.active_connections[session_id].subscriptions.add(channel)

            logger.debug(f"会话 {session_id} 订阅频道: {channel}")
            return True

    async def unsubscribe(self, session_id: str, channel: str) -> bool:
        """
        取消订阅频道

        Args:
            session_id: 会话 ID
            channel: 频道名称

        Returns:
            是否成功
        """
        async with self._lock:
            if session_id not in self.active_connections:
                return False

            # 从频道移除
            if channel in self.channels:
                self.channels[channel].discard(session_id)

            # 更新连接订阅列表
            self.active_connections[session_id].subscriptions.discard(channel)

            return True

    async def send_personal_message(
        self, session_id: str, message: Dict[str, Any], queue_on_disconnect: bool = True
    ) -> bool:
        """
        发送个人消息

        Args:
            session_id: 目标会话 ID
            message: 消息内容
            queue_on_disconnect: 如果连接断开，是否将消息加入队列等待重连

        Returns:
            是否成功
        """
        conn_info = self.active_connections.get(session_id)

        if not conn_info:
            # 连接不存在，如果需要则缓存消息
            if queue_on_disconnect:
                self._queue_message(session_id, message)
            # 不再记录 warning，因为这是正常的断连情况
            logger.debug(f"连接不存在，消息已缓存: {session_id}")
            return False

        # 检查连接状态
        if not conn_info.is_active():
            if queue_on_disconnect:
                self._queue_message(session_id, message)
            logger.debug(f"连接非活跃状态，消息已缓存: {session_id}")
            return False

        try:
            websocket = conn_info.websocket

            # 检查 WebSocket 状态（如果可用）
            # Starlette WebSocket 的状态检查
            client_state = getattr(websocket, "client_state", None)
            if client_state is not None:
                from starlette.websockets import WebSocketState

                if client_state != WebSocketState.CONNECTED:
                    if queue_on_disconnect:
                        self._queue_message(session_id, message)
                    logger.debug(f"WebSocket 未连接，消息已缓存: {session_id}")
                    return False

            await websocket.send_json(message)
            conn_info.last_activity = time.time()
            return True
        except Exception as e:
            error_str = str(e)
            # 连接关闭相关的错误不需要作为 ERROR 级别日志
            if any(
                keyword in error_str.lower()
                for keyword in ["closed", "disconnect", "not connected", "accept"]
            ):
                logger.debug(f"WebSocket 已关闭，发送失败: {session_id} - {error_str}")
                # 缓存消息以便重连后发送
                if queue_on_disconnect:
                    self._queue_message(session_id, message)
            else:
                logger.error(f"发送消息失败: {session_id} - {e}")

            # 标记连接为断开状态
            if conn_info:
                conn_info.state = ConnectionState.DISCONNECTED

            return False

    def _queue_message(self, session_id: str, message: Dict[str, Any]) -> None:
        """将消息加入队列"""
        if session_id not in self._message_queues:
            self._message_queues[session_id] = []

        queue = self._message_queues[session_id]

        # 限制队列大小
        if len(queue) >= self._max_queue_size:
            # 移除最旧的消息
            queue.pop(0)

        queue.append(message)

    def is_connected(self, session_id: str) -> bool:
        """检查会话是否已连接"""
        conn_info = self.active_connections.get(session_id)
        return conn_info is not None and conn_info.is_active()

    async def send_immediate(self, session_id: str, message: Dict[str, Any]) -> bool:
        """
        立即发送消息（不缓存，不排队）

        用于需要立即发送的优先级消息，如进度更新。
        如果发送失败，不会缓存消息。

        Args:
            session_id: 目标会话 ID
            message: 消息内容

        Returns:
            是否成功发送
        """
        conn_info = self.active_connections.get(session_id)

        if not conn_info or not conn_info.is_active():
            return False

        try:
            websocket = conn_info.websocket

            # 检查 WebSocket 状态
            client_state = getattr(websocket, "client_state", None)
            if client_state is not None:
                from starlette.websockets import WebSocketState

                if client_state != WebSocketState.CONNECTED:
                    return False

            await websocket.send_json(message)
            conn_info.last_activity = time.time()
            return True
        except Exception as e:
            logger.debug(f"立即发送消息失败: {session_id} - {e}")
            return False

    async def broadcast(
        self, message: Dict[str, Any], exclude: Optional[Set[str]] = None
    ) -> int:
        """
        广播消息给所有连接

        Args:
            message: 消息内容
            exclude: 排除的会话 ID 集合

        Returns:
            成功发送的连接数
        """
        exclude = exclude or set()
        success_count = 0

        for session_id in list(self.active_connections.keys()):
            if session_id in exclude:
                continue

            if await self.send_personal_message(session_id, message):
                success_count += 1

        return success_count

    async def broadcast_to_channel(
        self, channel: str, message: Dict[str, Any], exclude: Optional[Set[str]] = None
    ) -> int:
        """
        广播消息给频道订阅者

        Args:
            channel: 频道名称
            message: 消息内容
            exclude: 排除的会话 ID 集合

        Returns:
            成功发送的连接数
        """
        exclude = exclude or set()
        success_count = 0

        subscribers = self.channels.get(channel, set())

        for session_id in list(subscribers):
            if session_id in exclude:
                continue

            if await self.send_personal_message(session_id, message):
                success_count += 1

        return success_count

    async def send_to_user(self, user_id: str, message: Dict[str, Any]) -> int:
        """
        发送消息给用户的所有连接

        Args:
            user_id: 用户 ID
            message: 消息内容

        Returns:
            成功发送的连接数
        """
        success_count = 0

        for session_id, conn_info in list(self.active_connections.items()):
            if conn_info.user_id == user_id:
                if await self.send_personal_message(session_id, message):
                    success_count += 1

        return success_count

    def get_connection(self, session_id: str) -> Optional[ConnectionInfo]:
        """获取连接信息"""
        return self.active_connections.get(session_id)

    def get_connection_count(self) -> int:
        """获取活跃连接数"""
        return len(self.active_connections)

    def get_channel_subscribers(self, channel: str) -> Set[str]:
        """获取频道订阅者"""
        return self.channels.get(channel, set()).copy()

    def list_connections(self) -> List[Dict[str, Any]]:
        """列出所有连接信息"""
        return [conn.to_dict() for conn in self.active_connections.values()]


# 全局连接管理器实例
manager = ConnectionManager()

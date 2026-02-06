"""
Socket.IO 连接管理器

保持与原 ConnectionManager 相同的接口，最小化业务逻辑改动。
"""

import asyncio
import time
from typing import Dict, Set, Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import socketio

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
    """连接信息 - 保持与原结构兼容"""

    sid: str  # Socket.IO session id
    session_id: str  # 业务 session id
    user_id: Optional[str] = None
    connected_at: datetime = field(default_factory=datetime.now)
    subscriptions: Set[str] = field(default_factory=set)
    state: ConnectionState = ConnectionState.CONNECTED
    last_activity: float = field(default_factory=time.time)

    def is_active(self) -> bool:
        """检查连接是否活跃"""
        return self.state == ConnectionState.CONNECTED

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "sid": self.sid,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "connected_at": self.connected_at.isoformat(),
            "subscriptions": list(self.subscriptions),
            "state": self.state.value,
        }


class SocketIOConnectionManager:
    """
    Socket.IO 连接管理器

    保持与原 ConnectionManager 相同的公共接口：
    - connect() / disconnect()
    - subscribe() / unsubscribe()
    - send_personal_message() / broadcast() / broadcast_to_channel()
    - is_connected() / get_connection()
    """

    def __init__(self, sio: socketio.AsyncServer):
        self.sio = sio

        # sid -> ConnectionInfo
        self._connections: Dict[str, ConnectionInfo] = {}

        # session_id -> sid 映射
        self._session_to_sid: Dict[str, str] = {}

        # 频道订阅
        self.channels: Dict[str, Set[str]] = {}

        # 消息队列（断连期间缓存）
        self._message_queues: Dict[str, List[Dict[str, Any]]] = {}
        self._max_queue_size = 100

        # 并发控制
        self._lock = asyncio.Lock()

    async def connect(
        self, sid: str, session_id: str, user_id: Optional[str] = None
    ) -> ConnectionInfo:
        """
        注册新连接

        Args:
            sid: Socket.IO session id
            session_id: 业务 session id
            user_id: 用户 ID（可选）

        Returns:
            连接信息
        """
        async with self._lock:
            # 处理同一 session 的重连
            if session_id in self._session_to_sid:
                old_sid = self._session_to_sid[session_id]
                if old_sid in self._connections:
                    self._connections[old_sid].state = ConnectionState.DISCONNECTED
                    del self._connections[old_sid]
                    logger.debug(f"替换旧连接: session_id={session_id}")

            conn_info = ConnectionInfo(
                sid=sid,
                session_id=session_id,
                user_id=user_id,
            )
            self._connections[sid] = conn_info
            self._session_to_sid[session_id] = sid

            # 加入以 session_id 命名的房间，便于定向发送
            await self.sio.enter_room(sid, session_id)

        logger.info(f"Socket.IO 连接: sid={sid}, session_id={session_id}")

        # 刷新缓存消息
        await self._flush_message_queue(session_id)

        return conn_info

    async def disconnect(self, sid: str) -> None:
        """
        断开连接

        Args:
            sid: Socket.IO session id
        """
        async with self._lock:
            if sid not in self._connections:
                return

            conn_info = self._connections.pop(sid)
            conn_info.state = ConnectionState.DISCONNECTED

            # 移除 session 映射
            if conn_info.session_id in self._session_to_sid:
                if self._session_to_sid[conn_info.session_id] == sid:
                    del self._session_to_sid[conn_info.session_id]

            # 从频道移除
            for channel in list(conn_info.subscriptions):
                if channel in self.channels:
                    self.channels[channel].discard(conn_info.session_id)

        logger.info(f"Socket.IO 断开: sid={sid}")

    async def send_personal_message(
        self, session_id: str, message: Dict[str, Any], queue_on_disconnect: bool = True
    ) -> bool:
        """
        发送消息到指定 session

        Args:
            session_id: 目标会话 ID
            message: 消息内容
            queue_on_disconnect: 如果连接断开，是否将消息加入队列

        Returns:
            是否成功发送
        """
        sid = self._session_to_sid.get(session_id)

        if not sid or sid not in self._connections:
            if queue_on_disconnect:
                self._queue_message(session_id, message)
            logger.debug(f"连接不存在，消息已缓存: {session_id}")
            return False

        conn_info = self._connections[sid]
        if not conn_info.is_active():
            if queue_on_disconnect:
                self._queue_message(session_id, message)
            logger.debug(f"连接非活跃状态，消息已缓存: {session_id}")
            return False

        try:
            # 提取事件名
            event_name = message.get("type", "message")
            # Socket.IO 发送到 session_id 房间
            await self.sio.emit(event_name, message, room=session_id)
            conn_info.last_activity = time.time()
            return True
        except Exception as e:
            logger.error(f"发送消息失败: {session_id} - {e}")
            if queue_on_disconnect:
                self._queue_message(session_id, message)
            return False

    async def send_immediate(self, session_id: str, message: Dict[str, Any]) -> bool:
        """
        立即发送消息（不缓存，不排队）

        Args:
            session_id: 目标会话 ID
            message: 消息内容

        Returns:
            是否成功发送
        """
        return await self.send_personal_message(
            session_id, message, queue_on_disconnect=False
        )

    async def broadcast(
        self, message: Dict[str, Any], exclude: Optional[Set[str]] = None
    ) -> int:
        """
        广播消息给所有连接

        Args:
            message: 消息内容
            exclude: 排除的会话 ID 集合

        Returns:
            发送的连接数
        """
        exclude = exclude or set()
        event_name = message.get("type", "message")

        # 获取需要排除的 sid
        skip_sids = []
        for session_id in exclude:
            if session_id in self._session_to_sid:
                skip_sids.append(self._session_to_sid[session_id])

        await self.sio.emit(
            event_name, message, skip_sid=skip_sids if skip_sids else None
        )
        return len(self._connections) - len(exclude)

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
            发送的连接数
        """
        event_name = message.get("type", "message")
        # Socket.IO 的 room 就是频道
        await self.sio.emit(event_name, message, room=channel)
        return len(self.channels.get(channel, set()))

    async def subscribe(self, session_id: str, channel: str) -> bool:
        """
        订阅频道

        Args:
            session_id: 会话 ID
            channel: 频道名称

        Returns:
            是否成功
        """
        sid = self._session_to_sid.get(session_id)
        if not sid:
            return False

        async with self._lock:
            if channel not in self.channels:
                self.channels[channel] = set()
            self.channels[channel].add(session_id)

            if sid in self._connections:
                self._connections[sid].subscriptions.add(channel)

        # Socket.IO 加入房间
        await self.sio.enter_room(sid, channel)
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
        sid = self._session_to_sid.get(session_id)
        if not sid:
            return False

        async with self._lock:
            if channel in self.channels:
                self.channels[channel].discard(session_id)
            if sid in self._connections:
                self._connections[sid].subscriptions.discard(channel)

        # Socket.IO 离开房间
        await self.sio.leave_room(sid, channel)
        return True

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

        for sid, conn_info in list(self._connections.items()):
            if conn_info.user_id == user_id:
                if await self.send_personal_message(conn_info.session_id, message):
                    success_count += 1

        return success_count

    def is_connected(self, session_id: str) -> bool:
        """检查会话是否已连接"""
        sid = self._session_to_sid.get(session_id)
        if not sid:
            return False
        conn = self._connections.get(sid)
        return conn is not None and conn.is_active()

    def get_connection(self, session_id: str) -> Optional[ConnectionInfo]:
        """获取连接信息"""
        sid = self._session_to_sid.get(session_id)
        return self._connections.get(sid) if sid else None

    def get_connection_count(self) -> int:
        """获取活跃连接数"""
        return len(self._connections)

    def get_channel_subscribers(self, channel: str) -> Set[str]:
        """获取频道订阅者"""
        return self.channels.get(channel, set()).copy()

    def list_connections(self) -> List[Dict[str, Any]]:
        """列出所有连接信息"""
        return [conn.to_dict() for conn in self._connections.values()]

    def _queue_message(self, session_id: str, message: Dict[str, Any]) -> None:
        """将消息加入队列（带入队时间戳）"""
        if session_id not in self._message_queues:
            self._message_queues[session_id] = []

        queue = self._message_queues[session_id]

        # 添加入队时间，用于过期检查
        message["_queued_at"] = time.time()

        # 限制队列大小
        if len(queue) >= self._max_queue_size:
            queue.pop(0)

        queue.append(message)

    def _is_progress_message(self, msg: Dict[str, Any]) -> bool:
        """检查消息是否是进度类消息（不应缓存重发）"""
        SKIP_TYPES = {
            "agent_generation_progress",
            "execution_event",
            "progress_update",
            "node_progress",
        }

        # 检查顶层 type
        msg_type = msg.get("type", "")
        if msg_type in SKIP_TYPES:
            return True

        # 检查 CHAT_MESSAGE 类型中嵌套的进度消息
        # 结构: {"type": "chat_message", "payload": {"message_type": "progress", "data": {"type": "..."}}}
        if msg_type == "chat_message":
            payload = msg.get("payload", {})
            if isinstance(payload, dict):
                # 检查 message_type 是否为 progress
                if payload.get("message_type") == "progress":
                    return True
                # 检查 payload.data.type
                data = payload.get("data", {})
                if isinstance(data, dict) and data.get("type") in SKIP_TYPES:
                    return True

        return False

    async def _flush_message_queue(self, session_id: str) -> None:
        """发送缓存的消息队列（过滤进度类消息和过期消息）"""
        if session_id not in self._message_queues:
            return

        queue = self._message_queues.pop(session_id, [])

        # 消息过期时间：5 分钟
        MAX_AGE_SECONDS = 300
        now = time.time()

        filtered_queue = []
        skipped_by_type = 0
        skipped_by_expiry = 0

        for msg in queue:
            # 检查是否是进度类消息（包括嵌套在 CHAT_MESSAGE 中的）
            if self._is_progress_message(msg):
                skipped_by_type += 1
                continue

            # 检查消息是否过期
            queued_at = msg.get("_queued_at", 0)
            if queued_at > 0 and (now - queued_at) > MAX_AGE_SECONDS:
                skipped_by_expiry += 1
                continue

            # 移除内部时间戳字段，不发送给客户端
            msg_to_send = {k: v for k, v in msg.items() if k != "_queued_at"}
            filtered_queue.append(msg_to_send)

        if skipped_by_type > 0:
            logger.info(
                f"过滤掉 {skipped_by_type} 条进度类消息: session_id={session_id}"
            )
        if skipped_by_expiry > 0:
            logger.info(
                f"过滤掉 {skipped_by_expiry} 条过期消息: session_id={session_id}"
            )

        if filtered_queue:
            logger.info(
                f"发送缓存消息: session_id={session_id}, count={len(filtered_queue)}"
            )
            for msg in filtered_queue:
                await self.send_personal_message(
                    session_id, msg, queue_on_disconnect=False
                )

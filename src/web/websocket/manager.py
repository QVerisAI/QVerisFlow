"""
WebSocket 连接管理器

管理 WebSocket 连接的生命周期和消息广播。
"""

from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
import asyncio
import json

try:
    from fastapi import WebSocket, WebSocketDisconnect
except ImportError:
    WebSocket = Any
    WebSocketDisconnect = Exception

from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class ConnectionInfo:
    """连接信息"""
    websocket: WebSocket
    session_id: str
    user_id: Optional[str] = None
    connected_at: datetime = field(default_factory=datetime.now)
    subscriptions: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "connected_at": self.connected_at.isoformat(),
            "subscriptions": list(self.subscriptions),
        }


class ConnectionManager:
    """
    WebSocket 连接管理器
    
    功能：
    - 管理多个 WebSocket 连接
    - 支持按会话 ID 或用户 ID 发送消息
    - 支持频道订阅和广播
    """
    
    def __init__(self):
        # 活跃连接：session_id -> ConnectionInfo
        self.active_connections: Dict[str, ConnectionInfo] = {}
        
        # 频道订阅：channel -> Set[session_id]
        self.channels: Dict[str, Set[str]] = {}
        
        # 锁，用于并发控制
        self._lock = asyncio.Lock()
    
    async def connect(
        self,
        websocket: WebSocket,
        session_id: str,
        user_id: Optional[str] = None
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
            conn_info = ConnectionInfo(
                websocket=websocket,
                session_id=session_id,
                user_id=user_id,
            )
            self.active_connections[session_id] = conn_info
            
        logger.info(f"WebSocket 连接已建立: session_id={session_id}")
        return conn_info
    
    async def disconnect(self, session_id: str) -> None:
        """
        断开 WebSocket 连接
        
        Args:
            session_id: 会话 ID
        """
        async with self._lock:
            if session_id in self.active_connections:
                conn_info = self.active_connections.pop(session_id)
                
                # 从所有频道中移除
                for channel in conn_info.subscriptions:
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
        self,
        session_id: str,
        message: Dict[str, Any]
    ) -> bool:
        """
        发送个人消息
        
        Args:
            session_id: 目标会话 ID
            message: 消息内容
            
        Returns:
            是否成功
        """
        if session_id not in self.active_connections:
            logger.warning(f"连接不存在: {session_id}")
            return False
        
        try:
            conn_info = self.active_connections.get(session_id)
            if not conn_info:
                return False
                
            websocket = conn_info.websocket
            
            # 检查 WebSocket 状态（如果可用）
            # Starlette WebSocket 的状态检查
            client_state = getattr(websocket, 'client_state', None)
            if client_state is not None:
                from starlette.websockets import WebSocketState
                if client_state != WebSocketState.CONNECTED:
                    logger.debug(f"WebSocket 未连接，跳过发送: {session_id}")
                    return False
            
            await websocket.send_json(message)
            return True
        except Exception as e:
            error_str = str(e)
            # 连接关闭相关的错误不需要作为 ERROR 级别日志
            if any(keyword in error_str.lower() for keyword in [
                'closed', 'disconnect', 'not connected', 'accept'
            ]):
                logger.debug(f"WebSocket 已关闭，发送失败: {session_id} - {error_str}")
            else:
                logger.error(f"发送消息失败: {session_id} - {e}")
            
            # 异步清理连接，避免重复调用
            if session_id in self.active_connections:
                await self.disconnect(session_id)
            return False
    
    async def broadcast(
        self,
        message: Dict[str, Any],
        exclude: Optional[Set[str]] = None
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
        self,
        channel: str,
        message: Dict[str, Any],
        exclude: Optional[Set[str]] = None
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
    
    async def send_to_user(
        self,
        user_id: str,
        message: Dict[str, Any]
    ) -> int:
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

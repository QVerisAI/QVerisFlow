"""
Socket.IO 模块

提供 Socket.IO 连接管理和事件处理功能。
"""

from src.web.socketio.manager import (
    SocketIOConnectionManager,
    ConnectionInfo,
    ConnectionState,
)

__all__ = [
    "SocketIOConnectionManager",
    "ConnectionInfo",
    "ConnectionState",
]

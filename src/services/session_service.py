"""
会话服务

提供对话会话的业务逻辑，包括会话创建、消息管理、历史恢复等。
"""

import os
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass

from src.storage.repositories import (
    ConversationSessionRepository,
    ConversationMessageRepository,
)
from src.storage.models.db_models import SessionStatus
from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class SessionInfo:
    """会话信息"""

    id: str
    session_id: str
    status: str
    task_description: str
    message_count: int
    created_at: str
    updated_at: str
    last_activity_at: str
    workflow_definition_id: Optional[str] = None
    metadata: Dict[str, Any] = None


@dataclass
class MessageInfo:
    """消息信息"""

    role: str
    content: str
    timestamp: str
    message_type: str = "text"
    data: Dict[str, Any] = None


class SessionService:
    """
    会话服务

    提供对话会话的业务逻辑。
    """

    def __init__(
        self,
        session_repo: ConversationSessionRepository,
        message_repo: ConversationMessageRepository,
    ):
        """
        初始化会话服务

        Args:
            session_repo: 会话仓库
            message_repo: 消息仓库
        """
        self.session_repo = session_repo
        self.message_repo = message_repo

    async def get_or_create_session(
        self,
        session_id: str,
        task_description: str = "",
    ) -> SessionInfo:
        """
        获取或创建会话

        Args:
            session_id: 会话 ID
            task_description: 任务描述

        Returns:
            会话信息
        """
        # 先尝试获取现有会话
        session = await self.session_repo.get_by_session_id(session_id)

        if not session:
            # 创建新会话
            session = await self.session_repo.create_session(
                session_id=session_id,
                task_description=task_description,
                status=SessionStatus.idle,
            )
            logger.info(f"创建新会话: {session_id}")

        return SessionInfo(
            id=session.id,
            session_id=session.session_id,
            status=session.status.value if session.status else "idle",
            task_description=session.task_description or "",
            message_count=session.message_count or 0,
            created_at=session.created_at.isoformat() if session.created_at else "",
            updated_at=session.updated_at.isoformat() if session.updated_at else "",
            last_activity_at=(
                session.last_activity_at.isoformat() if session.last_activity_at else ""
            ),
            workflow_definition_id=session.workflow_definition_id,
            metadata=session.extra_metadata,
        )

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        data: Dict[str, Any] = None,
    ) -> MessageInfo:
        """
        添加消息

        Args:
            session_id: 会话 ID
            role: 角色
            content: 内容
            message_type: 消息类型
            data: 额外数据

        Returns:
            消息信息
        """
        # 获取会话
        session = await self.session_repo.get_by_session_id(session_id)
        if not session:
            raise ValueError(f"会话不存在: {session_id}")

        # 添加消息
        message = await self.message_repo.add_message(
            session_db_id=session.id,
            role=role,
            content=content,
            message_type=message_type,
            data=data,
        )

        # 更新会话消息计数和活动时间
        await self.session_repo.update(
            session.id,
            {
                "message_count": (session.message_count or 0) + 1,
                "last_activity_at": datetime.utcnow(),
            },
        )

        return MessageInfo(
            role=message.role,
            content=message.content,
            timestamp=message.timestamp.isoformat() if message.timestamp else "",
            message_type=message.message_type or "text",
            data=message.extra_data,
        )

    async def get_messages(
        self,
        session_id: str,
        limit: int = None,
        offset: int = 0,
    ) -> List[MessageInfo]:
        """
        获取会话消息

        Args:
            session_id: 会话 ID
            limit: 数量限制
            offset: 偏移量

        Returns:
            消息列表
        """
        session = await self.session_repo.get_by_session_id(session_id)
        if not session:
            return []

        messages = await self.message_repo.get_messages(
            session_db_id=session.id,
            limit=limit,
            offset=offset,
        )

        return [
            MessageInfo(
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp.isoformat() if msg.timestamp else "",
                message_type=msg.message_type or "text",
                data=msg.extra_data,
            )
            for msg in messages
        ]

    async def update_status(
        self,
        session_id: str,
        status: str,
    ) -> Optional[SessionInfo]:
        """
        更新会话状态

        Args:
            session_id: 会话 ID
            status: 新状态

        Returns:
            更新后的会话信息
        """
        try:
            status_enum = SessionStatus(status)
        except ValueError:
            logger.warning(f"无效的会话状态: {status}")
            return None

        session = await self.session_repo.update_status(session_id, status_enum)
        if session:
            return SessionInfo(
                id=session.id,
                session_id=session.session_id,
                status=session.status.value if session.status else "idle",
                task_description=session.task_description or "",
                message_count=session.message_count or 0,
                created_at=session.created_at.isoformat() if session.created_at else "",
                updated_at=session.updated_at.isoformat() if session.updated_at else "",
                last_activity_at=(
                    session.last_activity_at.isoformat()
                    if session.last_activity_at
                    else ""
                ),
                workflow_definition_id=session.workflow_definition_id,
                metadata=session.extra_metadata,
            )
        return None

    async def link_workflow(
        self,
        session_id: str,
        workflow_definition_id: str,
    ) -> bool:
        """
        关联工作流

        Args:
            session_id: 会话 ID
            workflow_definition_id: 工作流定义 ID

        Returns:
            是否成功
        """
        result = await self.session_repo.link_workflow(
            session_id, workflow_definition_id
        )
        return result is not None

    async def save_conversation_history(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        mode: str = "idle",
        task_description: str = "",
    ) -> bool:
        """
        保存完整的对话历史（批量操作）

        Args:
            session_id: 会话 ID
            messages: 消息列表
            mode: 会话模式
            task_description: 任务描述

        Returns:
            是否成功
        """
        try:
            # 获取或创建会话
            session = await self.session_repo.get_by_session_id(session_id)
            if not session:
                session = await self.session_repo.create_session(
                    session_id=session_id,
                    task_description=task_description,
                    status=SessionStatus(mode) if mode else SessionStatus.idle,
                )

            # 删除现有消息
            await self.message_repo.delete_session_messages(session.id)

            # 批量添加消息
            for msg in messages:
                await self.message_repo.add_message(
                    session_db_id=session.id,
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    message_type=msg.get("message_type", "text"),
                    data=msg.get("data"),
                )

            # 更新会话信息
            await self.session_repo.update(
                session.id,
                {
                    "status": SessionStatus(mode) if mode else SessionStatus.idle,
                    "task_description": task_description,
                    "message_count": len(messages),
                    "last_activity_at": datetime.utcnow(),
                },
            )

            logger.info(f"对话历史已保存到数据库: {session_id}, {len(messages)} 条消息")
            return True

        except Exception as e:
            logger.error(f"保存对话历史失败: {e}")
            return False

    async def load_conversation_history(
        self,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        加载对话历史

        Args:
            session_id: 会话 ID

        Returns:
            对话历史数据，包含 messages, mode, task_description
        """
        try:
            session = await self.session_repo.get_by_session_id(session_id)
            if not session:
                return None

            messages = await self.message_repo.get_messages(session.id)

            return {
                "session_id": session.session_id,
                "mode": session.status.value if session.status else "idle",
                "task_description": session.task_description or "",
                "messages": [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.timestamp.isoformat() if msg.timestamp else "",
                        "message_type": msg.message_type or "text",
                        "data": msg.extra_data,
                    }
                    for msg in messages
                ],
            }

        except Exception as e:
            logger.error(f"加载对话历史失败: {e}")
            return None

    async def get_recent_sessions(
        self,
        limit: int = 20,
    ) -> List[SessionInfo]:
        """
        获取最近的会话列表

        Args:
            limit: 数量限制

        Returns:
            会话列表
        """
        sessions = await self.session_repo.get_recent_sessions(limit=limit)
        return [
            SessionInfo(
                id=s.id,
                session_id=s.session_id,
                status=s.status.value if s.status else "idle",
                task_description=s.task_description or "",
                message_count=s.message_count or 0,
                created_at=s.created_at.isoformat() if s.created_at else "",
                updated_at=s.updated_at.isoformat() if s.updated_at else "",
                last_activity_at=(
                    s.last_activity_at.isoformat() if s.last_activity_at else ""
                ),
                workflow_definition_id=s.workflow_definition_id,
                metadata=s.extra_metadata,
            )
            for s in sessions
        ]


# 便捷函数：创建会话服务（带数据库连接）
async def create_session_service() -> Optional[SessionService]:
    """
    创建会话服务（自动连接数据库）

    Returns:
        会话服务实例，如果数据库未启用则返回 None
    """
    if os.getenv("ENABLE_POSTGRES", "false").lower() != "true":
        return None

    try:
        from src.storage.database import AsyncDatabaseManager
        from src.storage.config import PostgreSQLConfig

        config = PostgreSQLConfig(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "agent_framework"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
        )
        db = AsyncDatabaseManager(config)
        await db.connect()

        session_repo = ConversationSessionRepository(db._session_factory)
        message_repo = ConversationMessageRepository(db._session_factory)

        return SessionService(session_repo, message_repo)

    except Exception as e:
        logger.error(f"创建会话服务失败: {e}")
        return None


# 导出
__all__ = [
    "SessionService",
    "SessionInfo",
    "MessageInfo",
    "create_session_service",
]

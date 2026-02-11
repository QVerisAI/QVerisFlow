"""
会话仓库

提供对话会话和消息的持久化操作。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload

from .base import BaseRepository
from ..models.db_models import (
    ConversationSessionModel,
    ConversationMessageModel,
    SessionStatus,
)
from src.utils.logger import get_logger

logger = get_logger()


class ConversationSessionRepository(BaseRepository[ConversationSessionModel]):
    """
    对话会话仓库

    提供会话的 CRUD 操作和查询功能。
    """

    def __init__(self, session_factory):
        super().__init__(session_factory, ConversationSessionModel)

    async def get_by_session_id(
        self,
        session_id: str,
        include_messages: bool = False,
    ) -> Optional[ConversationSessionModel]:
        """
        根据 session_id 获取会话

        Args:
            session_id: 会话 ID
            include_messages: 是否加载消息

        Returns:
            会话模型
        """
        async with self.get_session() as session:
            query = select(ConversationSessionModel).where(
                ConversationSessionModel.session_id == session_id
            )

            if include_messages:
                query = query.options(selectinload(ConversationSessionModel.messages))

            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def create_session(
        self,
        session_id: str,
        task_description: str = "",
        status: SessionStatus = SessionStatus.idle,
        metadata: Dict[str, Any] = None,
    ) -> ConversationSessionModel:
        """
        创建新会话

        Args:
            session_id: 会话 ID
            task_description: 任务描述
            status: 会话状态
            metadata: 元数据

        Returns:
            创建的会话模型
        """
        data = {
            "id": self._generate_id(),
            "session_id": session_id,
            "status": status,
            "task_description": task_description,
            "message_count": 0,
            "extra_metadata": metadata or {},
        }
        return await self.create(data)

    async def update_status(
        self,
        session_id: str,
        status: SessionStatus,
    ) -> Optional[ConversationSessionModel]:
        """
        更新会话状态

        Args:
            session_id: 会话 ID
            status: 新状态

        Returns:
            更新后的会话模型
        """
        session_model = await self.get_by_session_id(session_id)
        if session_model:
            return await self.update(
                session_model.id,
                {
                    "status": status,
                    "last_activity_at": datetime.utcnow(),
                },
            )
        return None

    async def update_activity(
        self,
        session_id: str,
    ) -> Optional[ConversationSessionModel]:
        """更新会话最后活动时间"""
        session_model = await self.get_by_session_id(session_id)
        if session_model:
            return await self.update(
                session_model.id,
                {"last_activity_at": datetime.utcnow()},
            )
        return None

    async def get_recent_sessions(
        self,
        limit: int = 20,
        status: SessionStatus = None,
    ) -> List[ConversationSessionModel]:
        """
        获取最近的会话

        Args:
            limit: 数量限制
            status: 状态过滤

        Returns:
            会话列表
        """
        async with self.get_session() as session:
            query = select(ConversationSessionModel)

            if status:
                query = query.where(ConversationSessionModel.status == status)

            query = query.order_by(
                ConversationSessionModel.last_activity_at.desc()
            ).limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def link_workflow(
        self,
        session_id: str,
        workflow_definition_id: str,
    ) -> Optional[ConversationSessionModel]:
        """
        关联工作流

        Args:
            session_id: 会话 ID
            workflow_definition_id: 工作流定义 ID

        Returns:
            更新后的会话模型
        """
        session_model = await self.get_by_session_id(session_id)
        if session_model:
            return await self.update(
                session_model.id,
                {"workflow_definition_id": workflow_definition_id},
            )
        return None


class ConversationMessageRepository(BaseRepository[ConversationMessageModel]):
    """
    对话消息仓库

    提供消息的 CRUD 操作和查询功能。
    """

    def __init__(self, session_factory):
        super().__init__(session_factory, ConversationMessageModel)

    async def add_message(
        self,
        session_db_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        data: Dict[str, Any] = None,
    ) -> ConversationMessageModel:
        """
        添加消息

        Args:
            session_db_id: 会话数据库 ID
            role: 角色 (user, assistant, system)
            content: 消息内容
            message_type: 消息类型
            data: 额外数据

        Returns:
            创建的消息模型
        """
        # 获取当前最大序号
        async with self.get_session() as session:
            result = await session.execute(
                select(func.max(ConversationMessageModel.sequence)).where(
                    ConversationMessageModel.session_id == session_db_id
                )
            )
            max_sequence = result.scalar() or 0

        message_data = {
            "id": self._generate_id(),
            "session_id": session_db_id,
            "role": role,
            "content": content,
            "message_type": message_type,
            "sequence": max_sequence + 1,
            "extra_data": data or {},
        }
        return await self.create(message_data)

    async def get_messages(
        self,
        session_db_id: str,
        limit: int = None,
        offset: int = 0,
    ) -> List[ConversationMessageModel]:
        """
        获取会话消息

        Args:
            session_db_id: 会话数据库 ID
            limit: 数量限制
            offset: 偏移量

        Returns:
            消息列表
        """
        async with self.get_session() as session:
            query = (
                select(ConversationMessageModel)
                .where(ConversationMessageModel.session_id == session_db_id)
                .order_by(ConversationMessageModel.sequence)
                .offset(offset)
            )

            if limit:
                query = query.limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_messages_after(
        self,
        session_db_id: str,
        after_sequence: int,
    ) -> List[ConversationMessageModel]:
        """
        获取某个序号之后的消息（用于增量同步）

        Args:
            session_db_id: 会话数据库 ID
            after_sequence: 起始序号

        Returns:
            消息列表
        """
        async with self.get_session() as session:
            result = await session.execute(
                select(ConversationMessageModel)
                .where(
                    and_(
                        ConversationMessageModel.session_id == session_db_id,
                        ConversationMessageModel.sequence > after_sequence,
                    )
                )
                .order_by(ConversationMessageModel.sequence)
            )
            return list(result.scalars().all())

    async def get_message_count(self, session_db_id: str) -> int:
        """获取会话消息数量"""
        async with self.get_session() as session:
            result = await session.execute(
                select(func.count(ConversationMessageModel.id)).where(
                    ConversationMessageModel.session_id == session_db_id
                )
            )
            return result.scalar() or 0

    async def delete_session_messages(self, session_db_id: str) -> int:
        """
        删除会话所有消息

        Args:
            session_db_id: 会话数据库 ID

        Returns:
            删除的消息数量
        """
        async with self.get_session() as session:
            result = await session.execute(
                select(ConversationMessageModel).where(
                    ConversationMessageModel.session_id == session_db_id
                )
            )
            messages = result.scalars().all()
            count = len(messages)
            for msg in messages:
                await session.delete(msg)
            return count


# 导出
__all__ = ["ConversationSessionRepository", "ConversationMessageRepository"]

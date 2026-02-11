"""
Agent 仓库

提供 Agent 定义的持久化操作。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import select, and_

from .base import BaseRepository
from ..models.db_models import AgentDefinitionModel, AgentStatus
from src.utils.logger import get_logger

logger = get_logger()


class AgentRepository(BaseRepository[AgentDefinitionModel]):
    """
    Agent 仓库

    提供 Agent 定义的 CRUD 操作和查询功能。
    """

    def __init__(self, session_factory):
        super().__init__(session_factory, AgentDefinitionModel)

    async def create_from_definition(
        self,
        definition: Dict[str, Any],
        author: str = "system",
    ) -> AgentDefinitionModel:
        """
        从 Agent 定义创建记录

        Args:
            definition: Agent 定义字典
            author: 作者

        Returns:
            创建的模型实例
        """
        agent_id = definition.get("agent_id")
        version = definition.get("version", "1.0.0")

        data = {
            "id": f"{agent_id}_{version}_{self._generate_id()[:8]}",
            "agent_id": agent_id,
            "version": version,
            "name": definition.get("name", agent_id),
            "description": definition.get("description", ""),
            "definition_json": definition,
            "status": AgentStatus.DRAFT,
            "model_name": definition.get("model_config", {}).get("model_name"),
            "max_iterations": definition.get("model_config", {}).get("max_iterations"),
            "tags": definition.get("tags", []),
            "author": author,
        }

        return await self.create(data)

    async def get_by_agent_id(
        self,
        agent_id: str,
        version: str = None,
    ) -> Optional[AgentDefinitionModel]:
        """
        根据 agent_id 获取最新版本

        Args:
            agent_id: Agent ID
            version: 指定版本（可选）

        Returns:
            Agent 定义模型（返回最新版本）
        """
        async with self.get_session() as session:
            query = select(AgentDefinitionModel).where(
                AgentDefinitionModel.agent_id == agent_id
            )

            if version:
                query = query.where(AgentDefinitionModel.version == version)
            else:
                # 获取最新版本
                query = query.order_by(AgentDefinitionModel.created_at.desc())

            # 添加 limit(1) 避免多版本时 scalar_one_or_none 报错
            query = query.limit(1)

            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def get_all_versions(
        self,
        agent_id: str,
    ) -> List[AgentDefinitionModel]:
        """
        获取 Agent 的所有版本

        Args:
            agent_id: Agent ID

        Returns:
            版本列表
        """
        async with self.get_session() as session:
            result = await session.execute(
                select(AgentDefinitionModel)
                .where(AgentDefinitionModel.agent_id == agent_id)
                .order_by(AgentDefinitionModel.created_at.desc())
            )
            return list(result.scalars().all())

    async def get_active_agents(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AgentDefinitionModel]:
        """
        获取所有激活的 Agent

        Args:
            limit: 数量限制
            offset: 偏移量

        Returns:
            Agent 列表
        """
        async with self.get_session() as session:
            result = await session.execute(
                select(AgentDefinitionModel)
                .where(AgentDefinitionModel.status == AgentStatus.ACTIVE)
                .order_by(AgentDefinitionModel.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return list(result.scalars().all())

    async def activate(self, id: str) -> Optional[AgentDefinitionModel]:
        """激活 Agent"""
        return await self.update(id, {"status": AgentStatus.ACTIVE})

    async def deactivate(self, id: str) -> Optional[AgentDefinitionModel]:
        """停用 Agent"""
        return await self.update(id, {"status": AgentStatus.INACTIVE})

    async def archive(self, id: str) -> Optional[AgentDefinitionModel]:
        """归档 Agent"""
        return await self.update(id, {"status": AgentStatus.ARCHIVED})

    async def search(
        self,
        query: str = None,
        tags: List[str] = None,
        status: AgentStatus = None,
        limit: int = 100,
    ) -> List[AgentDefinitionModel]:
        """
        搜索 Agent

        Args:
            query: 搜索关键词（匹配名称和描述）
            tags: 标签过滤
            status: 状态过滤
            limit: 数量限制

        Returns:
            匹配的 Agent 列表
        """
        async with self.get_session() as session:
            stmt = select(AgentDefinitionModel)

            conditions = []

            if query:
                conditions.append(
                    AgentDefinitionModel.name.ilike(f"%{query}%")
                    | AgentDefinitionModel.description.ilike(f"%{query}%")
                    | AgentDefinitionModel.agent_id.ilike(
                        f"%{query}%"
                    )  # 也搜索 agent_id
                )

            if status:
                conditions.append(AgentDefinitionModel.status == status)

            if conditions:
                stmt = stmt.where(and_(*conditions))

            stmt = stmt.order_by(AgentDefinitionModel.updated_at.desc()).limit(limit)

            result = await session.execute(stmt)
            agents = list(result.scalars().all())

            # 标签过滤（JSON 字段过滤在应用层处理）
            if tags:
                agents = [
                    a for a in agents if any(tag in (a.tags or []) for tag in tags)
                ]

            return agents

    async def update_definition(
        self,
        id: str,
        definition: Dict[str, Any],
    ) -> Optional[AgentDefinitionModel]:
        """
        更新 Agent 定义

        Args:
            id: 记录 ID
            definition: 新的定义

        Returns:
            更新后的模型
        """
        data = {
            "definition_json": definition,
            "name": definition.get("name"),
            "description": definition.get("description"),
            "model_name": definition.get("model_config", {}).get("model_name"),
            "max_iterations": definition.get("model_config", {}).get("max_iterations"),
            "tags": definition.get("tags", []),
        }

        return await self.update(id, data)


# 导出
__all__ = ["AgentRepository"]

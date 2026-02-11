"""
工作流仓库

提供工作流定义和执行记录的持久化操作。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import select, and_

from .base import BaseRepository
from ..models.db_models import (
    WorkflowDefinitionModel,
    WorkflowExecutionModel,
    WorkflowStatus,
)
from src.utils.logger import get_logger

logger = get_logger()


class WorkflowDefinitionRepository(BaseRepository[WorkflowDefinitionModel]):
    """
    工作流定义仓库
    """

    def __init__(self, session_factory):
        super().__init__(session_factory, WorkflowDefinitionModel)

    async def create_from_definition(
        self,
        definition: Dict[str, Any],
        author: str = "system",
    ) -> WorkflowDefinitionModel:
        """
        从工作流定义创建记录

        Args:
            definition: 工作流定义字典
            author: 作者

        Returns:
            创建的模型实例
        """
        workflow_id = definition.get("workflow_id")
        version = definition.get("version", "1.0.0")

        # 计算节点和边数量
        nodes = definition.get("nodes", [])
        edges = definition.get("edges", [])

        data = {
            "id": f"{workflow_id}_{version}_{self._generate_id()[:8]}",
            "workflow_id": workflow_id,
            "version": version,
            "name": definition.get("name", workflow_id),
            "description": definition.get("description", ""),
            "definition_json": definition,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "is_active": definition.get("is_active", True),
            "tags": definition.get("tags", []),
            "author": author,
        }

        return await self.create(data)

    async def get_by_workflow_id(
        self,
        workflow_id: str,
        version: str = None,
    ) -> Optional[WorkflowDefinitionModel]:
        """
        根据 workflow_id 获取定义

        Args:
            workflow_id: 工作流 ID
            version: 指定版本（可选）

        Returns:
            工作流定义模型（返回最新版本）
        """
        async with self.get_session() as session:
            query = select(WorkflowDefinitionModel).where(
                WorkflowDefinitionModel.workflow_id == workflow_id
            )

            if version:
                query = query.where(WorkflowDefinitionModel.version == version)
            else:
                # 按创建时间倒序，取最新的一个版本
                query = query.order_by(WorkflowDefinitionModel.created_at.desc())

            # 添加 limit(1) 避免多版本时 scalar_one_or_none 报错
            query = query.limit(1)

            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def get_active_workflows(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[WorkflowDefinitionModel]:
        """获取所有激活的工作流"""
        async with self.get_session() as session:
            result = await session.execute(
                select(WorkflowDefinitionModel)
                .where(WorkflowDefinitionModel.is_active == True)
                .order_by(WorkflowDefinitionModel.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return list(result.scalars().all())

    async def activate(self, id: str) -> Optional[WorkflowDefinitionModel]:
        """激活工作流"""
        return await self.update(id, {"is_active": True})

    async def deactivate(self, id: str) -> Optional[WorkflowDefinitionModel]:
        """停用工作流"""
        return await self.update(id, {"is_active": False})


class WorkflowExecutionRepository(BaseRepository[WorkflowExecutionModel]):
    """
    工作流执行记录仓库
    """

    def __init__(self, session_factory):
        super().__init__(session_factory, WorkflowExecutionModel)

    async def create_execution(
        self,
        workflow_definition_id: str,
        initial_context: Dict[str, Any] = None,
    ) -> WorkflowExecutionModel:
        """
        创建执行记录

        Args:
            workflow_definition_id: 工作流定义 ID
            initial_context: 初始上下文

        Returns:
            创建的执行记录
        """
        data = {
            "workflow_definition_id": workflow_definition_id,
            "status": WorkflowStatus.PENDING,
            "initial_context": initial_context or {},
            "node_results": {},
            "started_at": datetime.utcnow(),  # 记录创建时间作为开始时间
        }

        return await self.create(data)

    async def update_status(
        self,
        id: str,
        status: WorkflowStatus,
        error: str = None,
    ) -> Optional[WorkflowExecutionModel]:
        """更新执行状态"""
        data = {"status": status}
        if error:
            data["error"] = error

        if status == WorkflowStatus.RUNNING:
            data["started_at"] = datetime.utcnow()
        elif status in (
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        ):
            data["completed_at"] = datetime.utcnow()

        return await self.update(id, data)

    async def update_result(
        self,
        id: str,
        final_output: Any,
        node_results: Dict[str, Any],
        total_duration_ms: float,
    ) -> Optional[WorkflowExecutionModel]:
        """更新执行结果"""
        return await self.update(
            id,
            {
                "final_output": final_output,
                "node_results": node_results,
                "total_duration_ms": total_duration_ms,
                "status": WorkflowStatus.COMPLETED,
                "completed_at": datetime.utcnow(),
            },
        )

    async def save_checkpoint(
        self,
        id: str,
        checkpoint_id: str,
        node_results: Dict[str, Any],
    ) -> Optional[WorkflowExecutionModel]:
        """保存检查点"""
        return await self.update(
            id,
            {
                "checkpoint_id": checkpoint_id,
                "node_results": node_results,
                "status": WorkflowStatus.PAUSED,
            },
        )

    async def get_by_workflow(
        self,
        workflow_definition_id: str,
        status: WorkflowStatus = None,
        limit: int = 100,
    ) -> List[WorkflowExecutionModel]:
        """获取工作流的执行记录"""
        async with self.get_session() as session:
            query = select(WorkflowExecutionModel).where(
                WorkflowExecutionModel.workflow_definition_id == workflow_definition_id
            )

            if status:
                query = query.where(WorkflowExecutionModel.status == status)

            query = query.order_by(WorkflowExecutionModel.created_at.desc()).limit(
                limit
            )

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_running_executions(
        self,
        limit: int = 100,
    ) -> List[WorkflowExecutionModel]:
        """获取正在运行的执行记录"""
        async with self.get_session() as session:
            result = await session.execute(
                select(WorkflowExecutionModel)
                .where(WorkflowExecutionModel.status == WorkflowStatus.RUNNING)
                .order_by(WorkflowExecutionModel.started_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def fix_stale_running_executions(self) -> int:
        """
        修复僵尸 running 状态的执行记录
        
        服务重启后，之前处于 running 状态的执行记录应被标记为 failed，
        因为内存中的执行状态已经丢失，这些执行无法恢复。
        
        Returns:
            修复的记录数量
        """
        async with self.get_session() as session:
            # 查询所有 running 状态的记录
            result = await session.execute(
                select(WorkflowExecutionModel)
                .where(WorkflowExecutionModel.status == WorkflowStatus.RUNNING)
            )
            running_executions = list(result.scalars().all())
            
            if not running_executions:
                return 0
            
            fixed_count = 0
            current_time = datetime.utcnow()
            
            for execution in running_executions:
                execution.status = WorkflowStatus.FAILED
                execution.error = "服务重启导致执行中断（Execution interrupted due to service restart）"
                execution.completed_at = current_time
                fixed_count += 1
                logger.info(
                    f"修复僵尸执行记录: execution_id={execution.id}, "
                    f"workflow_id={execution.workflow_definition_id}"
                )
            
            await session.commit()
            return fixed_count


# 导出
__all__ = [
    "WorkflowDefinitionRepository",
    "WorkflowExecutionRepository",
]

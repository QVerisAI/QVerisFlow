"""
任务仓库

提供任务执行记录和工具调用日志的持久化操作。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, and_, func

from .base import BaseRepository
from ..models.db_models import (
    TaskExecutionModel,
    ToolCallLogModel,
    TaskStatus,
)
from src.utils.logger import get_logger

logger = get_logger()


class TaskExecutionRepository(BaseRepository[TaskExecutionModel]):
    """
    任务执行记录仓库
    """

    def __init__(self, session_factory):
        super().__init__(session_factory, TaskExecutionModel)

    async def create_execution(
        self,
        task_id: str,
        agent_definition_id: str,
        task_description: str,
        input_data: Dict[str, Any] = None,
        workspace_path: str = None,
    ) -> TaskExecutionModel:
        """
        创建任务执行记录

        Args:
            task_id: 任务 ID
            agent_definition_id: Agent 定义 ID
            task_description: 任务描述
            input_data: 输入数据
            workspace_path: 工作空间路径

        Returns:
            创建的执行记录
        """
        data = {
            "task_id": task_id,
            "agent_definition_id": agent_definition_id,
            "task_description": task_description,
            "input_data": input_data or {},
            "status": TaskStatus.PENDING,
            "workspace_path": workspace_path,
            "output_files": [],
        }

        return await self.create(data)

    async def start_execution(self, id: str) -> Optional[TaskExecutionModel]:
        """开始执行"""
        return await self.update(
            id,
            {
                "status": TaskStatus.RUNNING,
                "started_at": datetime.utcnow(),
            },
        )

    async def complete_execution(
        self,
        id: str,
        result: Any,
        duration_ms: float,
        iterations: int,
        token_usage: int = 0,
        verification_passed: bool = None,
        verification_score: float = None,
        verification_feedback: str = None,
        output_files: List[str] = None,
    ) -> Optional[TaskExecutionModel]:
        """完成执行"""
        return await self.update(
            id,
            {
                "status": TaskStatus.COMPLETED,
                "result": result,
                "duration_ms": duration_ms,
                "iterations": iterations,
                "token_usage": token_usage,
                "verification_passed": verification_passed,
                "verification_score": verification_score,
                "verification_feedback": verification_feedback,
                "output_files": output_files or [],
                "completed_at": datetime.utcnow(),
            },
        )

    async def fail_execution(
        self,
        id: str,
        error: str,
        duration_ms: float = 0,
        iterations: int = 0,
    ) -> Optional[TaskExecutionModel]:
        """标记执行失败"""
        return await self.update(
            id,
            {
                "status": TaskStatus.FAILED,
                "error": error,
                "duration_ms": duration_ms,
                "iterations": iterations,
                "completed_at": datetime.utcnow(),
            },
        )

    async def cancel_execution(self, id: str) -> Optional[TaskExecutionModel]:
        """取消执行"""
        return await self.update(
            id,
            {
                "status": TaskStatus.CANCELLED,
                "completed_at": datetime.utcnow(),
            },
        )

    async def get_by_task_id(self, task_id: str) -> Optional[TaskExecutionModel]:
        """根据任务 ID 获取执行记录"""
        async with self.get_session() as session:
            result = await session.execute(
                select(TaskExecutionModel)
                .where(TaskExecutionModel.task_id == task_id)
                .order_by(TaskExecutionModel.created_at.desc())
            )
            return result.scalar_one_or_none()

    async def get_by_agent(
        self,
        agent_definition_id: str,
        status: TaskStatus = None,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 100,
    ) -> List[TaskExecutionModel]:
        """获取 Agent 的执行记录"""
        async with self.get_session() as session:
            query = select(TaskExecutionModel).where(
                TaskExecutionModel.agent_definition_id == agent_definition_id
            )

            if status:
                query = query.where(TaskExecutionModel.status == status)

            if start_date:
                query = query.where(TaskExecutionModel.created_at >= start_date)

            if end_date:
                query = query.where(TaskExecutionModel.created_at <= end_date)

            query = query.order_by(TaskExecutionModel.created_at.desc()).limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_statistics(
        self,
        agent_definition_id: str = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取执行统计信息

        Args:
            agent_definition_id: Agent 定义 ID（可选）
            days: 统计天数

        Returns:
            统计信息
        """
        async with self.get_session() as session:
            start_date = datetime.utcnow() - timedelta(days=days)

            # 基础查询条件
            conditions = [TaskExecutionModel.created_at >= start_date]
            if agent_definition_id:
                conditions.append(
                    TaskExecutionModel.agent_definition_id == agent_definition_id
                )

            # 总数
            total_query = (
                select(func.count())
                .select_from(TaskExecutionModel)
                .where(and_(*conditions))
            )
            total = (await session.execute(total_query)).scalar() or 0

            # 成功数
            success_conditions = conditions + [
                TaskExecutionModel.status == TaskStatus.COMPLETED
            ]
            success_query = (
                select(func.count())
                .select_from(TaskExecutionModel)
                .where(and_(*success_conditions))
            )
            successful = (await session.execute(success_query)).scalar() or 0

            # 失败数
            failed_conditions = conditions + [
                TaskExecutionModel.status == TaskStatus.FAILED
            ]
            failed_query = (
                select(func.count())
                .select_from(TaskExecutionModel)
                .where(and_(*failed_conditions))
            )
            failed = (await session.execute(failed_query)).scalar() or 0

            # 平均耗时
            duration_query = select(func.avg(TaskExecutionModel.duration_ms)).where(
                and_(*success_conditions)
            )
            avg_duration = (await session.execute(duration_query)).scalar() or 0

            # 平均迭代次数
            iterations_query = select(func.avg(TaskExecutionModel.iterations)).where(
                and_(*success_conditions)
            )
            avg_iterations = (await session.execute(iterations_query)).scalar() or 0

            return {
                "total_executions": total,
                "successful": successful,
                "failed": failed,
                "success_rate": successful / total if total > 0 else 0,
                "avg_duration_ms": float(avg_duration),
                "avg_iterations": float(avg_iterations),
                "period_days": days,
            }


class ToolCallLogRepository(BaseRepository[ToolCallLogModel]):
    """
    工具调用日志仓库
    """

    def __init__(self, session_factory):
        super().__init__(session_factory, ToolCallLogModel)

    async def log_call(
        self,
        task_execution_id: str,
        tool_id: str,
        tool_name: str,
        input_params: Dict[str, Any],
        output: Any = None,
        error: str = None,
        phase: str = "complete",
        duration_ms: float = 0,
    ) -> ToolCallLogModel:
        """记录工具调用"""
        data = {
            "task_execution_id": task_execution_id,
            "tool_id": tool_id,
            "tool_name": tool_name,
            "input_params": input_params,
            "output": output,
            "error": error,
            "phase": phase,
            "duration_ms": duration_ms,
        }

        return await self.create(data)

    async def get_by_task(
        self,
        task_execution_id: str,
    ) -> List[ToolCallLogModel]:
        """获取任务的所有工具调用"""
        async with self.get_session() as session:
            result = await session.execute(
                select(ToolCallLogModel)
                .where(ToolCallLogModel.task_execution_id == task_execution_id)
                .order_by(ToolCallLogModel.timestamp.asc())
            )
            return list(result.scalars().all())

    async def get_by_tool(
        self,
        tool_id: str,
        start_date: datetime = None,
        limit: int = 100,
    ) -> List[ToolCallLogModel]:
        """获取工具的调用记录"""
        async with self.get_session() as session:
            query = select(ToolCallLogModel).where(ToolCallLogModel.tool_id == tool_id)

            if start_date:
                query = query.where(ToolCallLogModel.timestamp >= start_date)

            query = query.order_by(ToolCallLogModel.timestamp.desc()).limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_tool_statistics(
        self,
        tool_id: str = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """获取工具调用统计"""
        async with self.get_session() as session:
            start_date = datetime.utcnow() - timedelta(days=days)

            conditions = [ToolCallLogModel.timestamp >= start_date]
            if tool_id:
                conditions.append(ToolCallLogModel.tool_id == tool_id)

            # 总调用次数
            total_query = (
                select(func.count())
                .select_from(ToolCallLogModel)
                .where(and_(*conditions))
            )
            total = (await session.execute(total_query)).scalar() or 0

            # 错误次数
            error_conditions = conditions + [ToolCallLogModel.error.isnot(None)]
            error_query = (
                select(func.count())
                .select_from(ToolCallLogModel)
                .where(and_(*error_conditions))
            )
            errors = (await session.execute(error_query)).scalar() or 0

            # 平均耗时
            duration_query = select(func.avg(ToolCallLogModel.duration_ms)).where(
                and_(*conditions)
            )
            avg_duration = (await session.execute(duration_query)).scalar() or 0

            return {
                "total_calls": total,
                "errors": errors,
                "error_rate": errors / total if total > 0 else 0,
                "avg_duration_ms": float(avg_duration),
                "period_days": days,
            }


# 导出
__all__ = [
    "TaskExecutionRepository",
    "ToolCallLogRepository",
]

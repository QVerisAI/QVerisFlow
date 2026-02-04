"""
执行服务

提供执行记录的业务逻辑处理，包括：
- 执行记录管理
- 执行状态追踪
- 执行结果查询
- 执行统计
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from src.storage.repositories import (
    WorkflowExecutionRepository,
    TaskExecutionRepository,
    ToolCallLogRepository,
)
from src.storage.models.db_models import (
    WorkflowExecutionModel,
    TaskExecutionModel,
    WorkflowStatus,
    TaskStatus,
)
from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class ExecutionSummary:
    """执行摘要"""

    id: str
    workflow_id: str
    status: str
    nodes_total: int
    nodes_completed: int
    nodes_failed: int
    total_duration_ms: int
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    error: Optional[str] = None


@dataclass
class ExecutionDetail:
    """执行详情"""

    id: str
    workflow_id: str
    status: str
    initial_context: Dict[str, Any]
    final_output: Any
    node_results: Dict[str, Any]
    total_duration_ms: int
    checkpoint_id: Optional[str]
    error: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str


@dataclass
class NodeExecutionDetail:
    """节点执行详情"""

    node_id: str
    status: str
    input_data: Dict[str, Any]
    output_data: Any
    started_at: Optional[str]
    completed_at: Optional[str]
    duration_ms: int
    error: Optional[str] = None


@dataclass
class ExecutionStatistics:
    """执行统计"""

    total_executions: int
    successful: int
    failed: int
    cancelled: int
    running: int
    success_rate: float
    avg_duration_ms: float
    period_days: int


@dataclass
class ExecutionFilters:
    """执行过滤条件"""

    workflow_id: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = 50
    offset: int = 0


class ExecutionService:
    """
    执行服务

    管理执行记录的查询、状态追踪和统计。
    """

    def __init__(
        self,
        workflow_execution_repo: WorkflowExecutionRepository,
        task_execution_repo: TaskExecutionRepository,
        tool_call_repo: ToolCallLogRepository,
    ):
        """
        初始化执行服务

        Args:
            workflow_execution_repo: 工作流执行仓库
            task_execution_repo: 任务执行仓库
            tool_call_repo: 工具调用仓库
        """
        self.workflow_execution_repo = workflow_execution_repo
        self.task_execution_repo = task_execution_repo
        self.tool_call_repo = tool_call_repo

    # ==================== 执行查询 ====================

    async def get_execution(self, execution_id: str) -> Optional[ExecutionDetail]:
        """
        获取执行详情

        Args:
            execution_id: 执行 ID

        Returns:
            执行详情
        """
        model = await self.workflow_execution_repo.get_by_id(execution_id)
        if not model:
            return None

        return self._model_to_detail(model)

    async def list_executions(
        self,
        filters: ExecutionFilters = None,
    ) -> List[ExecutionSummary]:
        """
        列出执行记录

        Args:
            filters: 过滤条件

        Returns:
            执行摘要列表
        """
        filters = filters or ExecutionFilters()

        if filters.workflow_id:
            models = await self.workflow_execution_repo.get_by_workflow(
                workflow_definition_id=filters.workflow_id,
                status=WorkflowStatus(filters.status) if filters.status else None,
                limit=filters.limit,
            )
        else:
            models = await self.workflow_execution_repo.get_all(
                limit=filters.limit,
                offset=filters.offset,
                order_by="created_at",
                order_desc=True,
            )

            # 应用状态过滤
            if filters.status:
                try:
                    status = WorkflowStatus(filters.status)
                    models = [m for m in models if m.status == status]
                except ValueError:
                    pass

        # 应用日期过滤
        if filters.start_date:
            models = [m for m in models if m.created_at >= filters.start_date]

        if filters.end_date:
            models = [m for m in models if m.created_at <= filters.end_date]

        return [self._model_to_summary(m) for m in models]

    async def get_running_executions(
        self,
        limit: int = 50,
    ) -> List[ExecutionSummary]:
        """
        获取正在运行的执行

        Args:
            limit: 数量限制

        Returns:
            执行摘要列表
        """
        models = await self.workflow_execution_repo.get_running_executions(limit=limit)
        return [self._model_to_summary(m) for m in models]

    async def get_recent_executions(
        self,
        days: int = 7,
        limit: int = 50,
    ) -> List[ExecutionSummary]:
        """
        获取最近的执行

        Args:
            days: 天数
            limit: 数量限制

        Returns:
            执行摘要列表
        """
        start_date = datetime.utcnow() - timedelta(days=days)

        models = await self.workflow_execution_repo.get_all(
            limit=limit,
            order_by="created_at",
            order_desc=True,
        )

        models = [m for m in models if m.created_at >= start_date]

        return [self._model_to_summary(m) for m in models]

    # ==================== 节点执行详情 ====================

    async def get_node_results(
        self,
        execution_id: str,
    ) -> Dict[str, NodeExecutionDetail]:
        """
        获取执行的节点结果

        Args:
            execution_id: 执行 ID

        Returns:
            节点执行详情字典
        """
        model = await self.workflow_execution_repo.get_by_id(execution_id)
        if not model:
            return {}

        node_results = model.node_results or {}

        return {
            node_id: self._parse_node_result(node_id, result)
            for node_id, result in node_results.items()
        }

    async def get_node_result(
        self,
        execution_id: str,
        node_id: str,
    ) -> Optional[NodeExecutionDetail]:
        """
        获取特定节点的执行结果

        Args:
            execution_id: 执行 ID
            node_id: 节点 ID

        Returns:
            节点执行详情
        """
        model = await self.workflow_execution_repo.get_by_id(execution_id)
        if not model:
            return None

        node_results = model.node_results or {}
        result = node_results.get(node_id)

        if not result:
            return None

        return self._parse_node_result(node_id, result)

    # ==================== 执行控制 ====================

    async def cancel_execution(self, execution_id: str) -> bool:
        """
        取消执行

        Args:
            execution_id: 执行 ID

        Returns:
            是否取消成功
        """
        model = await self.workflow_execution_repo.get_by_id(execution_id)
        if not model:
            return False

        # 只能取消 pending 或 running 状态的执行
        if model.status not in [WorkflowStatus.PENDING, WorkflowStatus.RUNNING]:
            logger.warning(f"无法取消执行 {execution_id}，当前状态: {model.status}")
            return False

        updated = await self.workflow_execution_repo.update_status(
            execution_id,
            WorkflowStatus.CANCELLED,
        )

        if updated:
            logger.info(f"取消执行: {execution_id}")
            return True

        return False

    # ==================== 执行统计 ====================

    async def get_statistics(
        self,
        workflow_id: str = None,
        days: int = 30,
    ) -> ExecutionStatistics:
        """
        获取执行统计

        Args:
            workflow_id: 工作流 ID（可选）
            days: 统计天数

        Returns:
            执行统计
        """
        start_date = datetime.utcnow() - timedelta(days=days)

        # 获取所有执行
        if workflow_id:
            models = await self.workflow_execution_repo.get_by_workflow(
                workflow_definition_id=workflow_id,
                limit=10000,  # 获取足够多的记录
            )
        else:
            models = await self.workflow_execution_repo.get_all(
                limit=10000,
                order_by="created_at",
                order_desc=True,
            )

        # 过滤日期
        models = [m for m in models if m.created_at >= start_date]

        # 统计
        total = len(models)
        successful = sum(1 for m in models if m.status == WorkflowStatus.COMPLETED)
        failed = sum(1 for m in models if m.status == WorkflowStatus.FAILED)
        cancelled = sum(1 for m in models if m.status == WorkflowStatus.CANCELLED)
        running = sum(1 for m in models if m.status == WorkflowStatus.RUNNING)

        # 计算平均耗时（仅统计完成的执行）
        completed_models = [m for m in models if m.status == WorkflowStatus.COMPLETED]
        total_duration = sum(m.total_duration_ms or 0 for m in completed_models)
        avg_duration = total_duration / len(completed_models) if completed_models else 0

        return ExecutionStatistics(
            total_executions=total,
            successful=successful,
            failed=failed,
            cancelled=cancelled,
            running=running,
            success_rate=successful / total if total > 0 else 0,
            avg_duration_ms=avg_duration,
            period_days=days,
        )

    async def get_task_statistics(
        self,
        agent_id: str = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取任务执行统计

        Args:
            agent_id: Agent ID（可选）
            days: 统计天数

        Returns:
            统计信息
        """
        return await self.task_execution_repo.get_statistics(
            agent_definition_id=agent_id,
            days=days,
        )

    async def get_tool_statistics(
        self,
        tool_id: str = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取工具调用统计

        Args:
            tool_id: 工具 ID（可选）
            days: 统计天数

        Returns:
            统计信息
        """
        return await self.tool_call_repo.get_tool_statistics(
            tool_id=tool_id,
            days=days,
        )

    # ==================== 辅助方法 ====================

    def _model_to_summary(self, model: WorkflowExecutionModel) -> ExecutionSummary:
        """转换为摘要"""
        node_results = model.node_results or {}
        completed = sum(
            1 for r in node_results.values() if r.get("status") == "completed"
        )
        failed = sum(1 for r in node_results.values() if r.get("status") == "failed")

        return ExecutionSummary(
            id=model.id,
            workflow_id=model.workflow_definition_id,
            status=model.status.value if model.status else "unknown",
            nodes_total=len(node_results),
            nodes_completed=completed,
            nodes_failed=failed,
            total_duration_ms=int(model.total_duration_ms or 0),
            started_at=model.started_at.isoformat() if model.started_at else None,
            completed_at=model.completed_at.isoformat() if model.completed_at else None,
            created_at=model.created_at.isoformat() if model.created_at else "",
            error=model.error,
        )

    def _model_to_detail(self, model: WorkflowExecutionModel) -> ExecutionDetail:
        """转换为详情"""
        return ExecutionDetail(
            id=model.id,
            workflow_id=model.workflow_definition_id,
            status=model.status.value if model.status else "unknown",
            initial_context=model.initial_context or {},
            final_output=model.final_output,
            node_results=model.node_results or {},
            total_duration_ms=int(model.total_duration_ms or 0),
            checkpoint_id=model.checkpoint_id,
            error=model.error,
            started_at=model.started_at.isoformat() if model.started_at else None,
            completed_at=model.completed_at.isoformat() if model.completed_at else None,
            created_at=model.created_at.isoformat() if model.created_at else "",
        )

    def _parse_node_result(
        self,
        node_id: str,
        result: Dict[str, Any],
    ) -> NodeExecutionDetail:
        """解析节点结果"""
        return NodeExecutionDetail(
            node_id=node_id,
            status=result.get("status", "unknown"),
            input_data=result.get("input", {}),
            output_data=result.get("output"),
            started_at=result.get("started_at"),
            completed_at=result.get("completed_at"),
            duration_ms=result.get("duration_ms", 0),
            error=result.get("error"),
        )

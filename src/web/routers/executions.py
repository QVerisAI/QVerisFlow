"""
执行历史路由

处理执行记录的查询和管理。
"""

from typing import Optional, List
from datetime import datetime

try:
    from fastapi import APIRouter, HTTPException, Query, Depends
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError("请安装 web 依赖: pip install -e '.[web]'")

from src.utils.logger import get_logger
from src.services import ExecutionService
from src.storage.database import AsyncDatabaseManager
from src.storage.repositories import (
    WorkflowExecutionRepository,
    TaskExecutionRepository,
    ToolCallLogRepository,
)

logger = get_logger()

router = APIRouter(prefix="/executions", tags=["executions"])


# ==================== 响应模型 ====================


class ExecutionSummaryResponse(BaseModel):
    """执行摘要响应"""

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


class ExecutionDetailResponse(BaseModel):
    """执行详情响应"""

    id: str
    workflow_id: str
    status: str
    initial_context: dict
    final_output: Optional[dict]
    node_results: dict
    total_duration_ms: int
    checkpoint_id: Optional[str]
    error: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str


class NodeExecutionResponse(BaseModel):
    """节点执行响应"""

    node_id: str
    status: str
    input_data: dict
    output_data: Optional[dict]
    started_at: Optional[str]
    completed_at: Optional[str]
    duration_ms: int
    error: Optional[str] = None


class ExecutionListResponse(BaseModel):
    """执行列表响应"""

    executions: List[ExecutionSummaryResponse]
    total: int


class ExecutionStatisticsResponse(BaseModel):
    """执行统计响应"""

    total_executions: int
    successful: int
    failed: int
    cancelled: int
    running: int
    success_rate: float
    avg_duration_ms: float
    period_days: int


# ==================== 依赖注入 ====================

_execution_service: Optional[ExecutionService] = None


async def get_execution_service() -> ExecutionService:
    """获取执行服务实例"""
    global _execution_service

    if _execution_service is None:
        from src.storage.config import PostgreSQLConfig
        import os

        config = PostgreSQLConfig(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "agent_framework"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
        )

        db = AsyncDatabaseManager(config)
        await db.connect()

        workflow_exec_repo = WorkflowExecutionRepository(db._session_factory)
        task_exec_repo = TaskExecutionRepository(db._session_factory)
        tool_call_repo = ToolCallLogRepository(db._session_factory)

        _execution_service = ExecutionService(
            workflow_execution_repo=workflow_exec_repo,
            task_execution_repo=task_exec_repo,
            tool_call_repo=tool_call_repo,
        )

    return _execution_service


# ==================== API 端点 ====================


@router.get("", response_model=ExecutionListResponse)
async def list_executions(
    workflow_id: Optional[str] = Query(None, description="工作流 ID 过滤"),
    status: Optional[str] = Query(None, description="状态过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: ExecutionService = Depends(get_execution_service),
):
    """
    获取执行列表
    """
    from src.services.execution_service import ExecutionFilters

    filters = ExecutionFilters(
        workflow_id=workflow_id,
        status=status,
        limit=limit,
        offset=offset,
    )

    executions = await service.list_executions(filters)

    return ExecutionListResponse(
        executions=[
            ExecutionSummaryResponse(
                id=e.id,
                workflow_id=e.workflow_id,
                status=e.status,
                nodes_total=e.nodes_total,
                nodes_completed=e.nodes_completed,
                nodes_failed=e.nodes_failed,
                total_duration_ms=e.total_duration_ms,
                started_at=e.started_at,
                completed_at=e.completed_at,
                created_at=e.created_at,
                error=e.error,
            )
            for e in executions
        ],
        total=len(executions),
    )


@router.get("/running", response_model=ExecutionListResponse)
async def get_running_executions(
    limit: int = Query(50, ge=1, le=200),
    service: ExecutionService = Depends(get_execution_service),
):
    """
    获取正在运行的执行
    """
    executions = await service.get_running_executions(limit=limit)

    return ExecutionListResponse(
        executions=[
            ExecutionSummaryResponse(
                id=e.id,
                workflow_id=e.workflow_id,
                status=e.status,
                nodes_total=e.nodes_total,
                nodes_completed=e.nodes_completed,
                nodes_failed=e.nodes_failed,
                total_duration_ms=e.total_duration_ms,
                started_at=e.started_at,
                completed_at=e.completed_at,
                created_at=e.created_at,
                error=e.error,
            )
            for e in executions
        ],
        total=len(executions),
    )


@router.get("/recent", response_model=ExecutionListResponse)
async def get_recent_executions(
    days: int = Query(7, ge=1, le=90, description="天数"),
    limit: int = Query(50, ge=1, le=200),
    service: ExecutionService = Depends(get_execution_service),
):
    """
    获取最近的执行
    """
    executions = await service.get_recent_executions(days=days, limit=limit)

    return ExecutionListResponse(
        executions=[
            ExecutionSummaryResponse(
                id=e.id,
                workflow_id=e.workflow_id,
                status=e.status,
                nodes_total=e.nodes_total,
                nodes_completed=e.nodes_completed,
                nodes_failed=e.nodes_failed,
                total_duration_ms=e.total_duration_ms,
                started_at=e.started_at,
                completed_at=e.completed_at,
                created_at=e.created_at,
                error=e.error,
            )
            for e in executions
        ],
        total=len(executions),
    )


@router.get("/statistics", response_model=ExecutionStatisticsResponse)
async def get_statistics(
    workflow_id: Optional[str] = Query(None, description="工作流 ID"),
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    service: ExecutionService = Depends(get_execution_service),
):
    """
    获取执行统计
    """
    stats = await service.get_statistics(workflow_id=workflow_id, days=days)

    return ExecutionStatisticsResponse(
        total_executions=stats.total_executions,
        successful=stats.successful,
        failed=stats.failed,
        cancelled=stats.cancelled,
        running=stats.running,
        success_rate=stats.success_rate,
        avg_duration_ms=stats.avg_duration_ms,
        period_days=stats.period_days,
    )


@router.get("/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution(
    execution_id: str,
    service: ExecutionService = Depends(get_execution_service),
):
    """
    获取执行详情
    """
    execution = await service.get_execution(execution_id)

    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")

    return ExecutionDetailResponse(
        id=execution.id,
        workflow_id=execution.workflow_id,
        status=execution.status,
        initial_context=execution.initial_context,
        final_output=execution.final_output,
        node_results=execution.node_results,
        total_duration_ms=execution.total_duration_ms,
        checkpoint_id=execution.checkpoint_id,
        error=execution.error,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        created_at=execution.created_at,
    )


@router.get("/{execution_id}/nodes")
async def get_node_results(
    execution_id: str,
    service: ExecutionService = Depends(get_execution_service),
):
    """
    获取执行的节点结果
    """
    nodes = await service.get_node_results(execution_id)

    if not nodes:
        raise HTTPException(status_code=404, detail="执行记录不存在")

    return {
        "nodes": [
            NodeExecutionResponse(
                node_id=n.node_id,
                status=n.status,
                input_data=n.input_data,
                output_data=n.output_data,
                started_at=n.started_at,
                completed_at=n.completed_at,
                duration_ms=n.duration_ms,
                error=n.error,
            )
            for n in nodes.values()
        ]
    }


@router.get("/{execution_id}/nodes/{node_id}", response_model=NodeExecutionResponse)
async def get_node_result(
    execution_id: str,
    node_id: str,
    service: ExecutionService = Depends(get_execution_service),
):
    """
    获取特定节点的执行结果
    """
    node = await service.get_node_result(execution_id, node_id)

    if not node:
        raise HTTPException(status_code=404, detail="节点执行记录不存在")

    return NodeExecutionResponse(
        node_id=node.node_id,
        status=node.status,
        input_data=node.input_data,
        output_data=node.output_data,
        started_at=node.started_at,
        completed_at=node.completed_at,
        duration_ms=node.duration_ms,
        error=node.error,
    )


@router.post("/{execution_id}/cancel")
async def cancel_execution(
    execution_id: str,
    service: ExecutionService = Depends(get_execution_service),
):
    """
    取消执行
    """
    result = await service.cancel_execution(execution_id)

    if not result:
        raise HTTPException(
            status_code=400, detail="无法取消执行（可能已完成或不存在）"
        )

    return {"success": True, "message": f"执行 {execution_id} 已取消"}

"""
执行路由

处理工作流执行相关的操作。
"""

from typing import Optional
from datetime import datetime
import uuid

try:
    from fastapi import APIRouter, HTTPException, BackgroundTasks
except ImportError:
    raise ImportError("请安装 web 依赖: pip install -e '.[web]'")

from src.utils.logger import get_logger
from src.web.models.api_models import (
    ExecutionRequest,
    ExecutionResponse,
    ExecutionStatus,
    InterventionRequest,
    BaseResponse,
)
from src.web.websocket.handlers import session_manager

logger = get_logger()

router = APIRouter(prefix="/execution", tags=["execution"])


# 存储执行状态
_execution_states: dict = {}


@router.post("/{session_id}/start", response_model=ExecutionResponse)
async def start_execution(
    session_id: str,
    request: ExecutionRequest,
    background_tasks: BackgroundTasks,
):
    """
    启动工作流执行
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    if not builder.builder or not builder.builder.draft_workflow:
        raise HTTPException(status_code=400, detail="没有可执行的工作流")
    
    # 生成执行 ID
    execution_id = f"exec_{uuid.uuid4().hex[:8]}"
    workflow_id = builder.builder.draft_workflow.workflow_id
    total_nodes = len(builder.builder.draft_workflow.nodes)
    
    # 初始化执行状态
    execution_state = {
        "execution_id": execution_id,
        "workflow_id": workflow_id,
        "status": ExecutionStatus.PENDING,
        "started_at": datetime.now(),
        "completed_at": None,
        "current_node": None,
        "nodes_completed": 0,
        "total_nodes": total_nodes,
        "result": None,
        "error": None,
    }
    _execution_states[execution_id] = execution_state
    
    # 在后台执行
    if request.streaming:
        # 流式执行（通过 WebSocket 推送事件）
        background_tasks.add_task(
            _execute_workflow_streaming,
            builder,
            execution_id,
            request.params,
        )
    else:
        # 非流式执行
        background_tasks.add_task(
            _execute_workflow,
            builder,
            execution_id,
            request.params,
        )
    
    return ExecutionResponse(
        execution_id=execution_id,
        workflow_id=workflow_id,
        status=ExecutionStatus.RUNNING,
        started_at=datetime.now(),
        total_nodes=total_nodes,
    )


async def _execute_workflow(builder, execution_id: str, params: dict):
    """执行工作流（非流式）"""
    try:
        _execution_states[execution_id]["status"] = ExecutionStatus.RUNNING
        
        # 发送消息触发执行
        message = "执行"
        if params:
            message += f" {params}"
        
        await builder.process_message(message)
        
        _execution_states[execution_id]["status"] = ExecutionStatus.COMPLETED
        _execution_states[execution_id]["completed_at"] = datetime.now()
        
    except Exception as e:
        logger.error(f"执行失败: {e}")
        _execution_states[execution_id]["status"] = ExecutionStatus.FAILED
        _execution_states[execution_id]["error"] = str(e)
        _execution_states[execution_id]["completed_at"] = datetime.now()


async def _execute_workflow_streaming(builder, execution_id: str, params: dict):
    """执行工作流（流式）"""
    try:
        _execution_states[execution_id]["status"] = ExecutionStatus.RUNNING
        
        # 发送消息触发执行
        message = "执行"
        if params:
            message += f" {params}"
        
        await builder.process_message(message)
        
        _execution_states[execution_id]["status"] = ExecutionStatus.COMPLETED
        _execution_states[execution_id]["completed_at"] = datetime.now()
        
    except Exception as e:
        logger.error(f"执行失败: {e}")
        _execution_states[execution_id]["status"] = ExecutionStatus.FAILED
        _execution_states[execution_id]["error"] = str(e)
        _execution_states[execution_id]["completed_at"] = datetime.now()


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution_status(execution_id: str):
    """
    获取执行状态
    """
    if execution_id not in _execution_states:
        raise HTTPException(status_code=404, detail="执行不存在")
    
    state = _execution_states[execution_id]
    
    return ExecutionResponse(
        execution_id=state["execution_id"],
        workflow_id=state["workflow_id"],
        status=state["status"],
        started_at=state["started_at"],
        completed_at=state.get("completed_at"),
        current_node=state.get("current_node"),
        nodes_completed=state.get("nodes_completed", 0),
        total_nodes=state.get("total_nodes", 0),
        result=state.get("result"),
        error=state.get("error"),
    )


@router.post("/{session_id}/intervene", response_model=BaseResponse)
async def intervene_execution(session_id: str, request: InterventionRequest):
    """
    干预执行中的工作流
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    action = request.action
    
    try:
        if action == "pause":
            response = await builder.process_message("暂停")
        elif action == "resume":
            response = await builder.process_message("继续")
        elif action == "stop":
            response = await builder.process_message("停止")
        elif action == "skip_node":
            node_id = request.node_id or ""
            response = await builder.process_message(f"跳过 {node_id}")
        elif action == "inject_context":
            context = request.params.get("context", "")
            response = await builder.process_message(f"注入上下文: {context}")
        else:
            raise HTTPException(status_code=400, detail=f"未知操作: {action}")
        
        return BaseResponse(
            success=True,
            message=response.message,
        )
        
    except Exception as e:
        logger.error(f"干预失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{execution_id}", response_model=BaseResponse)
async def cancel_execution(execution_id: str):
    """
    取消执行
    """
    if execution_id not in _execution_states:
        raise HTTPException(status_code=404, detail="执行不存在")
    
    state = _execution_states[execution_id]
    
    if state["status"] not in [ExecutionStatus.RUNNING, ExecutionStatus.PAUSED]:
        raise HTTPException(status_code=400, detail="执行已完成或已取消")
    
    # TODO: 实际取消执行（需要 WorkflowEngine 支持）
    state["status"] = ExecutionStatus.CANCELLED
    state["completed_at"] = datetime.now()
    
    return BaseResponse(
        success=True,
        message=f"执行 {execution_id} 已取消",
    )

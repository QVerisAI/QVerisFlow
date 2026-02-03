"""
工作流路由

处理工作流的查询、保存、加载等操作。
"""

from typing import Optional
from datetime import datetime
from pathlib import Path
import json

try:
    from fastapi import APIRouter, HTTPException, Query
except ImportError:
    raise ImportError("请安装 web 依赖: pip install -e '.[web]'")

from src.utils.logger import get_logger
from src.web.models.api_models import (
    WorkflowResponse,
    WorkflowState,
    WorkflowSaveRequest,
    WorkflowLoadRequest,
    AgentInfo,
    NodeInfo,
    EdgeInfo,
    CheckpointInfo,
    CheckpointListResponse,
    RollbackRequest,
    BaseResponse,
)
from src.web.websocket.handlers import session_manager

logger = get_logger()

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/{session_id}", response_model=WorkflowResponse)
async def get_workflow(session_id: str):
    """
    获取会话的工作流状态
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    if not builder.builder:
        raise HTTPException(status_code=400, detail="工作流尚未创建")
    
    state = builder._get_workflow_state()
    
    # 构建响应
    agents = []
    for agent_data in state.get("agents", []):
        agents.append(AgentInfo(
            agent_id=agent_data.get("agent_id", ""),
            name=agent_data.get("name", ""),
            description=agent_data.get("description"),
            domain_type=agent_data.get("domain_type", "general"),
        ))
    
    nodes = []
    for node_data in state.get("nodes", []):
        nodes.append(NodeInfo(
            node_id=node_data.get("node_id", ""),
            name=node_data.get("name", ""),
            node_type=node_data.get("node_type", "agent"),
            agent_id=node_data.get("agent_id"),
        ))
    
    edges = []
    for edge_data in state.get("edges", []):
        edges.append(EdgeInfo(
            source=edge_data.get("source", ""),
            target=edge_data.get("target", ""),
        ))
    
    workflow_state = WorkflowState(
        mode=state.get("mode", "idle"),
        stage=state.get("stage", "idle"),
        agents=agents,
        nodes=nodes,
        edges=edges,
        checkpoints=state.get("checkpoints", []),
    )
    
    workflow_id = builder.builder.draft_workflow.workflow_id if builder.builder.draft_workflow else session_id
    workflow_name = builder.builder.draft_workflow.name if builder.builder.draft_workflow else "未命名工作流"
    
    return WorkflowResponse(
        workflow_id=workflow_id,
        name=workflow_name,
        description=builder.builder.task_description,
        state=workflow_state,
        created_at=datetime.now(),
    )


@router.post("/{session_id}/save", response_model=BaseResponse)
async def save_workflow(session_id: str, request: WorkflowSaveRequest):
    """
    保存工作流到文件
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    if not builder.builder or not builder.builder.draft_workflow:
        raise HTTPException(status_code=400, detail="没有可保存的工作流")
    
    try:
        # 更新名称和描述
        if request.name:
            builder.builder.draft_workflow.name = request.name
        if request.description:
            builder.builder.draft_workflow.description = request.description
        
        # 保存工作流
        save_path = builder.storage_path / "workflow.json"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(
                builder.builder.draft_workflow.model_dump(),
                f,
                ensure_ascii=False,
                indent=2,
            )
        
        return BaseResponse(
            success=True,
            message=f"工作流已保存到 {save_path}",
        )
        
    except Exception as e:
        logger.error(f"保存工作流失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/load", response_model=BaseResponse)
async def load_workflow(session_id: str, request: WorkflowLoadRequest):
    """
    从文件加载工作流
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    workflow_path = Path(request.workflow_path)
    
    if not workflow_path.exists():
        raise HTTPException(status_code=404, detail="工作流文件不存在")
    
    try:
        from src.definitions import WorkflowDefinition
        
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow_data = json.load(f)
        
        workflow = WorkflowDefinition(**workflow_data)
        
        # 初始化构建器（如果需要）
        if not builder.builder:
            from src.evolution.interactive_builder import InteractiveWorkflowBuilder
            from src.evolution.conversational_builder import AutoApproveCallback
            
            builder.builder = InteractiveWorkflowBuilder(
                meta_agent=builder.meta_agent,
                callback=AutoApproveCallback(),
                storage_path=builder.storage_path,
            )
        
        builder.builder.draft_workflow = workflow
        
        return BaseResponse(
            success=True,
            message=f"已加载工作流: {workflow.name}",
        )
        
    except Exception as e:
        logger.error(f"加载工作流失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/checkpoints", response_model=CheckpointListResponse)
async def get_checkpoints(session_id: str):
    """
    获取会话的检查点列表
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    if not builder.builder:
        return CheckpointListResponse(checkpoints=[], current=None)
    
    checkpoints = builder.builder.iteration_manager.get_checkpoints()
    
    checkpoint_infos = []
    for ckpt in checkpoints:
        checkpoint_infos.append(CheckpointInfo(
            checkpoint_id=ckpt.checkpoint_id,
            label=ckpt.label,
            stage=ckpt.stage.value if hasattr(ckpt.stage, 'value') else str(ckpt.stage),
            timestamp=ckpt.timestamp if isinstance(ckpt.timestamp, datetime) else datetime.now(),
        ))
    
    current = checkpoints[-1].checkpoint_id if checkpoints else None
    
    return CheckpointListResponse(
        checkpoints=checkpoint_infos,
        current=current,
    )


@router.post("/{session_id}/rollback", response_model=BaseResponse)
async def rollback_workflow(session_id: str, request: RollbackRequest):
    """
    回滚到指定检查点
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    if not builder.builder:
        raise HTTPException(status_code=400, detail="没有可回滚的工作流")
    
    try:
        state = builder.builder.iteration_manager.rollback(request.checkpoint_id)
        builder.builder._restore_state(state)
        
        return BaseResponse(
            success=True,
            message=f"已回滚到检查点: {request.checkpoint_id}",
        )
        
    except Exception as e:
        logger.error(f"回滚失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

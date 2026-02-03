"""
会话路由

处理会话创建、查询、删除等操作。
"""

from typing import Optional
from datetime import datetime
from pathlib import Path
import uuid

try:
    from fastapi import APIRouter, HTTPException, Depends, Query
except ImportError:
    raise ImportError("请安装 web 依赖: pip install -e '.[web]'")

from src.utils.logger import get_logger
from src.web.models.api_models import (
    SessionCreate,
    SessionResponse,
    SessionListResponse,
    MessageRequest,
    MessageResponse,
    ChatMessage,
    BaseResponse,
    ErrorResponse,
)
from src.web.websocket.handlers import session_manager

logger = get_logger()

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_dependencies():
    """获取依赖（延迟导入以避免循环依赖）"""
    from src.web.app import get_meta_agent, get_tool_registry, get_llm_client, get_workflow_engine
    return get_meta_agent(), get_tool_registry(), get_llm_client(), get_workflow_engine()


@router.post("", response_model=SessionResponse)
async def create_session(request: SessionCreate):
    """
    创建新的对话会话
    """
    from src.evolution.conversational_builder import ConversationalWorkflowBuilder
    
    try:
        meta_agent, tool_registry, llm_client, workflow_engine = get_dependencies()
        
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        workspace_name = request.workspace_name or session_id
        storage_path = Path("./workspaces") / workspace_name
        
        builder = ConversationalWorkflowBuilder(
            meta_agent=meta_agent,
            tool_registry=tool_registry,
            llm_client=llm_client,
            workflow_engine=workflow_engine,
            storage_path=storage_path,
        )
        
        # 如果提供了任务描述，自动开始构建
        if request.task_description:
            await builder.process_message(request.task_description)
        
        # 保存会话
        await session_manager.create_session(session_id, builder)
        
        return SessionResponse(
            session_id=session_id,
            mode=builder.mode.value,
            stage=builder.builder.current_stage.value if builder.builder else None,
            created_at=datetime.now(),
            agents_count=len(builder.builder.draft_agents) if builder.builder else 0,
            has_workflow=builder.builder.draft_workflow is not None if builder.builder else False,
            message_count=len(builder.conversation_history),
        )
        
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """
    列出所有会话
    """
    sessions_info = session_manager.list_sessions()
    
    # 分页
    total = len(sessions_info)
    sessions_info = sessions_info[skip:skip + limit]
    
    sessions = []
    for info in sessions_info:
        builder = await session_manager.get_session(info["session_id"])
        if builder:
            sessions.append(SessionResponse(
                session_id=info["session_id"],
                mode=builder.mode.value,
                stage=builder.builder.current_stage.value if builder.builder else None,
                created_at=datetime.now(),  # TODO: 从 builder 获取创建时间
                agents_count=len(builder.builder.draft_agents) if builder.builder else 0,
                has_workflow=builder.builder.draft_workflow is not None if builder.builder else False,
                message_count=len(builder.conversation_history),
            ))
    
    return SessionListResponse(sessions=sessions, total=total)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """
    获取会话详情
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    return SessionResponse(
        session_id=session_id,
        mode=builder.mode.value,
        stage=builder.builder.current_stage.value if builder.builder else None,
        created_at=datetime.now(),
        agents_count=len(builder.builder.draft_agents) if builder.builder else 0,
        has_workflow=builder.builder.draft_workflow is not None if builder.builder else False,
        message_count=len(builder.conversation_history),
    )


@router.delete("/{session_id}", response_model=BaseResponse)
async def delete_session(session_id: str):
    """
    删除会话
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    await session_manager.remove_session(session_id)
    
    return BaseResponse(
        success=True,
        message=f"会话 {session_id} 已删除"
    )


@router.post("/{session_id}/messages", response_model=MessageResponse)
async def send_message(session_id: str, request: MessageRequest):
    """
    发送消息到会话
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    try:
        response = await builder.process_message(request.content)
        
        return MessageResponse(
            message=ChatMessage(
                role="assistant",
                content=response.message,
                timestamp=datetime.now(),
                message_type="text",
            ),
            workflow_changed=response.workflow_changed,
            suggested_actions=response.suggested_actions,
            highlighted_nodes=response.highlighted_nodes,
            data=response.data,
        )
        
    except Exception as e:
        logger.error(f"处理消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/messages")
async def get_messages(
    session_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """
    获取会话消息历史
    """
    builder = await session_manager.get_session(session_id)
    
    if not builder:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    messages = builder.conversation_history[skip:skip + limit]
    
    return {
        "messages": [m.to_dict() for m in messages],
        "total": len(builder.conversation_history),
    }

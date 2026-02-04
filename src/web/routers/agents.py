"""
Agent 路由

处理 Agent 的 CRUD 操作和模板管理。
"""

from typing import Optional, List
from datetime import datetime

try:
    from fastapi import APIRouter, HTTPException, Query, Depends
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError("请安装 web 依赖: pip install -e '.[web]'")

from src.utils.logger import get_logger
from src.services import AgentService
from src.storage.database import AsyncDatabaseManager
from src.storage.repositories import AgentRepository

logger = get_logger()

router = APIRouter(prefix="/agents", tags=["agents"])


# ==================== 请求/响应模型 ====================


class AgentCreateRequest(BaseModel):
    """创建 Agent 请求"""

    agent_id: str = Field(..., description="Agent ID")
    name: str = Field(..., description="Agent 名称")
    description: str = Field("", description="描述")
    definition: dict = Field(..., description="完整的 Agent 定义")
    is_template: bool = Field(False, description="是否为模板")


class AgentUpdateRequest(BaseModel):
    """更新 Agent 请求"""

    name: Optional[str] = None
    description: Optional[str] = None
    definition: Optional[dict] = None
    tags: Optional[List[str]] = None


class AgentSummaryResponse(BaseModel):
    """Agent 摘要响应"""

    id: str
    agent_id: str
    name: str
    description: str
    version: str
    status: str
    domain_type: str
    execution_type: str
    model_name: str
    tags: List[str]
    author: str
    is_template: bool
    created_at: str
    updated_at: str


class AgentDetailResponse(BaseModel):
    """Agent 详情响应"""

    id: str
    agent_id: str
    name: str
    description: str
    version: str
    status: str
    definition: dict
    tags: List[str]
    author: str
    is_template: bool
    created_at: str
    updated_at: str


class AgentListResponse(BaseModel):
    """Agent 列表响应"""

    agents: List[AgentSummaryResponse]
    total: int


class CreateFromTemplateRequest(BaseModel):
    """从模板创建请求"""

    template_id: str = Field(..., description="模板 Agent ID")
    new_agent_id: str = Field(..., description="新 Agent ID")
    overrides: Optional[dict] = Field(None, description="覆盖配置")


# ==================== 依赖注入 ====================

_agent_service: Optional[AgentService] = None


async def get_agent_service() -> AgentService:
    """获取 Agent 服务实例"""
    global _agent_service

    if _agent_service is None:
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

        agent_repo = AgentRepository(db._session_factory)
        _agent_service = AgentService(agent_repo)

    return _agent_service


# ==================== API 端点 ====================


@router.get("", response_model=AgentListResponse)
async def list_agents(
    status: Optional[str] = Query(None, description="状态过滤"),
    domain_type: Optional[str] = Query(None, description="领域类型过滤"),
    execution_type: Optional[str] = Query(None, description="执行类型过滤"),
    tags: Optional[str] = Query(None, description="标签过滤，逗号分隔"),
    query: Optional[str] = Query(None, description="搜索关键词"),
    is_template: Optional[bool] = Query(None, description="是否为模板"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: AgentService = Depends(get_agent_service),
):
    """
    获取 Agent 列表
    """
    from src.services.agent_service import AgentFilters

    filters = AgentFilters(
        status=status,
        domain_type=domain_type,
        execution_type=execution_type,
        tags=tags.split(",") if tags else None,
        query=query,
        is_template=is_template,
        limit=limit,
        offset=offset,
    )

    agents = await service.list_agents(filters)

    return AgentListResponse(
        agents=[
            AgentSummaryResponse(
                id=a.id,
                agent_id=a.agent_id,
                name=a.name,
                description=a.description,
                version=a.version,
                status=a.status,
                domain_type=a.domain_type,
                execution_type=a.execution_type,
                model_name=a.model_name,
                tags=a.tags,
                author=a.author,
                is_template=a.is_template,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in agents
        ],
        total=len(agents),
    )


@router.get("/templates", response_model=AgentListResponse)
async def list_templates(
    domain_type: Optional[str] = Query(None, description="领域类型过滤"),
    limit: int = Query(50, ge=1, le=200),
    service: AgentService = Depends(get_agent_service),
):
    """
    获取模板 Agent 列表
    """
    templates = await service.get_templates(
        domain_type=domain_type,
        limit=limit,
    )

    return AgentListResponse(
        agents=[
            AgentSummaryResponse(
                id=a.id,
                agent_id=a.agent_id,
                name=a.name,
                description=a.description,
                version=a.version,
                status=a.status,
                domain_type=a.domain_type,
                execution_type=a.execution_type,
                model_name=a.model_name,
                tags=a.tags,
                author=a.author,
                is_template=a.is_template,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in templates
        ],
        total=len(templates),
    )


@router.get("/{agent_id}", response_model=AgentDetailResponse)
async def get_agent(
    agent_id: str,
    version: Optional[str] = Query(None, description="版本号"),
    service: AgentService = Depends(get_agent_service),
):
    """
    获取 Agent 详情
    """
    agent = await service.get_agent(agent_id, version)

    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    return AgentDetailResponse(
        id=agent.id,
        agent_id=agent.agent_id,
        name=agent.name,
        description=agent.description,
        version=agent.version,
        status=agent.status,
        definition=agent.definition,
        tags=agent.tags,
        author=agent.author,
        is_template=agent.is_template,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.post("", response_model=AgentDetailResponse)
async def create_agent(
    request: AgentCreateRequest,
    service: AgentService = Depends(get_agent_service),
):
    """
    创建 Agent
    """
    try:
        agent = await service.create_agent_from_dict(
            agent_data=request.definition,
            author="api",
        )

        return AgentDetailResponse(
            id=agent.id,
            agent_id=agent.agent_id,
            name=agent.name,
            description=agent.description,
            version=agent.version,
            status=agent.status,
            definition=agent.definition,
            tags=agent.tags,
            author=agent.author,
            is_template=agent.is_template,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )
    except Exception as e:
        logger.error(f"创建 Agent 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{agent_id}", response_model=AgentDetailResponse)
async def update_agent(
    agent_id: str,
    request: AgentUpdateRequest,
    service: AgentService = Depends(get_agent_service),
):
    """
    更新 Agent
    """
    updates = {}
    if request.name:
        updates["name"] = request.name
    if request.description is not None:
        updates["description"] = request.description
    if request.definition:
        updates["definition"] = request.definition
    if request.tags is not None:
        updates["tags"] = request.tags

    if not updates:
        raise HTTPException(status_code=400, detail="没有要更新的字段")

    agent = await service.update_agent(agent_id, updates)

    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    return AgentDetailResponse(
        id=agent.id,
        agent_id=agent.agent_id,
        name=agent.name,
        description=agent.description,
        version=agent.version,
        status=agent.status,
        definition=agent.definition,
        tags=agent.tags,
        author=agent.author,
        is_template=agent.is_template,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    service: AgentService = Depends(get_agent_service),
):
    """
    删除 Agent
    """
    result = await service.delete_agent(agent_id)

    if not result:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    return {"success": True, "message": f"Agent {agent_id} 已删除"}


@router.post("/{agent_id}/activate")
async def activate_agent(
    agent_id: str,
    service: AgentService = Depends(get_agent_service),
):
    """
    激活 Agent
    """
    agent = await service.activate_agent(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    return {"success": True, "message": f"Agent {agent_id} 已激活"}


@router.post("/{agent_id}/deactivate")
async def deactivate_agent(
    agent_id: str,
    service: AgentService = Depends(get_agent_service),
):
    """
    停用 Agent
    """
    agent = await service.deactivate_agent(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    return {"success": True, "message": f"Agent {agent_id} 已停用"}


@router.post("/{agent_id}/save-as-template")
async def save_as_template(
    agent_id: str,
    service: AgentService = Depends(get_agent_service),
):
    """
    将 Agent 保存为模板
    """
    agent = await service.save_as_template(agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    return {"success": True, "message": f"Agent {agent_id} 已保存为模板"}


@router.post("/create-from-template", response_model=AgentDetailResponse)
async def create_from_template(
    request: CreateFromTemplateRequest,
    service: AgentService = Depends(get_agent_service),
):
    """
    从模板创建 Agent
    """
    agent = await service.create_from_template(
        template_id=request.template_id,
        new_agent_id=request.new_agent_id,
        overrides=request.overrides,
        author="api",
    )

    if not agent:
        raise HTTPException(status_code=404, detail="模板不存在")

    return AgentDetailResponse(
        id=agent.id,
        agent_id=agent.agent_id,
        name=agent.name,
        description=agent.description,
        version=agent.version,
        status=agent.status,
        definition=agent.definition,
        tags=agent.tags,
        author=agent.author,
        is_template=agent.is_template,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.get("/{agent_id}/versions", response_model=AgentListResponse)
async def get_agent_versions(
    agent_id: str,
    service: AgentService = Depends(get_agent_service),
):
    """
    获取 Agent 的所有版本
    """
    versions = await service.get_all_versions(agent_id)

    return AgentListResponse(
        agents=[
            AgentSummaryResponse(
                id=a.id,
                agent_id=a.agent_id,
                name=a.name,
                description=a.description,
                version=a.version,
                status=a.status,
                domain_type=a.domain_type,
                execution_type=a.execution_type,
                model_name=a.model_name,
                tags=a.tags,
                author=a.author,
                is_template=a.is_template,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in versions
        ],
        total=len(versions),
    )

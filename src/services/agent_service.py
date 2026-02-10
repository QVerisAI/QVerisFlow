"""
Agent 服务

提供 Agent 的业务逻辑处理，包括：
- Agent CRUD 操作
- Agent 模板管理
- Agent 复用和版本管理
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field

from src.storage.repositories import AgentRepository
from src.storage.models.db_models import AgentDefinitionModel, AgentStatus
from src.definitions.agent_definition import AgentDefinition
from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class AgentSummary:
    """Agent 摘要"""

    id: str
    agent_id: str
    name: str
    display_name: str  # 用户友好的显示名称（中文）
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


@dataclass
class AgentDetail:
    """Agent 详情"""

    id: str
    agent_id: str
    name: str
    description: str
    version: str
    status: str
    definition: Dict[str, Any]
    tags: List[str]
    author: str
    is_template: bool
    created_at: str
    updated_at: str

    # 统计信息
    execution_count: int = 0


@dataclass
class AgentFilters:
    """Agent 过滤条件"""

    status: Optional[str] = None
    domain_type: Optional[str] = None
    execution_type: Optional[str] = None
    tags: Optional[List[str]] = None
    query: Optional[str] = None
    is_template: Optional[bool] = None
    limit: int = 50
    offset: int = 0


class AgentService:
    """
    Agent 服务

    管理 Agent 的生命周期，包括创建、更新、模板管理和查询。
    """

    def __init__(self, agent_repo: AgentRepository):
        """
        初始化 Agent 服务

        Args:
            agent_repo: Agent 仓库
        """
        self.agent_repo = agent_repo

    # ==================== Agent CRUD ====================

    async def create_agent(
        self,
        definition: AgentDefinition,
        author: str = "system",
        is_template: bool = False,
    ) -> AgentDetail:
        """
        创建 Agent

        Args:
            definition: Agent 定义
            author: 作者
            is_template: 是否为模板

        Returns:
            创建的 Agent 详情
        """
        # 转换为字典
        definition_dict = definition.model_dump(mode="json")

        # 创建记录
        model = await self.agent_repo.create_from_definition(
            definition=definition_dict,
            author=author,
        )

        # 如果是模板，更新状态
        if is_template:
            # 添加 is_template 字段到定义中
            definition_dict["is_template"] = True
            await self.agent_repo.update(
                model.id,
                {
                    "definition_json": definition_dict,
                },
            )

        logger.info(f"创建 Agent: {model.agent_id} (id={model.id})")

        return self._model_to_detail(model)

    async def create_agent_from_dict(
        self,
        agent_data: Dict[str, Any],
        author: str = "system",
    ) -> AgentDetail:
        """
        从字典创建 Agent

        Args:
            agent_data: Agent 数据字典
            author: 作者

        Returns:
            创建的 Agent 详情
        """
        model = await self.agent_repo.create_from_definition(
            definition=agent_data,
            author=author,
        )

        logger.info(f"创建 Agent: {model.agent_id} (id={model.id})")

        return self._model_to_detail(model)

    async def get_agent(
        self,
        agent_id: str,
        version: str = None,
    ) -> Optional[AgentDetail]:
        """
        获取 Agent 详情

        Args:
            agent_id: Agent ID
            version: 版本号（可选）

        Returns:
            Agent 详情
        """
        model = await self.agent_repo.get_by_agent_id(
            agent_id=agent_id,
            version=version,
        )

        if not model:
            return None

        return self._model_to_detail(model)

    async def get_agent_by_id(self, id: str) -> Optional[AgentDetail]:
        """
        根据记录 ID 获取 Agent

        Args:
            id: 记录 ID

        Returns:
            Agent 详情
        """
        model = await self.agent_repo.get_by_id(id)

        if not model:
            return None

        return self._model_to_detail(model)

    async def list_agents(
        self,
        filters: AgentFilters = None,
    ) -> List[AgentSummary]:
        """
        列出 Agent

        Args:
            filters: 过滤条件

        Returns:
            Agent 摘要列表
        """
        filters = filters or AgentFilters()

        # 使用搜索方法
        status = None
        if filters.status:
            try:
                status = AgentStatus(filters.status)
            except ValueError:
                pass

        models = await self.agent_repo.search(
            query=filters.query,
            tags=filters.tags,
            status=status,
            limit=filters.limit,
        )

        # 应用额外过滤
        if filters.is_template is not None:
            models = [
                m
                for m in models
                if (m.definition_json or {}).get("is_template") == filters.is_template
            ]

        if filters.domain_type:
            models = [
                m
                for m in models
                if (m.definition_json or {}).get("domain_type") == filters.domain_type
            ]

        if filters.execution_type:
            models = [
                m
                for m in models
                if (m.definition_json or {}).get("execution_type")
                == filters.execution_type
            ]

        return [self._model_to_summary(m) for m in models]

    async def update_agent(
        self,
        agent_id: str,
        updates: Dict[str, Any],
    ) -> Optional[AgentDetail]:
        """
        更新 Agent

        Args:
            agent_id: Agent ID
            updates: 更新数据，支持以下格式：
                     - {"definition": {...}} - 完整的 Agent 定义字典
                     - 直接传入完整的 Agent 定义字典（会自动检测）
                     - 其他字段更新

        Returns:
            更新后的 Agent 详情
        """
        # 获取现有 Agent
        model = await self.agent_repo.get_by_agent_id(agent_id)
        if not model:
            return None

        # 检测更新类型
        # 1. 显式使用 "definition" key 包装
        if "definition" in updates:
            updated = await self.agent_repo.update_definition(
                model.id,
                updates["definition"],
            )
        # 2. 直接传入完整的 Agent 定义字典（检测常见的 Agent 定义字段）
        elif any(key in updates for key in [
            "agent_id", "system_prompt", "background_instruction",
            "execution_type", "domain_type", "llm_config", "tools"
        ]):
            # 这是一个完整的 Agent 定义字典，作为 definition 更新
            updated = await self.agent_repo.update_definition(
                model.id,
                updates,
            )
        else:
            # 更新其他字段（如 status, tags 等数据库列）
            updated = await self.agent_repo.update(model.id, updates)

        if updated:
            logger.info(f"更新 Agent: {agent_id}")
            return self._model_to_detail(updated)

        return None

    async def delete_agent(self, agent_id: str) -> bool:
        """
        删除 Agent

        Args:
            agent_id: Agent ID

        Returns:
            是否删除成功
        """
        model = await self.agent_repo.get_by_agent_id(agent_id)
        if not model:
            return False

        result = await self.agent_repo.delete(model.id)

        if result:
            logger.info(f"删除 Agent: {agent_id}")

        return result

    # ==================== Agent 状态管理 ====================

    async def activate_agent(self, agent_id: str) -> Optional[AgentDetail]:
        """激活 Agent"""
        model = await self.agent_repo.get_by_agent_id(agent_id)
        if not model:
            return None

        updated = await self.agent_repo.activate(model.id)
        if updated:
            logger.info(f"激活 Agent: {agent_id}")
            return self._model_to_detail(updated)

        return None

    async def deactivate_agent(self, agent_id: str) -> Optional[AgentDetail]:
        """停用 Agent"""
        model = await self.agent_repo.get_by_agent_id(agent_id)
        if not model:
            return None

        updated = await self.agent_repo.deactivate(model.id)
        if updated:
            logger.info(f"停用 Agent: {agent_id}")
            return self._model_to_detail(updated)

        return None

    async def archive_agent(self, agent_id: str) -> Optional[AgentDetail]:
        """归档 Agent"""
        model = await self.agent_repo.get_by_agent_id(agent_id)
        if not model:
            return None

        updated = await self.agent_repo.archive(model.id)
        if updated:
            logger.info(f"归档 Agent: {agent_id}")
            return self._model_to_detail(updated)

        return None

    # ==================== 模板管理 ====================

    async def get_templates(
        self,
        domain_type: str = None,
        limit: int = 50,
    ) -> List[AgentSummary]:
        """
        获取模板 Agent 列表

        Args:
            domain_type: 领域类型过滤
            limit: 数量限制

        Returns:
            模板 Agent 列表
        """
        models = await self.agent_repo.get_active_agents(limit=limit)

        # 过滤出模板
        templates = [
            m for m in models if (m.definition_json or {}).get("is_template", False)
        ]

        # 按领域过滤
        if domain_type:
            templates = [
                m
                for m in templates
                if (m.definition_json or {}).get("domain_type") == domain_type
            ]

        return [self._model_to_summary(m) for m in templates]

    async def save_as_template(self, agent_id: str) -> Optional[AgentDetail]:
        """
        将 Agent 保存为模板

        Args:
            agent_id: Agent ID

        Returns:
            更新后的 Agent 详情
        """
        model = await self.agent_repo.get_by_agent_id(agent_id)
        if not model:
            return None

        # 更新定义，添加 is_template 标记
        definition = model.definition_json.copy()
        definition["is_template"] = True

        updated = await self.agent_repo.update(
            model.id,
            {
                "definition_json": definition,
            },
        )

        if updated:
            logger.info(f"将 Agent 保存为模板: {agent_id}")
            return self._model_to_detail(updated)

        return None

    async def create_from_template(
        self,
        template_id: str,
        new_agent_id: str,
        overrides: Dict[str, Any] = None,
        author: str = "system",
    ) -> Optional[AgentDetail]:
        """
        从模板创建 Agent

        Args:
            template_id: 模板 Agent ID
            new_agent_id: 新 Agent ID
            overrides: 覆盖配置
            author: 作者

        Returns:
            创建的 Agent 详情
        """
        # 获取模板
        template = await self.agent_repo.get_by_agent_id(template_id)
        if not template:
            logger.error(f"模板不存在: {template_id}")
            return None

        # 复制定义
        definition = template.definition_json.copy()

        # 更新 ID 和名称
        definition["agent_id"] = new_agent_id
        definition["is_template"] = False
        definition["version"] = "1.0.0"

        # 应用覆盖
        if overrides:
            self._deep_update(definition, overrides)

        # 创建新 Agent
        new_model = await self.agent_repo.create_from_definition(
            definition=definition,
            author=author,
        )

        logger.info(f"从模板 {template_id} 创建 Agent: {new_agent_id}")

        return self._model_to_detail(new_model)

    # ==================== 版本管理 ====================

    async def get_all_versions(self, agent_id: str) -> List[AgentSummary]:
        """
        获取 Agent 的所有版本

        Args:
            agent_id: Agent ID

        Returns:
            版本列表
        """
        models = await self.agent_repo.get_all_versions(agent_id)
        return [self._model_to_summary(m) for m in models]

    async def create_new_version(
        self,
        agent_id: str,
        new_version: str,
        definition_updates: Dict[str, Any] = None,
        author: str = "system",
    ) -> Optional[AgentDetail]:
        """
        创建新版本

        Args:
            agent_id: Agent ID
            new_version: 新版本号
            definition_updates: 定义更新
            author: 作者

        Returns:
            新版本的 Agent 详情
        """
        # 获取当前版本
        current = await self.agent_repo.get_by_agent_id(agent_id)
        if not current:
            return None

        # 复制定义
        definition = current.definition_json.copy()
        definition["version"] = new_version

        # 应用更新
        if definition_updates:
            self._deep_update(definition, definition_updates)

        # 创建新版本
        new_model = await self.agent_repo.create_from_definition(
            definition=definition,
            author=author,
        )

        logger.info(f"创建 Agent 新版本: {agent_id} v{new_version}")

        return self._model_to_detail(new_model)

    # ==================== 辅助方法 ====================

    def _model_to_summary(self, model: AgentDefinitionModel) -> AgentSummary:
        """转换为摘要"""
        definition = model.definition_json or {}

        return AgentSummary(
            id=model.id,
            agent_id=model.agent_id,
            name=model.name,
            display_name=definition.get("display_name", ""),
            description=model.description or "",
            version=model.version,
            status=model.status.value if model.status else "unknown",
            domain_type=definition.get("domain_type", "general"),
            execution_type=definition.get("execution_type", "executor"),
            model_name=model.model_name
            or definition.get("llm_config", {}).get("model_name", ""),
            tags=model.tags or [],
            author=model.author or "system",
            is_template=definition.get("is_template", False),
            created_at=model.created_at.isoformat() if model.created_at else "",
            updated_at=model.updated_at.isoformat() if model.updated_at else "",
        )

    def _model_to_detail(self, model: AgentDefinitionModel) -> AgentDetail:
        """转换为详情"""
        definition = model.definition_json or {}

        return AgentDetail(
            id=model.id,
            agent_id=model.agent_id,
            name=model.name,
            description=model.description or "",
            version=model.version,
            status=model.status.value if model.status else "unknown",
            definition=definition,
            tags=model.tags or [],
            author=model.author or "system",
            is_template=definition.get("is_template", False),
            created_at=model.created_at.isoformat() if model.created_at else "",
            updated_at=model.updated_at.isoformat() if model.updated_at else "",
        )

    def _deep_update(self, base: Dict, updates: Dict) -> None:
        """深度更新字典"""
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

"""
工作流服务

提供工作流的业务逻辑处理，包括：
- 工作流 CRUD 操作
- 工作流状态管理
- 工作流执行触发
- 执行历史查询
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field

from src.storage.repositories import (
    WorkflowDefinitionRepository,
    WorkflowExecutionRepository,
)
from src.storage.models.db_models import (
    WorkflowDefinitionModel,
    WorkflowExecutionModel,
    WorkflowStatus,
)
from src.definitions.workflow_definition import WorkflowDefinition
from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class WorkflowSummary:
    """工作流摘要"""

    id: str
    workflow_id: str
    name: str
    description: str
    version: str
    status: str
    node_count: int
    edge_count: int
    is_active: bool
    tags: List[str]
    author: str
    created_at: str
    updated_at: str
    # 执行历史相关字段
    last_execution_at: Optional[str] = None
    last_execution_status: Optional[str] = None
    last_execution_triggered_by: Optional[str] = None  # 'scheduler' or 'manual'
    last_execution_id: Optional[str] = None
    execution_count: int = 0
    # 定时任务配置
    schedule_config: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowDetail:
    """工作流详情"""

    id: str
    workflow_id: str
    name: str
    description: str
    version: str
    definition: Dict[str, Any]
    is_active: bool
    tags: List[str]
    author: str
    created_at: str
    updated_at: str

    # 关联信息
    execution_count: int = 0
    last_execution: Optional[Dict] = None


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


@dataclass
class WorkflowFilters:
    """工作流过滤条件"""

    status: Optional[str] = None
    is_active: Optional[bool] = None
    tags: Optional[List[str]] = None
    query: Optional[str] = None
    limit: int = 50
    offset: int = 0


class WorkflowService:
    """
    工作流服务

    管理工作流的生命周期，包括创建、更新、执行和查询。
    """

    def __init__(
        self,
        workflow_repo: WorkflowDefinitionRepository,
        execution_repo: WorkflowExecutionRepository,
    ):
        """
        初始化工作流服务

        Args:
            workflow_repo: 工作流定义仓库
            execution_repo: 工作流执行仓库
        """
        self.workflow_repo = workflow_repo
        self.execution_repo = execution_repo

    # ==================== 工作流 CRUD ====================

    async def create_workflow(
        self,
        definition: WorkflowDefinition,
        author: str = "system",
    ) -> WorkflowDetail:
        """
        创建工作流

        Args:
            definition: 工作流定义
            author: 作者

        Returns:
            创建的工作流详情
        """
        # 转换为字典
        definition_dict = definition.model_dump(mode="json")

        # 创建记录
        model = await self.workflow_repo.create_from_definition(
            definition=definition_dict,
            author=author,
        )

        logger.info(f"创建工作流: {model.workflow_id} (id={model.id})")

        return self._model_to_detail(model)

    async def create_workflow_from_dict(
        self,
        workflow_data: Dict[str, Any],
        author: str = "system",
    ) -> WorkflowDetail:
        """
        从字典创建工作流

        Args:
            workflow_data: 工作流数据字典
            author: 作者

        Returns:
            创建的工作流详情
        """
        model = await self.workflow_repo.create_from_definition(
            definition=workflow_data,
            author=author,
        )

        logger.info(f"创建工作流: {model.workflow_id} (id={model.id})")

        return self._model_to_detail(model)

    async def get_workflow(
        self,
        workflow_id: str,
        version: str = None,
    ) -> Optional[WorkflowDetail]:
        """
        获取工作流详情

        Args:
            workflow_id: 工作流 ID
            version: 版本号（可选）

        Returns:
            工作流详情
        """
        model = await self.workflow_repo.get_by_workflow_id(
            workflow_id=workflow_id,
            version=version,
        )

        if not model:
            return None

        # 获取执行统计
        executions = await self.execution_repo.get_by_workflow(
            workflow_definition_id=model.id,
            limit=1,
        )

        detail = self._model_to_detail(model)
        detail.execution_count = len(executions)

        if executions:
            detail.last_execution = executions[0].to_dict()

        return detail

    async def get_workflow_by_id(self, id: str) -> Optional[WorkflowDetail]:
        """
        根据记录 ID 获取工作流

        Args:
            id: 记录 ID

        Returns:
            工作流详情
        """
        model = await self.workflow_repo.get_by_id(id)

        if not model:
            return None

        return self._model_to_detail(model)

    async def list_workflows(
        self,
        filters: WorkflowFilters = None,
    ) -> List[WorkflowSummary]:
        """
        列出工作流

        Args:
            filters: 过滤条件

        Returns:
            工作流摘要列表
        """
        filters = filters or WorkflowFilters()

        if filters.is_active is not None and filters.is_active:
            models = await self.workflow_repo.get_active_workflows(
                limit=filters.limit,
                offset=filters.offset,
            )
        else:
            models = await self.workflow_repo.get_all(
                limit=filters.limit,
                offset=filters.offset,
                order_by="updated_at",
                order_desc=True,
            )

        # 应用过滤
        if filters.tags:
            models = [
                m for m in models if any(tag in (m.tags or []) for tag in filters.tags)
            ]

        if filters.query:
            query_lower = filters.query.lower()

            # 使用 jieba 进行智能中文分词的模糊匹配
            import jieba

            def fuzzy_match_jieba(
                query: str, target: str, threshold: float = 0.6
            ) -> bool:
                """
                使用 jieba 分词进行智能模糊匹配

                Args:
                    query: 用户查询字符串
                    target: 目标字符串（name/description/workflow_id）
                    threshold: 关键词匹配比例阈值，默认 60%

                Returns:
                    是否匹配
                """
                if not target:
                    return False

                target_lower = target.lower()
                query_lower = query.lower()

                # 1) 完整子串匹配（精确包含）
                if query_lower in target_lower:
                    return True

                # 2) jieba 分词匹配（搜索引擎模式，更细粒度）
                # lcut_for_search 会输出更细的粒度，适合搜索场景
                query_keywords = jieba.lcut_for_search(query_lower)
                # 过滤掉单字符和纯标点
                query_keywords = [
                    kw for kw in query_keywords if len(kw) > 1 or kw.isalnum()
                ]

                if not query_keywords:
                    return False

                # 计算匹配的关键词数量
                matched_count = sum(1 for kw in query_keywords if kw in target_lower)
                match_ratio = matched_count / len(query_keywords)

                return match_ratio >= threshold

            models = [
                m
                for m in models
                if fuzzy_match_jieba(query_lower, m.name)
                or fuzzy_match_jieba(query_lower, m.description)
                or fuzzy_match_jieba(query_lower, m.workflow_id)
            ]

        # 批量获取执行历史信息
        summaries = []
        for m in models:
            summary = self._model_to_summary(m)
            # 获取该工作流的最近执行记录
            try:
                executions = await self.execution_repo.get_by_workflow(
                    workflow_definition_id=m.id,
                    limit=1,
                )
                if executions:
                    latest = executions[0]
                    # 优先使用 started_at，如果为空则使用 created_at
                    execution_time = latest.started_at or latest.created_at
                    summary.last_execution_at = (
                        execution_time.isoformat() if execution_time else None
                    )
                    # 转换状态：completed -> success
                    if latest.status:
                        status_value = latest.status.value if hasattr(latest.status, 'value') else str(latest.status)
                        if status_value == "completed":
                            summary.last_execution_status = "success"
                        else:
                            summary.last_execution_status = status_value
                    
                    # 获取执行 ID
                    summary.last_execution_id = latest.id
                    
                    # 获取触发来源（从 initial_context 中提取）
                    if latest.initial_context:
                        triggered_by = latest.initial_context.get("triggered_by")
                        if triggered_by == "scheduler":
                            summary.last_execution_triggered_by = "scheduler"
                        else:
                            summary.last_execution_triggered_by = "manual"
                    else:
                        summary.last_execution_triggered_by = "manual"
                        
                # 获取执行总数
                all_executions = await self.execution_repo.get_by_workflow(
                    workflow_definition_id=m.id,
                    limit=1000,  # 获取总数
                )
                summary.execution_count = len(all_executions)
            except Exception as e:
                logger.warning(f"获取工作流 {m.id} 执行历史失败: {e}")

            summaries.append(summary)

        return summaries

    async def update_workflow(
        self,
        workflow_id: str,
        updates: Dict[str, Any],
    ) -> Optional[WorkflowDetail]:
        """
        更新工作流

        Args:
            workflow_id: 工作流 ID
            updates: 更新数据

        Returns:
            更新后的工作流详情
        """
        # 获取现有工作流
        model = await self.workflow_repo.get_by_workflow_id(workflow_id)
        if not model:
            return None

        # 更新定义
        if "definition" in updates:
            definition = model.definition_json.copy()
            definition.update(updates["definition"])
            updates["definition_json"] = definition
            updates["node_count"] = len(definition.get("nodes", []))
            updates["edge_count"] = len(definition.get("edges", []))
            del updates["definition"]

        # 更新其他字段
        updated = await self.workflow_repo.update(model.id, updates)

        if updated:
            logger.info(f"更新工作流: {workflow_id}")
            return self._model_to_detail(updated)

        return None

    async def delete_workflow(self, workflow_id: str) -> bool:
        """
        删除工作流

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否删除成功
        """
        model = await self.workflow_repo.get_by_workflow_id(workflow_id)
        if not model:
            return False

        result = await self.workflow_repo.delete(model.id)

        if result:
            logger.info(f"删除工作流: {workflow_id}")

        return result

    async def delete_workflow_by_id(self, workflow_db_id: str) -> bool:
        """
        根据数据库主键删除工作流（零歧义）

        Args:
            workflow_db_id: 数据库主键 ID

        Returns:
            是否删除成功
        """
        model = await self.workflow_repo.get_by_id(workflow_db_id)
        if not model:
            return False

        result = await self.workflow_repo.delete(model.id)

        if result:
            logger.info(f"删除工作流: {workflow_db_id}")

        return result

    # ==================== 工作流状态管理 ====================

    async def activate_workflow(self, workflow_id: str) -> Optional[WorkflowDetail]:
        """激活工作流"""
        model = await self.workflow_repo.get_by_workflow_id(workflow_id)
        if not model:
            return None

        updated = await self.workflow_repo.activate(model.id)
        if updated:
            logger.info(f"激活工作流: {workflow_id}")
            return self._model_to_detail(updated)

        return None

    async def deactivate_workflow(self, workflow_id: str) -> Optional[WorkflowDetail]:
        """停用工作流"""
        model = await self.workflow_repo.get_by_workflow_id(workflow_id)
        if not model:
            return None

        updated = await self.workflow_repo.deactivate(model.id)
        if updated:
            logger.info(f"停用工作流: {workflow_id}")
            return self._model_to_detail(updated)

        return None

    # ==================== 执行管理 ====================

    async def create_execution(
        self,
        workflow_id: str,
        input_data: Dict[str, Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        创建执行记录

        Args:
            workflow_id: 工作流 ID
            input_data: 输入数据

        Returns:
            执行记录
        """
        model = await self.workflow_repo.get_by_workflow_id(workflow_id)
        if not model:
            logger.error(f"工作流不存在: {workflow_id}")
            return None

        execution = await self.execution_repo.create_execution(
            workflow_definition_id=model.id,
            initial_context=input_data,
        )

        logger.info(f"创建执行记录: {execution.id} for workflow {workflow_id}")

        return execution.to_dict()

    async def start_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """开始执行"""
        execution = await self.execution_repo.update_status(
            execution_id,
            WorkflowStatus.RUNNING,
        )

        if execution:
            logger.info(f"开始执行: {execution_id}")
            return execution.to_dict()

        return None

    async def complete_execution(
        self,
        execution_id: str,
        final_output: Any,
        node_results: Dict[str, Any],
        total_duration_ms: float,
    ) -> Optional[Dict[str, Any]]:
        """完成执行"""
        execution = await self.execution_repo.update_result(
            execution_id,
            final_output=final_output,
            node_results=node_results,
            total_duration_ms=total_duration_ms,
        )

        if execution:
            logger.info(f"执行完成: {execution_id}, 耗时 {total_duration_ms}ms")
            return execution.to_dict()

        return None

    async def fail_execution(
        self,
        execution_id: str,
        error: str,
    ) -> Optional[Dict[str, Any]]:
        """标记执行失败"""
        execution = await self.execution_repo.update_status(
            execution_id,
            WorkflowStatus.FAILED,
            error=error,
        )

        if execution:
            logger.error(f"执行失败: {execution_id}, error={error}")
            return execution.to_dict()

        return None

    async def get_execution_history(
        self,
        workflow_id: str,
        limit: int = 20,
    ) -> List[ExecutionSummary]:
        """
        获取执行历史

        Args:
            workflow_id: 工作流 ID
            limit: 数量限制

        Returns:
            执行摘要列表
        """
        model = await self.workflow_repo.get_by_workflow_id(workflow_id)
        if not model:
            return []

        executions = await self.execution_repo.get_by_workflow(
            workflow_definition_id=model.id,
            limit=limit,
        )

        return [self._execution_to_summary(e) for e in executions]

    async def get_execution_detail(
        self,
        execution_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        获取执行详情

        Args:
            execution_id: 执行 ID

        Returns:
            执行详情
        """
        execution = await self.execution_repo.get_by_id(execution_id)
        if not execution:
            return None

        return execution.to_dict()

    # ==================== 定时任务管理 ====================

    async def schedule_workflow(
        self,
        workflow_db_id: str,
        schedule_config: Dict[str, Any],
    ) -> Optional[WorkflowDetail]:
        """
        设置工作流定时任务

        Args:
            workflow_db_id: 工作流数据库 ID
            schedule_config: 定时任务配置，包含:
                - enabled: bool 是否启用
                - cronExpression: str cron 表达式
                - timezone: str 时区
                - notifyOnComplete: bool 完成时通知
                - notifyOnFailure: bool 失败时通知

        Returns:
            更新后的工作流详情
        """
        model = await self.workflow_repo.get_by_id(workflow_db_id)
        if not model:
            logger.error(f"工作流不存在: {workflow_db_id}")
            return None

        # 更新 definition_json 中的 schedule_config
        definition = model.definition_json.copy() if model.definition_json else {}
        definition["schedule_config"] = schedule_config

        # 更新记录
        updated = await self.workflow_repo.update(
            model.id,
            {"definition_json": definition},
        )

        if updated:
            logger.info(
                f"设置工作流定时任务: {workflow_db_id}, "
                f"cron={schedule_config.get('cronExpression')}"
            )
            return self._model_to_detail(updated)

        return None

    async def unschedule_workflow(self, workflow_db_id: str) -> Optional[WorkflowDetail]:
        """
        取消工作流定时任务

        Args:
            workflow_db_id: 工作流数据库 ID

        Returns:
            更新后的工作流详情
        """
        model = await self.workflow_repo.get_by_id(workflow_db_id)
        if not model:
            logger.error(f"工作流不存在: {workflow_db_id}")
            return None

        # 移除 schedule_config
        definition = model.definition_json.copy() if model.definition_json else {}
        if "schedule_config" in definition:
            del definition["schedule_config"]

        # 更新记录
        updated = await self.workflow_repo.update(
            model.id,
            {"definition_json": definition},
        )

        if updated:
            logger.info(f"取消工作流定时任务: {workflow_db_id}")
            return self._model_to_detail(updated)

        return None

    async def get_scheduled_workflows(self) -> List[WorkflowSummary]:
        """
        获取所有启用定时任务的工作流

        Returns:
            启用定时任务的工作流摘要列表
        """
        # 获取所有活跃工作流
        models = await self.workflow_repo.get_active_workflows(limit=1000)

        # 过滤出启用定时任务的工作流
        scheduled_workflows = []
        for m in models:
            if m.definition_json:
                schedule_config = m.definition_json.get("schedule_config")
                if schedule_config and schedule_config.get("enabled"):
                    summary = self._model_to_summary(m)
                    summary.schedule_config = schedule_config
                    scheduled_workflows.append(summary)

        return scheduled_workflows

    # ==================== 辅助方法 ====================

    def _model_to_summary(self, model: WorkflowDefinitionModel) -> WorkflowSummary:
        """转换为摘要"""
        # 获取定时任务配置（如果有）
        schedule_config = None
        if model.definition_json:
            schedule_config = model.definition_json.get("schedule_config")

        return WorkflowSummary(
            id=model.id,
            workflow_id=model.workflow_id,
            name=model.name,
            description=model.description or "",
            version=model.version,
            status="active" if model.is_active else "inactive",
            node_count=model.node_count or 0,
            edge_count=model.edge_count or 0,
            is_active=model.is_active,
            tags=model.tags or [],
            author=model.author or "system",
            created_at=model.created_at.isoformat() if model.created_at else "",
            updated_at=model.updated_at.isoformat() if model.updated_at else "",
            # 执行历史字段（由 list_workflows 方法填充）
            last_execution_at=None,
            last_execution_status=None,
            last_execution_triggered_by=None,
            last_execution_id=None,
            execution_count=0,
            schedule_config=schedule_config,
        )

    def _model_to_detail(self, model: WorkflowDefinitionModel) -> WorkflowDetail:
        """转换为详情"""
        return WorkflowDetail(
            id=model.id,
            workflow_id=model.workflow_id,
            name=model.name,
            description=model.description or "",
            version=model.version,
            definition=model.definition_json,
            is_active=model.is_active,
            tags=model.tags or [],
            author=model.author or "system",
            created_at=model.created_at.isoformat() if model.created_at else "",
            updated_at=model.updated_at.isoformat() if model.updated_at else "",
        )

    def _execution_to_summary(self, model: WorkflowExecutionModel) -> ExecutionSummary:
        """转换执行记录为摘要"""
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
        )

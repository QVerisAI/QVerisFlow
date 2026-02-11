"""
任务元数据模型

提供简化版的任务状态和元数据定义，用于基于文件系统的任务管理。
"""

from enum import Enum
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class SimpleTaskStatus(str, Enum):
    """任务状态（简化版）"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskMetadata(BaseModel):
    """
    任务元数据（简化版）

    用于跟踪任务的基本信息和执行状态，
    不依赖外部数据库，可序列化为 JSON 存储。
    """

    # 基本信息
    task_id: str = Field(description="任务唯一标识")
    name: str = Field(description="任务名称")
    description: str = Field(default="", description="任务描述")

    # 状态
    status: SimpleTaskStatus = Field(
        default=SimpleTaskStatus.PENDING, description="任务状态"
    )

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    started_at: Optional[datetime] = Field(default=None, description="开始时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")

    # 关联信息
    agent_id: Optional[str] = Field(default=None, description="执行的 Agent ID")
    workflow_id: Optional[str] = Field(default=None, description="所属工作流 ID")
    parent_task_id: Optional[str] = Field(default=None, description="父任务 ID")
    workspace_path: Optional[str] = Field(default=None, description="工作空间路径")

    # 摘要信息
    input_summary: Dict[str, Any] = Field(
        default_factory=dict, description="输入数据摘要"
    )
    output_summary: Dict[str, Any] = Field(
        default_factory=dict, description="输出数据摘要"
    )
    execution_summary: Dict[str, Any] = Field(
        default_factory=dict, description="执行摘要（耗时、迭代次数等）"
    )

    # 标签和分类
    tags: List[str] = Field(default_factory=list, description="标签列表")
    labels: Dict[str, str] = Field(default_factory=dict, description="标签键值对")

    # 错误信息
    error: Optional[str] = Field(default=None, description="错误信息")
    error_details: Optional[Dict[str, Any]] = Field(
        default=None, description="错误详情"
    )

    class Config:
        """Pydantic 配置"""

        use_enum_values = True
        json_encoders = {datetime: lambda v: v.isoformat()}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（JSON 兼容）"""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskMetadata":
        """从字典创建"""
        # 处理时间戳字符串
        for field in ["created_at", "started_at", "completed_at"]:
            if field in data and isinstance(data[field], str):
                data[field] = datetime.fromisoformat(data[field])
        return cls(**data)

    def is_terminal(self) -> bool:
        """检查任务是否处于终态"""
        return self.status in (
            SimpleTaskStatus.COMPLETED,
            SimpleTaskStatus.FAILED,
            SimpleTaskStatus.CANCELLED,
        )

    def duration_ms(self) -> Optional[float]:
        """计算执行时长（毫秒）"""
        if self.started_at is None:
            return None
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds() * 1000


class TaskIndex(BaseModel):
    """
    任务索引

    用于快速查询和统计任务。
    """

    # 计数
    total_tasks: int = Field(default=0, description="总任务数")
    pending_tasks: int = Field(default=0, description="待处理任务数")
    running_tasks: int = Field(default=0, description="运行中任务数")
    completed_tasks: int = Field(default=0, description="已完成任务数")
    failed_tasks: int = Field(default=0, description="失败任务数")
    cancelled_tasks: int = Field(default=0, description="已取消任务数")

    # 索引映射
    tasks: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict, description="任务 ID 到基本信息的映射"
    )

    # 分类索引
    by_status: Dict[str, List[str]] = Field(
        default_factory=dict, description="按状态分组的任务 ID"
    )
    by_agent: Dict[str, List[str]] = Field(
        default_factory=dict, description="按 Agent 分组的任务 ID"
    )
    by_workflow: Dict[str, List[str]] = Field(
        default_factory=dict, description="按工作流分组的任务 ID"
    )
    by_tag: Dict[str, List[str]] = Field(
        default_factory=dict, description="按标签分组的任务 ID"
    )
    by_date: Dict[str, List[str]] = Field(
        default_factory=dict, description="按日期分组的任务 ID（YYYY-MM-DD）"
    )

    # 更新时间
    updated_at: datetime = Field(
        default_factory=datetime.now, description="索引更新时间"
    )

    class Config:
        """Pydantic 配置"""

        json_encoders = {datetime: lambda v: v.isoformat()}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskIndex":
        """从字典创建"""
        if "updated_at" in data and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)

    def add_task(self, metadata: TaskMetadata):
        """添加任务到索引"""
        task_id = metadata.task_id

        # 基本信息
        self.tasks[task_id] = {
            "name": metadata.name,
            "status": metadata.status,
            "agent_id": metadata.agent_id,
            "workflow_id": metadata.workflow_id,
            "created_at": metadata.created_at.isoformat(),
            "tags": metadata.tags,
        }

        # 更新计数
        self.total_tasks += 1
        self._increment_status_count(metadata.status)

        # 状态索引
        status_key = (
            metadata.status
            if isinstance(metadata.status, str)
            else metadata.status.value
        )
        if status_key not in self.by_status:
            self.by_status[status_key] = []
        self.by_status[status_key].append(task_id)

        # Agent 索引
        if metadata.agent_id:
            if metadata.agent_id not in self.by_agent:
                self.by_agent[metadata.agent_id] = []
            self.by_agent[metadata.agent_id].append(task_id)

        # 工作流索引
        if metadata.workflow_id:
            if metadata.workflow_id not in self.by_workflow:
                self.by_workflow[metadata.workflow_id] = []
            self.by_workflow[metadata.workflow_id].append(task_id)

        # 标签索引
        for tag in metadata.tags:
            if tag not in self.by_tag:
                self.by_tag[tag] = []
            self.by_tag[tag].append(task_id)

        # 日期索引
        date_key = metadata.created_at.strftime("%Y-%m-%d")
        if date_key not in self.by_date:
            self.by_date[date_key] = []
        self.by_date[date_key].append(task_id)

        self.updated_at = datetime.now()

    def update_task_status(self, task_id: str, old_status: str, new_status: str):
        """更新任务状态"""
        if task_id not in self.tasks:
            return

        # 更新任务信息
        self.tasks[task_id]["status"] = new_status

        # 从旧状态索引移除
        if old_status in self.by_status and task_id in self.by_status[old_status]:
            self.by_status[old_status].remove(task_id)
            self._decrement_status_count(old_status)

        # 添加到新状态索引
        if new_status not in self.by_status:
            self.by_status[new_status] = []
        self.by_status[new_status].append(task_id)
        self._increment_status_count(new_status)

        self.updated_at = datetime.now()

    def remove_task(self, task_id: str):
        """从索引移除任务"""
        if task_id not in self.tasks:
            return

        task_info = self.tasks[task_id]

        # 更新计数
        self.total_tasks -= 1
        self._decrement_status_count(task_info.get("status", "pending"))

        # 从状态索引移除
        status = task_info.get("status", "pending")
        if status in self.by_status and task_id in self.by_status[status]:
            self.by_status[status].remove(task_id)

        # 从 Agent 索引移除
        agent_id = task_info.get("agent_id")
        if agent_id and agent_id in self.by_agent:
            if task_id in self.by_agent[agent_id]:
                self.by_agent[agent_id].remove(task_id)

        # 从工作流索引移除
        workflow_id = task_info.get("workflow_id")
        if workflow_id and workflow_id in self.by_workflow:
            if task_id in self.by_workflow[workflow_id]:
                self.by_workflow[workflow_id].remove(task_id)

        # 从标签索引移除
        for tag in task_info.get("tags", []):
            if tag in self.by_tag and task_id in self.by_tag[tag]:
                self.by_tag[tag].remove(task_id)

        # 从主索引移除
        del self.tasks[task_id]

        self.updated_at = datetime.now()

    def _increment_status_count(self, status: str):
        """增加状态计数"""
        if status == "pending":
            self.pending_tasks += 1
        elif status == "running":
            self.running_tasks += 1
        elif status == "completed":
            self.completed_tasks += 1
        elif status == "failed":
            self.failed_tasks += 1
        elif status == "cancelled":
            self.cancelled_tasks += 1

    def _decrement_status_count(self, status: str):
        """减少状态计数"""
        if status == "pending":
            self.pending_tasks = max(0, self.pending_tasks - 1)
        elif status == "running":
            self.running_tasks = max(0, self.running_tasks - 1)
        elif status == "completed":
            self.completed_tasks = max(0, self.completed_tasks - 1)
        elif status == "failed":
            self.failed_tasks = max(0, self.failed_tasks - 1)
        elif status == "cancelled":
            self.cancelled_tasks = max(0, self.cancelled_tasks - 1)


# 导出
__all__ = [
    "SimpleTaskStatus",
    "TaskMetadata",
    "TaskIndex",
]

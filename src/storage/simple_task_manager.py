"""
简化版任务管理器

基于文件系统的任务管理器，不依赖外部数据库。
提供任务的创建、查询、状态更新和清理功能。
"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from .task_metadata import TaskMetadata, TaskIndex, SimpleTaskStatus
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SimpleTaskManager:
    """
    简化版任务管理器（基于文件系统）

    不依赖外部数据库，使用本地 JSON 文件存储任务元数据。
    适合开发、测试和小规模部署。

    目录结构:
        storage_path/
        ├── index.json          # 任务索引
        └── tasks/              # 任务目录
            ├── task_001/
            │   └── metadata.json
            └── task_002/
                └── metadata.json

    用法:
        ```python
        from storage import SimpleTaskManager

        manager = SimpleTaskManager("./storage/tasks")

        # 创建任务
        task = manager.create_task(
            task_id="task_001",
            name="分析任务",
            agent_id="analyst",
        )

        # 更新状态
        manager.start_task("task_001")
        manager.complete_task("task_001", output_summary={"result": "success"})

        # 查询任务
        tasks = manager.list_tasks(status="completed")
        stats = manager.get_statistics()
        ```
    """

    def __init__(self, storage_path: str = "./storage/tasks"):
        """
        初始化任务管理器

        Args:
            storage_path: 存储路径
        """
        self.storage_path = Path(storage_path)
        self.tasks_path = self.storage_path / "tasks"
        self.index_file = self.storage_path / "index.json"

        self._ensure_directories()
        self._index = self._load_index()

        logger.info(f"SimpleTaskManager 初始化: {self.storage_path}")

    def _ensure_directories(self):
        """确保目录存在"""
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.tasks_path.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> TaskIndex:
        """加载任务索引"""
        if self.index_file.exists():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return TaskIndex.from_dict(data)
            except Exception as e:
                logger.warning(f"加载索引失败，创建新索引: {e}")
        return TaskIndex()

    def _save_index(self):
        """保存任务索引"""
        self._index.updated_at = datetime.now()
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self._index.to_dict(), f, ensure_ascii=False, indent=2)

    def _get_task_dir(self, task_id: str) -> Path:
        """获取任务目录"""
        return self.tasks_path / task_id

    def _get_metadata_file(self, task_id: str) -> Path:
        """获取元数据文件路径"""
        return self._get_task_dir(task_id) / "metadata.json"

    def _save_task_metadata(self, metadata: TaskMetadata):
        """保存任务元数据"""
        task_dir = self._get_task_dir(metadata.task_id)
        task_dir.mkdir(parents=True, exist_ok=True)

        metadata_file = task_dir / "metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata.to_dict(), f, ensure_ascii=False, indent=2)

    def _load_task_metadata(self, task_id: str) -> Optional[TaskMetadata]:
        """加载任务元数据"""
        metadata_file = self._get_metadata_file(task_id)
        if not metadata_file.exists():
            return None

        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return TaskMetadata.from_dict(data)
        except Exception as e:
            logger.error(f"加载任务元数据失败 {task_id}: {e}")
            return None

    # ========== 任务生命周期 ==========

    def create_task(
        self,
        task_id: str,
        name: str,
        description: str = "",
        agent_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        labels: Optional[Dict[str, str]] = None,
    ) -> TaskMetadata:
        """
        创建任务

        Args:
            task_id: 任务 ID
            name: 任务名称
            description: 任务描述
            agent_id: Agent ID
            workflow_id: 工作流 ID
            parent_task_id: 父任务 ID
            workspace_path: 工作空间路径
            input_data: 输入数据（用于生成摘要）
            tags: 标签列表
            labels: 标签键值对

        Returns:
            创建的任务元数据
        """
        # 检查是否已存在
        if task_id in self._index.tasks:
            raise ValueError(f"任务已存在: {task_id}")

        # 生成输入摘要
        input_summary = {}
        if input_data:
            # 保留关键字段，截断大值
            for key, value in input_data.items():
                if isinstance(value, str) and len(value) > 200:
                    input_summary[key] = value[:200] + "..."
                elif isinstance(value, (dict, list)):
                    input_summary[key] = f"<{type(value).__name__}, len={len(value)}>"
                else:
                    input_summary[key] = value

        # 创建元数据
        metadata = TaskMetadata(
            task_id=task_id,
            name=name,
            description=description,
            status=SimpleTaskStatus.PENDING,
            agent_id=agent_id,
            workflow_id=workflow_id,
            parent_task_id=parent_task_id,
            workspace_path=workspace_path,
            input_summary=input_summary,
            tags=tags or [],
            labels=labels or {},
        )

        # 保存
        self._save_task_metadata(metadata)
        self._index.add_task(metadata)
        self._save_index()

        logger.info(f"创建任务: {task_id} ({name})")
        return metadata

    def start_task(self, task_id: str) -> TaskMetadata:
        """
        标记任务开始

        Args:
            task_id: 任务 ID

        Returns:
            更新后的任务元数据
        """
        metadata = self._load_task_metadata(task_id)
        if metadata is None:
            raise ValueError(f"任务不存在: {task_id}")

        old_status = metadata.status
        metadata.status = SimpleTaskStatus.RUNNING
        metadata.started_at = datetime.now()

        self._save_task_metadata(metadata)
        self._index.update_task_status(
            task_id, old_status, SimpleTaskStatus.RUNNING.value
        )
        self._save_index()

        logger.info(f"任务开始: {task_id}")
        return metadata

    def complete_task(
        self,
        task_id: str,
        output_summary: Optional[Dict[str, Any]] = None,
        execution_summary: Optional[Dict[str, Any]] = None,
    ) -> TaskMetadata:
        """
        标记任务完成

        Args:
            task_id: 任务 ID
            output_summary: 输出摘要
            execution_summary: 执行摘要

        Returns:
            更新后的任务元数据
        """
        metadata = self._load_task_metadata(task_id)
        if metadata is None:
            raise ValueError(f"任务不存在: {task_id}")

        old_status = metadata.status
        metadata.status = SimpleTaskStatus.COMPLETED
        metadata.completed_at = datetime.now()

        if output_summary:
            metadata.output_summary = output_summary
        if execution_summary:
            metadata.execution_summary = execution_summary

        # 自动计算耗时
        if metadata.started_at:
            duration_ms = (
                metadata.completed_at - metadata.started_at
            ).total_seconds() * 1000
            metadata.execution_summary["duration_ms"] = duration_ms

        self._save_task_metadata(metadata)
        self._index.update_task_status(
            task_id, old_status, SimpleTaskStatus.COMPLETED.value
        )
        self._save_index()

        logger.info(f"任务完成: {task_id}")
        return metadata

    def fail_task(
        self,
        task_id: str,
        error: str,
        error_details: Optional[Dict[str, Any]] = None,
    ) -> TaskMetadata:
        """
        标记任务失败

        Args:
            task_id: 任务 ID
            error: 错误消息
            error_details: 错误详情

        Returns:
            更新后的任务元数据
        """
        metadata = self._load_task_metadata(task_id)
        if metadata is None:
            raise ValueError(f"任务不存在: {task_id}")

        old_status = metadata.status
        metadata.status = SimpleTaskStatus.FAILED
        metadata.completed_at = datetime.now()
        metadata.error = error
        metadata.error_details = error_details

        # 自动计算耗时
        if metadata.started_at:
            duration_ms = (
                metadata.completed_at - metadata.started_at
            ).total_seconds() * 1000
            metadata.execution_summary["duration_ms"] = duration_ms

        self._save_task_metadata(metadata)
        self._index.update_task_status(
            task_id, old_status, SimpleTaskStatus.FAILED.value
        )
        self._save_index()

        logger.warning(f"任务失败: {task_id} - {error}")
        return metadata

    def cancel_task(self, task_id: str) -> TaskMetadata:
        """
        取消任务

        Args:
            task_id: 任务 ID

        Returns:
            更新后的任务元数据
        """
        metadata = self._load_task_metadata(task_id)
        if metadata is None:
            raise ValueError(f"任务不存在: {task_id}")

        if metadata.is_terminal():
            raise ValueError(f"任务已处于终态，无法取消: {task_id}")

        old_status = metadata.status
        metadata.status = SimpleTaskStatus.CANCELLED
        metadata.completed_at = datetime.now()

        self._save_task_metadata(metadata)
        self._index.update_task_status(
            task_id, old_status, SimpleTaskStatus.CANCELLED.value
        )
        self._save_index()

        logger.info(f"任务取消: {task_id}")
        return metadata

    def update_task(
        self,
        task_id: str,
        **updates,
    ) -> TaskMetadata:
        """
        更新任务元数据

        Args:
            task_id: 任务 ID
            **updates: 要更新的字段

        Returns:
            更新后的任务元数据
        """
        metadata = self._load_task_metadata(task_id)
        if metadata is None:
            raise ValueError(f"任务不存在: {task_id}")

        # 更新字段
        for key, value in updates.items():
            if hasattr(metadata, key):
                setattr(metadata, key, value)

        self._save_task_metadata(metadata)

        # 如果状态变化，更新索引
        if "status" in updates:
            old_status = self._index.tasks[task_id].get("status", "pending")
            new_status = updates["status"]
            if isinstance(new_status, SimpleTaskStatus):
                new_status = new_status.value
            self._index.update_task_status(task_id, old_status, new_status)
            self._save_index()

        return metadata

    # ========== 查询方法 ==========

    def get_task(self, task_id: str) -> Optional[TaskMetadata]:
        """
        获取任务

        Args:
            task_id: 任务 ID

        Returns:
            任务元数据，不存在则返回 None
        """
        return self._load_task_metadata(task_id)

    def list_tasks(
        self,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TaskMetadata]:
        """
        列出任务

        Args:
            status: 状态过滤
            agent_id: Agent ID 过滤
            workflow_id: 工作流 ID 过滤
            tags: 标签过滤（AND 逻辑）
            start_date: 开始日期
            end_date: 结束日期
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            任务元数据列表
        """
        # 初步筛选（使用索引）
        task_ids = set(self._index.tasks.keys())

        if status:
            status_tasks = set(self._index.by_status.get(status, []))
            task_ids &= status_tasks

        if agent_id:
            agent_tasks = set(self._index.by_agent.get(agent_id, []))
            task_ids &= agent_tasks

        if workflow_id:
            workflow_tasks = set(self._index.by_workflow.get(workflow_id, []))
            task_ids &= workflow_tasks

        if tags:
            for tag in tags:
                tag_tasks = set(self._index.by_tag.get(tag, []))
                task_ids &= tag_tasks

        # 按创建时间排序
        sorted_ids = sorted(
            task_ids,
            key=lambda x: self._index.tasks.get(x, {}).get("created_at", ""),
            reverse=True,
        )

        # 日期过滤（需要加载元数据）
        if start_date or end_date:
            filtered_ids = []
            for task_id in sorted_ids:
                metadata = self._load_task_metadata(task_id)
                if metadata:
                    if start_date and metadata.created_at < start_date:
                        continue
                    if end_date and metadata.created_at > end_date:
                        continue
                    filtered_ids.append(task_id)
            sorted_ids = filtered_ids

        # 分页
        paginated_ids = sorted_ids[offset : offset + limit]

        # 加载完整元数据
        tasks = []
        for task_id in paginated_ids:
            metadata = self._load_task_metadata(task_id)
            if metadata:
                tasks.append(metadata)

        return tasks

    def search_tasks(self, query: str, limit: int = 20) -> List[TaskMetadata]:
        """
        搜索任务（简单文本匹配）

        Args:
            query: 搜索关键词
            limit: 返回数量限制

        Returns:
            匹配的任务列表
        """
        query_lower = query.lower()
        matched = []

        for task_id, task_info in self._index.tasks.items():
            # 搜索名称
            if query_lower in task_info.get("name", "").lower():
                matched.append(task_id)
                continue

            # 搜索 ID
            if query_lower in task_id.lower():
                matched.append(task_id)
                continue

            # 搜索标签
            tags = task_info.get("tags", [])
            if any(query_lower in tag.lower() for tag in tags):
                matched.append(task_id)
                continue

        # 加载完整元数据
        tasks = []
        for task_id in matched[:limit]:
            metadata = self._load_task_metadata(task_id)
            if metadata:
                tasks.append(metadata)

        return tasks

    # ========== 统计方法 ==========

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        # 计算平均耗时（已完成任务）
        completed_tasks = self.list_tasks(status="completed", limit=1000)
        durations = [
            t.execution_summary.get("duration_ms", 0)
            for t in completed_tasks
            if t.execution_summary.get("duration_ms")
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            "total_tasks": self._index.total_tasks,
            "pending_tasks": self._index.pending_tasks,
            "running_tasks": self._index.running_tasks,
            "completed_tasks": self._index.completed_tasks,
            "failed_tasks": self._index.failed_tasks,
            "cancelled_tasks": self._index.cancelled_tasks,
            "success_rate": (
                self._index.completed_tasks / self._index.total_tasks
                if self._index.total_tasks > 0
                else 0
            ),
            "failure_rate": (
                self._index.failed_tasks / self._index.total_tasks
                if self._index.total_tasks > 0
                else 0
            ),
            "avg_duration_ms": avg_duration,
            "by_agent": {k: len(v) for k, v in self._index.by_agent.items()},
            "by_workflow": {k: len(v) for k, v in self._index.by_workflow.items()},
            "storage_path": str(self.storage_path),
            "updated_at": self._index.updated_at.isoformat(),
        }

    # ========== 清理方法 ==========

    def delete_task(self, task_id: str, force: bool = False) -> bool:
        """
        删除任务

        Args:
            task_id: 任务 ID
            force: 是否强制删除（包括运行中的任务）

        Returns:
            是否成功删除
        """
        metadata = self._load_task_metadata(task_id)
        if metadata is None:
            return False

        if not force and metadata.status == SimpleTaskStatus.RUNNING:
            raise ValueError(f"无法删除运行中的任务: {task_id}")

        # 删除任务目录
        task_dir = self._get_task_dir(task_id)
        if task_dir.exists():
            shutil.rmtree(task_dir)

        # 从索引移除
        self._index.remove_task(task_id)
        self._save_index()

        logger.info(f"删除任务: {task_id}")
        return True

    def cleanup_old_tasks(
        self,
        days: int = 30,
        status: Optional[str] = None,
    ) -> int:
        """
        清理旧任务

        Args:
            days: 清理多少天前的任务
            status: 只清理特定状态的任务（默认只清理已完成和失败的）

        Returns:
            删除的任务数量
        """
        cutoff = datetime.now() - timedelta(days=days)
        deleted_count = 0

        # 确定要清理的状态
        if status:
            statuses_to_clean = [status]
        else:
            statuses_to_clean = ["completed", "failed", "cancelled"]

        for clean_status in statuses_to_clean:
            task_ids = list(self._index.by_status.get(clean_status, []))
            for task_id in task_ids:
                metadata = self._load_task_metadata(task_id)
                if metadata and metadata.created_at < cutoff:
                    try:
                        self.delete_task(task_id, force=True)
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"清理任务失败 {task_id}: {e}")

        logger.info(f"清理了 {deleted_count} 个旧任务")
        return deleted_count

    def rebuild_index(self) -> TaskIndex:
        """
        重建索引（从任务目录扫描）

        Returns:
            重建后的索引
        """
        logger.info("重建任务索引...")

        new_index = TaskIndex()

        for task_dir in self.tasks_path.iterdir():
            if not task_dir.is_dir():
                continue

            metadata_file = task_dir / "metadata.json"
            if not metadata_file.exists():
                continue

            try:
                with open(metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                metadata = TaskMetadata.from_dict(data)
                new_index.add_task(metadata)
            except Exception as e:
                logger.warning(f"加载任务元数据失败 {task_dir.name}: {e}")

        self._index = new_index
        self._save_index()

        logger.info(f"索引重建完成: {new_index.total_tasks} 个任务")
        return new_index


# 导出
__all__ = ["SimpleTaskManager"]

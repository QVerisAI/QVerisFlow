"""
测试简化版任务管理器

测试 SimpleTaskManager 的功能，包括：
- 任务创建、启动、完成、失败、取消
- 任务查询和搜索
- 统计信息
- 清理功能
"""

import pytest
import time
from pathlib import Path
from datetime import datetime, timedelta

from src.storage import (
    SimpleTaskManager,
    TaskMetadata,
    TaskIndex,
    SimpleTaskStatus,
)


@pytest.fixture
def task_manager(tmp_path):
    """创建测试用的任务管理器"""
    return SimpleTaskManager(storage_path=str(tmp_path / "tasks"))


class TestTaskLifecycle:
    """测试任务生命周期"""

    def test_create_task(self, task_manager):
        """测试创建任务"""
        task = task_manager.create_task(
            task_id="task_001",
            name="Test Task",
            description="A test task",
            agent_id="test_agent",
            workflow_id="test_workflow",
            input_data={"key": "value"},
            tags=["test", "example"],
        )

        assert task.task_id == "task_001"
        assert task.name == "Test Task"
        assert task.status == SimpleTaskStatus.PENDING
        assert task.agent_id == "test_agent"
        assert "test" in task.tags

    def test_create_duplicate_task_raises(self, task_manager):
        """测试创建重复任务抛出异常"""
        task_manager.create_task(task_id="task_001", name="Task 1")

        with pytest.raises(ValueError, match="任务已存在"):
            task_manager.create_task(task_id="task_001", name="Task 1 Duplicate")

    def test_start_task(self, task_manager):
        """测试启动任务"""
        task_manager.create_task(task_id="task_001", name="Test Task")
        task = task_manager.start_task("task_001")

        assert task.status == SimpleTaskStatus.RUNNING
        assert task.started_at is not None

    def test_complete_task(self, task_manager):
        """测试完成任务"""
        task_manager.create_task(task_id="task_001", name="Test Task")
        task_manager.start_task("task_001")

        task = task_manager.complete_task(
            "task_001",
            output_summary={"result": "success"},
            execution_summary={"iterations": 3},
        )

        assert task.status == SimpleTaskStatus.COMPLETED
        assert task.completed_at is not None
        assert task.output_summary["result"] == "success"
        assert "duration_ms" in task.execution_summary

    def test_fail_task(self, task_manager):
        """测试任务失败"""
        task_manager.create_task(task_id="task_001", name="Test Task")
        task_manager.start_task("task_001")

        task = task_manager.fail_task(
            "task_001",
            error="Something went wrong",
            error_details={"traceback": "..."},
        )

        assert task.status == SimpleTaskStatus.FAILED
        assert task.error == "Something went wrong"
        assert task.error_details["traceback"] == "..."

    def test_cancel_task(self, task_manager):
        """测试取消任务"""
        task_manager.create_task(task_id="task_001", name="Test Task")
        task_manager.start_task("task_001")

        task = task_manager.cancel_task("task_001")

        assert task.status == SimpleTaskStatus.CANCELLED

    def test_cancel_completed_task_raises(self, task_manager):
        """测试取消已完成任务抛出异常"""
        task_manager.create_task(task_id="task_001", name="Test Task")
        task_manager.start_task("task_001")
        task_manager.complete_task("task_001")

        with pytest.raises(ValueError, match="终态"):
            task_manager.cancel_task("task_001")

    def test_start_nonexistent_task_raises(self, task_manager):
        """测试启动不存在的任务抛出异常"""
        with pytest.raises(ValueError, match="任务不存在"):
            task_manager.start_task("nonexistent")


class TestTaskQuery:
    """测试任务查询"""

    def test_get_task(self, task_manager):
        """测试获取单个任务"""
        task_manager.create_task(task_id="task_001", name="Test Task")

        task = task_manager.get_task("task_001")
        assert task is not None
        assert task.task_id == "task_001"

    def test_get_nonexistent_task(self, task_manager):
        """测试获取不存在的任务"""
        task = task_manager.get_task("nonexistent")
        assert task is None

    def test_list_tasks(self, task_manager):
        """测试列出任务"""
        for i in range(5):
            task_manager.create_task(task_id=f"task_{i}", name=f"Task {i}")

        tasks = task_manager.list_tasks()
        assert len(tasks) == 5

    def test_list_tasks_by_status(self, task_manager):
        """测试按状态过滤任务"""
        task_manager.create_task(task_id="task_1", name="Task 1")
        task_manager.create_task(task_id="task_2", name="Task 2")
        task_manager.start_task("task_1")

        pending_tasks = task_manager.list_tasks(status="pending")
        running_tasks = task_manager.list_tasks(status="running")

        assert len(pending_tasks) == 1
        assert len(running_tasks) == 1

    def test_list_tasks_by_agent(self, task_manager):
        """测试按 Agent 过滤任务"""
        task_manager.create_task(task_id="task_1", name="Task 1", agent_id="agent_a")
        task_manager.create_task(task_id="task_2", name="Task 2", agent_id="agent_b")
        task_manager.create_task(task_id="task_3", name="Task 3", agent_id="agent_a")

        tasks = task_manager.list_tasks(agent_id="agent_a")
        assert len(tasks) == 2

    def test_list_tasks_by_tags(self, task_manager):
        """测试按标签过滤任务"""
        task_manager.create_task(
            task_id="task_1", name="Task 1", tags=["important", "urgent"]
        )
        task_manager.create_task(task_id="task_2", name="Task 2", tags=["important"])
        task_manager.create_task(task_id="task_3", name="Task 3", tags=["other"])

        tasks = task_manager.list_tasks(tags=["important"])
        assert len(tasks) == 2

        tasks = task_manager.list_tasks(tags=["important", "urgent"])
        assert len(tasks) == 1

    def test_list_tasks_pagination(self, task_manager):
        """测试任务列表分页"""
        for i in range(10):
            task_manager.create_task(task_id=f"task_{i:02d}", name=f"Task {i}")

        page1 = task_manager.list_tasks(limit=5, offset=0)
        page2 = task_manager.list_tasks(limit=5, offset=5)

        assert len(page1) == 5
        assert len(page2) == 5
        # 确保没有重复
        ids1 = {t.task_id for t in page1}
        ids2 = {t.task_id for t in page2}
        assert len(ids1 & ids2) == 0

    def test_search_tasks(self, task_manager):
        """测试搜索任务"""
        task_manager.create_task(task_id="task_1", name="Financial Analysis")
        task_manager.create_task(
            task_id="task_2", name="Data Processing", tags=["financial"]
        )
        task_manager.create_task(task_id="task_3", name="Report Generation")

        # 按名称搜索
        results = task_manager.search_tasks("financial")
        assert len(results) == 2  # 匹配名称和标签

        # 按 ID 搜索
        results = task_manager.search_tasks("task_1")
        assert len(results) == 1


class TestTaskStatistics:
    """测试任务统计"""

    def test_get_statistics(self, task_manager):
        """测试获取统计信息"""
        # 创建不同状态的任务
        task_manager.create_task(task_id="task_1", name="Task 1")
        task_manager.create_task(task_id="task_2", name="Task 2")
        task_manager.start_task("task_1")
        task_manager.complete_task("task_1")
        task_manager.start_task("task_2")
        task_manager.fail_task("task_2", error="Error")

        stats = task_manager.get_statistics()

        assert stats["total_tasks"] == 2
        assert stats["completed_tasks"] == 1
        assert stats["failed_tasks"] == 1
        assert "success_rate" in stats
        assert "failure_rate" in stats

    def test_statistics_by_agent(self, task_manager):
        """测试按 Agent 统计"""
        task_manager.create_task(task_id="task_1", name="Task 1", agent_id="agent_a")
        task_manager.create_task(task_id="task_2", name="Task 2", agent_id="agent_a")
        task_manager.create_task(task_id="task_3", name="Task 3", agent_id="agent_b")

        stats = task_manager.get_statistics()

        assert "by_agent" in stats
        assert stats["by_agent"]["agent_a"] == 2
        assert stats["by_agent"]["agent_b"] == 1


class TestTaskCleanup:
    """测试任务清理"""

    def test_delete_task(self, task_manager):
        """测试删除任务"""
        task_manager.create_task(task_id="task_001", name="Test Task")

        result = task_manager.delete_task("task_001")
        assert result is True

        # 确认已删除
        task = task_manager.get_task("task_001")
        assert task is None

    def test_delete_running_task_raises(self, task_manager):
        """测试删除运行中的任务抛出异常"""
        task_manager.create_task(task_id="task_001", name="Test Task")
        task_manager.start_task("task_001")

        with pytest.raises(ValueError, match="运行中"):
            task_manager.delete_task("task_001")

    def test_delete_running_task_force(self, task_manager):
        """测试强制删除运行中的任务"""
        task_manager.create_task(task_id="task_001", name="Test Task")
        task_manager.start_task("task_001")

        result = task_manager.delete_task("task_001", force=True)
        assert result is True

    def test_cleanup_old_tasks(self, task_manager):
        """测试清理旧任务"""
        # 创建并完成任务
        task_manager.create_task(task_id="task_old", name="Old Task")
        task_manager.start_task("task_old")
        task_manager.complete_task("task_old")

        task_manager.create_task(task_id="task_new", name="New Task")

        # 清理 0 天前的任务（应该清理已完成的）
        deleted = task_manager.cleanup_old_tasks(days=0)
        assert deleted == 1

        # 确认只有新任务存在
        tasks = task_manager.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].task_id == "task_new"


class TestTaskIndex:
    """测试任务索引"""

    def test_rebuild_index(self, task_manager):
        """测试重建索引"""
        # 创建任务
        task_manager.create_task(task_id="task_1", name="Task 1", agent_id="agent_a")
        task_manager.create_task(task_id="task_2", name="Task 2", agent_id="agent_b")

        # 重建索引
        index = task_manager.rebuild_index()

        assert index.total_tasks == 2
        assert "task_1" in index.tasks
        assert "task_2" in index.tasks

    def test_index_persistence(self, tmp_path):
        """测试索引持久化"""
        storage_path = str(tmp_path / "tasks")

        # 创建任务
        manager1 = SimpleTaskManager(storage_path=storage_path)
        manager1.create_task(task_id="task_1", name="Task 1")
        manager1.create_task(task_id="task_2", name="Task 2")

        # 重新加载
        manager2 = SimpleTaskManager(storage_path=storage_path)
        tasks = manager2.list_tasks()

        assert len(tasks) == 2


class TestTaskMetadataModel:
    """测试 TaskMetadata 模型"""

    def test_to_dict_and_from_dict(self):
        """测试序列化和反序列化"""
        metadata = TaskMetadata(
            task_id="task_001",
            name="Test Task",
            status=SimpleTaskStatus.RUNNING,
            agent_id="agent_a",
            tags=["important"],
        )

        # 转换为字典
        data = metadata.to_dict()
        assert data["task_id"] == "task_001"
        assert data["status"] == "running"

        # 从字典创建
        restored = TaskMetadata.from_dict(data)
        assert restored.task_id == "task_001"
        assert restored.status == SimpleTaskStatus.RUNNING

    def test_is_terminal(self):
        """测试终态判断"""
        pending = TaskMetadata(task_id="1", name="1", status=SimpleTaskStatus.PENDING)
        running = TaskMetadata(task_id="2", name="2", status=SimpleTaskStatus.RUNNING)
        completed = TaskMetadata(
            task_id="3", name="3", status=SimpleTaskStatus.COMPLETED
        )
        failed = TaskMetadata(task_id="4", name="4", status=SimpleTaskStatus.FAILED)
        cancelled = TaskMetadata(
            task_id="5", name="5", status=SimpleTaskStatus.CANCELLED
        )

        assert not pending.is_terminal()
        assert not running.is_terminal()
        assert completed.is_terminal()
        assert failed.is_terminal()
        assert cancelled.is_terminal()

    def test_duration_ms(self):
        """测试执行时长计算"""
        now = datetime.now()
        metadata = TaskMetadata(
            task_id="task_001",
            name="Test Task",
            started_at=now - timedelta(seconds=5),
            completed_at=now,
        )

        duration = metadata.duration_ms()
        assert duration is not None
        assert 4900 < duration < 5100  # 约 5000ms

    def test_duration_ms_without_start(self):
        """测试未启动任务的时长"""
        metadata = TaskMetadata(
            task_id="task_001",
            name="Test Task",
        )

        assert metadata.duration_ms() is None


class TestTaskIndexModel:
    """测试 TaskIndex 模型"""

    def test_add_task(self):
        """测试添加任务到索引"""
        index = TaskIndex()
        metadata = TaskMetadata(
            task_id="task_001",
            name="Test Task",
            agent_id="agent_a",
            tags=["important"],
        )

        index.add_task(metadata)

        assert index.total_tasks == 1
        assert index.pending_tasks == 1
        assert "task_001" in index.tasks
        assert "agent_a" in index.by_agent
        assert "important" in index.by_tag

    def test_update_task_status(self):
        """测试更新任务状态"""
        index = TaskIndex()
        metadata = TaskMetadata(
            task_id="task_001",
            name="Test Task",
        )
        index.add_task(metadata)

        index.update_task_status("task_001", "pending", "running")

        assert index.pending_tasks == 0
        assert index.running_tasks == 1
        assert index.tasks["task_001"]["status"] == "running"

    def test_remove_task(self):
        """测试从索引移除任务"""
        index = TaskIndex()
        metadata = TaskMetadata(
            task_id="task_001",
            name="Test Task",
            agent_id="agent_a",
        )
        index.add_task(metadata)

        index.remove_task("task_001")

        assert index.total_tasks == 0
        assert "task_001" not in index.tasks

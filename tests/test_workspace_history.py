"""
测试工作空间历史版本功能

测试 AgentWorkspace 的版本化存储功能，包括：
- 上下文历史版本
- 结果历史版本
- 任务元数据管理
"""

import pytest
import json
import time
from pathlib import Path
from datetime import datetime

from src.workspace import AgentWorkspace, WorkspaceConfig


class TestContextVersioning:
    """测试上下文版本化存储"""

    def test_save_context_creates_history(self, tmp_path):
        """测试保存上下文时创建历史版本"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 保存第一个版本
        workspace.save_gathered_context("Context v1")
        time.sleep(0.1)  # 确保时间戳不同

        # 保存第二个版本
        workspace.save_gathered_context("Context v2")

        # 检查历史目录存在
        history_dir = workspace.context_dir / "history"
        assert history_dir.exists()

        # 检查历史文件
        history_files = list(history_dir.glob("gathered_context_*.md"))
        assert len(history_files) == 1  # 第一个版本被归档

        # 检查当前版本
        assert workspace.get_gathered_context() == "Context v2"

    def test_list_context_versions(self, tmp_path):
        """测试列出上下文版本"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 保存多个版本 - 微秒级时间戳确保唯一性
        workspace.save_gathered_context("Context v1")
        time.sleep(0.01)  # 小延迟确保微秒不同
        workspace.save_gathered_context("Context v2")
        time.sleep(0.01)
        workspace.save_gathered_context("Context v3")

        # 列出版本
        versions = workspace.list_context_versions()
        assert len(versions) == 3  # 2 个历史 + 1 个当前

        # 检查当前版本
        current = [v for v in versions if v["is_current"]]
        assert len(current) == 1
        assert current[0]["version_id"] == "latest"

    def test_get_context_version(self, tmp_path):
        """测试获取指定版本的上下文"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 保存版本
        workspace.save_gathered_context("Context v1")
        time.sleep(0.1)
        workspace.save_gathered_context("Context v2")

        # 获取最新版本
        latest = workspace.get_context_version("latest")
        assert latest == "Context v2"

        # 获取历史版本
        versions = workspace.list_context_versions()
        history_versions = [v for v in versions if not v["is_current"]]
        if history_versions:
            version_id = history_versions[0]["version_id"]
            content = workspace.get_context_version(version_id)
            assert content == "Context v1"

    def test_context_history_cleanup(self, tmp_path):
        """测试上下文历史版本清理"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 保存超过限制的版本
        max_history = 3
        for i in range(max_history + 2):
            workspace.save_gathered_context(f"Context v{i}", max_history=max_history)
            time.sleep(0.05)

        # 检查历史文件数量（应该被清理到 max_history）
        history_dir = workspace.context_dir / "history"
        history_files = list(history_dir.glob("gathered_context_*.md"))
        assert len(history_files) <= max_history

    def test_save_context_without_history(self, tmp_path):
        """测试不保留历史版本"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 保存多个版本但不保留历史
        workspace.save_gathered_context("Context v1", keep_history=False)
        workspace.save_gathered_context("Context v2", keep_history=False)

        # 历史目录不应该存在或为空
        history_dir = workspace.context_dir / "history"
        if history_dir.exists():
            history_files = list(history_dir.glob("gathered_context_*.md"))
            assert len(history_files) == 0


class TestResultVersioning:
    """测试结果版本化存储"""

    def test_write_result_creates_history(self, tmp_path):
        """测试写入结果时创建历史版本"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 写入第一个结果
        workspace.write_result({"status": "success", "value": 1})
        time.sleep(0.1)

        # 写入第二个结果
        workspace.write_result({"status": "success", "value": 2})

        # 检查历史目录
        history_dir = workspace.output_dir / "history"
        assert history_dir.exists()

        # 检查历史文件
        history_files = list(history_dir.glob("result_*.json"))
        assert len(history_files) == 1

        # 检查当前结果
        result = workspace.read_result()
        assert result["value"] == 2

    def test_list_result_versions(self, tmp_path):
        """测试列出结果版本"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 写入多个结果
        workspace.write_result({"version": 1})
        time.sleep(0.1)
        workspace.write_result({"version": 2})
        time.sleep(0.1)
        workspace.write_result({"version": 3})

        # 列出版本
        versions = workspace.list_result_versions()
        assert len(versions) == 3

        # 检查当前版本
        current = [v for v in versions if v["is_current"]]
        assert len(current) == 1

    def test_get_result_version(self, tmp_path):
        """测试获取指定版本的结果"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 写入结果
        workspace.write_result({"version": 1})
        time.sleep(0.1)
        workspace.write_result({"version": 2})

        # 获取最新版本
        latest = workspace.get_result_version("latest")
        assert latest["version"] == 2

        # 获取历史版本
        versions = workspace.list_result_versions()
        history_versions = [v for v in versions if not v["is_current"]]
        if history_versions:
            version_id = history_versions[0]["version_id"]
            result = workspace.get_result_version(version_id)
            assert result["version"] == 1

    def test_result_history_cleanup(self, tmp_path):
        """测试结果历史版本清理"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 写入超过限制的结果
        max_history = 3
        for i in range(max_history + 2):
            workspace.write_result({"version": i}, max_history=max_history)
            time.sleep(0.05)

        # 检查历史文件数量
        history_dir = workspace.output_dir / "history"
        history_files = list(history_dir.glob("result_*.json"))
        assert len(history_files) <= max_history


class TestTaskMetadata:
    """测试任务元数据管理"""

    def test_save_and_get_metadata(self, tmp_path):
        """测试保存和获取元数据"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 保存元数据
        workspace.save_task_metadata(
            {
                "task_id": "test_task",
                "name": "Test Task",
                "status": "running",
            }
        )

        # 获取元数据
        metadata = workspace.get_task_metadata()
        assert metadata is not None
        assert metadata["task_id"] == "test_task"
        assert metadata["name"] == "Test Task"
        assert "updated_at" in metadata

    def test_update_metadata(self, tmp_path):
        """测试更新元数据"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 保存初始元数据
        workspace.save_task_metadata(
            {
                "task_id": "test_task",
                "status": "pending",
            }
        )

        # 更新元数据
        workspace.update_task_metadata(status="completed", result="success")

        # 检查更新
        metadata = workspace.get_task_metadata()
        assert metadata["status"] == "completed"
        assert metadata["result"] == "success"
        assert metadata["task_id"] == "test_task"  # 原有字段保留

    def test_metadata_file_location(self, tmp_path):
        """测试元数据文件位置"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        workspace.save_task_metadata({"test": "data"})

        # 检查文件位置
        meta_file = workspace.root / ".task_metadata.json"
        assert meta_file.exists()

    def test_get_metadata_nonexistent(self, tmp_path):
        """测试获取不存在的元数据"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        metadata = workspace.get_task_metadata()
        assert metadata is None


class TestBackwardsCompatibility:
    """测试向后兼容性"""

    def test_save_context_default_keeps_history(self, tmp_path):
        """测试 save_gathered_context 默认保留历史"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 默认行为应该保留历史
        workspace.save_gathered_context("v1")
        workspace.save_gathered_context("v2")

        # 应该有历史
        history_dir = workspace.context_dir / "history"
        assert history_dir.exists()

    def test_write_result_default_keeps_history(self, tmp_path):
        """测试 write_result 默认保留历史"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        # 默认行为应该保留历史
        workspace.write_result({"v": 1})
        workspace.write_result({"v": 2})

        # 应该有历史
        history_dir = workspace.output_dir / "history"
        assert history_dir.exists()

    def test_read_result_unchanged(self, tmp_path):
        """测试 read_result 行为不变"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        workspace.write_result({"test": "data"})
        result = workspace.read_result()

        assert result == {"test": "data"}

    def test_get_gathered_context_unchanged(self, tmp_path):
        """测试 get_gathered_context 行为不变"""
        workspace = AgentWorkspace(
            WorkspaceConfig(base_path=str(tmp_path), task_id="test_task")
        )

        workspace.save_gathered_context("test context")
        context = workspace.get_gathered_context()

        assert context == "test context"

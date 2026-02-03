"""
工作空间隔离机制测试

测试 IsolationManager, ResourceLimits 等隔离功能。
"""

import pytest
import json
from pathlib import Path

from src.workspace.isolation import (
    IsolationLevel,
    ResourceLimits,
    ResourceUsage,
    IsolationError,
    ResourceLimitExceededError,
    PathTraversalError,
    IsolationManager,
)


class TestIsolationLevel:
    """IsolationLevel 测试"""

    def test_enum_values(self):
        """测试枚举值"""
        assert IsolationLevel.NONE.value == "none"
        assert IsolationLevel.SOFT.value == "soft"
        assert IsolationLevel.STRICT.value == "strict"


class TestResourceLimits:
    """ResourceLimits 测试"""

    def test_default_values(self):
        """测试默认值"""
        limits = ResourceLimits()

        assert limits.max_files == 1000
        assert limits.max_total_size == 100 * 1024 * 1024  # 100 MB
        assert limits.max_file_size == 10 * 1024 * 1024  # 10 MB
        assert limits.max_depth == 10

    def test_custom_values(self):
        """测试自定义值"""
        limits = ResourceLimits(
            max_files=50,
            max_total_size=10 * 1024 * 1024,
            max_file_size=1024 * 1024,
            max_depth=5,
        )

        assert limits.max_files == 50
        assert limits.max_total_size == 10 * 1024 * 1024
        assert limits.max_file_size == 1024 * 1024
        assert limits.max_depth == 5

    def test_blocked_extensions(self):
        """测试默认禁止的扩展名"""
        limits = ResourceLimits()

        assert ".exe" in limits.blocked_extensions
        assert ".dll" in limits.blocked_extensions
        assert ".sh" in limits.blocked_extensions


class TestResourceUsage:
    """ResourceUsage 测试"""

    def test_to_dict(self):
        """测试序列化"""
        from datetime import datetime

        usage = ResourceUsage(
            file_count=10, total_size=1024 * 1024, last_updated=datetime.now()
        )

        d = usage.to_dict()

        assert d["file_count"] == 10
        assert d["total_size"] == 1024 * 1024
        assert d["total_size_mb"] == 1.0
        assert d["last_updated"] is not None


class TestIsolationManager:
    """IsolationManager 测试"""

    @pytest.fixture
    def parent_workspace(self, tmp_path):
        """创建父工作空间"""
        parent = tmp_path / "parent"
        parent.mkdir()

        # 创建一些文件
        (parent / "input").mkdir()
        (parent / "input" / "task.json").write_text('{"task": "test"}')
        (parent / "context").mkdir()
        (parent / "context" / "shared.txt").write_text("shared content")

        return parent

    @pytest.fixture
    def child_workspace(self, tmp_path):
        """创建子工作空间"""
        child = tmp_path / "parent" / "sub_agents" / "child1"
        child.mkdir(parents=True)
        return child

    @pytest.fixture
    def manager(self, parent_workspace, child_workspace):
        """创建隔离管理器"""
        return IsolationManager(
            parent_root=parent_workspace,
            child_root=child_workspace,
            level=IsolationLevel.SOFT,
            limits=ResourceLimits(max_files=100, max_total_size=10 * 1024 * 1024),
        )

    # ========== 路径验证测试 ==========

    def test_validate_path_normal(self, manager):
        """测试正常路径验证"""
        path = manager.validate_path("output/result.json")

        assert path.is_absolute()
        assert str(manager.child_root) in str(path)

    def test_validate_path_directory_traversal(self, manager):
        """测试目录遍历攻击检测"""
        with pytest.raises(PathTraversalError):
            manager.validate_path("../../../etc/passwd")

        with pytest.raises(PathTraversalError):
            manager.validate_path("output/../../../etc/passwd")

    def test_validate_path_dangerous_chars(self, manager):
        """测试危险字符检测"""
        with pytest.raises(PathTraversalError):
            manager.validate_path("output/$(whoami).txt")

        with pytest.raises(PathTraversalError):
            manager.validate_path("output/`id`.txt")

        with pytest.raises(PathTraversalError):
            manager.validate_path("output/file;rm -rf /.txt")

    def test_validate_path_depth_limit(self, manager):
        """测试路径深度限制"""
        manager.limits.max_depth = 4

        # 正常深度 (a/b/c/file.txt = 4 parts)
        manager.validate_path("a/b/c/file.txt")

        # 超过深度
        with pytest.raises(PathTraversalError):
            manager.validate_path("a/b/c/d/e/file.txt")

    # ========== 资源限制测试 ==========

    def test_check_resource_limits_ok(self, manager, child_workspace):
        """测试资源限制检查通过"""
        # 子工作空间为空，应该通过
        manager.check_resource_limits()

    def test_check_resource_limits_file_count(self, manager, child_workspace):
        """测试文件数量限制"""
        manager.limits.max_files = 5

        # 创建文件
        for i in range(5):
            (child_workspace / f"file{i}.txt").write_text("content")

        manager.invalidate_cache()

        with pytest.raises(ResourceLimitExceededError):
            manager.check_resource_limits()

    def test_check_resource_limits_total_size(self, manager, child_workspace):
        """测试总大小限制"""
        manager.limits.max_total_size = 100  # 100 bytes

        # 创建大文件
        (child_workspace / "large.txt").write_text("x" * 200)

        manager.invalidate_cache()

        with pytest.raises(ResourceLimitExceededError):
            manager.check_resource_limits()

    def test_check_file_write_size_limit(self, manager, child_workspace):
        """测试单文件大小限制"""
        manager.limits.max_file_size = 100

        path = child_workspace / "test.txt"

        with pytest.raises(ResourceLimitExceededError):
            manager.check_file_write(path, 200)

    def test_check_file_write_blocked_extension(self, manager, child_workspace):
        """测试禁止的扩展名"""
        path = child_workspace / "script.sh"

        with pytest.raises(ResourceLimitExceededError):
            manager.check_file_write(path, 10)

    def test_check_file_write_allowed_extension(self, manager, child_workspace):
        """测试允许的扩展名"""
        manager.limits.allowed_extensions = {".txt", ".json"}
        manager.limits.blocked_extensions = set()

        # 允许的扩展名
        manager.check_file_write(child_workspace / "data.json", 10)

        # 不允许的扩展名
        with pytest.raises(ResourceLimitExceededError):
            manager.check_file_write(child_workspace / "script.py", 10)

    # ========== 隔离访问控制测试 ==========

    def test_can_read_parent_soft_isolation(self, manager, parent_workspace):
        """测试软隔离可以读取父工作空间"""
        manager.level = IsolationLevel.SOFT

        assert manager.can_read_parent("context/shared.txt") is True
        assert manager.can_read_parent("nonexistent.txt") is False

    def test_can_read_parent_strict_isolation(self, manager):
        """测试严格隔离不能读取父工作空间"""
        manager.level = IsolationLevel.STRICT

        assert manager.can_read_parent("context/shared.txt") is False

    def test_can_read_parent_none_isolation(self, manager):
        """测试无隔离可以读取父工作空间"""
        manager.level = IsolationLevel.NONE

        assert manager.can_read_parent("context/shared.txt") is True

    def test_can_write_parent(self, manager):
        """测试写入父工作空间权限"""
        manager.level = IsolationLevel.NONE
        assert manager.can_write_parent("any.txt") is True

        manager.level = IsolationLevel.SOFT
        assert manager.can_write_parent("any.txt") is False

        manager.level = IsolationLevel.STRICT
        assert manager.can_write_parent("any.txt") is False

    def test_read_from_parent(self, manager, parent_workspace):
        """测试从父工作空间读取"""
        manager.level = IsolationLevel.SOFT

        content = manager.read_from_parent("context/shared.txt")
        assert content == "shared content"

    def test_read_from_parent_strict_denied(self, manager):
        """测试严格隔离读取被拒绝"""
        manager.level = IsolationLevel.STRICT

        with pytest.raises(IsolationError):
            manager.read_from_parent("context/shared.txt")

    # ========== 写时复制测试 ==========

    def test_copy_from_parent(self, manager, child_workspace, parent_workspace):
        """测试从父工作空间复制"""
        manager.level = IsolationLevel.SOFT

        copied_path = manager.copy_from_parent("context/shared.txt")

        assert copied_path.exists()
        assert copied_path.read_text() == "shared content"
        assert manager.is_copied("context/shared.txt") is True

    def test_copy_from_parent_strict_denied(self, manager):
        """测试严格隔离不能复制"""
        manager.level = IsolationLevel.STRICT

        with pytest.raises(IsolationError):
            manager.copy_from_parent("context/shared.txt")

    def test_copy_from_parent_custom_target(self, manager, child_workspace):
        """测试复制到自定义目标路径"""
        manager.level = IsolationLevel.SOFT

        copied_path = manager.copy_from_parent(
            "context/shared.txt", target_path="data/copied_shared.txt"
        )

        assert copied_path.name == "copied_shared.txt"
        assert "data" in str(copied_path)

    def test_get_copied_files(self, manager, parent_workspace):
        """测试获取已复制文件列表"""
        manager.level = IsolationLevel.SOFT

        manager.copy_from_parent("context/shared.txt")
        manager.copy_from_parent("input/task.json")

        copied = manager.get_copied_files()
        assert len(copied) == 2

    # ========== 安全文件操作测试 ==========

    def test_safe_write(self, manager, child_workspace):
        """测试安全写入"""
        path = manager.safe_write("output/result.txt", "test content")

        assert path.exists()
        assert path.read_text() == "test content"

    def test_safe_write_creates_directory(self, manager, child_workspace):
        """测试安全写入自动创建目录"""
        path = manager.safe_write("deep/nested/dir/file.txt", "content")

        assert path.exists()
        assert "deep/nested/dir" in str(path)

    def test_safe_read_child_first(self, manager, child_workspace, parent_workspace):
        """测试安全读取优先从子工作空间"""
        manager.level = IsolationLevel.SOFT

        # 在子工作空间创建同名文件
        (child_workspace / "context").mkdir(exist_ok=True)
        (child_workspace / "context" / "shared.txt").write_text("child content")

        content = manager.safe_read("context/shared.txt")
        assert content == "child content"  # 子工作空间优先

    def test_safe_read_fallback_to_parent(self, manager, parent_workspace):
        """测试安全读取回退到父工作空间"""
        manager.level = IsolationLevel.SOFT

        content = manager.safe_read("context/shared.txt")
        assert content == "shared content"  # 从父工作空间读取

    def test_safe_read_not_found(self, manager):
        """测试安全读取文件不存在"""
        manager.level = IsolationLevel.STRICT

        with pytest.raises(FileNotFoundError):
            manager.safe_read("nonexistent.txt")

    # ========== 状态持久化测试 ==========

    def test_save_state(self, manager, parent_workspace):
        """测试保存状态"""
        manager.level = IsolationLevel.SOFT
        manager.copy_from_parent("context/shared.txt")

        state = manager.save_state()

        assert state["level"] == "soft"
        assert "limits" in state
        assert "usage" in state
        assert "context/shared.txt" in state["copied_files"]

    def test_load_state(self, manager):
        """测试加载状态"""
        state = {"copied_files": ["file1.txt", "file2.txt"]}

        manager.load_state(state)

        assert manager.is_copied("file1.txt") is True
        assert manager.is_copied("file2.txt") is True

    def test_get_usage(self, manager, child_workspace):
        """测试获取使用统计"""
        (child_workspace / "test1.txt").write_text("content1")
        (child_workspace / "test2.txt").write_text("content2")

        manager.invalidate_cache()
        usage = manager.get_usage()

        assert usage.file_count == 2
        assert usage.total_size > 0
        assert usage.last_updated is not None

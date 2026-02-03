"""
工作空间隔离机制

提供子工作空间的隔离控制，包括：
- 隔离级别（无隔离、软隔离、严格隔离）
- 资源限制（文件数量、总大小）
- 路径验证（防止目录遍历攻击）
- 写时复制（共享资源的安全访问）
"""

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import json

from src.utils.logger import get_logger

logger = get_logger(__name__)


class IsolationLevel(str, Enum):
    """
    隔离级别

    - NONE: 无隔离，子工作空间可完全访问父工作空间
    - SOFT: 软隔离，可读取父工作空间，但写入隔离
    - STRICT: 严格隔离，完全独立，无法访问父工作空间
    """

    NONE = "none"
    SOFT = "soft"
    STRICT = "strict"


@dataclass
class ResourceLimits:
    """
    资源限制配置

    用于限制子工作空间的资源使用。
    """

    # 文件数量限制
    max_files: int = 1000

    # 总大小限制（字节）
    max_total_size: int = 100 * 1024 * 1024  # 100 MB

    # 单文件大小限制（字节）
    max_file_size: int = 10 * 1024 * 1024  # 10 MB

    # 目录深度限制
    max_depth: int = 10

    # 允许的文件扩展名（空集合表示允许所有）
    allowed_extensions: Set[str] = field(default_factory=set)

    # 禁止的文件扩展名
    blocked_extensions: Set[str] = field(
        default_factory=lambda: {".exe", ".dll", ".so", ".dylib", ".sh", ".bat"}
    )


@dataclass
class ResourceUsage:
    """资源使用统计"""

    file_count: int = 0
    total_size: int = 0
    last_updated: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_count": self.file_count,
            "total_size": self.total_size,
            "total_size_mb": round(self.total_size / (1024 * 1024), 2),
            "last_updated": (
                self.last_updated.isoformat() if self.last_updated else None
            ),
        }


class IsolationError(Exception):
    """隔离相关错误"""

    pass


class ResourceLimitExceededError(IsolationError):
    """资源限制超出错误"""

    pass


class PathTraversalError(IsolationError):
    """路径遍历攻击错误"""

    pass


class IsolationManager:
    """
    隔离管理器

    管理工作空间之间的隔离，提供安全的文件访问控制。

    用法:
        ```python
        manager = IsolationManager(
            parent_root=Path("/workspaces/parent"),
            child_root=Path("/workspaces/parent/sub_agents/child_1"),
            level=IsolationLevel.SOFT,
            limits=ResourceLimits(max_files=100),
        )

        # 验证路径安全性
        manager.validate_path("output/result.json")

        # 检查资源限制
        manager.check_resource_limits()

        # 安全复制父工作空间文件
        manager.copy_from_parent("context/shared_context.md")
        ```
    """

    def __init__(
        self,
        parent_root: Path,
        child_root: Path,
        level: IsolationLevel = IsolationLevel.SOFT,
        limits: Optional[ResourceLimits] = None,
    ):
        """
        初始化隔离管理器

        Args:
            parent_root: 父工作空间根目录
            child_root: 子工作空间根目录
            level: 隔离级别
            limits: 资源限制
        """
        self.parent_root = parent_root.resolve()
        self.child_root = child_root.resolve()
        self.level = level
        self.limits = limits or ResourceLimits()

        # 使用统计
        self._usage = ResourceUsage()
        self._usage_cache_valid = False

        # 写时复制追踪
        self._copied_files: Set[str] = set()

        logger.info(
            f"隔离管理器初始化: level={level.value}, "
            f"parent={parent_root}, child={child_root}"
        )

    # ========== 路径验证 ==========

    def validate_path(self, relative_path: str) -> Path:
        """
        验证并规范化路径

        防止目录遍历攻击，确保路径在允许的范围内。

        Args:
            relative_path: 相对路径

        Returns:
            规范化后的绝对路径

        Raises:
            PathTraversalError: 路径不安全
        """
        # 规范化路径
        normalized = Path(relative_path)

        # 检查是否包含危险模式
        path_str = str(normalized)
        dangerous_patterns = ["..", "~", "$", "`", "|", ";", "&"]

        for pattern in dangerous_patterns:
            if pattern in path_str:
                raise PathTraversalError(
                    f"路径包含不安全模式 '{pattern}': {relative_path}"
                )

        # 构建绝对路径并解析
        absolute_path = (self.child_root / normalized).resolve()

        # 确保在子工作空间内
        if not self._is_within_workspace(absolute_path):
            raise PathTraversalError(f"路径超出工作空间范围: {relative_path}")

        # 检查目录深度
        relative_to_root = absolute_path.relative_to(self.child_root)
        depth = len(relative_to_root.parts)
        if depth > self.limits.max_depth:
            raise PathTraversalError(
                f"路径深度超出限制 ({depth} > {self.limits.max_depth}): {relative_path}"
            )

        return absolute_path

    def _is_within_workspace(self, path: Path) -> bool:
        """检查路径是否在工作空间内"""
        try:
            path.relative_to(self.child_root)
            return True
        except ValueError:
            return False

    # ========== 资源限制 ==========

    def check_resource_limits(self, additional_size: int = 0) -> None:
        """
        检查资源限制

        Args:
            additional_size: 预计增加的大小（字节）

        Raises:
            ResourceLimitExceededError: 超出资源限制
        """
        self._update_usage()

        # 检查文件数量
        if self._usage.file_count >= self.limits.max_files:
            raise ResourceLimitExceededError(
                f"文件数量超出限制: {self._usage.file_count} >= {self.limits.max_files}"
            )

        # 检查总大小
        projected_size = self._usage.total_size + additional_size
        if projected_size > self.limits.max_total_size:
            raise ResourceLimitExceededError(
                f"总大小超出限制: {projected_size} > {self.limits.max_total_size} bytes"
            )

    def check_file_write(self, path: Path, content_size: int) -> None:
        """
        检查文件写入是否允许

        Args:
            path: 文件路径
            content_size: 内容大小

        Raises:
            ResourceLimitExceededError: 超出资源限制
            PathTraversalError: 路径不安全
        """
        # 检查单文件大小
        if content_size > self.limits.max_file_size:
            raise ResourceLimitExceededError(
                f"文件大小超出限制: {content_size} > {self.limits.max_file_size} bytes"
            )

        # 检查文件扩展名
        ext = path.suffix.lower()

        if self.limits.blocked_extensions and ext in self.limits.blocked_extensions:
            raise ResourceLimitExceededError(f"文件扩展名被禁止: {ext}")

        if self.limits.allowed_extensions and ext not in self.limits.allowed_extensions:
            raise ResourceLimitExceededError(f"文件扩展名不被允许: {ext}")

        # 检查总资源限制
        existing_size = path.stat().st_size if path.exists() else 0
        additional_size = content_size - existing_size
        self.check_resource_limits(additional_size=max(0, additional_size))

    def _update_usage(self) -> None:
        """更新资源使用统计"""
        if self._usage_cache_valid:
            return

        file_count = 0
        total_size = 0

        for path in self.child_root.rglob("*"):
            if path.is_file():
                file_count += 1
                total_size += path.stat().st_size

        self._usage = ResourceUsage(
            file_count=file_count,
            total_size=total_size,
            last_updated=datetime.now(),
        )
        self._usage_cache_valid = True

    def invalidate_cache(self) -> None:
        """使缓存失效"""
        self._usage_cache_valid = False

    def get_usage(self) -> ResourceUsage:
        """获取资源使用统计"""
        self._update_usage()
        return self._usage

    # ========== 隔离访问控制 ==========

    def can_read_parent(self, relative_path: str) -> bool:
        """
        检查是否可以读取父工作空间的文件

        Args:
            relative_path: 相对于父工作空间的路径

        Returns:
            是否允许读取
        """
        if self.level == IsolationLevel.STRICT:
            return False

        # NONE 和 SOFT 都允许读取
        parent_path = self.parent_root / relative_path
        return parent_path.exists() and parent_path.is_file()

    def can_write_parent(self, relative_path: str) -> bool:
        """
        检查是否可以写入父工作空间

        Args:
            relative_path: 相对于父工作空间的路径

        Returns:
            是否允许写入
        """
        # 只有 NONE 级别允许写入父工作空间
        return self.level == IsolationLevel.NONE

    def read_from_parent(self, relative_path: str) -> str:
        """
        从父工作空间读取文件

        Args:
            relative_path: 相对于父工作空间的路径

        Returns:
            文件内容

        Raises:
            IsolationError: 不允许读取
            FileNotFoundError: 文件不存在
        """
        if not self.can_read_parent(relative_path):
            if self.level == IsolationLevel.STRICT:
                raise IsolationError(
                    f"严格隔离模式下不允许访问父工作空间: {relative_path}"
                )
            raise FileNotFoundError(f"父工作空间文件不存在: {relative_path}")

        parent_path = self.parent_root / relative_path
        return parent_path.read_text(encoding="utf-8")

    # ========== 写时复制 ==========

    def copy_from_parent(
        self,
        relative_path: str,
        target_path: Optional[str] = None,
    ) -> Path:
        """
        从父工作空间复制文件（写时复制）

        在软隔离模式下，需要修改父工作空间的文件时，
        先复制到子工作空间再修改。

        Args:
            relative_path: 父工作空间中的相对路径
            target_path: 目标路径（可选，默认使用相同路径）

        Returns:
            复制后的文件路径

        Raises:
            IsolationError: 不允许复制
        """
        if self.level == IsolationLevel.STRICT:
            raise IsolationError("严格隔离模式下不允许从父工作空间复制")

        # 读取源文件
        parent_path = self.parent_root / relative_path
        if not parent_path.exists():
            raise FileNotFoundError(f"父工作空间文件不存在: {relative_path}")

        # 确定目标路径
        target = target_path or relative_path
        child_path = self.validate_path(target)

        # 检查资源限制
        self.check_file_write(child_path, parent_path.stat().st_size)

        # 创建目标目录
        child_path.parent.mkdir(parents=True, exist_ok=True)

        # 复制文件
        shutil.copy2(parent_path, child_path)

        # 记录复制
        self._copied_files.add(target)
        self.invalidate_cache()

        logger.debug(f"写时复制: {relative_path} -> {target}")

        return child_path

    def is_copied(self, relative_path: str) -> bool:
        """检查文件是否已从父工作空间复制"""
        return relative_path in self._copied_files

    def get_copied_files(self) -> Set[str]:
        """获取所有已复制的文件列表"""
        return self._copied_files.copy()

    # ========== 安全文件操作 ==========

    def safe_write(self, relative_path: str, content: str) -> Path:
        """
        安全写入文件

        检查隔离规则和资源限制后写入文件。

        Args:
            relative_path: 相对路径
            content: 文件内容

        Returns:
            写入的文件路径
        """
        # 验证路径
        file_path = self.validate_path(relative_path)

        # 检查写入限制
        content_bytes = content.encode("utf-8")
        self.check_file_write(file_path, len(content_bytes))

        # 创建目录
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        file_path.write_bytes(content_bytes)
        self.invalidate_cache()

        return file_path

    def safe_read(self, relative_path: str) -> str:
        """
        安全读取文件

        优先读取子工作空间，如果不存在且允许，则从父工作空间读取。

        Args:
            relative_path: 相对路径

        Returns:
            文件内容
        """
        # 先尝试从子工作空间读取
        try:
            file_path = self.validate_path(relative_path)
            if file_path.exists():
                return file_path.read_text(encoding="utf-8")
        except PathTraversalError:
            pass

        # 尝试从父工作空间读取
        if self.can_read_parent(relative_path):
            return self.read_from_parent(relative_path)

        raise FileNotFoundError(f"文件不存在: {relative_path}")

    # ========== 状态持久化 ==========

    def save_state(self) -> Dict[str, Any]:
        """保存隔离管理器状态"""
        return {
            "level": self.level.value,
            "limits": {
                "max_files": self.limits.max_files,
                "max_total_size": self.limits.max_total_size,
                "max_file_size": self.limits.max_file_size,
                "max_depth": self.limits.max_depth,
                "allowed_extensions": list(self.limits.allowed_extensions),
                "blocked_extensions": list(self.limits.blocked_extensions),
            },
            "usage": self.get_usage().to_dict(),
            "copied_files": list(self._copied_files),
        }

    def load_state(self, state: Dict[str, Any]) -> None:
        """加载隔离管理器状态"""
        self._copied_files = set(state.get("copied_files", []))


class IsolatedWorkspaceBuilder:
    """
    隔离工作空间构建器

    辅助创建具有适当隔离配置的子工作空间。

    用法:
        ```python
        builder = IsolatedWorkspaceBuilder(parent_workspace)

        sub_workspace, manager = builder.build(
            sub_task_id="analyze_data",
            isolation_level=IsolationLevel.SOFT,
            resource_limits=ResourceLimits(max_files=50),
            shared_context=["context/shared_config.json"],
        )
        ```
    """

    def __init__(self, parent_workspace: "AgentWorkspace"):
        """
        初始化构建器

        Args:
            parent_workspace: 父工作空间实例
        """
        from .workspace import AgentWorkspace

        self.parent_workspace: AgentWorkspace = parent_workspace

    def build(
        self,
        sub_task_id: str,
        isolation_level: IsolationLevel = IsolationLevel.SOFT,
        resource_limits: Optional[ResourceLimits] = None,
        shared_context: Optional[List[str]] = None,
        inherit_config: bool = True,
    ) -> tuple:
        """
        构建隔离的子工作空间

        Args:
            sub_task_id: 子任务 ID
            isolation_level: 隔离级别
            resource_limits: 资源限制
            shared_context: 需要共享的上下文文件列表
            inherit_config: 是否继承父工作空间配置

        Returns:
            (AgentWorkspace, IsolationManager) 元组
        """
        from .workspace import AgentWorkspace, WorkspaceConfig

        # 创建子工作空间配置
        sub_config = WorkspaceConfig(
            base_path=str(self.parent_workspace.root / "sub_agents"),
            task_id=sub_task_id,
            auto_create=True,
            preserve_files=(
                self.parent_workspace.config.preserve_files if inherit_config else True
            ),
        )

        # 创建子工作空间
        sub_workspace = AgentWorkspace(sub_config)

        # 创建隔离管理器
        manager = IsolationManager(
            parent_root=self.parent_workspace.root,
            child_root=sub_workspace.root,
            level=isolation_level,
            limits=resource_limits or ResourceLimits(),
        )

        # 复制共享上下文
        if shared_context and isolation_level != IsolationLevel.STRICT:
            for context_path in shared_context:
                try:
                    manager.copy_from_parent(context_path)
                except FileNotFoundError:
                    logger.warning(f"共享上下文文件不存在: {context_path}")

        # 保存隔离配置到子工作空间
        isolation_config_path = sub_workspace.root / ".isolation_config.json"
        with open(isolation_config_path, "w") as f:
            json.dump(manager.save_state(), f, indent=2)

        logger.info(
            f"创建隔离子工作空间: {sub_task_id}, " f"level={isolation_level.value}"
        )

        return sub_workspace, manager


# 导出
__all__ = [
    # 枚举
    "IsolationLevel",
    # 配置
    "ResourceLimits",
    "ResourceUsage",
    # 异常
    "IsolationError",
    "ResourceLimitExceededError",
    "PathTraversalError",
    # 核心类
    "IsolationManager",
    "IsolatedWorkspaceBuilder",
]

"""
Agent 版本控制系统

提供 Agent 定义的版本管理，包括版本存储、比较、回滚和发布控制。
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.utils.logger import get_logger

logger = get_logger()


class VersionStatus(str, Enum):
    """版本状态"""

    DRAFT = "draft"  # 草稿
    TESTING = "testing"  # 测试中
    ACTIVE = "active"  # 激活（生产）
    DEPRECATED = "deprecated"  # 已弃用
    ARCHIVED = "archived"  # 已归档


@dataclass
class AgentVersion:
    """Agent 版本"""

    version_id: str
    agent_id: str
    version: str  # 语义版本号，如 "1.0.0"
    definition: Dict[str, Any]
    created_at: datetime
    author: str = "system"
    message: str = ""
    parent_version: Optional[str] = None
    status: VersionStatus = VersionStatus.DRAFT
    tags: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)  # 性能指标

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version_id": self.version_id,
            "agent_id": self.agent_id,
            "version": self.version,
            "definition": self.definition,
            "created_at": self.created_at.isoformat(),
            "author": self.author,
            "message": self.message,
            "parent_version": self.parent_version,
            "status": self.status.value,
            "tags": self.tags,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentVersion":
        """从字典创建"""
        return cls(
            version_id=data["version_id"],
            agent_id=data["agent_id"],
            version=data["version"],
            definition=data["definition"],
            created_at=datetime.fromisoformat(data["created_at"]),
            author=data.get("author", "system"),
            message=data.get("message", ""),
            parent_version=data.get("parent_version"),
            status=VersionStatus(data.get("status", "draft")),
            tags=data.get("tags", []),
            metrics=data.get("metrics", {}),
        )


@dataclass
class VersionDiff:
    """版本差异"""

    path: str
    diff_type: str  # "added", "removed", "changed"
    old_value: Any = None
    new_value: Any = None


class VersionControl:
    """
    Agent 版本控制系统

    功能：
    - 版本提交和存储
    - 版本检索和列表
    - 版本比较（diff）
    - 版本回滚
    - 版本状态管理（草稿、测试、生产、弃用）
    - 版本标签管理

    用法：
        ```python
        vc = VersionControl("./agent_versions")

        # 提交新版本
        version = vc.commit(
            agent_id="my_agent",
            definition={"name": "My Agent", ...},
            version="1.0.0",
            author="developer",
            message="Initial version"
        )

        # 获取活跃版本
        active = vc.get_active_version("my_agent")

        # 比较版本
        diff = vc.diff(version_id_1, version_id_2)

        # 回滚
        vc.rollback("my_agent", old_version_id)
        ```
    """

    def __init__(self, storage_path: str = "./agent_versions"):
        """
        初始化版本控制

        Args:
            storage_path: 版本存储路径
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # 索引文件
        self.index_file = self.storage_path / "index.json"
        self.index = self._load_index()

        logger.info(f"VersionControl 初始化完成，存储路径: {storage_path}")

    def _load_index(self) -> Dict[str, Any]:
        """加载版本索引"""
        if self.index_file.exists():
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "agents": {},  # agent_id -> [version_ids]
            "active_versions": {},  # agent_id -> version_id
            "tags": {},  # tag -> version_id
        }

    def _save_index(self):
        """保存版本索引"""
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2, ensure_ascii=False)

    def commit(
        self,
        agent_id: str,
        definition: Dict[str, Any],
        version: str,
        author: str = "system",
        message: str = "",
        tags: Optional[List[str]] = None,
        auto_activate: bool = False,
    ) -> AgentVersion:
        """
        提交新版本

        Args:
            agent_id: Agent ID
            definition: Agent 定义（完整配置）
            version: 版本号（语义版本，如 "1.0.0"）
            author: 作者
            message: 提交信息
            tags: 标签列表
            auto_activate: 是否自动激活为当前版本

        Returns:
            创建的版本对象
        """
        # 生成版本 ID（基于内容哈希）
        content_hash = hashlib.sha256(
            json.dumps(definition, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:12]
        version_id = f"{agent_id}_{version}_{content_hash}"

        # 检查是否已存在
        if self._version_exists(version_id):
            logger.warning(f"版本 {version_id} 已存在，返回现有版本")
            return self.get_version(version_id)

        # 获取父版本
        parent_version = self.index["active_versions"].get(agent_id)

        # 创建版本对象
        agent_version = AgentVersion(
            version_id=version_id,
            agent_id=agent_id,
            version=version,
            definition=definition,
            created_at=datetime.now(),
            author=author,
            message=message,
            parent_version=parent_version,
            tags=tags or [],
        )

        # 保存版本文件
        version_file = self.storage_path / f"{version_id}.json"
        with open(version_file, "w", encoding="utf-8") as f:
            json.dump(agent_version.to_dict(), f, indent=2, ensure_ascii=False)

        # 更新索引
        if agent_id not in self.index["agents"]:
            self.index["agents"][agent_id] = []
        self.index["agents"][agent_id].append(version_id)

        # 处理标签
        for tag in tags or []:
            self.index["tags"][f"{agent_id}:{tag}"] = version_id

        # 自动激活（如果指定了 auto_activate，或者这是该 Agent 的第一个版本）
        if auto_activate or agent_id not in self.index["active_versions"]:
            self.set_active_version(agent_id, version_id)

        self._save_index()

        logger.info(f"提交版本: {version_id}")
        return agent_version

    def get_version(self, version_id: str) -> Optional[AgentVersion]:
        """获取指定版本"""
        version_file = self.storage_path / f"{version_id}.json"
        if not version_file.exists():
            return None

        with open(version_file, "r", encoding="utf-8") as f:
            return AgentVersion.from_dict(json.load(f))

    def get_active_version(self, agent_id: str) -> Optional[AgentVersion]:
        """获取 Agent 的活跃版本"""
        version_id = self.index["active_versions"].get(agent_id)
        if not version_id:
            return None
        return self.get_version(version_id)

    def set_active_version(self, agent_id: str, version_id: str) -> bool:
        """
        设置活跃版本

        Args:
            agent_id: Agent ID
            version_id: 版本 ID

        Returns:
            是否成功
        """
        version = self.get_version(version_id)
        if not version:
            logger.error(f"版本 {version_id} 不存在")
            return False

        if version.agent_id != agent_id:
            logger.error(f"版本 {version_id} 不属于 Agent {agent_id}")
            return False

        # 更新旧版本状态
        old_version_id = self.index["active_versions"].get(agent_id)
        if old_version_id:
            old_version = self.get_version(old_version_id)
            if old_version:
                old_version.status = VersionStatus.DEPRECATED
                self._save_version(old_version)

        # 更新新版本状态
        version.status = VersionStatus.ACTIVE
        self._save_version(version)

        self.index["active_versions"][agent_id] = version_id
        self._save_index()

        logger.info(f"设置活跃版本: {agent_id} -> {version_id}")
        return True

    def list_versions(
        self,
        agent_id: str,
        status: Optional[VersionStatus] = None,
        limit: int = 100,
    ) -> List[AgentVersion]:
        """
        列出 Agent 的所有版本

        Args:
            agent_id: Agent ID
            status: 过滤状态
            limit: 返回数量限制

        Returns:
            版本列表（按创建时间倒序）
        """
        version_ids = self.index["agents"].get(agent_id, [])
        versions = []

        for vid in version_ids:
            v = self.get_version(vid)
            if v:
                if status is None or v.status == status:
                    versions.append(v)

        # 按创建时间倒序
        versions.sort(key=lambda v: v.created_at, reverse=True)

        return versions[:limit]

    def list_all_agents(self) -> List[str]:
        """列出所有 Agent ID"""
        return list(self.index["agents"].keys())

    def rollback(self, agent_id: str, version_id: str) -> AgentVersion:
        """
        回滚到指定版本

        Args:
            agent_id: Agent ID
            version_id: 目标版本 ID

        Returns:
            回滚后的版本

        Raises:
            ValueError: 版本不存在或不属于该 Agent
        """
        version = self.get_version(version_id)
        if not version:
            raise ValueError(f"版本 {version_id} 不存在")

        if version.agent_id != agent_id:
            raise ValueError(f"版本 {version_id} 不属于 Agent {agent_id}")

        self.set_active_version(agent_id, version_id)

        logger.info(f"回滚 {agent_id} 到版本 {version_id}")
        return version

    def diff(self, version_id_1: str, version_id_2: str) -> Dict[str, Any]:
        """
        比较两个版本的差异

        Args:
            version_id_1: 第一个版本 ID（基准）
            version_id_2: 第二个版本 ID（比较对象）

        Returns:
            差异信息
        """
        v1 = self.get_version(version_id_1)
        v2 = self.get_version(version_id_2)

        if not v1 or not v2:
            raise ValueError("版本不存在")

        differences = self._find_diff(v1.definition, v2.definition)

        return {
            "version_1": {
                "id": version_id_1,
                "version": v1.version,
                "created_at": v1.created_at.isoformat(),
            },
            "version_2": {
                "id": version_id_2,
                "version": v2.version,
                "created_at": v2.created_at.isoformat(),
            },
            "differences": differences,
            "summary": {
                "added": sum(1 for d in differences if d["type"] == "added"),
                "removed": sum(1 for d in differences if d["type"] == "removed"),
                "changed": sum(1 for d in differences if d["type"] == "changed"),
            },
        }

    def add_tag(self, version_id: str, tag: str) -> bool:
        """
        为版本添加标签

        Args:
            version_id: 版本 ID
            tag: 标签名

        Returns:
            是否成功
        """
        version = self.get_version(version_id)
        if not version:
            return False

        if tag not in version.tags:
            version.tags.append(tag)
            self._save_version(version)

        # 更新索引
        self.index["tags"][f"{version.agent_id}:{tag}"] = version_id
        self._save_index()

        logger.debug(f"添加标签: {version_id} -> {tag}")
        return True

    def get_version_by_tag(self, agent_id: str, tag: str) -> Optional[AgentVersion]:
        """根据标签获取版本"""
        version_id = self.index["tags"].get(f"{agent_id}:{tag}")
        if version_id:
            return self.get_version(version_id)
        return None

    def update_metrics(self, version_id: str, metrics: Dict[str, float]) -> bool:
        """
        更新版本的性能指标

        Args:
            version_id: 版本 ID
            metrics: 指标字典

        Returns:
            是否成功
        """
        version = self.get_version(version_id)
        if not version:
            return False

        version.metrics.update(metrics)
        self._save_version(version)

        logger.debug(f"更新指标: {version_id}")
        return True

    def update_status(self, version_id: str, status: VersionStatus) -> bool:
        """
        更新版本状态

        Args:
            version_id: 版本 ID
            status: 新状态

        Returns:
            是否成功
        """
        version = self.get_version(version_id)
        if not version:
            return False

        version.status = status
        self._save_version(version)

        logger.info(f"更新状态: {version_id} -> {status.value}")
        return True

    def delete_version(self, version_id: str, force: bool = False) -> bool:
        """
        删除版本

        Args:
            version_id: 版本 ID
            force: 是否强制删除（即使是活跃版本）

        Returns:
            是否成功
        """
        version = self.get_version(version_id)
        if not version:
            return False

        # 检查是否是活跃版本
        if self.index["active_versions"].get(version.agent_id) == version_id:
            if not force:
                logger.warning(f"无法删除活跃版本: {version_id}")
                return False
            del self.index["active_versions"][version.agent_id]

        # 从索引中移除
        if version.agent_id in self.index["agents"]:
            self.index["agents"][version.agent_id] = [
                vid
                for vid in self.index["agents"][version.agent_id]
                if vid != version_id
            ]

        # 移除标签
        self.index["tags"] = {
            k: v for k, v in self.index["tags"].items() if v != version_id
        }

        self._save_index()

        # 删除文件
        version_file = self.storage_path / f"{version_id}.json"
        if version_file.exists():
            version_file.unlink()

        logger.info(f"删除版本: {version_id}")
        return True

    def get_version_history(
        self, version_id: str, depth: int = 10
    ) -> List[AgentVersion]:
        """
        获取版本的历史链

        Args:
            version_id: 起始版本 ID
            depth: 最大深度

        Returns:
            版本历史列表（从新到旧）
        """
        history = []
        current_id = version_id

        for _ in range(depth):
            version = self.get_version(current_id)
            if not version:
                break
            history.append(version)
            if not version.parent_version:
                break
            current_id = version.parent_version

        return history

    def _version_exists(self, version_id: str) -> bool:
        """检查版本是否存在"""
        version_file = self.storage_path / f"{version_id}.json"
        return version_file.exists()

    def _save_version(self, version: AgentVersion) -> None:
        """保存版本"""
        version_file = self.storage_path / f"{version.version_id}.json"
        with open(version_file, "w", encoding="utf-8") as f:
            json.dump(version.to_dict(), f, indent=2, ensure_ascii=False)

    def _find_diff(self, d1: Dict, d2: Dict, path: str = "") -> List[Dict[str, Any]]:
        """递归查找差异"""
        diffs = []
        all_keys = set(d1.keys()) | set(d2.keys())

        for key in all_keys:
            current_path = f"{path}.{key}" if path else key

            if key not in d1:
                diffs.append({"path": current_path, "type": "added", "value": d2[key]})
            elif key not in d2:
                diffs.append(
                    {"path": current_path, "type": "removed", "value": d1[key]}
                )
            elif d1[key] != d2[key]:
                if isinstance(d1[key], dict) and isinstance(d2[key], dict):
                    diffs.extend(self._find_diff(d1[key], d2[key], current_path))
                else:
                    diffs.append(
                        {
                            "path": current_path,
                            "type": "changed",
                            "old": d1[key],
                            "new": d2[key],
                        }
                    )

        return diffs

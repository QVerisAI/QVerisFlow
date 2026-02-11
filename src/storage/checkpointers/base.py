"""
检查点存储基类

定义 LangGraph 检查点存储的标准接口。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)


class BaseCheckpointSaver(ABC):
    """
    检查点存储基类

    定义检查点存储的标准接口，与 LangGraph 兼容。

    所有检查点存储实现都应继承此基类并实现以下方法：
    - put: 保存检查点
    - get: 获取检查点
    - list: 列出检查点
    """

    @abstractmethod
    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        保存检查点

        Args:
            config: 配置（包含 thread_id 等）
            checkpoint: 检查点数据
            metadata: 元数据

        Returns:
            更新后的配置
        """
        pass

    @abstractmethod
    def get(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        获取检查点

        Args:
            config: 配置

        Returns:
            检查点数据，不存在则返回 None
        """
        pass

    @abstractmethod
    def list(
        self,
        config: Dict[str, Any],
        limit: int = 10,
        before: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        列出检查点

        Args:
            config: 配置
            limit: 返回数量限制
            before: 在此时间戳之前的检查点

        Yields:
            检查点数据
        """
        pass

    def get_tuple(
        self, config: Dict[str, Any]
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """
        获取检查点和元数据

        Args:
            config: 配置

        Returns:
            (检查点, 元数据) 元组，不存在则返回 None
        """
        checkpoint = self.get(config)
        if checkpoint is None:
            return None
        metadata = checkpoint.pop("__metadata__", {})
        return checkpoint, metadata

    def _get_thread_id(self, config: Dict[str, Any]) -> str:
        """从配置中提取 thread_id"""
        return config.get("configurable", {}).get("thread_id", "default")

    def _get_checkpoint_id(self, config: Dict[str, Any]) -> Optional[str]:
        """从配置中提取 checkpoint_id"""
        return config.get("configurable", {}).get("checkpoint_id")

    def _update_config_with_checkpoint_id(
        self, config: Dict[str, Any], checkpoint_id: str
    ) -> Dict[str, Any]:
        """更新配置中的 checkpoint_id"""
        new_config = config.copy()
        new_config.setdefault("configurable", {})
        new_config["configurable"]["checkpoint_id"] = checkpoint_id
        return new_config


__all__ = ["BaseCheckpointSaver"]

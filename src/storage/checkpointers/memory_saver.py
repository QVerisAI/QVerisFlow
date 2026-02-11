"""
内存检查点存储

使用内存存储检查点。
适用于单元测试和短期任务。
"""

from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from .base import BaseCheckpointSaver
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SimpleMemoryCheckpointSaver(BaseCheckpointSaver):
    """
    简单内存检查点存储

    使用 Python 字典存储检查点。

    特点：
    - 无外部依赖
    - 快速读写
    - 进程重启后数据丢失
    - 适合测试和短期任务

    用法:
        ```python
        from storage.checkpointers import SimpleMemoryCheckpointSaver

        saver = SimpleMemoryCheckpointSaver()

        # 与 LangGraph 集成
        graph = builder.compile(checkpointer=saver)
        ```
    """

    def __init__(self):
        """初始化内存检查点存储"""
        self._storage: Dict[str, Dict[str, Any]] = {}
        self._lists: Dict[str, List[str]] = {}

        logger.info("内存检查点存储初始化")

    def _make_key(self, thread_id: str, checkpoint_id: Optional[str] = None) -> str:
        """生成存储键"""
        if checkpoint_id:
            return f"{thread_id}:{checkpoint_id}"
        return f"{thread_id}:latest"

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """保存检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        data = checkpoint.copy()
        data["__metadata__"] = metadata or {}
        data["__checkpoint_id__"] = checkpoint_id
        data["__timestamp__"] = datetime.now().isoformat()

        key = self._make_key(thread_id, checkpoint_id)
        latest_key = self._make_key(thread_id)

        self._storage[key] = data
        self._storage[latest_key] = data

        # 维护检查点列表
        if thread_id not in self._lists:
            self._lists[thread_id] = []
        self._lists[thread_id].insert(0, checkpoint_id)
        self._lists[thread_id] = self._lists[thread_id][:100]  # 保留最近 100 个

        logger.debug(
            f"保存检查点: thread_id={thread_id}, checkpoint_id={checkpoint_id}"
        )

        return self._update_config_with_checkpoint_id(config, checkpoint_id)

    def get(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """获取检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._get_checkpoint_id(config)

        if checkpoint_id:
            key = self._make_key(thread_id, checkpoint_id)
        else:
            key = self._make_key(thread_id)

        return self._storage.get(key)

    def list(
        self,
        config: Dict[str, Any],
        limit: int = 10,
        before: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """列出检查点"""
        thread_id = self._get_thread_id(config)

        checkpoint_ids = self._lists.get(thread_id, [])[:limit]

        for checkpoint_id in checkpoint_ids:
            if before and checkpoint_id >= before:
                continue

            key = self._make_key(thread_id, checkpoint_id)
            data = self._storage.get(key)
            if data:
                yield data

    def delete(self, config: Dict[str, Any]) -> bool:
        """删除检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._get_checkpoint_id(config)

        if checkpoint_id:
            key = self._make_key(thread_id, checkpoint_id)
            if key in self._storage:
                del self._storage[key]
                if thread_id in self._lists and checkpoint_id in self._lists[thread_id]:
                    self._lists[thread_id].remove(checkpoint_id)
                return True
            return False
        else:
            # 删除所有相关键
            keys_to_delete = [
                k for k in self._storage.keys() if k.startswith(f"{thread_id}:")
            ]
            for key in keys_to_delete:
                del self._storage[key]
            if thread_id in self._lists:
                del self._lists[thread_id]
            return len(keys_to_delete) > 0

    def clear(self) -> None:
        """清空所有检查点"""
        self._storage.clear()
        self._lists.clear()
        logger.info("内存检查点已清空")


__all__ = ["SimpleMemoryCheckpointSaver"]

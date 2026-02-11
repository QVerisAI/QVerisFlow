"""
文件系统检查点存储

使用本地文件系统存储检查点。
适用于开发和测试环境。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .base import BaseCheckpointSaver
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FileCheckpointSaver(BaseCheckpointSaver):
    """
    文件系统检查点存储

    使用本地文件系统存储检查点。

    特点：
    - 无需外部依赖
    - 简单可调试
    - 适合开发和测试

    用法:
        ```python
        from storage.checkpointers import FileCheckpointSaver

        saver = FileCheckpointSaver(path="./checkpoints")

        # 与 LangGraph 集成
        graph = builder.compile(checkpointer=saver)
        ```
    """

    def __init__(self, path: str = "/tmp/langgraph_checkpoints"):
        """
        初始化文件系统检查点存储

        Args:
            path: 检查点存储目录
        """
        self.base_path = Path(path)
        self.base_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"文件系统检查点存储初始化: {self.base_path}")

    def _get_thread_path(self, thread_id: str) -> Path:
        """获取线程目录"""
        path = self.base_path / thread_id
        path.mkdir(exist_ok=True)
        return path

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """保存检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        thread_path = self._get_thread_path(thread_id)

        data = checkpoint.copy()
        data["__metadata__"] = metadata or {}
        data["__checkpoint_id__"] = checkpoint_id
        data["__timestamp__"] = datetime.now().isoformat()

        # 保存检查点
        checkpoint_file = thread_path / f"{checkpoint_id}.json"
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(data, f, default=str, ensure_ascii=False, indent=2)

        # 更新 latest 链接
        latest_file = thread_path / "latest.json"
        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump(data, f, default=str, ensure_ascii=False, indent=2)

        logger.debug(
            f"保存检查点: thread_id={thread_id}, checkpoint_id={checkpoint_id}"
        )

        return self._update_config_with_checkpoint_id(config, checkpoint_id)

    def get(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """获取检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._get_checkpoint_id(config)

        thread_path = self._get_thread_path(thread_id)

        if checkpoint_id:
            file_path = thread_path / f"{checkpoint_id}.json"
        else:
            file_path = thread_path / "latest.json"

        if not file_path.exists():
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list(
        self,
        config: Dict[str, Any],
        limit: int = 10,
        before: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """列出检查点"""
        thread_id = self._get_thread_id(config)
        thread_path = self._get_thread_path(thread_id)

        files = sorted(thread_path.glob("*.json"), reverse=True)

        count = 0
        for file_path in files:
            if file_path.name == "latest.json":
                continue

            checkpoint_id = file_path.stem
            if before and checkpoint_id >= before:
                continue

            with open(file_path, "r", encoding="utf-8") as f:
                yield json.load(f)

            count += 1
            if count >= limit:
                break

    def delete(self, config: Dict[str, Any]) -> bool:
        """删除检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._get_checkpoint_id(config)

        thread_path = self._get_thread_path(thread_id)

        if checkpoint_id:
            file_path = thread_path / f"{checkpoint_id}.json"
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        else:
            # 删除整个线程目录
            import shutil

            if thread_path.exists():
                shutil.rmtree(thread_path)
                return True
            return False

    def cleanup(self, older_than_days: int = 7) -> int:
        """
        清理过期检查点

        Args:
            older_than_days: 清理多少天之前的检查点

        Returns:
            删除的文件数
        """
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=older_than_days)
        deleted = 0

        for thread_path in self.base_path.iterdir():
            if not thread_path.is_dir():
                continue

            for file_path in thread_path.glob("*.json"):
                if file_path.name == "latest.json":
                    continue

                try:
                    # 从文件名解析时间
                    checkpoint_id = file_path.stem
                    # 格式: YYYYMMDD_HHMMSS_ffffff
                    file_time = datetime.strptime(checkpoint_id[:15], "%Y%m%d_%H%M%S")
                    if file_time < cutoff:
                        file_path.unlink()
                        deleted += 1
                except (ValueError, OSError):
                    continue

        logger.info(f"清理了 {deleted} 个过期检查点文件")
        return deleted


__all__ = ["FileCheckpointSaver"]

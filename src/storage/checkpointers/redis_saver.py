"""
Redis 检查点存储

使用 Redis 作为 LangGraph 检查点的存储后端。
通过依赖注入使用统一的 RedisClient。
"""

import json
import pickle
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Union

from .base import BaseCheckpointSaver
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RedisCheckpointSaver(BaseCheckpointSaver):
    """
    Redis 检查点存储

    使用注入的 RedisClient 实现检查点存储。

    特点：
    - 高性能读写
    - 支持 TTL 自动过期
    - 适合临时状态和分布式部署
    - 使用同步 API (LangGraph 要求)

    用法:
        ```python
        from storage.redis_client import RedisClient
        from storage.checkpointers import RedisCheckpointSaver

        redis_client = RedisClient(host="localhost", port=6379)
        saver = RedisCheckpointSaver(
            redis_client=redis_client,
            prefix="myapp:checkpoint:",
            ttl=3600,  # 1小时过期
        )

        # 与 LangGraph 集成
        graph = builder.compile(checkpointer=saver)
        ```
    """

    def __init__(
        self,
        redis_client: Optional["RedisClient"] = None,
        redis_url: Optional[str] = None,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        prefix: str = "langgraph:checkpoint:",
        ttl: Optional[int] = None,
        serializer: str = "json",
    ):
        """
        初始化 Redis 检查点存储

        Args:
            redis_client: 已有的 RedisClient 实例（推荐，依赖注入）
            redis_url: Redis URL（当 redis_client 未提供时使用）
            host: Redis 主机
            port: Redis 端口
            db: Redis 数据库编号
            password: Redis 密码
            prefix: 键前缀
            ttl: 过期时间（秒）
            serializer: 序列化方式（json 或 pickle）
        """
        self.prefix = prefix
        self.ttl = ttl
        self.serializer = serializer

        # 使用注入的客户端或创建新客户端
        if redis_client is not None:
            self._client = redis_client
            self._own_client = False
        else:
            # 延迟导入以避免循环依赖
            from ..redis_client import RedisClient

            self._client = RedisClient(
                host=host,
                port=port,
                db=db,
                password=password,
                url=redis_url,
            )
            self._own_client = True

        logger.info("Redis 检查点存储初始化: prefix=%s, ttl=%s", prefix, ttl)

    def _make_key(self, thread_id: str, checkpoint_id: Optional[str] = None) -> str:
        """生成 Redis 键"""
        if checkpoint_id:
            return f"{self.prefix}{thread_id}:{checkpoint_id}"
        return f"{self.prefix}{thread_id}:latest"

    def _serialize(self, data: Dict[str, Any]) -> bytes:
        """序列化数据"""
        if self.serializer == "pickle":
            return pickle.dumps(data)
        else:
            return json.dumps(data, default=str).encode("utf-8")

    def _deserialize(self, data: bytes) -> Dict[str, Any]:
        """反序列化数据"""
        if data is None:
            return None
        if self.serializer == "pickle":
            return pickle.loads(data)
        else:
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            return json.loads(data)

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """保存检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        # 合并元数据
        data = checkpoint.copy()
        data["__metadata__"] = metadata or {}
        data["__checkpoint_id__"] = checkpoint_id
        data["__timestamp__"] = datetime.now().isoformat()

        # 保存到 Redis (使用同步 API)
        key = self._make_key(thread_id, checkpoint_id)
        latest_key = self._make_key(thread_id)
        serialized = self._serialize(data)

        pipe = self._client.pipeline_sync()
        if self.ttl:
            pipe.setex(key, self.ttl, serialized)
            pipe.setex(latest_key, self.ttl, serialized)
        else:
            pipe.set(key, serialized)
            pipe.set(latest_key, serialized)

        # 维护检查点列表
        list_key = f"{self.prefix}{thread_id}:list"
        pipe.lpush(list_key, checkpoint_id)
        pipe.ltrim(list_key, 0, 99)  # 保留最近 100 个
        if self.ttl:
            pipe.expire(list_key, self.ttl)

        pipe.execute()

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

        data = self._client.get_sync(key)
        if data is None:
            return None

        return self._deserialize(data)

    def list(
        self,
        config: Dict[str, Any],
        limit: int = 10,
        before: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """列出检查点"""
        thread_id = self._get_thread_id(config)
        list_key = f"{self.prefix}{thread_id}:list"

        checkpoint_ids = self._client.lrange_sync(list_key, 0, limit - 1)

        for checkpoint_id in checkpoint_ids:
            if isinstance(checkpoint_id, bytes):
                checkpoint_id = checkpoint_id.decode("utf-8")

            if before and checkpoint_id >= before:
                continue

            key = self._make_key(thread_id, checkpoint_id)
            data = self._client.get_sync(key)
            if data:
                yield self._deserialize(data)

    def delete(self, config: Dict[str, Any]) -> bool:
        """删除检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._get_checkpoint_id(config)

        if checkpoint_id:
            key = self._make_key(thread_id, checkpoint_id)
            return self._client.delete_sync(key) > 0
        else:
            # 删除所有相关键
            pattern = f"{self.prefix}{thread_id}:*"
            keys = list(self._client.scan_iter_sync(match=pattern))
            if keys:
                return self._client.delete_sync(*keys) > 0
            return False

    def close(self):
        """关闭连接（仅当自己创建的客户端）"""
        if self._own_client:
            self._client.close_sync()


__all__ = ["RedisCheckpointSaver"]

"""
检查点存储工厂

根据配置创建合适的检查点存储后端。
"""

import os
from typing import Optional, TYPE_CHECKING

from .base import BaseCheckpointSaver
from .redis_saver import RedisCheckpointSaver
from .postgres_saver import PostgresCheckpointSaver
from .file_saver import FileCheckpointSaver
from .memory_saver import SimpleMemoryCheckpointSaver

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from ..config import CheckpointStorageConfig, StorageConfig
    from ..redis_client import RedisClient
    from ..database import AsyncDatabaseManager

logger = get_logger(__name__)


class CheckpointerFactory:
    """
    检查点存储工厂

    根据配置创建合适的检查点存储后端。

    用法:
        ```python
        from storage.config import StorageConfig, CheckpointerType
        from storage.checkpointers import CheckpointerFactory

        # 从配置创建
        config = StorageConfig()
        config.checkpoint.type = CheckpointerType.REDIS
        saver = CheckpointerFactory.create_from_config(config)

        # 快捷方法
        saver = CheckpointerFactory.create_redis("redis://localhost:6379/0")
        saver = CheckpointerFactory.create_postgres("postgresql://...")

        # 从环境变量
        saver = CheckpointerFactory.from_env()
        ```
    """

    @staticmethod
    def create_from_config(
        config: "CheckpointStorageConfig",
        redis_client: Optional["RedisClient"] = None,
        db_manager: Optional["AsyncDatabaseManager"] = None,
    ) -> BaseCheckpointSaver:
        """
        根据配置创建检查点存储

        Args:
            config: 检查点存储配置
            redis_client: 已有的 Redis 客户端（用于依赖注入）
            db_manager: 已有的数据库管理器（用于依赖注入）

        Returns:
            检查点存储实例
        """
        from ..config import CheckpointerType

        if config.type == CheckpointerType.MEMORY:
            return CheckpointerFactory._create_memory()

        elif config.type == CheckpointerType.REDIS:
            return RedisCheckpointSaver(
                redis_client=redis_client,
                prefix=config.redis_prefix,
                ttl=config.redis_ttl,
                serializer=config.serializer,
            )

        elif config.type == CheckpointerType.POSTGRESQL:
            return PostgresCheckpointSaver(
                db_manager=db_manager,
                table_name=config.postgres_table,
                serializer=config.serializer,
            )

        elif config.type == CheckpointerType.FILE:
            return FileCheckpointSaver(path=config.file_path)

        else:
            raise ValueError(f"不支持的检查点存储类型: {config.type}")

    @staticmethod
    def create_from_storage_config(
        storage_config: "StorageConfig",
        redis_client: Optional["RedisClient"] = None,
        db_manager: Optional["AsyncDatabaseManager"] = None,
    ) -> BaseCheckpointSaver:
        """
        从统一存储配置创建检查点存储

        Args:
            storage_config: 统一存储配置
            redis_client: 已有的 Redis 客户端
            db_manager: 已有的数据库管理器

        Returns:
            检查点存储实例
        """
        return CheckpointerFactory.create_from_config(
            storage_config.checkpoint,
            redis_client=redis_client,
            db_manager=db_manager,
        )

    @staticmethod
    def _create_memory() -> BaseCheckpointSaver:
        """创建内存检查点存储"""
        try:
            from langgraph.checkpoint.memory import MemorySaver

            logger.info("使用 LangGraph 原生 MemorySaver")
            return MemorySaver()
        except ImportError:
            logger.warning("LangGraph 未安装，使用简单内存存储")
            return SimpleMemoryCheckpointSaver()

    @staticmethod
    def create_redis(
        redis_url: Optional[str] = None,
        redis_client: Optional["RedisClient"] = None,
        prefix: str = "langgraph:checkpoint:",
        ttl: Optional[int] = None,
    ) -> RedisCheckpointSaver:
        """
        快捷方法：创建 Redis 检查点存储

        Args:
            redis_url: Redis URL
            redis_client: 已有的 Redis 客户端（优先）
            prefix: 键前缀
            ttl: 过期时间

        Returns:
            Redis 检查点存储实例
        """
        return RedisCheckpointSaver(
            redis_client=redis_client,
            redis_url=redis_url,
            prefix=prefix,
            ttl=ttl,
        )

    @staticmethod
    def create_postgres(
        postgres_url: Optional[str] = None,
        db_manager: Optional["AsyncDatabaseManager"] = None,
        table_name: str = "langgraph_checkpoints",
    ) -> PostgresCheckpointSaver:
        """
        快捷方法：创建 PostgreSQL 检查点存储

        Args:
            postgres_url: PostgreSQL URL
            db_manager: 已有的数据库管理器（优先）
            table_name: 表名

        Returns:
            PostgreSQL 检查点存储实例
        """
        return PostgresCheckpointSaver(
            db_manager=db_manager,
            postgres_url=postgres_url,
            table_name=table_name,
        )

    @staticmethod
    def create_file(path: str = "/tmp/langgraph_checkpoints") -> FileCheckpointSaver:
        """
        快捷方法：创建文件系统检查点存储

        Args:
            path: 存储目录

        Returns:
            文件系统检查点存储实例
        """
        return FileCheckpointSaver(path=path)

    @staticmethod
    def from_env() -> BaseCheckpointSaver:
        """
        从环境变量创建检查点存储

        环境变量：
        - CHECKPOINT_TYPE: memory, redis, postgresql, file
        - REDIS_URL: Redis 连接 URL
        - POSTGRES_URL: PostgreSQL 连接 URL
        - CHECKPOINT_PATH: 文件系统检查点路径
        """
        checkpoint_type = os.getenv("CHECKPOINT_TYPE", "memory").lower()

        if checkpoint_type == "redis":
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            return RedisCheckpointSaver(redis_url=redis_url)

        elif checkpoint_type == "postgresql":
            postgres_url = os.getenv(
                "POSTGRES_URL",
                "postgresql://postgres:postgres@localhost:5432/agent_framework",
            )
            return PostgresCheckpointSaver(postgres_url=postgres_url)

        elif checkpoint_type == "file":
            path = os.getenv("CHECKPOINT_PATH", "/tmp/langgraph_checkpoints")
            return FileCheckpointSaver(path=path)

        else:
            return CheckpointerFactory._create_memory()


__all__ = ["CheckpointerFactory"]

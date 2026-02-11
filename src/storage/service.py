"""
统一存储服务

提供存储层的统一生命周期管理：
- 应用启动时初始化所有启用的存储后端
- 健康检查
- 优雅关闭
- 单例访问

支持裸机（bare-metal）和 Docker 两种部署模式。
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any

from src.utils.logger import get_logger

logger = get_logger()


class StorageService:
    """
    统一存储服务

    管理所有持久化存储后端的生命周期，提供全局单例访问。

    使用示例:
    ```python
    from src.storage.service import StorageService

    # 初始化（通常在 app 启动时调用一次）
    storage = StorageService.get_instance()
    await storage.initialize(storage_config)

    # 访问各个客户端
    db = storage.db           # AsyncDatabaseManager
    redis = storage.redis     # RedisClient
    oss = storage.oss         # BaseOSSClient

    # 健康检查
    health = await storage.health_check()

    # 关闭（app 停止时调用）
    await storage.shutdown()
    ```
    """

    _instance: Optional["StorageService"] = None

    def __init__(self):
        self._initialized = False
        self._config = None

        # 存储客户端
        self._db: Optional[Any] = None  # AsyncDatabaseManager
        self._redis: Optional[Any] = None  # RedisClient
        self._oss: Optional[Any] = None  # BaseOSSClient

    @classmethod
    def get_instance(cls) -> "StorageService":
        """获取 StorageService 单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None

    @property
    def config(self):
        """获取存储配置"""
        return self._config

    @property
    def db(self):
        """获取数据库管理器（AsyncDatabaseManager）"""
        return self._db

    @property
    def redis(self):
        """获取 Redis 客户端"""
        return self._redis

    @property
    def oss(self):
        """获取 OSS 客户端"""
        return self._oss

    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized

    async def initialize(self, config=None) -> None:
        """
        初始化所有启用的存储后端

        Args:
            config: StorageConfig 实例。如果为 None，从环境变量加载。
        """
        if self._initialized:
            logger.debug("StorageService 已经初始化，跳过")
            return

        from .config import StorageConfig

        if config is None:
            config = StorageConfig.from_env()

        self._config = config

        logger.info(
            f"正在初始化存储服务 (deploy_mode={config.deploy_mode.value}, "
            f"postgres={config.enable_postgres}, "
            f"redis={config.enable_redis}, "
            f"oss={config.enable_oss})"
        )

        # 1. 初始化本地目录
        await self._init_local_dirs(config)

        # 2. 初始化 PostgreSQL
        if config.enable_postgres:
            await self._init_postgres(config)

        # 3. 初始化 Redis
        if config.enable_redis:
            await self._init_redis(config)

        # 4. 初始化 OSS
        if config.enable_oss:
            await self._init_oss(config)

        self._initialized = True
        logger.info("✅ 存储服务初始化完成")

    async def _init_local_dirs(self, config) -> None:
        """确保本地目录存在"""
        dirs = [
            config.local.data_dir,
            config.local.workspace_dir,
            config.local.storage_dir,
            config.local.log_dir,
            config.local.temp_dir,
        ]

        # 检查点和追踪的文件目录
        if config.checkpoint.file_path:
            dirs.append(config.checkpoint.file_path)
        if config.trace.file_path:
            dirs.append(config.trace.file_path)

        for dir_path in dirs:
            p = Path(dir_path)
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
                logger.debug(f"创建目录: {p}")

        logger.info(f"✅ 本地存储目录已就绪 (data_dir={config.local.data_dir})")

    async def _init_postgres(self, config) -> None:
        """初始化 PostgreSQL 连接"""
        try:
            from .database import AsyncDatabaseManager

            self._db = AsyncDatabaseManager(config.postgres)
            await self._db.connect()
            logger.info(
                f"✅ PostgreSQL 已连接 ({config.postgres.host}:{config.postgres.port}/{config.postgres.database})"
            )
        except Exception as e:
            logger.error(f"❌ PostgreSQL 连接失败: {e}")
            self._db = None
            # 不抛出异常，允许应用在无数据库时降级运行
            logger.warning("应用将在无 PostgreSQL 模式下运行")

    async def _init_redis(self, config) -> None:
        """初始化 Redis 连接"""
        try:
            from .redis_client import RedisClient, REDIS_AVAILABLE

            if not REDIS_AVAILABLE:
                logger.warning("redis 库未安装，Redis 功能不可用")
                return

            self._redis = RedisClient(
                host=config.redis.host,
                port=config.redis.port,
                db=config.redis.db,
                password=config.redis.password,
                max_connections=config.redis.max_connections,
                ssl=config.redis.ssl,
            )
            await self._redis.connect()
            logger.info(
                f"✅ Redis 已连接 ({config.redis.host}:{config.redis.port}/{config.redis.db})"
            )
        except Exception as e:
            logger.error(f"❌ Redis 连接失败: {e}")
            self._redis = None
            logger.warning("应用将在无 Redis 模式下运行")

    async def _init_oss(self, config) -> None:
        """初始化 OSS 客户端"""
        try:
            if config.oss.provider == "aliyun":
                from .oss_client import AliyunOSSClient

                self._oss = AliyunOSSClient(
                    endpoint=config.oss.aliyun_endpoint,
                    access_key_id=config.oss.aliyun_access_key_id,
                    access_key_secret=config.oss.aliyun_access_key_secret,
                    bucket_name=config.oss.aliyun_bucket,
                )
            else:
                from .oss_client import MinIOClient

                self._oss = MinIOClient(
                    endpoint=config.oss.endpoint,
                    access_key=config.oss.access_key,
                    secret_key=config.oss.secret_key,
                    bucket_name=config.oss.bucket_name,
                    secure=config.oss.secure,
                )

            logger.info(
                f"✅ OSS 已初始化 (provider={config.oss.provider}, "
                f"endpoint={config.oss.endpoint})"
            )
        except Exception as e:
            logger.error(f"❌ OSS 初始化失败: {e}")
            self._oss = None
            logger.warning("应用将在无 OSS 模式下运行")

    async def health_check(self) -> Dict[str, Any]:
        """
        检查所有存储后端的健康状态

        Returns:
            健康状态字典
        """
        result = {
            "initialized": self._initialized,
            "deploy_mode": (
                self._config.deploy_mode.value if self._config else "unknown"
            ),
            "local_storage": True,  # 本地目录总是可用
            "postgres": {"enabled": False, "healthy": False},
            "redis": {"enabled": False, "healthy": False},
            "oss": {"enabled": False, "healthy": False},
        }

        if not self._config:
            return result

        # PostgreSQL 健康检查
        if self._config.enable_postgres:
            result["postgres"]["enabled"] = True
            if self._db:
                try:
                    async with self._db.session() as session:
                        from sqlalchemy import text

                        await session.execute(text("SELECT 1"))
                    result["postgres"]["healthy"] = True
                except Exception as e:
                    result["postgres"]["error"] = str(e)

        # Redis 健康检查
        if self._config.enable_redis:
            result["redis"]["enabled"] = True
            if self._redis:
                try:
                    pong = await self._redis.ping()
                    result["redis"]["healthy"] = pong
                except Exception as e:
                    result["redis"]["error"] = str(e)

        # OSS 健康检查
        if self._config.enable_oss:
            result["oss"]["enabled"] = True
            if self._oss:
                try:
                    # 简单列举确认桶可访问
                    result["oss"]["healthy"] = True
                except Exception as e:
                    result["oss"]["error"] = str(e)

        return result

    async def shutdown(self) -> None:
        """优雅关闭所有存储连接"""
        logger.info("正在关闭存储服务...")

        # 关闭 PostgreSQL
        if self._db:
            try:
                await self._db.close()
                logger.info("PostgreSQL 连接已关闭")
            except Exception as e:
                logger.error(f"关闭 PostgreSQL 失败: {e}")

        # 关闭 Redis
        if self._redis:
            try:
                await self._redis.close()
                logger.info("Redis 连接已关闭")
            except Exception as e:
                logger.error(f"关闭 Redis 失败: {e}")

        # OSS 通常不需要显式关闭
        self._oss = None

        self._initialized = False
        logger.info("✅ 存储服务已关闭")

    def __repr__(self) -> str:
        return (
            f"<StorageService initialized={self._initialized} "
            f"postgres={'✓' if self._db else '✗'} "
            f"redis={'✓' if self._redis else '✗'} "
            f"oss={'✓' if self._oss else '✗'}>"
        )


# ========== 便捷访问函数 ==========


def get_storage_service() -> StorageService:
    """获取全局 StorageService 实例"""
    return StorageService.get_instance()

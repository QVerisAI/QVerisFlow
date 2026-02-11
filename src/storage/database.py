"""
数据库初始化和管理

提供数据库连接、会话管理和初始化功能。
支持 PostgreSQL（生产）和 SQLite（开发/测试）。

包含：
- DatabaseManager: 同步数据库管理器
- AsyncDatabaseManager: 异步数据库管理器（支持 SQLAlchemy 和 raw asyncpg）
"""

import os
from typing import Any, Optional, Generator, AsyncGenerator
from contextlib import contextmanager, asynccontextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, NullPool

from src.utils.logger import get_logger

logger = get_logger()

# 延迟导入 Base 以避免循环导入
_Base = None


def get_base():
    """延迟获取 Base"""
    global _Base
    if _Base is None:
        from .models.db_models import Base

        _Base = Base
    return _Base


class DatabaseManager:
    """
    数据库管理器

    提供数据库连接和会话管理功能。

    使用示例:
    ```python
    # 初始化
    db = DatabaseManager("postgresql://user:pass@localhost/dbname")
    db.init_db()

    # 使用会话
    with db.session() as session:
        agent = session.query(AgentDefinitionModel).first()

    # 关闭连接
    db.close()
    ```
    """

    _instance: Optional["DatabaseManager"] = None

    def __init__(
        self,
        database_url: Optional[str] = None,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
    ):
        """
        初始化数据库管理器

        Args:
            database_url: 数据库连接 URL
            echo: 是否打印 SQL 语句
            pool_size: 连接池大小
            max_overflow: 最大溢出连接数
        """
        self.database_url = database_url or self._get_database_url()
        self.echo = echo
        self.pool_size = pool_size
        self.max_overflow = max_overflow

        self._engine = None
        self._session_factory = None

    @classmethod
    def get_instance(cls, **kwargs) -> "DatabaseManager":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例实例"""
        if cls._instance:
            cls._instance.close()
        cls._instance = None

    def _get_database_url(self) -> str:
        """从环境变量获取数据库 URL"""
        from urllib.parse import quote_plus

        # 优先使用完整 URL
        if os.environ.get("DATABASE_URL"):
            return os.environ["DATABASE_URL"]

        # 从组件构建 PostgreSQL URL
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "agent_framework")
        user = os.environ.get("POSTGRES_USER", "postgres")
        password = os.environ.get("POSTGRES_PASSWORD", "")

        if password:
            # URL 编码密码（处理特殊字符如 % @ 等）
            encoded_password = quote_plus(password)
            return f"postgresql://{user}:{encoded_password}@{host}:{port}/{db}"

        # 默认使用 SQLite（开发环境）
        logger.warning("未设置数据库 URL，使用 SQLite 本地数据库")
        return "sqlite:///./agent_framework.db"

    @property
    def engine(self):
        """获取数据库引擎"""
        if self._engine is None:
            self._create_engine()
        return self._engine

    def _create_engine(self):
        """创建数据库引擎"""
        is_sqlite = self.database_url.startswith("sqlite")

        if is_sqlite:
            # SQLite 使用 NullPool
            self._engine = create_engine(
                self.database_url,
                echo=self.echo,
                poolclass=NullPool,
                connect_args={"check_same_thread": False},
            )

            # 启用 SQLite 外键约束
            @event.listens_for(self._engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        else:
            # PostgreSQL 使用连接池
            self._engine = create_engine(
                self.database_url,
                echo=self.echo,
                poolclass=QueuePool,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_pre_ping=True,  # 自动重连
            )

        db_type = "SQLite" if is_sqlite else "PostgreSQL"
        logger.info("数据库引擎已创建: %s", db_type)

    @property
    def session_factory(self) -> sessionmaker:
        """获取会话工厂"""
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False,
            )
        return self._session_factory

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        获取数据库会话（上下文管理器）

        使用示例:
        ```python
        with db.session() as session:
            agent = session.query(AgentDefinitionModel).first()
            session.commit()
        ```
        """
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"数据库会话错误: {e}")
            raise
        finally:
            session.close()

    def init_db(self, drop_existing: bool = False) -> None:
        """
        初始化数据库表

        Args:
            drop_existing: 是否删除已存在的表
        """
        Base = get_base()
        if drop_existing:
            logger.warning("正在删除所有数据库表...")
            Base.metadata.drop_all(self.engine)

        logger.info("正在创建数据库表...")
        Base.metadata.create_all(self.engine)
        logger.info("数据库表创建完成")

    def close(self) -> None:
        """关闭数据库连接"""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("数据库连接已关闭")

    def health_check(self) -> bool:
        """检查数据库连接健康状态"""
        try:
            with self.session() as session:
                session.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"数据库健康检查失败: {e}")
            return False


# 便捷函数
def get_db() -> DatabaseManager:
    """获取全局数据库管理器实例"""
    return DatabaseManager.get_instance()


def init_database(
    database_url: Optional[str] = None, drop_existing: bool = False
) -> DatabaseManager:
    """
    初始化数据库

    Args:
        database_url: 数据库连接 URL
        drop_existing: 是否删除已存在的表

    Returns:
        DatabaseManager 实例
    """
    db = DatabaseManager.get_instance(database_url=database_url)
    db.init_db(drop_existing=drop_existing)
    return db


class AsyncDatabaseManager:
    """
    异步数据库管理器

    提供统一的异步数据库访问，支持：
    - SQLAlchemy AsyncSession (用于 ORM 操作)
    - Raw asyncpg Pool (用于低级操作，如检查点)

    使用示例:
    ```python
    # 初始化
    from storage.config import PostgreSQLConfig
    config = PostgreSQLConfig(host="localhost", database="mydb")
    db = AsyncDatabaseManager(config)
    await db.connect()

    # 使用 SQLAlchemy Session
    async with db.session() as session:
        result = await session.execute(select(Model))
        items = result.scalars().all()

    # 使用 raw asyncpg pool
    async with db.raw_pool.acquire() as conn:
        await conn.execute("INSERT INTO ...")

    # 关闭
    await db.close()
    ```
    """

    _instance: Optional["AsyncDatabaseManager"] = None

    def __init__(self, config: Optional["PostgreSQLConfig"] = None):
        """
        初始化异步数据库管理器

        Args:
            config: PostgreSQL 配置，如果不提供则从环境变量读取（支持 Docker 部署模式）
        """
        if config is None:
            # 使用 StorageConfig.from_env() 获取配置，它会根据 DEPLOY_MODE 选择正确的主机名
            from .config import StorageConfig
            config = StorageConfig.from_env().postgres
        
        self.config = config

        # SQLAlchemy async
        self._engine = None
        self._session_factory = None

        # Raw asyncpg pool
        self._raw_pool = None

        self._connected = False

    @classmethod
    def get_instance(
        cls, config: Optional["PostgreSQLConfig"] = None
    ) -> "AsyncDatabaseManager":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例实例"""
        if cls._instance:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(cls._instance.close())
                else:
                    loop.run_until_complete(cls._instance.close())
            except RuntimeError:
                pass
        cls._instance = None

    async def connect(self) -> None:
        """建立数据库连接"""
        if self._connected:
            return

        try:
            # 创建 SQLAlchemy async engine
            from sqlalchemy.ext.asyncio import (
                create_async_engine,
                async_sessionmaker,
                AsyncSession,
            )

            self._engine = create_async_engine(
                self.config.async_url,
                pool_size=self.config.pool_size,
                max_overflow=self.config.max_overflow,
                pool_pre_ping=True,
                echo=False,
            )

            self._session_factory = async_sessionmaker(
                bind=self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )

            # 创建 raw asyncpg pool
            try:
                import asyncpg

                self._raw_pool = await asyncpg.create_pool(
                    self.config.asyncpg_url,
                    min_size=1,
                    max_size=self.config.pool_size,
                )
            except ImportError:
                logger.warning("asyncpg 未安装，raw pool 不可用")
                self._raw_pool = None

            self._connected = True
            logger.info(
                "AsyncDatabaseManager 连接成功: %s:%s",
                self.config.host,
                self.config.port,
            )

        except Exception as e:
            logger.error(f"AsyncDatabaseManager 连接失败: {e}")
            raise

    async def close(self) -> None:
        """关闭所有连接"""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

        if self._raw_pool:
            await self._raw_pool.close()
            self._raw_pool = None

        self._connected = False
        logger.info("AsyncDatabaseManager 连接已关闭")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _ensure_connected(self):
        """确保已连接"""
        if not self._connected:
            raise RuntimeError("数据库未连接。请先调用 connect()")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator["AsyncSession", None]:
        """
        获取 SQLAlchemy 异步会话

        使用示例:
        ```python
        async with db.session() as session:
            result = await session.execute(select(Model))
            items = result.scalars().all()
            await session.commit()
        ```
        """
        self._ensure_connected()

        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"数据库会话错误: {e}")
            raise
        finally:
            await session.close()

    @property
    def raw_pool(self):
        """
        获取 raw asyncpg 连接池

        用于需要直接操作数据库的场景（如检查点存储）。

        使用示例:
        ```python
        async with db.raw_pool.acquire() as conn:
            await conn.execute("INSERT INTO checkpoints ...")
        ```
        """
        self._ensure_connected()
        if self._raw_pool is None:
            raise RuntimeError("asyncpg 未安装，raw pool 不可用")
        return self._raw_pool

    async def execute_raw(self, query: str, *args) -> Any:
        """
        执行 raw SQL

        Args:
            query: SQL 查询
            *args: 参数

        Returns:
            查询结果
        """
        self._ensure_connected()

        if self._raw_pool:
            async with self._raw_pool.acquire() as conn:
                return await conn.execute(query, *args)
        else:
            # 回退到 SQLAlchemy
            async with self.session() as session:
                result = await session.execute(text(query), args)
                return result

    async def fetch_one(self, query: str, *args) -> Optional[Any]:
        """执行查询并返回单行"""
        self._ensure_connected()

        if self._raw_pool:
            async with self._raw_pool.acquire() as conn:
                return await conn.fetchrow(query, *args)
        else:
            async with self.session() as session:
                result = await session.execute(text(query), args)
                return result.fetchone()

    async def fetch_all(self, query: str, *args) -> list:
        """执行查询并返回所有行"""
        self._ensure_connected()

        if self._raw_pool:
            async with self._raw_pool.acquire() as conn:
                return await conn.fetch(query, *args)
        else:
            async with self.session() as session:
                result = await session.execute(text(query), args)
                return result.fetchall()

    async def init_db(self, drop_existing: bool = False) -> None:
        """
        初始化数据库表

        Args:
            drop_existing: 是否删除已存在的表
        """
        self._ensure_connected()
        Base = get_base()

        async with self._engine.begin() as conn:
            if drop_existing:
                logger.warning("正在删除所有数据库表...")
                await conn.run_sync(Base.metadata.drop_all)

            logger.info("正在创建数据库表...")
            await conn.run_sync(Base.metadata.create_all)
            logger.info("数据库表创建完成")

    async def health_check(self) -> bool:
        """检查数据库连接健康状态"""
        try:
            self._ensure_connected()
            async with self.session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"数据库健康检查失败: {e}")
            return False


# 全局异步数据库管理器实例
_async_db: Optional[AsyncDatabaseManager] = None


async def get_async_db(
    config: Optional["PostgreSQLConfig"] = None,
) -> AsyncDatabaseManager:
    """
    获取全局异步数据库管理器实例

    Args:
        config: PostgreSQL 配置

    Returns:
        AsyncDatabaseManager 实例
    """
    global _async_db
    if _async_db is None:
        _async_db = AsyncDatabaseManager(config)
        await _async_db.connect()
    return _async_db


async def close_async_db() -> None:
    """关闭全局异步数据库连接"""
    global _async_db
    if _async_db:
        await _async_db.close()
        _async_db = None


# 导出
__all__ = [
    "DatabaseManager",
    "AsyncDatabaseManager",
    "get_db",
    "get_async_db",
    "close_async_db",
    "init_database",
]

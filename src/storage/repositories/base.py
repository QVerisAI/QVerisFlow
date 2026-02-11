"""
基础仓库类

提供通用的 CRUD 操作和数据库会话管理。
"""

from typing import Generic, TypeVar, Optional, List, Dict, Any, Type
from datetime import datetime
from contextlib import asynccontextmanager
import uuid

from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeMeta

from src.utils.logger import get_logger

logger = get_logger()

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """
    基础仓库类

    提供通用的 CRUD 操作，所有具体仓库都应继承此类。

    类型参数:
        T: SQLAlchemy 模型类型
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        model_class: Type[T],
    ):
        """
        初始化仓库

        Args:
            session_factory: 异步会话工厂
            model_class: 模型类
        """
        self.session_factory = session_factory
        self.model_class = model_class

    @asynccontextmanager
    async def get_session(self):
        """获取数据库会话"""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def create(self, data: Dict[str, Any], **kwargs) -> T:
        """
        创建记录

        Args:
            data: 记录数据
            **kwargs: 额外属性

        Returns:
            创建的模型实例
        """
        async with self.get_session() as session:
            # 生成 ID（如果未提供）
            if "id" not in data:
                data["id"] = self._generate_id()

            instance = self.model_class(**data, **kwargs)
            session.add(instance)
            await session.flush()
            await session.refresh(instance)

            logger.debug(f"创建记录: {self.model_class.__name__} id={data['id']}")
            return instance

    async def get_by_id(self, id: str) -> Optional[T]:
        """
        根据 ID 获取记录

        Args:
            id: 记录 ID

        Returns:
            模型实例，如果不存在则返回 None
        """
        async with self.get_session() as session:
            result = await session.execute(
                select(self.model_class).where(self.model_class.id == id)
            )
            return result.scalar_one_or_none()

    async def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
        order_by: str = None,
        order_desc: bool = True,
    ) -> List[T]:
        """
        获取所有记录

        Args:
            limit: 返回数量限制
            offset: 偏移量
            order_by: 排序字段
            order_desc: 是否降序

        Returns:
            模型实例列表
        """
        async with self.get_session() as session:
            query = select(self.model_class)

            # 排序
            if order_by and hasattr(self.model_class, order_by):
                order_col = getattr(self.model_class, order_by)
                if order_desc:
                    query = query.order_by(order_col.desc())
                else:
                    query = query.order_by(order_col.asc())

            # 分页
            query = query.offset(offset).limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def update(self, id: str, data: Dict[str, Any]) -> Optional[T]:
        """
        更新记录

        Args:
            id: 记录 ID
            data: 更新数据

        Returns:
            更新后的模型实例
        """
        async with self.get_session() as session:
            # 设置更新时间
            if hasattr(self.model_class, "updated_at"):
                data["updated_at"] = datetime.utcnow()

            await session.execute(
                update(self.model_class).where(self.model_class.id == id).values(**data)
            )

            # 获取更新后的实例
            result = await session.execute(
                select(self.model_class).where(self.model_class.id == id)
            )
            instance = result.scalar_one_or_none()

            if instance:
                logger.debug(f"更新记录: {self.model_class.__name__} id={id}")

            return instance

    async def delete(self, id: str) -> bool:
        """
        删除记录

        Args:
            id: 记录 ID

        Returns:
            是否删除成功
        """
        async with self.get_session() as session:
            result = await session.execute(
                delete(self.model_class).where(self.model_class.id == id)
            )

            deleted = result.rowcount > 0
            if deleted:
                logger.debug(f"删除记录: {self.model_class.__name__} id={id}")

            return deleted

    async def count(self, filters: Dict[str, Any] = None) -> int:
        """
        统计记录数量

        Args:
            filters: 过滤条件

        Returns:
            记录数量
        """
        from sqlalchemy import func

        async with self.get_session() as session:
            query = select(func.count()).select_from(self.model_class)

            if filters:
                for key, value in filters.items():
                    if hasattr(self.model_class, key):
                        query = query.where(getattr(self.model_class, key) == value)

            result = await session.execute(query)
            return result.scalar() or 0

    async def exists(self, id: str) -> bool:
        """检查记录是否存在"""
        instance = await self.get_by_id(id)
        return instance is not None

    def _generate_id(self) -> str:
        """生成唯一 ID"""
        return uuid.uuid4().hex


class DatabaseManager:
    """
    数据库管理器

    负责数据库连接和会话管理。
    """

    def __init__(
        self,
        database_url: str,
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
        self.database_url = database_url

        # 创建异步引擎
        self.engine = create_async_engine(
            database_url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )

        # 创建会话工厂
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def create_tables(self):
        """创建所有表"""
        from ..models.db_models import Base

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info("数据库表创建完成")

    async def drop_tables(self):
        """删除所有表（谨慎使用）"""
        from ..models.db_models import Base

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

        logger.warning("数据库表已删除")

    async def close(self):
        """关闭数据库连接"""
        await self.engine.dispose()
        logger.info("数据库连接已关闭")

    def get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """获取会话工厂"""
        return self.session_factory


# 导出
__all__ = [
    "BaseRepository",
    "DatabaseManager",
]

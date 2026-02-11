"""
PostgreSQL 检查点存储

使用 PostgreSQL 作为 LangGraph 检查点的存储后端。
支持异步操作，同时提供同步包装供 LangGraph 使用。
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional

from .base import BaseCheckpointSaver
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PostgresCheckpointSaver(BaseCheckpointSaver):
    """
    PostgreSQL 检查点存储

    使用注入的 AsyncDatabaseManager 实现检查点存储。

    特点：
    - 持久化存储
    - 支持复杂查询
    - 适合长期保存和审计

    用法:
        ```python
        from storage.database import AsyncDatabaseManager
        from storage.config import PostgreSQLConfig
        from storage.checkpointers import PostgresCheckpointSaver

        config = PostgreSQLConfig(host="localhost", database="mydb")
        db = AsyncDatabaseManager(config)
        await db.connect()

        saver = PostgresCheckpointSaver(
            db_manager=db,
            table_name="langgraph_checkpoints",
        )
        await saver.setup()

        # 与 LangGraph 集成
        graph = builder.compile(checkpointer=saver)
        ```
    """

    def __init__(
        self,
        db_manager: Optional["AsyncDatabaseManager"] = None,
        postgres_url: Optional[str] = None,
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres",
        password: str = "",
        database: str = "agent_framework",
        table_name: str = "langgraph_checkpoints",
        serializer: str = "json",
    ):
        """
        初始化 PostgreSQL 检查点存储

        Args:
            db_manager: 已有的 AsyncDatabaseManager 实例（推荐，依赖注入）
            postgres_url: PostgreSQL URL（当 db_manager 未提供时使用）
            host: 主机
            port: 端口
            user: 用户名
            password: 密码
            database: 数据库名
            table_name: 表名
            serializer: 序列化方式
        """
        self.table_name = table_name
        self.serializer = serializer

        # 使用注入的管理器或创建新的
        if db_manager is not None:
            self._db = db_manager
            self._own_db = False
        else:
            # 延迟导入以避免循环依赖
            from ..config import PostgreSQLConfig
            from ..database import AsyncDatabaseManager

            config = PostgreSQLConfig(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
            )
            self._db = AsyncDatabaseManager(config)
            self._own_db = True

        # 事件循环缓存
        self._loop = None
        self._setup_done = False

        logger.info(f"PostgreSQL 检查点存储初始化: table={table_name}")

    def _get_loop(self):
        """获取事件循环"""
        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            # 没有运行中的事件循环，创建新的
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            return self._loop

    def _run_async(self, coro):
        """运行异步协程（同步包装）"""
        loop = self._get_loop()
        if loop.is_running():
            # 在已运行的循环中，创建任务
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)

    async def setup(self):
        """
        初始化数据库表结构

        创建检查点存储表（如果不存在）。
        """
        if self._own_db:
            await self._db.connect()

        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            thread_id VARCHAR(256) NOT NULL,
            checkpoint_id VARCHAR(64) NOT NULL,
            checkpoint_data JSONB NOT NULL,
            metadata JSONB DEFAULT '{{}}',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            
            UNIQUE(thread_id, checkpoint_id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_thread_id 
            ON {self.table_name} (thread_id);
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_created_at 
            ON {self.table_name} (created_at DESC);
        """

        await self._db.execute_raw(create_table_sql)
        self._setup_done = True

        logger.info(f"PostgreSQL 检查点表已创建: {self.table_name}")

    def _serialize(self, data: Dict[str, Any]) -> str:
        """序列化数据为 JSON 字符串"""
        return json.dumps(data, default=str)

    def _deserialize(self, data) -> Dict[str, Any]:
        """反序列化 JSON 字符串"""
        if isinstance(data, str):
            return json.loads(data)
        if isinstance(data, dict):
            return data
        return data

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """保存检查点（同步包装）"""
        return self._run_async(self.aput(config, checkpoint, metadata))

    async def aput(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """异步保存检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        # 添加时间戳
        data = checkpoint.copy()
        data["__checkpoint_id__"] = checkpoint_id
        data["__timestamp__"] = datetime.now().isoformat()

        upsert_sql = f"""
        INSERT INTO {self.table_name} (thread_id, checkpoint_id, checkpoint_data, metadata)
        VALUES ($1, $2, $3::jsonb, $4::jsonb)
        ON CONFLICT (thread_id, checkpoint_id) 
        DO UPDATE SET checkpoint_data = $3::jsonb, metadata = $4::jsonb
        """

        await self._db.execute_raw(
            upsert_sql,
            thread_id,
            checkpoint_id,
            self._serialize(data),
            self._serialize(metadata or {}),
        )

        logger.debug(
            f"保存检查点: thread_id={thread_id}, checkpoint_id={checkpoint_id}"
        )

        return self._update_config_with_checkpoint_id(config, checkpoint_id)

    def get(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """获取检查点（同步包装）"""
        return self._run_async(self.aget(config))

    async def aget(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """异步获取检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._get_checkpoint_id(config)

        if checkpoint_id:
            query = f"""
            SELECT checkpoint_data, metadata FROM {self.table_name}
            WHERE thread_id = $1 AND checkpoint_id = $2
            """
            params = (thread_id, checkpoint_id)
        else:
            query = f"""
            SELECT checkpoint_data, metadata FROM {self.table_name}
            WHERE thread_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """
            params = (thread_id,)

        row = await self._db.fetch_one(query, *params)

        if row is None:
            return None

        data = self._deserialize(row["checkpoint_data"])
        data["__metadata__"] = self._deserialize(row["metadata"])

        return data

    def list(
        self,
        config: Dict[str, Any],
        limit: int = 10,
        before: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """列出检查点（同步包装）"""
        results = self._run_async(self.alist(config, limit, before))
        return iter(results)

    async def alist(
        self,
        config: Dict[str, Any],
        limit: int = 10,
        before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """异步列出检查点"""
        thread_id = self._get_thread_id(config)

        if before:
            query = f"""
            SELECT checkpoint_data, metadata FROM {self.table_name}
            WHERE thread_id = $1 AND checkpoint_id < $2
            ORDER BY created_at DESC
            LIMIT $3
            """
            params = (thread_id, before, limit)
        else:
            query = f"""
            SELECT checkpoint_data, metadata FROM {self.table_name}
            WHERE thread_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """
            params = (thread_id, limit)

        rows = await self._db.fetch_all(query, *params)

        results = []
        for row in rows:
            data = self._deserialize(row["checkpoint_data"])
            data["__metadata__"] = self._deserialize(row["metadata"])
            results.append(data)

        return results

    async def delete(self, config: Dict[str, Any]) -> bool:
        """删除检查点"""
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._get_checkpoint_id(config)

        if checkpoint_id:
            query = f"""
            DELETE FROM {self.table_name}
            WHERE thread_id = $1 AND checkpoint_id = $2
            """
            params = (thread_id, checkpoint_id)
        else:
            query = f"""
            DELETE FROM {self.table_name}
            WHERE thread_id = $1
            """
            params = (thread_id,)

        result = await self._db.execute_raw(query, *params)
        return "DELETE" in str(result) if result else False

    async def cleanup(
        self,
        older_than: timedelta = timedelta(days=7),
    ) -> int:
        """
        清理过期检查点

        Args:
            older_than: 清理多久之前的检查点

        Returns:
            删除的记录数
        """
        cutoff = datetime.now() - older_than

        query = f"""
        DELETE FROM {self.table_name}
        WHERE created_at < $1
        """

        result = await self._db.execute_raw(query, cutoff)
        deleted = int(result.split()[-1]) if result else 0
        logger.info(f"清理了 {deleted} 条过期检查点")

        return deleted

    async def close(self):
        """关闭连接（仅当自己创建的数据库管理器）"""
        if self._own_db:
            await self._db.close()


__all__ = ["PostgresCheckpointSaver"]

"""
追踪存储后端

提供将追踪数据持久化到不同存储后端的实现。
"""

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .models import SpanRecord, ExecutionTrace, TraceFilters, ExecutionStatus
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from ..storage.database import AsyncDatabaseManager

logger = get_logger(__name__)


class TraceStorage(ABC):
    """
    追踪存储抽象基类

    定义追踪存储的标准接口。
    """

    @abstractmethod
    async def save_span(self, span: SpanRecord) -> None:
        """保存单个 Span"""
        pass

    @abstractmethod
    async def save_trace(self, trace: ExecutionTrace) -> None:
        """保存完整追踪"""
        pass

    @abstractmethod
    async def get_trace(self, trace_id: str) -> Optional[ExecutionTrace]:
        """获取追踪"""
        pass

    @abstractmethod
    async def list_traces(self, filters: TraceFilters) -> List[ExecutionTrace]:
        """列出追踪"""
        pass

    @abstractmethod
    async def delete_trace(self, trace_id: str) -> bool:
        """删除追踪"""
        pass


class FileTraceStorage(TraceStorage):
    """
    文件系统追踪存储

    将追踪数据存储到本地文件系统。

    目录结构：
    traces/
    ├── index.json              # 索引文件
    ├── 2024/
    │   ├── 01/
    │   │   ├── 01/
    │   │   │   ├── trace_xxx.json
    │   │   │   └── trace_yyy.json
    └── by_task/                # 按任务索引
        └── task_001/
            └── traces.json
    """

    def __init__(self, base_path: str = "./traces"):
        """
        初始化文件追踪存储

        Args:
            base_path: 存储目录
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._index_path = self.base_path / "index.json"
        self._ensure_index()

        logger.info(f"文件追踪存储初始化: {self.base_path}")

    def _ensure_index(self) -> None:
        """确保索引文件存在"""
        if not self._index_path.exists():
            self._save_index({"traces": {}, "updated_at": datetime.now().isoformat()})

    def _load_index(self) -> Dict[str, Any]:
        """加载索引"""
        with open(self._index_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_index(self, index: Dict[str, Any]) -> None:
        """保存索引"""
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def _get_trace_path(self, trace: ExecutionTrace) -> Path:
        """获取追踪文件路径"""
        date = trace.started_at or datetime.now()
        dir_path = (
            self.base_path
            / str(date.year)
            / f"{date.month:02d}"
            / f"{date.day:02d}"
        )
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / f"trace_{trace.trace_id}.json"

    def _serialize_dates(self, data: Any) -> Any:
        """序列化日期"""
        if isinstance(data, datetime):
            return data.isoformat()
        elif isinstance(data, dict):
            return {k: self._serialize_dates(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._serialize_dates(v) for v in data]
        return data

    def _deserialize_dates(self, data: Any) -> Any:
        """反序列化日期"""
        if isinstance(data, str):
            try:
                return datetime.fromisoformat(data)
            except ValueError:
                return data
        elif isinstance(data, dict):
            return {k: self._deserialize_dates(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._deserialize_dates(v) for v in data]
        return data

    async def save_span(self, span: SpanRecord) -> None:
        """保存单个 Span"""
        # 将 Span 保存到按 trace_id 组织的文件中
        span_dir = self.base_path / "spans" / span.trace_id
        span_dir.mkdir(parents=True, exist_ok=True)

        span_file = span_dir / f"{span.span_id}.json"
        with open(span_file, "w", encoding="utf-8") as f:
            json.dump(span.to_dict(), f, ensure_ascii=False, indent=2)

    async def save_trace(self, trace: ExecutionTrace) -> None:
        """保存完整追踪"""
        # 保存追踪文件
        trace_path = self._get_trace_path(trace)
        trace_data = self._serialize_dates(trace.to_dict())

        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace_data, f, ensure_ascii=False, indent=2)

        # 更新索引
        index = self._load_index()
        index["traces"][trace.trace_id] = {
            "task_id": trace.task_id,
            "agent_id": trace.agent_id,
            "status": trace.status.value,
            "started_at": trace.started_at.isoformat() if trace.started_at else None,
            "path": str(trace_path.relative_to(self.base_path)),
        }
        index["updated_at"] = datetime.now().isoformat()
        self._save_index(index)

        # 更新任务索引
        await self._update_task_index(trace)

        logger.debug(f"保存追踪: {trace.trace_id}")

    async def _update_task_index(self, trace: ExecutionTrace) -> None:
        """更新任务索引"""
        task_dir = self.base_path / "by_task" / trace.task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        task_index_path = task_dir / "traces.json"

        if task_index_path.exists():
            with open(task_index_path, "r", encoding="utf-8") as f:
                task_index = json.load(f)
        else:
            task_index = {"task_id": trace.task_id, "traces": []}

        # 添加或更新追踪
        trace_entry = {
            "trace_id": trace.trace_id,
            "agent_id": trace.agent_id,
            "status": trace.status.value,
            "started_at": trace.started_at.isoformat() if trace.started_at else None,
            "completed_at": trace.completed_at.isoformat()
            if trace.completed_at
            else None,
        }

        # 检查是否已存在
        existing = [
            t for t in task_index["traces"] if t["trace_id"] == trace.trace_id
        ]
        if existing:
            task_index["traces"].remove(existing[0])
        task_index["traces"].append(trace_entry)

        with open(task_index_path, "w", encoding="utf-8") as f:
            json.dump(task_index, f, ensure_ascii=False, indent=2)

    async def get_trace(self, trace_id: str) -> Optional[ExecutionTrace]:
        """获取追踪"""
        index = self._load_index()

        if trace_id not in index["traces"]:
            return None

        trace_info = index["traces"][trace_id]
        trace_path = self.base_path / trace_info["path"]

        if not trace_path.exists():
            return None

        with open(trace_path, "r", encoding="utf-8") as f:
            trace_data = json.load(f)

        # 转换为 ExecutionTrace 对象
        return self._dict_to_trace(trace_data)

    def _dict_to_trace(self, data: Dict[str, Any]) -> ExecutionTrace:
        """从字典创建 ExecutionTrace"""
        trace = ExecutionTrace(
            trace_id=data["trace_id"],
            task_id=data.get("task_id", ""),
            agent_id=data.get("agent_id", ""),
            workflow_id=data.get("workflow_id"),
            parent_trace_id=data.get("parent_trace_id"),
            input_data=data.get("input_data", {}),
            task_description=data.get("task_description", ""),
            output_data=data.get("output_data"),
            output_files=data.get("output_files", []),
            status=ExecutionStatus(data.get("status", "pending")),
            started_at=datetime.fromisoformat(data["started_at"])
            if data.get("started_at")
            else None,
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
            duration_ms=data.get("duration_ms"),
            summary=data.get("summary", {}),
            error=data.get("error"),
            error_stack=data.get("error_stack"),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            workspace_path=data.get("workspace_path"),
        )

        # 转换 spans
        for span_data in data.get("spans", []):
            trace.spans.append(SpanRecord.from_dict(span_data))

        return trace

    async def list_traces(self, filters: TraceFilters) -> List[ExecutionTrace]:
        """列出追踪"""
        index = self._load_index()

        # 过滤
        filtered = []
        for trace_id, info in index["traces"].items():
            if filters.task_id and info.get("task_id") != filters.task_id:
                continue
            if filters.agent_id and info.get("agent_id") != filters.agent_id:
                continue
            if filters.status and info.get("status") != filters.status.value:
                continue
            if filters.start_time and info.get("started_at"):
                trace_time = datetime.fromisoformat(info["started_at"])
                if trace_time < filters.start_time:
                    continue
            if filters.end_time and info.get("started_at"):
                trace_time = datetime.fromisoformat(info["started_at"])
                if trace_time > filters.end_time:
                    continue

            filtered.append(trace_id)

        # 排序（按时间倒序）
        filtered.sort(
            key=lambda x: index["traces"][x].get("started_at", ""), reverse=True
        )

        # 分页
        paginated = filtered[filters.offset : filters.offset + filters.limit]

        # 加载完整追踪
        traces = []
        for trace_id in paginated:
            trace = await self.get_trace(trace_id)
            if trace:
                traces.append(trace)

        return traces

    async def delete_trace(self, trace_id: str) -> bool:
        """删除追踪"""
        index = self._load_index()

        if trace_id not in index["traces"]:
            return False

        trace_info = index["traces"][trace_id]
        trace_path = self.base_path / trace_info["path"]

        # 删除文件
        if trace_path.exists():
            trace_path.unlink()

        # 更新索引
        del index["traces"][trace_id]
        index["updated_at"] = datetime.now().isoformat()
        self._save_index(index)

        return True


class DatabaseTraceStorage(TraceStorage):
    """
    数据库追踪存储

    将追踪数据存储到 PostgreSQL。

    使用 AsyncDatabaseManager 进行数据库操作。
    """

    def __init__(
        self,
        db_manager: "AsyncDatabaseManager",
        table_prefix: str = "trace_",
    ):
        """
        初始化数据库追踪存储

        Args:
            db_manager: 异步数据库管理器
            table_prefix: 表名前缀
        """
        self.db = db_manager
        self.table_prefix = table_prefix
        self._setup_done = False

        logger.info(f"数据库追踪存储初始化: prefix={table_prefix}")

    async def setup(self) -> None:
        """初始化数据库表"""
        if self._setup_done:
            return

        # 创建表
        create_tables_sql = f"""
        -- 执行追踪主表
        CREATE TABLE IF NOT EXISTS {self.table_prefix}executions (
            id SERIAL PRIMARY KEY,
            trace_id VARCHAR(64) UNIQUE NOT NULL,
            task_id VARCHAR(256),
            agent_id VARCHAR(256),
            workflow_id VARCHAR(256),
            parent_trace_id VARCHAR(64),
            input_data JSONB DEFAULT '{{}}',
            task_description TEXT,
            output_data JSONB,
            status VARCHAR(32) DEFAULT 'pending',
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            duration_ms INTEGER,
            summary JSONB DEFAULT '{{}}',
            error TEXT,
            error_stack TEXT,
            tags TEXT[] DEFAULT ARRAY[]::TEXT[],
            metadata JSONB DEFAULT '{{}}',
            workspace_path TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        -- Spans 表
        CREATE TABLE IF NOT EXISTS {self.table_prefix}spans (
            id SERIAL PRIMARY KEY,
            span_id VARCHAR(64) NOT NULL,
            trace_id VARCHAR(64) NOT NULL,
            parent_span_id VARCHAR(64),
            name VARCHAR(256),
            start_time TIMESTAMP WITH TIME ZONE,
            end_time TIMESTAMP WITH TIME ZONE,
            duration_ms FLOAT,
            status VARCHAR(32),
            attributes JSONB DEFAULT '{{}}',
            events JSONB DEFAULT '[]',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        -- 索引
        CREATE INDEX IF NOT EXISTS idx_{self.table_prefix}executions_task_id
            ON {self.table_prefix}executions (task_id);
        CREATE INDEX IF NOT EXISTS idx_{self.table_prefix}executions_agent_id
            ON {self.table_prefix}executions (agent_id);
        CREATE INDEX IF NOT EXISTS idx_{self.table_prefix}executions_status
            ON {self.table_prefix}executions (status);
        CREATE INDEX IF NOT EXISTS idx_{self.table_prefix}executions_started_at
            ON {self.table_prefix}executions (started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_{self.table_prefix}spans_trace_id
            ON {self.table_prefix}spans (trace_id);
        """

        await self.db.execute_raw(create_tables_sql)
        self._setup_done = True

        logger.info("数据库追踪表已创建")

    async def save_span(self, span: SpanRecord) -> None:
        """保存单个 Span"""
        await self.setup()

        insert_sql = f"""
        INSERT INTO {self.table_prefix}spans 
        (span_id, trace_id, parent_span_id, name, start_time, end_time, 
         duration_ms, status, attributes, events)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb)
        ON CONFLICT (span_id) DO UPDATE SET
            end_time = EXCLUDED.end_time,
            duration_ms = EXCLUDED.duration_ms,
            status = EXCLUDED.status,
            attributes = EXCLUDED.attributes,
            events = EXCLUDED.events
        """

        await self.db.execute_raw(
            insert_sql,
            span.span_id,
            span.trace_id,
            span.parent_span_id,
            span.name,
            span.start_time,
            span.end_time,
            span.duration_ms,
            span.status,
            json.dumps(span.attributes),
            json.dumps(span.events),
        )

    async def save_trace(self, trace: ExecutionTrace) -> None:
        """保存完整追踪"""
        await self.setup()

        upsert_sql = f"""
        INSERT INTO {self.table_prefix}executions 
        (trace_id, task_id, agent_id, workflow_id, parent_trace_id,
         input_data, task_description, output_data, status,
         started_at, completed_at, duration_ms, summary,
         error, error_stack, tags, metadata, workspace_path)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8::jsonb, $9,
                $10, $11, $12, $13::jsonb, $14, $15, $16, $17::jsonb, $18)
        ON CONFLICT (trace_id) DO UPDATE SET
            output_data = EXCLUDED.output_data,
            status = EXCLUDED.status,
            completed_at = EXCLUDED.completed_at,
            duration_ms = EXCLUDED.duration_ms,
            summary = EXCLUDED.summary,
            error = EXCLUDED.error,
            error_stack = EXCLUDED.error_stack
        """

        await self.db.execute_raw(
            upsert_sql,
            trace.trace_id,
            trace.task_id,
            trace.agent_id,
            trace.workflow_id,
            trace.parent_trace_id,
            json.dumps(trace.input_data),
            trace.task_description,
            json.dumps(trace.output_data) if trace.output_data else None,
            trace.status.value,
            trace.started_at,
            trace.completed_at,
            trace.duration_ms,
            json.dumps(trace.summary),
            trace.error,
            trace.error_stack,
            trace.tags,
            json.dumps(trace.metadata),
            trace.workspace_path,
        )

        # 保存 spans
        for span in trace.spans:
            await self.save_span(span)

        logger.debug(f"保存追踪到数据库: {trace.trace_id}")

    async def get_trace(self, trace_id: str) -> Optional[ExecutionTrace]:
        """获取追踪"""
        await self.setup()

        query = f"""
        SELECT * FROM {self.table_prefix}executions
        WHERE trace_id = $1
        """

        row = await self.db.fetch_one(query, trace_id)
        if row is None:
            return None

        trace = self._row_to_trace(row)

        # 加载 spans
        spans_query = f"""
        SELECT * FROM {self.table_prefix}spans
        WHERE trace_id = $1
        ORDER BY start_time
        """
        span_rows = await self.db.fetch_all(spans_query, trace_id)

        for span_row in span_rows:
            trace.spans.append(self._row_to_span(span_row))

        return trace

    def _row_to_trace(self, row) -> ExecutionTrace:
        """从数据库行转换为 ExecutionTrace"""
        return ExecutionTrace(
            trace_id=row["trace_id"],
            task_id=row.get("task_id", ""),
            agent_id=row.get("agent_id", ""),
            workflow_id=row.get("workflow_id"),
            parent_trace_id=row.get("parent_trace_id"),
            input_data=row.get("input_data") or {},
            task_description=row.get("task_description", ""),
            output_data=row.get("output_data"),
            status=ExecutionStatus(row.get("status", "pending")),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            duration_ms=row.get("duration_ms"),
            summary=row.get("summary") or {},
            error=row.get("error"),
            error_stack=row.get("error_stack"),
            tags=row.get("tags") or [],
            metadata=row.get("metadata") or {},
            workspace_path=row.get("workspace_path"),
        )

    def _row_to_span(self, row) -> SpanRecord:
        """从数据库行转换为 SpanRecord"""
        return SpanRecord(
            span_id=row["span_id"],
            trace_id=row["trace_id"],
            parent_span_id=row.get("parent_span_id"),
            name=row.get("name", ""),
            start_time=row.get("start_time"),
            end_time=row.get("end_time"),
            duration_ms=row.get("duration_ms", 0),
            status=row.get("status", "ok"),
            attributes=row.get("attributes") or {},
            events=row.get("events") or [],
        )

    async def list_traces(self, filters: TraceFilters) -> List[ExecutionTrace]:
        """列出追踪"""
        await self.setup()

        conditions = []
        params = []
        param_idx = 1

        if filters.task_id:
            conditions.append(f"task_id = ${param_idx}")
            params.append(filters.task_id)
            param_idx += 1

        if filters.agent_id:
            conditions.append(f"agent_id = ${param_idx}")
            params.append(filters.agent_id)
            param_idx += 1

        if filters.status:
            conditions.append(f"status = ${param_idx}")
            params.append(filters.status.value)
            param_idx += 1

        if filters.start_time:
            conditions.append(f"started_at >= ${param_idx}")
            params.append(filters.start_time)
            param_idx += 1

        if filters.end_time:
            conditions.append(f"started_at <= ${param_idx}")
            params.append(filters.end_time)
            param_idx += 1

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
        SELECT * FROM {self.table_prefix}executions
        WHERE {where_clause}
        ORDER BY started_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([filters.limit, filters.offset])

        rows = await self.db.fetch_all(query, *params)

        traces = []
        for row in rows:
            traces.append(self._row_to_trace(row))

        return traces

    async def delete_trace(self, trace_id: str) -> bool:
        """删除追踪"""
        await self.setup()

        # 删除 spans
        await self.db.execute_raw(
            f"DELETE FROM {self.table_prefix}spans WHERE trace_id = $1",
            trace_id,
        )

        # 删除追踪
        result = await self.db.execute_raw(
            f"DELETE FROM {self.table_prefix}executions WHERE trace_id = $1",
            trace_id,
        )

        return "DELETE" in str(result) if result else False


class TraceStorageFactory:
    """追踪存储工厂"""

    @staticmethod
    def create_file_storage(path: str = "./traces") -> FileTraceStorage:
        """创建文件追踪存储"""
        return FileTraceStorage(path)

    @staticmethod
    def create_database_storage(
        db_manager: "AsyncDatabaseManager",
        table_prefix: str = "trace_",
    ) -> DatabaseTraceStorage:
        """创建数据库追踪存储"""
        return DatabaseTraceStorage(db_manager, table_prefix)

    @staticmethod
    def from_config(config: "TraceStorageConfig") -> TraceStorage:
        """从配置创建追踪存储"""
        if config.type == "file":
            return FileTraceStorage(config.file_path)
        elif config.type == "database":
            # 需要传入 db_manager
            raise ValueError("数据库存储需要提供 db_manager")
        else:
            return FileTraceStorage(config.file_path)


__all__ = [
    "TraceStorage",
    "FileTraceStorage",
    "DatabaseTraceStorage",
    "TraceStorageFactory",
]

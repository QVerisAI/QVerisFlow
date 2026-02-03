# 任务文件持久化存储设计

> **存储介质**: 本模块的文件存储基于 OSS（MinIO/阿里云 OSS），任务元数据存储于 PostgreSQL，详见 [11_storage_infrastructure.md](./11_storage_infrastructure.md)

## 1. 设计目标

任务文件持久化存储是一个全局的任务和文件管理系统，提供：

| 目标 | 说明 |
|------|------|
| **任务全生命周期管理** | 从创建到归档的完整任务管理 |
| **文件统一存储** | 所有任务文件的集中管理和访问 |
| **跨任务引用** | 支持任务间共享文件和上下文 |
| **分层存储** | 热/温/冷数据分层，优化存储成本 |
| **版本控制** | 重要文件的版本管理 |
| **智能清理** | 自动清理过期数据 |

### 1.1 存储架构

```
┌─────────────────────────────────────────────────────────────┐
│                    文件存储架构                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  PostgreSQL (任务元数据)              OSS (文件内容)         │
│  ├── tasks                            ├── workspaces/       │
│  │   ├── task_id                      │   └── {task_id}/    │
│  │   ├── status                       │       ├── input/    │
│  │   ├── workspace_oss_path           │       ├── output/   │
│  │   └── files_summary                │       ├── scratch/  │
│  ├── task_sub_tasks                   │       ├── context/  │
│  │   (父子任务关系)                   │       └── logs/     │
│  └── ...                              ├── shared/           │
│                                       │   ├── templates/    │
│                                       │   └── knowledge/    │
│                                       └── archives/         │
│                                           └── {year}/{Q}/   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**存储策略：**
- **任务元数据** → PostgreSQL：状态、索引、关联关系
- **工作空间文件** → OSS：所有实际文件内容
- **共享资源** → OSS：模板、知识库
- **归档文件** → OSS (低频存储)：压缩包

---

## 2. 存储架构

### 2.1 全局目录结构

```
storage/
├── config/                         # 全局配置
│   ├── storage_config.yaml         # 存储配置
│   └── retention_policy.yaml       # 保留策略
│
├── tasks/                          # 任务存储（热数据）
│   ├── index.json                  # 任务索引
│   ├── active/                     # 活跃任务
│   │   ├── task_001/               # = 单个工作空间
│   │   │   ├── metadata.json       # 任务元数据
│   │   │   ├── input/
│   │   │   ├── output/
│   │   │   ├── scratch/
│   │   │   ├── context/
│   │   │   ├── logs/
│   │   │   ├── state/
│   │   │   └── sub_agents/
│   │   └── task_002/
│   ├── completed/                  # 已完成任务（温数据）
│   │   └── 2024/
│   │       └── 01/
│   │           └── task_xxx/
│   └── archived/                   # 归档任务（冷数据）
│       └── 2024/
│           └── Q1/
│               └── task_xxx.tar.gz
│
├── shared/                         # 共享资源
│   ├── templates/                  # 模板文件
│   │   ├── prompts/                # Prompt 模板
│   │   ├── reports/                # 报告模板
│   │   └── workflows/              # 工作流模板
│   ├── knowledge/                  # 知识库
│   │   ├── domain/                 # 领域知识
│   │   └── reference/              # 参考资料
│   └── cache/                      # 缓存
│       ├── llm_cache/              # LLM 响应缓存
│       └── tool_cache/             # 工具结果缓存
│
├── outputs/                        # 全局输出（便于访问）
│   ├── reports/                    # 按类型
│   │   └── 2024-01-01_task_001_report.md
│   ├── data/
│   │   └── 2024-01-01_task_001_data.json
│   └── artifacts/
│       └── 2024-01-01_task_001_chart.png
│
├── traces/                         # 执行追踪（关联 09_data_persistence）
│   └── ...
│
└── backups/                        # 备份
    └── daily/
        └── 2024-01-01.tar.gz
```

### 2.2 任务元数据结构

```json
{
  "task_id": "task_001",
  "name": "贵州茅台投资分析",
  "description": "分析贵州茅台的投资价值",
  
  "status": "completed",
  "priority": "high",
  
  "created_at": "2024-01-01T10:00:00Z",
  "started_at": "2024-01-01T10:00:05Z",
  "completed_at": "2024-01-01T10:05:30Z",
  "archived_at": null,
  
  "agent_id": "financial_analyst",
  "workflow_id": "financial_analysis_v1",
  "parent_task_id": null,
  "sub_task_ids": ["task_001_sub_001", "task_001_sub_002"],
  
  "input": {
    "company": "贵州茅台",
    "ticker": "600519.SH"
  },
  
  "output": {
    "result_file": "output/result.json",
    "report_file": "output/report.md"
  },
  
  "files": {
    "total_count": 15,
    "total_size_bytes": 125000,
    "by_type": {
      "json": 5,
      "md": 8,
      "png": 2
    }
  },
  
  "execution": {
    "trace_id": "trace_xxx",
    "iterations": 2,
    "llm_calls": 5,
    "tool_calls": 12,
    "total_tokens": 15000,
    "cost_usd": 0.015
  },
  
  "tags": ["financial", "stock", "analysis"],
  "labels": {
    "company": "贵州茅台",
    "sector": "白酒",
    "type": "investment_analysis"
  },
  
  "retention": {
    "policy": "standard",
    "expires_at": "2024-04-01T00:00:00Z",
    "archive_after_days": 30,
    "delete_after_days": 90
  }
}
```

---

## 3. 任务管理器

```python
# etf_common/agent_framework/storage/task_manager.py

from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from pathlib import Path
from pydantic import BaseModel, Field
import json
import shutil
import tarfile


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class TaskPriority(str, Enum):
    """任务优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class RetentionPolicy(str, Enum):
    """保留策略"""
    TRANSIENT = "transient"      # 临时：7 天后删除
    STANDARD = "standard"        # 标准：30 天后归档，90 天后删除
    IMPORTANT = "important"      # 重要：90 天后归档，365 天后删除
    PERMANENT = "permanent"      # 永久：仅归档，不删除


class TaskMetadata(BaseModel):
    """任务元数据"""
    
    task_id: str = Field(description="任务 ID")
    name: str = Field(description="任务名称")
    description: str = Field(default="", description="任务描述")
    
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    priority: TaskPriority = Field(default=TaskPriority.NORMAL)
    
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    archived_at: Optional[datetime] = Field(default=None)
    
    agent_id: Optional[str] = Field(default=None)
    workflow_id: Optional[str] = Field(default=None)
    parent_task_id: Optional[str] = Field(default=None)
    sub_task_ids: List[str] = Field(default_factory=list)
    
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_summary: Dict[str, Any] = Field(default_factory=dict)
    
    files_summary: Dict[str, Any] = Field(default_factory=dict)
    execution_summary: Dict[str, Any] = Field(default_factory=dict)
    
    tags: List[str] = Field(default_factory=list)
    labels: Dict[str, str] = Field(default_factory=dict)
    
    retention_policy: RetentionPolicy = Field(default=RetentionPolicy.STANDARD)
    expires_at: Optional[datetime] = Field(default=None)
    
    workspace_path: Optional[str] = Field(default=None)
    trace_id: Optional[str] = Field(default=None)


class TaskIndex(BaseModel):
    """任务索引"""
    
    total_tasks: int = Field(default=0)
    active_tasks: int = Field(default=0)
    completed_tasks: int = Field(default=0)
    archived_tasks: int = Field(default=0)
    
    tasks: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    
    # 索引
    by_status: Dict[str, List[str]] = Field(default_factory=dict)
    by_agent: Dict[str, List[str]] = Field(default_factory=dict)
    by_workflow: Dict[str, List[str]] = Field(default_factory=dict)
    by_tag: Dict[str, List[str]] = Field(default_factory=dict)
    by_date: Dict[str, List[str]] = Field(default_factory=dict)  # YYYY-MM-DD
    
    updated_at: datetime = Field(default_factory=datetime.now)


class TaskManager:
    """
    任务管理器
    
    负责任务的完整生命周期管理：
    - 创建、查询、更新、删除
    - 状态转换
    - 文件管理
    - 归档和清理
    """
    
    def __init__(self, storage_path: str):
        self.storage_path = Path(storage_path)
        self.tasks_path = self.storage_path / "tasks"
        self.active_path = self.tasks_path / "active"
        self.completed_path = self.tasks_path / "completed"
        self.archived_path = self.tasks_path / "archived"
        
        self._ensure_directories()
        self._index = self._load_index()
    
    def _ensure_directories(self):
        """确保目录结构存在"""
        for path in [
            self.active_path,
            self.completed_path,
            self.archived_path
        ]:
            path.mkdir(parents=True, exist_ok=True)
    
    def _load_index(self) -> TaskIndex:
        """加载任务索引"""
        index_path = self.tasks_path / "index.json"
        if index_path.exists():
            with open(index_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return TaskIndex(**data)
        return TaskIndex()
    
    def _save_index(self):
        """保存任务索引"""
        self._index.updated_at = datetime.now()
        index_path = self.tasks_path / "index.json"
        
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(
                self._index.model_dump(mode='json'),
                f,
                ensure_ascii=False,
                indent=2,
                default=str
            )
    
    # ========== 任务生命周期 ==========
    
    def create_task(
        self,
        task_id: str,
        name: str,
        description: str = "",
        agent_id: str = None,
        workflow_id: str = None,
        input_data: Dict[str, Any] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        retention_policy: RetentionPolicy = RetentionPolicy.STANDARD,
        tags: List[str] = None,
        labels: Dict[str, str] = None,
        parent_task_id: str = None
    ) -> TaskMetadata:
        """
        创建新任务
        
        Returns:
            TaskMetadata 和对应的 AgentWorkspace
        """
        # 创建任务目录
        task_path = self.active_path / task_id
        task_path.mkdir(parents=True, exist_ok=True)
        
        # 创建元数据
        metadata = TaskMetadata(
            task_id=task_id,
            name=name,
            description=description,
            agent_id=agent_id,
            workflow_id=workflow_id,
            input_data=input_data or {},
            priority=priority,
            retention_policy=retention_policy,
            tags=tags or [],
            labels=labels or {},
            parent_task_id=parent_task_id,
            workspace_path=str(task_path),
            expires_at=self._calculate_expiry(retention_policy)
        )
        
        # 保存元数据
        self._save_task_metadata(task_id, metadata)
        
        # 更新索引
        self._add_to_index(metadata)
        self._save_index()
        
        return metadata
    
    def start_task(self, task_id: str) -> TaskMetadata:
        """开始任务"""
        metadata = self.get_task(task_id)
        if metadata is None:
            raise ValueError(f"任务不存在: {task_id}")
        
        metadata.status = TaskStatus.RUNNING
        metadata.started_at = datetime.now()
        
        self._save_task_metadata(task_id, metadata)
        self._update_index(metadata)
        self._save_index()
        
        return metadata
    
    def complete_task(
        self,
        task_id: str,
        output_summary: Dict[str, Any] = None,
        execution_summary: Dict[str, Any] = None
    ) -> TaskMetadata:
        """完成任务"""
        metadata = self.get_task(task_id)
        if metadata is None:
            raise ValueError(f"任务不存在: {task_id}")
        
        metadata.status = TaskStatus.COMPLETED
        metadata.completed_at = datetime.now()
        metadata.output_summary = output_summary or {}
        metadata.execution_summary = execution_summary or {}
        
        # 更新文件统计
        metadata.files_summary = self._calculate_files_summary(task_id)
        
        self._save_task_metadata(task_id, metadata)
        self._update_index(metadata)
        
        # 移动到已完成目录
        self._move_to_completed(task_id)
        
        self._save_index()
        
        return metadata
    
    def fail_task(self, task_id: str, error: str = None) -> TaskMetadata:
        """标记任务失败"""
        metadata = self.get_task(task_id)
        if metadata is None:
            raise ValueError(f"任务不存在: {task_id}")
        
        metadata.status = TaskStatus.FAILED
        metadata.completed_at = datetime.now()
        if error:
            metadata.execution_summary["error"] = error
        
        self._save_task_metadata(task_id, metadata)
        self._update_index(metadata)
        self._save_index()
        
        return metadata
    
    def archive_task(self, task_id: str) -> str:
        """
        归档任务
        
        Returns:
            归档文件路径
        """
        metadata = self.get_task(task_id)
        if metadata is None:
            raise ValueError(f"任务不存在: {task_id}")
        
        # 确定归档路径
        now = datetime.now()
        quarter = f"Q{(now.month - 1) // 3 + 1}"
        archive_dir = self.archived_path / str(now.year) / quarter
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        archive_file = archive_dir / f"{task_id}.tar.gz"
        
        # 获取任务目录
        task_path = self._get_task_path(task_id)
        if task_path is None:
            raise ValueError(f"任务目录不存在: {task_id}")
        
        # 创建压缩归档
        with tarfile.open(archive_file, "w:gz") as tar:
            tar.add(task_path, arcname=task_id)
        
        # 更新元数据
        metadata.status = TaskStatus.ARCHIVED
        metadata.archived_at = datetime.now()
        metadata.workspace_path = str(archive_file)
        
        # 删除原目录
        shutil.rmtree(task_path)
        
        # 更新索引
        self._update_index(metadata)
        self._save_index()
        
        return str(archive_file)
    
    def delete_task(self, task_id: str, force: bool = False):
        """
        删除任务
        
        Args:
            task_id: 任务 ID
            force: 是否强制删除（跳过保留策略检查）
        """
        metadata = self.get_task(task_id)
        if metadata is None:
            return
        
        if not force and metadata.retention_policy == RetentionPolicy.PERMANENT:
            raise ValueError(f"永久保留的任务不能删除: {task_id}")
        
        # 删除文件
        task_path = self._get_task_path(task_id)
        if task_path and task_path.exists():
            if task_path.is_file():
                task_path.unlink()
            else:
                shutil.rmtree(task_path)
        
        # 从索引中移除
        self._remove_from_index(task_id)
        self._save_index()
    
    # ========== 查询方法 ==========
    
    def get_task(self, task_id: str) -> Optional[TaskMetadata]:
        """获取任务元数据"""
        if task_id not in self._index.tasks:
            return None
        
        task_path = self._get_task_path(task_id)
        if task_path is None:
            return None
        
        # 如果是归档文件，从索引返回基本信息
        if task_path.suffix == '.gz':
            task_info = self._index.tasks[task_id]
            return TaskMetadata(**task_info)
        
        # 读取元数据文件
        metadata_path = task_path / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return TaskMetadata(**data)
        
        return None
    
    def list_tasks(
        self,
        status: TaskStatus = None,
        agent_id: str = None,
        workflow_id: str = None,
        tags: List[str] = None,
        labels: Dict[str, str] = None,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[TaskMetadata]:
        """列出任务"""
        # 初步筛选
        task_ids = set(self._index.tasks.keys())
        
        if status:
            task_ids &= set(self._index.by_status.get(status.value, []))
        
        if agent_id:
            task_ids &= set(self._index.by_agent.get(agent_id, []))
        
        if workflow_id:
            task_ids &= set(self._index.by_workflow.get(workflow_id, []))
        
        if tags:
            for tag in tags:
                task_ids &= set(self._index.by_tag.get(tag, []))
        
        # 按日期筛选
        if start_date or end_date:
            date_filtered = set()
            for date_str, ids in self._index.by_date.items():
                date = datetime.fromisoformat(date_str)
                if start_date and date < start_date:
                    continue
                if end_date and date > end_date:
                    continue
                date_filtered.update(ids)
            task_ids &= date_filtered
        
        # 标签筛选
        if labels:
            label_filtered = set()
            for tid in task_ids:
                task_info = self._index.tasks.get(tid, {})
                task_labels = task_info.get("labels", {})
                if all(task_labels.get(k) == v for k, v in labels.items()):
                    label_filtered.add(tid)
            task_ids = label_filtered
        
        # 排序（按创建时间倒序）
        sorted_ids = sorted(
            task_ids,
            key=lambda x: self._index.tasks[x].get("created_at", ""),
            reverse=True
        )
        
        # 分页
        paginated_ids = sorted_ids[offset:offset + limit]
        
        # 获取完整元数据
        tasks = []
        for task_id in paginated_ids:
            metadata = self.get_task(task_id)
            if metadata:
                tasks.append(metadata)
        
        return tasks
    
    def search_tasks(self, query: str, limit: int = 20) -> List[TaskMetadata]:
        """
        搜索任务（简单文本匹配）
        
        搜索范围：名称、描述、标签
        """
        query_lower = query.lower()
        matched = []
        
        for task_id, task_info in self._index.tasks.items():
            # 搜索名称
            if query_lower in task_info.get("name", "").lower():
                matched.append(task_id)
                continue
            
            # 搜索描述
            if query_lower in task_info.get("description", "").lower():
                matched.append(task_id)
                continue
            
            # 搜索标签
            tags = task_info.get("tags", [])
            if any(query_lower in tag.lower() for tag in tags):
                matched.append(task_id)
                continue
        
        # 获取元数据
        tasks = []
        for task_id in matched[:limit]:
            metadata = self.get_task(task_id)
            if metadata:
                tasks.append(metadata)
        
        return tasks
    
    # ========== 文件操作 ==========
    
    def get_task_files(self, task_id: str) -> List[Dict[str, Any]]:
        """获取任务的所有文件列表"""
        task_path = self._get_task_path(task_id)
        if task_path is None or not task_path.is_dir():
            return []
        
        files = []
        for file_path in task_path.rglob('*'):
            if file_path.is_file():
                rel_path = file_path.relative_to(task_path)
                files.append({
                    "path": str(rel_path),
                    "name": file_path.name,
                    "size": file_path.stat().st_size,
                    "modified_at": datetime.fromtimestamp(
                        file_path.stat().st_mtime
                    ).isoformat(),
                    "type": file_path.suffix[1:] if file_path.suffix else "unknown"
                })
        
        return files
    
    def read_task_file(self, task_id: str, file_path: str) -> str:
        """读取任务文件"""
        task_path = self._get_task_path(task_id)
        if task_path is None:
            raise ValueError(f"任务不存在: {task_id}")
        
        full_path = task_path / file_path
        if not full_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        return full_path.read_text(encoding='utf-8')
    
    def copy_file_to_task(
        self,
        source_task_id: str,
        source_path: str,
        target_task_id: str,
        target_path: str
    ) -> str:
        """跨任务复制文件"""
        source_task_path = self._get_task_path(source_task_id)
        target_task_path = self._get_task_path(target_task_id)
        
        if source_task_path is None:
            raise ValueError(f"源任务不存在: {source_task_id}")
        if target_task_path is None:
            raise ValueError(f"目标任务不存在: {target_task_id}")
        
        source_file = source_task_path / source_path
        target_file = target_task_path / target_path
        
        if not source_file.exists():
            raise FileNotFoundError(f"源文件不存在: {source_path}")
        
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
        
        return str(target_file)
    
    # ========== 统计方法 ==========
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取全局统计信息"""
        return {
            "total_tasks": self._index.total_tasks,
            "active_tasks": self._index.active_tasks,
            "completed_tasks": self._index.completed_tasks,
            "archived_tasks": self._index.archived_tasks,
            "by_status": {
                k: len(v) for k, v in self._index.by_status.items()
            },
            "by_agent": {
                k: len(v) for k, v in self._index.by_agent.items()
            },
            "storage_size": self._calculate_storage_size(),
            "updated_at": self._index.updated_at.isoformat()
        }
    
    # ========== 内部方法 ==========
    
    def _get_task_path(self, task_id: str) -> Optional[Path]:
        """获取任务路径"""
        # 检查活跃目录
        active = self.active_path / task_id
        if active.exists():
            return active
        
        # 检查已完成目录（按日期组织）
        for date_dir in self.completed_path.rglob(task_id):
            if date_dir.exists():
                return date_dir
        
        # 检查归档目录
        for archive in self.archived_path.rglob(f"{task_id}.tar.gz"):
            if archive.exists():
                return archive
        
        return None
    
    def _save_task_metadata(self, task_id: str, metadata: TaskMetadata):
        """保存任务元数据"""
        task_path = self._get_task_path(task_id)
        if task_path is None or task_path.suffix == '.gz':
            return
        
        metadata_path = task_path / "metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(
                metadata.model_dump(mode='json'),
                f,
                ensure_ascii=False,
                indent=2,
                default=str
            )
    
    def _move_to_completed(self, task_id: str):
        """移动任务到已完成目录"""
        source = self.active_path / task_id
        if not source.exists():
            return
        
        now = datetime.now()
        target_dir = self.completed_path / str(now.year) / f"{now.month:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        
        target = target_dir / task_id
        shutil.move(str(source), str(target))
    
    def _add_to_index(self, metadata: TaskMetadata):
        """添加到索引"""
        task_id = metadata.task_id
        
        # 基本信息
        self._index.tasks[task_id] = {
            "name": metadata.name,
            "description": metadata.description,
            "status": metadata.status.value,
            "agent_id": metadata.agent_id,
            "workflow_id": metadata.workflow_id,
            "created_at": metadata.created_at.isoformat(),
            "tags": metadata.tags,
            "labels": metadata.labels
        }
        
        # 状态索引
        status_key = metadata.status.value
        if status_key not in self._index.by_status:
            self._index.by_status[status_key] = []
        self._index.by_status[status_key].append(task_id)
        
        # Agent 索引
        if metadata.agent_id:
            if metadata.agent_id not in self._index.by_agent:
                self._index.by_agent[metadata.agent_id] = []
            self._index.by_agent[metadata.agent_id].append(task_id)
        
        # Workflow 索引
        if metadata.workflow_id:
            if metadata.workflow_id not in self._index.by_workflow:
                self._index.by_workflow[metadata.workflow_id] = []
            self._index.by_workflow[metadata.workflow_id].append(task_id)
        
        # 标签索引
        for tag in metadata.tags:
            if tag not in self._index.by_tag:
                self._index.by_tag[tag] = []
            self._index.by_tag[tag].append(task_id)
        
        # 日期索引
        date_key = metadata.created_at.strftime("%Y-%m-%d")
        if date_key not in self._index.by_date:
            self._index.by_date[date_key] = []
        self._index.by_date[date_key].append(task_id)
        
        # 更新计数
        self._index.total_tasks += 1
        if metadata.status == TaskStatus.RUNNING:
            self._index.active_tasks += 1
    
    def _update_index(self, metadata: TaskMetadata):
        """更新索引"""
        task_id = metadata.task_id
        old_info = self._index.tasks.get(task_id, {})
        old_status = old_info.get("status")
        
        # 更新基本信息
        self._index.tasks[task_id] = {
            "name": metadata.name,
            "description": metadata.description,
            "status": metadata.status.value,
            "agent_id": metadata.agent_id,
            "workflow_id": metadata.workflow_id,
            "created_at": metadata.created_at.isoformat(),
            "tags": metadata.tags,
            "labels": metadata.labels
        }
        
        # 更新状态索引
        if old_status and old_status != metadata.status.value:
            # 从旧状态列表移除
            if old_status in self._index.by_status:
                if task_id in self._index.by_status[old_status]:
                    self._index.by_status[old_status].remove(task_id)
            
            # 添加到新状态列表
            new_status = metadata.status.value
            if new_status not in self._index.by_status:
                self._index.by_status[new_status] = []
            self._index.by_status[new_status].append(task_id)
            
            # 更新计数
            if old_status == TaskStatus.RUNNING.value:
                self._index.active_tasks -= 1
            if metadata.status == TaskStatus.RUNNING:
                self._index.active_tasks += 1
            if metadata.status == TaskStatus.COMPLETED:
                self._index.completed_tasks += 1
            if metadata.status == TaskStatus.ARCHIVED:
                self._index.archived_tasks += 1
    
    def _remove_from_index(self, task_id: str):
        """从索引中移除"""
        if task_id not in self._index.tasks:
            return
        
        task_info = self._index.tasks[task_id]
        
        # 从状态索引移除
        status = task_info.get("status")
        if status and status in self._index.by_status:
            if task_id in self._index.by_status[status]:
                self._index.by_status[status].remove(task_id)
        
        # 从 Agent 索引移除
        agent_id = task_info.get("agent_id")
        if agent_id and agent_id in self._index.by_agent:
            if task_id in self._index.by_agent[agent_id]:
                self._index.by_agent[agent_id].remove(task_id)
        
        # 从 Workflow 索引移除
        workflow_id = task_info.get("workflow_id")
        if workflow_id and workflow_id in self._index.by_workflow:
            if task_id in self._index.by_workflow[workflow_id]:
                self._index.by_workflow[workflow_id].remove(task_id)
        
        # 从标签索引移除
        for tag in task_info.get("tags", []):
            if tag in self._index.by_tag:
                if task_id in self._index.by_tag[tag]:
                    self._index.by_tag[tag].remove(task_id)
        
        # 从主索引移除
        del self._index.tasks[task_id]
        
        # 更新计数
        self._index.total_tasks -= 1
    
    def _calculate_expiry(self, policy: RetentionPolicy) -> Optional[datetime]:
        """计算过期时间"""
        now = datetime.now()
        
        if policy == RetentionPolicy.TRANSIENT:
            return now + timedelta(days=7)
        elif policy == RetentionPolicy.STANDARD:
            return now + timedelta(days=90)
        elif policy == RetentionPolicy.IMPORTANT:
            return now + timedelta(days=365)
        else:  # PERMANENT
            return None
    
    def _calculate_files_summary(self, task_id: str) -> Dict[str, Any]:
        """计算文件统计"""
        task_path = self._get_task_path(task_id)
        if task_path is None or not task_path.is_dir():
            return {}
        
        total_count = 0
        total_size = 0
        by_type = {}
        
        for file_path in task_path.rglob('*'):
            if file_path.is_file():
                total_count += 1
                total_size += file_path.stat().st_size
                
                ext = file_path.suffix[1:] if file_path.suffix else "other"
                by_type[ext] = by_type.get(ext, 0) + 1
        
        return {
            "total_count": total_count,
            "total_size_bytes": total_size,
            "by_type": by_type
        }
    
    def _calculate_storage_size(self) -> int:
        """计算总存储大小"""
        total = 0
        for path in self.tasks_path.rglob('*'):
            if path.is_file():
                total += path.stat().st_size
        return total
```

---

## 4. 自动清理服务

```python
# etf_common/agent_framework/storage/cleanup_service.py

import asyncio
from datetime import datetime, timedelta
from typing import List
import logging

from .task_manager import TaskManager, TaskStatus, RetentionPolicy


logger = logging.getLogger(__name__)


class CleanupService:
    """
    自动清理服务
    
    定期执行：
    1. 归档过期的已完成任务
    2. 删除超过保留期的归档任务
    3. 清理临时文件
    4. 压缩大文件
    """
    
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self._running = False
    
    async def start(self, interval_hours: int = 24):
        """启动清理服务"""
        self._running = True
        
        while self._running:
            try:
                await self.run_cleanup()
            except Exception as e:
                logger.error(f"清理任务失败: {e}")
            
            await asyncio.sleep(interval_hours * 3600)
    
    def stop(self):
        """停止清理服务"""
        self._running = False
    
    async def run_cleanup(self):
        """执行一次清理"""
        logger.info("开始执行清理任务...")
        
        stats = {
            "archived": 0,
            "deleted": 0,
            "errors": 0
        }
        
        # 1. 归档过期的已完成任务
        archived = await self._archive_expired_tasks()
        stats["archived"] = archived
        
        # 2. 删除超过保留期的归档任务
        deleted = await self._delete_expired_archives()
        stats["deleted"] = deleted
        
        # 3. 清理临时文件
        await self._cleanup_temp_files()
        
        logger.info(f"清理完成: {stats}")
        return stats
    
    async def _archive_expired_tasks(self) -> int:
        """归档过期的已完成任务"""
        count = 0
        now = datetime.now()
        
        # 获取所有已完成任务
        completed_tasks = self.task_manager.list_tasks(
            status=TaskStatus.COMPLETED,
            limit=1000
        )
        
        for task in completed_tasks:
            # 检查是否应该归档
            should_archive = False
            
            if task.retention_policy == RetentionPolicy.TRANSIENT:
                # 临时任务：7 天后归档
                if task.completed_at and (now - task.completed_at).days >= 7:
                    should_archive = True
            
            elif task.retention_policy == RetentionPolicy.STANDARD:
                # 标准任务：30 天后归档
                if task.completed_at and (now - task.completed_at).days >= 30:
                    should_archive = True
            
            elif task.retention_policy == RetentionPolicy.IMPORTANT:
                # 重要任务：90 天后归档
                if task.completed_at and (now - task.completed_at).days >= 90:
                    should_archive = True
            
            # PERMANENT 不自动归档
            
            if should_archive:
                try:
                    self.task_manager.archive_task(task.task_id)
                    count += 1
                    logger.info(f"已归档任务: {task.task_id}")
                except Exception as e:
                    logger.error(f"归档任务失败 {task.task_id}: {e}")
        
        return count
    
    async def _delete_expired_archives(self) -> int:
        """删除超过保留期的归档任务"""
        count = 0
        now = datetime.now()
        
        # 获取所有已归档任务
        archived_tasks = self.task_manager.list_tasks(
            status=TaskStatus.ARCHIVED,
            limit=1000
        )
        
        for task in archived_tasks:
            should_delete = False
            
            if task.retention_policy == RetentionPolicy.TRANSIENT:
                # 临时任务：归档后 7 天删除（总共 14 天）
                if task.archived_at and (now - task.archived_at).days >= 7:
                    should_delete = True
            
            elif task.retention_policy == RetentionPolicy.STANDARD:
                # 标准任务：归档后 60 天删除（总共 90 天）
                if task.archived_at and (now - task.archived_at).days >= 60:
                    should_delete = True
            
            elif task.retention_policy == RetentionPolicy.IMPORTANT:
                # 重要任务：归档后 275 天删除（总共 365 天）
                if task.archived_at and (now - task.archived_at).days >= 275:
                    should_delete = True
            
            # PERMANENT 不删除
            
            if should_delete:
                try:
                    self.task_manager.delete_task(task.task_id)
                    count += 1
                    logger.info(f"已删除归档任务: {task.task_id}")
                except Exception as e:
                    logger.error(f"删除归档任务失败 {task.task_id}: {e}")
        
        return count
    
    async def _cleanup_temp_files(self):
        """清理临时文件"""
        # 清理各任务的 scratch/temp 目录中超过 24 小时的文件
        active_tasks = self.task_manager.list_tasks(
            status=TaskStatus.RUNNING,
            limit=1000
        )
        
        now = datetime.now()
        
        for task in active_tasks:
            task_path = self.task_manager._get_task_path(task.task_id)
            if task_path is None:
                continue
            
            temp_dir = task_path / "scratch" / "temp"
            if not temp_dir.exists():
                continue
            
            for file_path in temp_dir.iterdir():
                if file_path.is_file():
                    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if (now - mtime).total_seconds() > 86400:  # 24 小时
                        try:
                            file_path.unlink()
                            logger.debug(f"已删除临时文件: {file_path}")
                        except Exception as e:
                            logger.warning(f"删除临时文件失败: {e}")
```

---

## 5. 共享资源管理

```python
# etf_common/agent_framework/storage/shared_resources.py

from pathlib import Path
from typing import Dict, Any, Optional, List
import json
import shutil


class SharedResourceManager:
    """
    共享资源管理器
    
    管理跨任务共享的资源：
    - 模板文件
    - 知识库
    - 缓存
    """
    
    def __init__(self, storage_path: str):
        self.storage_path = Path(storage_path)
        self.shared_path = self.storage_path / "shared"
        
        self._ensure_directories()
    
    def _ensure_directories(self):
        """确保目录结构存在"""
        dirs = [
            "templates/prompts",
            "templates/reports",
            "templates/workflows",
            "knowledge/domain",
            "knowledge/reference",
            "cache/llm_cache",
            "cache/tool_cache"
        ]
        
        for d in dirs:
            (self.shared_path / d).mkdir(parents=True, exist_ok=True)
    
    # ========== 模板管理 ==========
    
    def save_template(
        self,
        category: str,  # prompts, reports, workflows
        name: str,
        content: str,
        metadata: Dict[str, Any] = None
    ) -> str:
        """保存模板"""
        template_dir = self.shared_path / "templates" / category
        template_path = template_dir / f"{name}.md"
        
        template_path.write_text(content, encoding='utf-8')
        
        # 保存元数据
        if metadata:
            meta_path = template_dir / f"{name}.meta.json"
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        return str(template_path)
    
    def get_template(self, category: str, name: str) -> Optional[str]:
        """获取模板"""
        template_path = self.shared_path / "templates" / category / f"{name}.md"
        
        if template_path.exists():
            return template_path.read_text(encoding='utf-8')
        
        return None
    
    def list_templates(self, category: str) -> List[Dict[str, Any]]:
        """列出模板"""
        template_dir = self.shared_path / "templates" / category
        
        if not template_dir.exists():
            return []
        
        templates = []
        for template_file in template_dir.glob("*.md"):
            name = template_file.stem
            
            # 读取元数据
            meta_path = template_dir / f"{name}.meta.json"
            metadata = {}
            if meta_path.exists():
                with open(meta_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            
            templates.append({
                "name": name,
                "path": str(template_file),
                "metadata": metadata
            })
        
        return templates
    
    # ========== 知识库管理 ==========
    
    def add_knowledge(
        self,
        category: str,  # domain, reference
        name: str,
        content: str,
        metadata: Dict[str, Any] = None
    ) -> str:
        """添加知识条目"""
        knowledge_dir = self.shared_path / "knowledge" / category
        knowledge_path = knowledge_dir / f"{name}.md"
        
        knowledge_path.write_text(content, encoding='utf-8')
        
        if metadata:
            meta_path = knowledge_dir / f"{name}.meta.json"
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        return str(knowledge_path)
    
    def get_knowledge(self, category: str, name: str) -> Optional[str]:
        """获取知识条目"""
        knowledge_path = self.shared_path / "knowledge" / category / f"{name}.md"
        
        if knowledge_path.exists():
            return knowledge_path.read_text(encoding='utf-8')
        
        return None
    
    def search_knowledge(self, query: str, category: str = None) -> List[Dict[str, Any]]:
        """搜索知识库（简单文本匹配）"""
        results = []
        
        categories = [category] if category else ["domain", "reference"]
        
        for cat in categories:
            knowledge_dir = self.shared_path / "knowledge" / cat
            if not knowledge_dir.exists():
                continue
            
            for file_path in knowledge_dir.glob("*.md"):
                content = file_path.read_text(encoding='utf-8')
                
                if query.lower() in content.lower():
                    results.append({
                        "name": file_path.stem,
                        "category": cat,
                        "path": str(file_path),
                        "snippet": self._extract_snippet(content, query)
                    })
        
        return results
    
    def _extract_snippet(self, content: str, query: str, context_chars: int = 100) -> str:
        """提取匹配片段"""
        query_lower = query.lower()
        content_lower = content.lower()
        
        idx = content_lower.find(query_lower)
        if idx == -1:
            return content[:200]
        
        start = max(0, idx - context_chars)
        end = min(len(content), idx + len(query) + context_chars)
        
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        
        return snippet
    
    # ========== 缓存管理 ==========
    
    def cache_llm_response(
        self,
        cache_key: str,
        response: str,
        metadata: Dict[str, Any] = None,
        ttl_hours: int = 24
    ):
        """缓存 LLM 响应"""
        from datetime import datetime, timedelta
        
        cache_dir = self.shared_path / "cache" / "llm_cache"
        cache_file = cache_dir / f"{cache_key}.json"
        
        cache_data = {
            "response": response,
            "cached_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=ttl_hours)).isoformat(),
            "metadata": metadata or {}
        }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    
    def get_cached_llm_response(self, cache_key: str) -> Optional[str]:
        """获取缓存的 LLM 响应"""
        from datetime import datetime
        
        cache_file = self.shared_path / "cache" / "llm_cache" / f"{cache_key}.json"
        
        if not cache_file.exists():
            return None
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        # 检查是否过期
        expires_at = datetime.fromisoformat(cache_data["expires_at"])
        if datetime.now() > expires_at:
            cache_file.unlink()
            return None
        
        return cache_data["response"]
    
    def cache_tool_result(
        self,
        tool_id: str,
        params_hash: str,
        result: Any,
        ttl_hours: int = 1
    ):
        """缓存工具结果"""
        from datetime import datetime, timedelta
        
        cache_dir = self.shared_path / "cache" / "tool_cache" / tool_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        cache_file = cache_dir / f"{params_hash}.json"
        
        cache_data = {
            "result": result,
            "cached_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=ttl_hours)).isoformat()
        }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2, default=str)
    
    def get_cached_tool_result(self, tool_id: str, params_hash: str) -> Optional[Any]:
        """获取缓存的工具结果"""
        from datetime import datetime
        
        cache_file = (
            self.shared_path / "cache" / "tool_cache" / tool_id / f"{params_hash}.json"
        )
        
        if not cache_file.exists():
            return None
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        # 检查是否过期
        expires_at = datetime.fromisoformat(cache_data["expires_at"])
        if datetime.now() > expires_at:
            cache_file.unlink()
            return None
        
        return cache_data["result"]
    
    def clear_cache(self, cache_type: str = None):
        """清理缓存"""
        if cache_type:
            cache_dir = self.shared_path / "cache" / cache_type
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)
        else:
            cache_root = self.shared_path / "cache"
            for cache_dir in cache_root.iterdir():
                if cache_dir.is_dir():
                    shutil.rmtree(cache_dir)
                    cache_dir.mkdir(parents=True, exist_ok=True)
```

---

## 6. 与工作空间集成

```python
# etf_common/agent_framework/storage/workspace_integration.py

from typing import Dict, Any, Optional
from pathlib import Path

from .task_manager import TaskManager, TaskMetadata, TaskPriority, RetentionPolicy
from ..workspace import AgentWorkspace, WorkspaceConfig


class StorageIntegratedWorkspace:
    """
    存储集成的工作空间
    
    将 TaskManager 和 AgentWorkspace 集成，提供统一的接口
    """
    
    def __init__(
        self,
        task_manager: TaskManager,
        task_id: str = None,
        create_new: bool = True,
        **task_kwargs
    ):
        self.task_manager = task_manager
        
        if task_id and not create_new:
            # 打开现有任务
            self.metadata = task_manager.get_task(task_id)
            if self.metadata is None:
                raise ValueError(f"任务不存在: {task_id}")
            self.workspace = AgentWorkspace(WorkspaceConfig(
                base_path=str(Path(self.metadata.workspace_path).parent),
                task_id=task_id
            ))
        else:
            # 创建新任务
            if task_id is None:
                from datetime import datetime
                task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            self.metadata = task_manager.create_task(
                task_id=task_id,
                **task_kwargs
            )
            
            self.workspace = AgentWorkspace(WorkspaceConfig(
                base_path=str(Path(self.metadata.workspace_path).parent),
                task_id=task_id
            ))
    
    @property
    def task_id(self) -> str:
        return self.metadata.task_id
    
    def start(self):
        """开始任务"""
        self.metadata = self.task_manager.start_task(self.task_id)
    
    def complete(
        self,
        output_summary: Dict[str, Any] = None,
        execution_summary: Dict[str, Any] = None
    ):
        """完成任务"""
        self.metadata = self.task_manager.complete_task(
            self.task_id,
            output_summary=output_summary,
            execution_summary=execution_summary
        )
    
    def fail(self, error: str = None):
        """标记任务失败"""
        self.metadata = self.task_manager.fail_task(self.task_id, error)
    
    # ========== 代理工作空间方法 ==========
    
    def write_task(self, task_description: str, input_data: Dict[str, Any] = None):
        """写入任务"""
        self.workspace.write_task(task_description, input_data)
        
        # 更新元数据
        self.metadata.input_data = input_data or {}
        self.task_manager._save_task_metadata(self.task_id, self.metadata)
    
    def read_task(self):
        """读取任务"""
        return self.workspace.read_task()
    
    def write_result(self, result: Dict[str, Any]):
        """写入结果"""
        self.workspace.write_result(result)
    
    def read_result(self):
        """读取结果"""
        return self.workspace.read_result()
    
    def write_draft(self, content: str, version: int = None) -> str:
        """写入草稿"""
        return self.workspace.write_draft(content, version)
    
    def read_draft(self, version: int = None):
        """读取草稿"""
        return self.workspace.read_draft(version)
    
    def save_gathered_context(self, context: str):
        """保存收集的上下文"""
        self.workspace.save_gathered_context(context)
    
    def get_gathered_context(self):
        """获取收集的上下文"""
        return self.workspace.get_gathered_context()
    
    def log_action(self, action: str, details: Dict[str, Any] = None):
        """记录操作日志"""
        self.workspace.log_action(action, details)
    
    def save_checkpoint(self, state: Dict[str, Any]) -> str:
        """保存检查点"""
        return self.workspace.save_checkpoint(state)
    
    # ========== 跨任务操作 ==========
    
    def copy_from_task(
        self,
        source_task_id: str,
        source_path: str,
        target_path: str
    ) -> str:
        """从其他任务复制文件"""
        return self.task_manager.copy_file_to_task(
            source_task_id,
            source_path,
            self.task_id,
            target_path
        )
    
    def create_sub_task(
        self,
        sub_task_id: str,
        name: str,
        **kwargs
    ) -> "StorageIntegratedWorkspace":
        """创建子任务"""
        full_sub_id = f"{self.task_id}_{sub_task_id}"
        
        sub_workspace = StorageIntegratedWorkspace(
            task_manager=self.task_manager,
            task_id=full_sub_id,
            name=name,
            parent_task_id=self.task_id,
            **kwargs
        )
        
        # 更新父任务的子任务列表
        self.metadata.sub_task_ids.append(full_sub_id)
        self.task_manager._save_task_metadata(self.task_id, self.metadata)
        
        return sub_workspace
```

---

## 7. 使用示例

```python
# 示例：完整的任务管理流程

from etf_common.agent_framework.storage import (
    TaskManager,
    SharedResourceManager,
    CleanupService,
    StorageIntegratedWorkspace
)


async def example_task_management():
    # 1. 初始化存储
    storage_path = "./storage"
    task_manager = TaskManager(storage_path)
    shared_resources = SharedResourceManager(storage_path)
    
    # 2. 创建集成工作空间
    workspace = StorageIntegratedWorkspace(
        task_manager=task_manager,
        name="贵州茅台投资分析",
        description="分析贵州茅台的投资价值",
        agent_id="financial_analyst",
        tags=["financial", "stock"],
        labels={"company": "贵州茅台"},
        priority=TaskPriority.HIGH,
        retention_policy=RetentionPolicy.IMPORTANT
    )
    
    # 3. 开始任务
    workspace.start()
    
    # 4. 写入任务
    workspace.write_task(
        "请分析贵州茅台的投资价值",
        {"company": "贵州茅台", "ticker": "600519.SH"}
    )
    
    # 5. 使用共享模板
    prompt_template = shared_resources.get_template("prompts", "financial_analysis")
    if prompt_template:
        # 使用模板...
        pass
    
    # 6. 使用知识库
    domain_knowledge = shared_resources.search_knowledge("白酒行业", category="domain")
    
    # 7. 执行分析（模拟）
    workspace.save_gathered_context("# 收集的信息\n...")
    workspace.write_draft("# 分析报告草稿 V1\n...")
    workspace.write_draft("# 分析报告草稿 V2\n...")
    
    # 8. 写入结果
    result = {
        "company": "贵州茅台",
        "summary": "长期看好",
        "target_price": 1900
    }
    workspace.write_result(result)
    
    # 9. 完成任务
    workspace.complete(
        output_summary={"summary": "分析完成"},
        execution_summary={"llm_calls": 5, "tool_calls": 12}
    )
    
    # 10. 查询任务
    tasks = task_manager.list_tasks(
        tags=["financial"],
        limit=10
    )
    print(f"找到 {len(tasks)} 个金融分析任务")
    
    # 11. 获取统计
    stats = task_manager.get_statistics()
    print(f"总任务数: {stats['total_tasks']}")
    
    # 12. 启动清理服务（后台）
    cleanup_service = CleanupService(task_manager)
    # await cleanup_service.start(interval_hours=24)  # 生产环境


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_task_management())
```

---

## 8. 目录结构

```
etf_common/agent_framework/storage/
├── __init__.py
├── task_manager.py              # 任务管理器
├── cleanup_service.py           # 自动清理服务
├── shared_resources.py          # 共享资源管理
├── workspace_integration.py     # 工作空间集成
├── backup/                      # 备份模块
│   ├── __init__.py
│   ├── backup_manager.py        # 备份管理
│   └── restore_manager.py       # 恢复管理
└── migration/                   # 数据迁移
    ├── __init__.py
    └── storage_migration.py     # 存储迁移工具
```

---

## 9. 与追踪系统的关联

任务管理系统与追踪系统（09_data_persistence）紧密关联：

```
TaskMetadata                    ExecutionTrace
├── task_id         ←───────→   ├── task_id
├── trace_id        ←───────→   ├── trace_id
├── execution_summary            ├── summary
│   ├── llm_calls   ←───────→   │   ├── total_llm_calls
│   ├── tool_calls  ←───────→   │   ├── total_tool_calls
│   ├── tokens      ←───────→   │   ├── total_tokens
│   └── cost        ←───────→   │   └── total_cost_usd
└── workspace_path  ←───────→   └── workspace_path
```

**集成点：**

1. **任务创建时** → 自动创建 ExecutionTrace
2. **任务完成时** → 从 ExecutionTrace 同步 summary 到 TaskMetadata
3. **查询任务时** → 可以同时获取对应的 ExecutionTrace
4. **归档任务时** → 同时归档对应的 ExecutionTrace


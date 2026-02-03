# 工作空间与文件系统交互

## 1. 设计理念

基于 Anthropic Claude Agent SDK 的核心原则：**文件系统是交互总线**

| 传统方式 | 文件系统方式 |
|----------|--------------|
| ❌ Tool Call 输出不稳定，中断即丢失 | ✅ 文件持久化，可恢复 |
| ❌ 输出不可迭代修改 | ✅ 草稿机制，逐步完善 |
| ❌ 难以传递大量数据 | ✅ 支持任意大小数据 |
| ❌ 子 Agent 传参复杂 | ✅ 清晰的输入输出边界 |
| ❌ 调试困难 | ✅ 所有中间状态可查看 |

---

## 2. 工作空间目录结构

```
workspace/{task_id}/
├── input/                  # 输入数据
│   ├── task.md             # 任务描述
│   ├── data.json           # 输入数据
│   └── context/            # 上下文文件
│       └── *.md
├── output/                 # 最终输出
│   ├── result.json         # 结构化结果
│   ├── report.md           # 报告文件
│   └── artifacts/          # 产出物
│       └── *.png, *.pdf
├── scratch/                # 草稿和中间文件
│   ├── draft_v1.md         # 草稿版本1
│   ├── draft_v2.md         # 草稿版本2
│   ├── notes.md            # 笔记
│   └── temp/               # 临时文件
├── context/                # 聚合的上下文
│   ├── gathered.md         # 收集的信息
│   ├── summary.md          # 上下文摘要
│   └── references/         # 引用资料
├── logs/                   # 执行日志
│   ├── actions.jsonl       # 操作日志
│   ├── errors.jsonl        # 错误日志
│   └── progress.json       # 进度信息
├── sub_agents/             # 子 Agent 工作空间
│   ├── sub_001/
│   │   ├── input/
│   │   ├── output/
│   │   └── ...
│   └── sub_002/
└── state/                  # 状态快照（用于恢复）
    ├── checkpoint_001.json
    └── checkpoint_002.json
```

---

## 3. 工作空间实现

```python
# etf_common/agent_framework/workspace/workspace.py

from pathlib import Path
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
import json
import shutil


class WorkspaceConfig(BaseModel):
    """工作空间配置"""
    
    base_path: str = Field(description="工作空间根路径")
    task_id: str = Field(description="任务 ID")
    
    # 目录名称配置
    input_dir: str = Field(default="input", description="输入目录")
    output_dir: str = Field(default="output", description="输出目录")
    scratch_dir: str = Field(default="scratch", description="草稿目录")
    context_dir: str = Field(default="context", description="上下文目录")
    logs_dir: str = Field(default="logs", description="日志目录")
    state_dir: str = Field(default="state", description="状态目录")
    sub_agents_dir: str = Field(default="sub_agents", description="子 Agent 目录")
    
    # 文件命名配置
    task_file: str = Field(default="task.md", description="任务描述文件")
    result_file: str = Field(default="result.json", description="结果文件")
    progress_file: str = Field(default="progress.json", description="进度文件")
    
    # 保留配置
    max_drafts: int = Field(default=10, description="最大草稿数量")
    max_checkpoints: int = Field(default=5, description="最大检查点数量")


class AgentWorkspace:
    """
    Agent 工作空间 - 文件系统作为交互总线
    
    所有 Agent 的输入、输出、中间状态都通过工作空间管理。
    支持：
    - 文件读写编辑
    - 草稿迭代
    - 状态持久化
    - 子 Agent 隔离
    - 错误恢复
    """
    
    def __init__(self, config: WorkspaceConfig):
        self.config = config
        self.root = Path(config.base_path) / config.task_id
        self._init_workspace()
    
    def _init_workspace(self):
        """初始化工作空间目录结构"""
        dirs = [
            self.config.input_dir,
            f"{self.config.input_dir}/context",
            self.config.output_dir,
            f"{self.config.output_dir}/artifacts",
            self.config.scratch_dir,
            f"{self.config.scratch_dir}/temp",
            self.config.context_dir,
            f"{self.config.context_dir}/references",
            self.config.logs_dir,
            self.config.state_dir,
            self.config.sub_agents_dir,
        ]
        for d in dirs:
            (self.root / d).mkdir(parents=True, exist_ok=True)
    
    # ========== 核心文件操作（Unix 风格）==========
    
    def ls(self, path: str = "") -> List[str]:
        """列出目录内容"""
        target = self.root / path
        if not target.exists():
            return []
        return sorted([f.name for f in target.iterdir()])
    
    def read_file(self, path: str, encoding: str = 'utf-8') -> str:
        """读取文件内容"""
        file_path = self.root / path
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        return file_path.read_text(encoding=encoding)
    
    def read_file_lines(
        self,
        path: str,
        start_line: int = None,
        end_line: int = None
    ) -> str:
        """读取文件指定行范围"""
        content = self.read_file(path)
        lines = content.split('\n')
        
        start = (start_line - 1) if start_line else 0
        end = end_line if end_line else len(lines)
        
        return '\n'.join(lines[start:end])
    
    def write_file(self, path: str, content: str) -> str:
        """写入文件（覆盖）"""
        file_path = self.root / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding='utf-8')
        return str(file_path)
    
    def append_file(self, path: str, content: str) -> str:
        """追加内容到文件"""
        file_path = self.root / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(content)
        return str(file_path)
    
    def edit_file(
        self,
        path: str,
        old_content: str,
        new_content: str
    ) -> str:
        """编辑文件（替换指定内容）"""
        file_path = self.root / path
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        
        content = file_path.read_text(encoding='utf-8')
        if old_content not in content:
            raise ValueError(f"未找到要替换的内容: {old_content[:50]}...")
        
        new_file_content = content.replace(old_content, new_content, 1)
        file_path.write_text(new_file_content, encoding='utf-8')
        return str(file_path)
    
    def delete_file(self, path: str) -> bool:
        """删除文件"""
        file_path = self.root / path
        if file_path.exists():
            file_path.unlink()
            return True
        return False
    
    def exists(self, path: str) -> bool:
        """检查路径是否存在"""
        return (self.root / path).exists()
    
    def copy_file(self, src: str, dst: str) -> str:
        """复制文件"""
        src_path = self.root / src
        dst_path = self.root / dst
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        return str(dst_path)
    
    # ========== 任务管理 ==========
    
    def write_task(
        self,
        task_description: str,
        input_data: Dict[str, Any] = None
    ):
        """
        写入任务描述（Main → Sub-Agent 通信）
        
        Args:
            task_description: 任务描述文本
            input_data: 输入数据字典
        """
        # 写入任务描述文件
        self.write_file(
            f"{self.config.input_dir}/{self.config.task_file}",
            task_description
        )
        
        # 写入输入数据文件
        if input_data:
            self.write_file(
                f"{self.config.input_dir}/data.json",
                json.dumps(input_data, ensure_ascii=False, indent=2)
            )
    
    def read_task(self) -> tuple[str, Optional[Dict[str, Any]]]:
        """
        读取任务描述
        
        Returns:
            (任务描述, 输入数据)
        """
        task_path = f"{self.config.input_dir}/{self.config.task_file}"
        task = self.read_file(task_path) if self.exists(task_path) else ""
        
        data = None
        data_path = f"{self.config.input_dir}/data.json"
        if self.exists(data_path):
            data = json.loads(self.read_file(data_path))
        
        return task, data
    
    def write_result(self, result: Dict[str, Any]):
        """
        写入结果（Sub-Agent → Main 通信）
        
        Args:
            result: 结果字典
        """
        self.write_file(
            f"{self.config.output_dir}/{self.config.result_file}",
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    
    def read_result(self) -> Optional[Dict[str, Any]]:
        """读取结果"""
        result_path = f"{self.config.output_dir}/{self.config.result_file}"
        if not self.exists(result_path):
            return None
        return json.loads(self.read_file(result_path))
    
    # ========== 草稿管理 ==========
    
    def write_draft(self, content: str, version: int = None) -> str:
        """
        写入草稿（可迭代输出）
        
        Args:
            content: 草稿内容
            version: 版本号（不指定则自动递增）
            
        Returns:
            草稿文件路径
        """
        if version is None:
            version = self._get_next_draft_version()
        
        draft_path = f"{self.config.scratch_dir}/draft_v{version}.md"
        self.write_file(draft_path, content)
        
        # 清理旧草稿
        self._cleanup_old_drafts()
        
        return draft_path
    
    def read_draft(self, version: int = None) -> Optional[str]:
        """
        读取草稿
        
        Args:
            version: 版本号（不指定则读取最新）
        """
        if version is None:
            version = self._get_latest_draft_version()
        
        if version == 0:
            return None
        
        draft_path = f"{self.config.scratch_dir}/draft_v{version}.md"
        if self.exists(draft_path):
            return self.read_file(draft_path)
        return None
    
    def list_drafts(self) -> List[str]:
        """列出所有草稿"""
        scratch_dir = self.root / self.config.scratch_dir
        drafts = sorted([
            f.name for f in scratch_dir.glob("draft_v*.md")
        ])
        return drafts
    
    def _get_next_draft_version(self) -> int:
        """获取下一个草稿版本号"""
        drafts = self.list_drafts()
        if not drafts:
            return 1
        # 解析最大版本号
        versions = []
        for d in drafts:
            try:
                v = int(d.replace("draft_v", "").replace(".md", ""))
                versions.append(v)
            except ValueError:
                pass
        return max(versions) + 1 if versions else 1
    
    def _get_latest_draft_version(self) -> int:
        """获取最新草稿版本号"""
        return self._get_next_draft_version() - 1
    
    def _cleanup_old_drafts(self):
        """清理超出限制的旧草稿"""
        drafts = self.list_drafts()
        if len(drafts) > self.config.max_drafts:
            for old_draft in drafts[:-self.config.max_drafts]:
                self.delete_file(f"{self.config.scratch_dir}/{old_draft}")
    
    # ========== 上下文管理 ==========
    
    def save_gathered_context(self, context: str):
        """保存收集的上下文"""
        self.write_file(f"{self.config.context_dir}/gathered.md", context)
    
    def get_gathered_context(self) -> Optional[str]:
        """获取收集的上下文"""
        path = f"{self.config.context_dir}/gathered.md"
        if self.exists(path):
            return self.read_file(path)
        return None
    
    def save_context_summary(self, summary: str):
        """保存上下文摘要"""
        self.write_file(f"{self.config.context_dir}/summary.md", summary)
    
    def add_reference(self, name: str, content: str):
        """添加引用资料"""
        self.write_file(
            f"{self.config.context_dir}/references/{name}.md",
            content
        )
    
    # ========== 日志管理 ==========
    
    def log_action(self, action: str, details: Dict[str, Any] = None):
        """记录操作日志"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details or {}
        }
        self.append_file(
            f"{self.config.logs_dir}/actions.jsonl",
            json.dumps(log_entry, ensure_ascii=False) + "\n"
        )
    
    def log_error(self, error: str, details: Dict[str, Any] = None):
        """记录错误日志"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "error": error,
            "details": details or {}
        }
        self.append_file(
            f"{self.config.logs_dir}/errors.jsonl",
            json.dumps(log_entry, ensure_ascii=False) + "\n"
        )
    
    def update_progress(
        self,
        stage: str,
        progress: float,
        message: str = ""
    ):
        """更新进度"""
        progress_data = {
            "stage": stage,
            "progress": progress,
            "message": message,
            "updated_at": datetime.now().isoformat()
        }
        self.write_file(
            f"{self.config.logs_dir}/{self.config.progress_file}",
            json.dumps(progress_data, ensure_ascii=False, indent=2)
        )
    
    def get_progress(self) -> Optional[Dict[str, Any]]:
        """获取进度"""
        path = f"{self.config.logs_dir}/{self.config.progress_file}"
        if self.exists(path):
            return json.loads(self.read_file(path))
        return None
    
    # ========== 状态管理（错误恢复）==========
    
    def save_checkpoint(self, state: Dict[str, Any]) -> str:
        """
        保存检查点（用于错误恢复）
        
        Args:
            state: 状态字典
            
        Returns:
            检查点文件路径
        """
        checkpoint_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        checkpoint_path = f"{self.config.state_dir}/checkpoint_{checkpoint_id}.json"
        
        checkpoint_data = {
            "checkpoint_id": checkpoint_id,
            "timestamp": datetime.now().isoformat(),
            "state": state
        }
        
        self.write_file(
            checkpoint_path,
            json.dumps(checkpoint_data, ensure_ascii=False, indent=2)
        )
        
        # 清理旧检查点
        self._cleanup_old_checkpoints()
        
        return checkpoint_path
    
    def load_latest_checkpoint(self) -> Optional[Dict[str, Any]]:
        """加载最新检查点"""
        checkpoints = self.list_checkpoints()
        if not checkpoints:
            return None
        
        latest = checkpoints[-1]
        checkpoint_data = json.loads(
            self.read_file(f"{self.config.state_dir}/{latest}")
        )
        return checkpoint_data.get("state")
    
    def list_checkpoints(self) -> List[str]:
        """列出所有检查点"""
        state_dir = self.root / self.config.state_dir
        checkpoints = sorted([
            f.name for f in state_dir.glob("checkpoint_*.json")
        ])
        return checkpoints
    
    def _cleanup_old_checkpoints(self):
        """清理超出限制的旧检查点"""
        checkpoints = self.list_checkpoints()
        if len(checkpoints) > self.config.max_checkpoints:
            for old_cp in checkpoints[:-self.config.max_checkpoints]:
                self.delete_file(f"{self.config.state_dir}/{old_cp}")
    
    # ========== 子 Agent 支持（增强隔离）==========
    
    def create_sub_workspace(
        self,
        sub_task_id: str,
        isolation_level: "IsolationLevel" = None,
        resource_limits: "ResourceLimits" = None
    ) -> "AgentWorkspace":
        """
        创建子 Agent 工作空间
        
        Args:
            sub_task_id: 子任务 ID
            isolation_level: 隔离级别 (NONE, SOFT, STRICT)
            resource_limits: 资源限制
            
        Returns:
            子 Agent 工作空间
        """
        from .isolation import IsolationLevel, ResourceLimits
        
        # 默认使用 SOFT 隔离
        if isolation_level is None:
            isolation_level = IsolationLevel.SOFT
        
        sub_config = WorkspaceConfig(
            base_path=str(self.root / self.config.sub_agents_dir),
            task_id=sub_task_id,
            isolation_level=isolation_level,
            resource_limits=resource_limits,
        )
        return AgentWorkspace(sub_config)
    
    def list_sub_workspaces(self) -> List[str]:
        """列出所有子 Agent 工作空间"""
        sub_dir = self.root / self.config.sub_agents_dir
        if not sub_dir.exists():
            return []
        return [d.name for d in sub_dir.iterdir() if d.is_dir()]
    
    # ========== 工具方法 ==========
    
    def get_absolute_path(self, relative_path: str) -> str:
        """获取绝对路径"""
        return str(self.root / relative_path)
    
    def get_workspace_size(self) -> int:
        """获取工作空间大小（字节）"""
        total_size = 0
        for file_path in self.root.rglob('*'):
            if file_path.is_file():
                total_size += file_path.stat().st_size
        return total_size
    
    def cleanup(self, keep_output: bool = True):
        """
        清理工作空间
        
        Args:
            keep_output: 是否保留输出目录
        """
        for item in self.root.iterdir():
            if keep_output and item.name == self.config.output_dir:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
```

---

## 4. 草稿迭代管理器

```python
# etf_common/agent_framework/workspace/draft_manager.py

from typing import Dict, Any, List, Optional
from datetime import datetime
import difflib


class DraftManager:
    """
    草稿迭代管理器
    
    支持：
    - 版本管理
    - 差异对比
    - 合并建议
    """
    
    def __init__(self, workspace: "AgentWorkspace"):
        self.workspace = workspace
    
    def create_draft(
        self,
        content: str,
        metadata: Dict[str, Any] = None
    ) -> int:
        """
        创建新草稿
        
        Args:
            content: 草稿内容
            metadata: 元数据（来源、修改原因等）
            
        Returns:
            草稿版本号
        """
        version = self.workspace._get_next_draft_version()
        
        # 写入草稿内容
        self.workspace.write_draft(content, version)
        
        # 写入元数据
        if metadata:
            meta_path = f"scratch/draft_v{version}.meta.json"
            import json
            self.workspace.write_file(
                meta_path,
                json.dumps({
                    "version": version,
                    "created_at": datetime.now().isoformat(),
                    **metadata
                }, ensure_ascii=False, indent=2)
            )
        
        return version
    
    def get_diff(
        self,
        version1: int,
        version2: int = None
    ) -> str:
        """
        获取两个版本之间的差异
        
        Args:
            version1: 版本1
            version2: 版本2（默认为最新版本）
            
        Returns:
            差异文本（unified diff 格式）
        """
        if version2 is None:
            version2 = self.workspace._get_latest_draft_version()
        
        content1 = self.workspace.read_draft(version1) or ""
        content2 = self.workspace.read_draft(version2) or ""
        
        diff = difflib.unified_diff(
            content1.splitlines(keepends=True),
            content2.splitlines(keepends=True),
            fromfile=f"draft_v{version1}.md",
            tofile=f"draft_v{version2}.md"
        )
        
        return ''.join(diff)
    
    def get_all_versions(self) -> List[Dict[str, Any]]:
        """
        获取所有版本信息
        
        Returns:
            版本信息列表
        """
        drafts = self.workspace.list_drafts()
        versions = []
        
        for draft in drafts:
            version = int(draft.replace("draft_v", "").replace(".md", ""))
            
            # 读取元数据
            meta_path = f"scratch/draft_v{version}.meta.json"
            metadata = {}
            if self.workspace.exists(meta_path):
                import json
                metadata = json.loads(self.workspace.read_file(meta_path))
            
            versions.append({
                "version": version,
                "file": draft,
                "metadata": metadata
            })
        
        return versions
    
    def rollback(self, version: int) -> str:
        """
        回滚到指定版本
        
        Args:
            version: 目标版本号
            
        Returns:
            回滚后的草稿内容
        """
        content = self.workspace.read_draft(version)
        if content is None:
            raise ValueError(f"版本 {version} 不存在")
        
        # 创建新版本（保留历史）
        self.create_draft(
            content,
            metadata={"rollback_from": version}
        )
        
        return content
```

---

## 5. 使用示例

```python
# 示例：使用工作空间进行 Agent 任务

async def example_workflow():
    # 1. 创建工作空间
    workspace = AgentWorkspace(WorkspaceConfig(
        base_path="./workspaces",
        task_id="analysis_20240101_001"
    ))
    
    # 2. 写入任务
    workspace.write_task(
        task_description="""
        请分析贵州茅台（600519.SH）的投资价值，包括：
        1. 财务分析：营收、利润、现金流
        2. 估值分析：PE、PB 历史分位
        3. 风险评估：主要风险因素
        4. 投资建议：买入/持有/卖出
        """,
        input_data={
            "company": "贵州茅台",
            "ticker": "600519.SH",
            "date": "2024-01-01"
        }
    )
    
    # 3. 收集上下文
    gathered_context = """
    ## 公司基本信息
    贵州茅台是中国最大的白酒生产企业...
    
    ## 财务数据
    - 2023年营收：1505亿元
    - 净利润：747亿元
    - 毛利率：91.5%
    """
    workspace.save_gathered_context(gathered_context)
    
    # 4. 写入草稿（迭代）
    draft_v1 = """
    # 贵州茅台投资分析报告
    
    ## 一、财务分析
    公司营收保持稳定增长...
    """
    workspace.write_draft(draft_v1, version=1)
    
    # 5. 基于反馈修改
    draft_v2 = """
    # 贵州茅台投资分析报告（修订版）
    
    ## 一、财务分析
    公司营收保持稳定增长，2023年实现营收1505亿元，同比增长18.5%...
    
    ## 二、估值分析
    当前PE为35倍，处于历史50%分位...
    """
    workspace.write_draft(draft_v2, version=2)
    
    # 6. 写入最终结果
    workspace.write_result({
        "company": "贵州茅台",
        "summary": "长期看好，当前估值合理",
        "investment_opinion": "推荐",
        "target_price": 1900
    })
    
    # 7. 记录日志
    workspace.log_action("analysis_complete", {
        "iterations": 2,
        "final_score": 0.85
    })
    
    # 8. 创建子 Agent 工作空间
    sub_workspace = workspace.create_sub_workspace("risk_analysis_001")
    sub_workspace.write_task(
        "分析贵州茅台的主要风险因素",
        {"company": "贵州茅台"}
    )
    
    print("工作空间创建完成:", workspace.root)
```

---

## 6. 子工作空间隔离机制

### 6.1 设计目标

子 Agent 工作空间需要与父工作空间和其他子工作空间隔离，以确保：

- **安全性**：防止子 Agent 访问或修改父工作空间的敏感数据
- **稳定性**：子 Agent 的错误不会影响父工作空间
- **资源控制**：限制子 Agent 的资源使用

### 6.2 隔离级别

```python
# src/workspace/isolation.py

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class IsolationLevel(Enum):
    """工作空间隔离级别"""
    
    NONE = "none"       # 无隔离，完全访问父工作空间
    SOFT = "soft"       # 软隔离，可读父工作空间，写入隔离
    STRICT = "strict"   # 严格隔离，完全独立


@dataclass
class ResourceLimits:
    """子工作空间资源限制"""
    
    max_files: Optional[int] = None          # 最大文件数量
    max_total_size_mb: Optional[int] = None  # 最大总大小 (MB)
    max_cpu_time_seconds: Optional[int] = None  # 最大 CPU 时间
    max_memory_mb: Optional[int] = None      # 最大内存使用


class WorkspaceIsolationError(Exception):
    """工作空间隔离错误"""
    pass


class ResourceLimitExceededError(WorkspaceIsolationError):
    """资源限制超出错误"""
    
    def __init__(self, resource_type: str, limit: Any, current: Any):
        super().__init__(
            f"Resource limit exceeded for {resource_type}: "
            f"limit={limit}, current={current}"
        )
        self.resource_type = resource_type
        self.limit = limit
        self.current = current
```

### 6.3 隔离级别对比

| 隔离级别 | 读取父空间 | 写入父空间 | 资源限制 | 适用场景 |
|----------|------------|------------|----------|----------|
| NONE | ✅ | ✅ | ❌ | 可信子 Agent |
| SOFT | ✅ | ❌ | ✅ | 默认模式 |
| STRICT | ❌ | ❌ | ✅ | 不可信代码 |

### 6.4 使用示例

```python
from workspace import AgentWorkspace, WorkspaceConfig
from workspace.isolation import IsolationLevel, ResourceLimits

# 创建主工作空间
main_workspace = AgentWorkspace(WorkspaceConfig(
    base_path="./workspaces",
    task_id="main_task"
))

# 创建隔离的子工作空间
sub_workspace = main_workspace.create_sub_workspace(
    sub_task_id="risky_analysis",
    isolation_level=IsolationLevel.STRICT,
    resource_limits=ResourceLimits(
        max_files=100,
        max_total_size_mb=50,
        max_cpu_time_seconds=300,
        max_memory_mb=512
    )
)

# 子 Agent 只能在自己的空间内操作
sub_workspace.write_file("output/result.json", '{"status": "ok"}')

# 尝试访问父空间将失败（STRICT 模式）
try:
    sub_workspace.read_file("../main_task/input/data.json")
except WorkspaceIsolationError:
    print("访问被拒绝：严格隔离模式")
```

### 6.5 路径验证

```python
class IsolatedWorkspace(AgentWorkspace):
    """带隔离功能的工作空间"""
    
    def __init__(
        self,
        config: WorkspaceConfig,
        parent_workspace: Optional["AgentWorkspace"] = None,
        isolation_level: IsolationLevel = IsolationLevel.SOFT,
        resource_limits: Optional[ResourceLimits] = None,
    ):
        super().__init__(config)
        self.parent_workspace = parent_workspace
        self.isolation_level = isolation_level
        self.resource_limits = resource_limits
    
    def _validate_path(self, path: str, operation: str = "read") -> Path:
        """验证路径访问权限"""
        resolved = (self.root / path).resolve()
        
        # 检查是否在工作空间内
        if not str(resolved).startswith(str(self.root.resolve())):
            if self.isolation_level == IsolationLevel.STRICT:
                raise WorkspaceIsolationError(
                    f"Path escapes workspace: {path}"
                )
            elif self.isolation_level == IsolationLevel.SOFT:
                if operation == "write":
                    raise WorkspaceIsolationError(
                        f"Cannot write outside workspace: {path}"
                    )
        
        return resolved
    
    def _check_resource_limits(self):
        """检查资源限制"""
        if self.resource_limits is None:
            return
        
        if self.resource_limits.max_files:
            file_count = sum(1 for _ in self.root.rglob('*') if _.is_file())
            if file_count >= self.resource_limits.max_files:
                raise ResourceLimitExceededError(
                    "files", self.resource_limits.max_files, file_count
                )
        
        if self.resource_limits.max_total_size_mb:
            total_size = self.get_workspace_size() / (1024 * 1024)
            if total_size >= self.resource_limits.max_total_size_mb:
                raise ResourceLimitExceededError(
                    "total_size_mb", 
                    self.resource_limits.max_total_size_mb, 
                    total_size
                )
```

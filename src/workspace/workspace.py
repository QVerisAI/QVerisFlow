"""
Agent 工作空间管理

提供文件系统优先的 Agent 工作空间实现，所有输入输出、
上下文、草稿等都通过文件系统交互。

增强特性：
- 子工作空间隔离机制
- 资源限制和监控
- 路径安全验证
"""

from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Union, TYPE_CHECKING
from datetime import datetime
import json
from src.utils.logger import get_logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .isolation import IsolationManager, IsolationLevel, ResourceLimits

logger = get_logger()


class WorkspaceConfig(BaseModel):
    """工作空间配置"""

    base_path: str = Field(description="基础路径")
    task_id: str = Field(description="任务ID")
    auto_create: bool = Field(default=True, description="自动创建目录")
    preserve_files: bool = Field(default=True, description="保留文件")

    # 隔离配置（用于子工作空间）
    isolation_level: Optional[str] = Field(default=None, description="隔离级别")
    max_files: Optional[int] = Field(default=None, description="最大文件数")
    max_total_size: Optional[int] = Field(default=None, description="最大总大小(字节)")


class AgentWorkspace:
    """
    Agent 工作空间

    文件系统优先的设计，所有交互通过文件系统：
    - input/ - 输入文件
    - output/ - 输出文件
    - scratch/ - 草稿和临时文件
    - context/ - 收集的上下文
    - logs/ - 日志文件
    - state/ - 状态快照

    支持子工作空间隔离：
    - 隔离级别控制（none/soft/strict）
    - 资源限制（文件数量、大小）
    - 路径安全验证
    """

    def __init__(
        self,
        config: WorkspaceConfig,
        isolation_manager: Optional["IsolationManager"] = None,
    ):
        self.config = config
        self.root = Path(config.base_path) / config.task_id

        # 隔离管理器（用于子工作空间）
        self._isolation_manager = isolation_manager

        # 目录结构
        self.input_dir = self.root / "input"
        self.output_dir = self.root / "output"
        self.scratch_dir = self.root / "scratch"
        self.context_dir = self.root / "context"
        self.logs_dir = self.root / "logs"
        self.state_dir = self.root / "state"

        if config.auto_create:
            self._ensure_directories()

    def _ensure_directories(self):
        """确保所有目录存在"""
        for directory in [
            self.input_dir,
            self.output_dir,
            self.scratch_dir,
            self.context_dir,
            self.logs_dir,
            self.state_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_path(cls, workspace_path: str) -> "AgentWorkspace":
        """从现有路径加载工作空间"""
        path = Path(workspace_path)
        return cls(
            WorkspaceConfig(
                base_path=str(path.parent), task_id=path.name, auto_create=False
            )
        )

    # ========== 任务管理 ==========

    def write_task(
        self, task_description: str, input_data: Optional[Dict[str, Any]] = None
    ):
        """
        写入任务描述和输入数据

        Args:
            task_description: 任务描述文本
            input_data: 输入数据字典
        """
        task_file = self.input_dir / "task.md"
        task_file.write_text(task_description, encoding="utf-8")

        if input_data:
            input_file = self.input_dir / "input.json"
            with open(input_file, "w", encoding="utf-8") as f:
                json.dump(input_data, f, ensure_ascii=False, indent=2)

        logger.info(f"任务已写入: {self.config.task_id}")

    def read_task(self) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        读取任务描述和输入数据

        Returns:
            (任务描述, 输入数据) 元组
        """
        task_file = self.input_dir / "task.md"
        if not task_file.exists():
            raise FileNotFoundError(f"任务文件不存在: {task_file}")

        task_description = task_file.read_text(encoding="utf-8")

        input_file = self.input_dir / "input.json"
        input_data = None
        if input_file.exists():
            with open(input_file, "r", encoding="utf-8") as f:
                input_data = json.load(f)

        return task_description, input_data

    # ========== 结果管理 ==========

    def write_result(self, result: Dict[str, Any]):
        """
        写入执行结果

        Args:
            result: 结果字典
        """
        result_file = self.output_dir / "result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"结果已写入: {result_file}")

    def read_result(self) -> Optional[Dict[str, Any]]:
        """
        读取执行结果

        Returns:
            结果字典，如果不存在则返回 None
        """
        result_file = self.output_dir / "result.json"
        if not result_file.exists():
            return None

        with open(result_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # ========== 草稿管理 ==========

    def write_draft(self, content: str, version: Optional[int] = None) -> str:
        """
        写入草稿

        Args:
            content: 草稿内容
            version: 版本号，如果为 None 则自动递增

        Returns:
            草稿文件路径
        """
        if version is None:
            # 自动计算版本号
            existing_drafts = list(self.scratch_dir.glob("draft_v*.md"))
            version = len(existing_drafts) + 1

        draft_file = self.scratch_dir / f"draft_v{version}.md"
        draft_file.write_text(content, encoding="utf-8")

        logger.info(f"草稿已保存: {draft_file}")
        return str(draft_file)

    def read_draft(self, version: Optional[int] = None) -> Optional[str]:
        """
        读取草稿

        Args:
            version: 版本号，如果为 None 则读取最新版本

        Returns:
            草稿内容，如果不存在则返回 None
        """
        if version is None:
            # 读取最新版本
            drafts = sorted(self.scratch_dir.glob("draft_v*.md"))
            if not drafts:
                return None
            draft_file = drafts[-1]
        else:
            draft_file = self.scratch_dir / f"draft_v{version}.md"

        if not draft_file.exists():
            return None

        return draft_file.read_text(encoding="utf-8")

    def list_drafts(self) -> List[Dict[str, Any]]:
        """
        列出所有草稿

        Returns:
            草稿信息列表
        """
        drafts = []
        for draft_file in sorted(self.scratch_dir.glob("draft_v*.md")):
            version = int(draft_file.stem.replace("draft_v", ""))
            drafts.append(
                {
                    "version": version,
                    "path": str(draft_file),
                    "size": draft_file.stat().st_size,
                    "modified_at": datetime.fromtimestamp(
                        draft_file.stat().st_mtime
                    ).isoformat(),
                }
            )
        return drafts

    # ========== 上下文管理 ==========

    def save_gathered_context(self, context: str):
        """
        保存收集的上下文

        Args:
            context: 上下文内容
        """
        context_file = self.context_dir / "gathered_context.md"
        context_file.write_text(context, encoding="utf-8")

        logger.info(f"上下文已保存: {context_file}")

    def get_gathered_context(self) -> Optional[str]:
        """
        获取收集的上下文

        Returns:
            上下文内容，如果不存在则返回 None
        """
        context_file = self.context_dir / "gathered_context.md"
        if not context_file.exists():
            return None

        return context_file.read_text(encoding="utf-8")

    # ========== 日志管理 ==========

    def log_action(self, action: str, details: Optional[Dict[str, Any]] = None):
        """
        记录操作日志

        Args:
            action: 操作名称
            details: 详细信息
        """
        log_file = self.logs_dir / "actions.jsonl"

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details or {},
        }

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def log_error(self, error: str, details: Optional[Dict[str, Any]] = None):
        """
        记录错误日志

        Args:
            error: 错误消息
            details: 详细信息
        """
        log_file = self.logs_dir / "errors.jsonl"

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "error": error,
            "details": details or {},
        }

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def log_tool_call(
        self,
        tool_id: str,
        input_params: Dict[str, Any],
        output: Any = None,
        error: str = None,
        phase: str = "complete",
        duration_ms: float = None,
    ):
        """
        记录工具调用日志到文件（文件系统交互总线核心功能）

        Args:
            tool_id: 工具 ID
            input_params: 输入参数
            output: 输出结果（可选）
            error: 错误信息（可选）
            phase: 阶段 (start/success/error/complete)
            duration_ms: 执行时长（毫秒）
        """
        log_file = self.logs_dir / "tool_calls.jsonl"

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "tool_id": tool_id,
            "phase": phase,
            "input": input_params,
        }

        if duration_ms is not None:
            log_entry["duration_ms"] = duration_ms

        if output is not None:
            # 对于大型输出，可以选择写入单独文件
            if isinstance(output, (dict, list)) and len(str(output)) > 10000:
                # 大型输出写入单独文件
                output_file = (
                    self.logs_dir
                    / f"tool_output_{tool_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
                )
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2, default=str)
                log_entry["output_file"] = str(output_file.relative_to(self.root))
            else:
                log_entry["output"] = output

        if error:
            log_entry["error"] = error

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False, default=str) + "\n")

        logger.debug(f"工具调用已记录: {tool_id} ({phase})")

    def get_tool_call_history(
        self, tool_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取工具调用历史

        Args:
            tool_id: 工具 ID（可选，不指定则返回所有）

        Returns:
            工具调用记录列表
        """
        log_file = self.logs_dir / "tool_calls.jsonl"
        if not log_file.exists():
            return []

        history = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if tool_id is None or entry.get("tool_id") == tool_id:
                        history.append(entry)

        return history

    def log_llm_call(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        response: str = None,
        tool_calls: List[Dict[str, Any]] = None,
        tokens_used: int = None,
        duration_ms: float = None,
        error: str = None,
    ):
        """
        记录 LLM 调用日志到文件

        Args:
            model: 模型名称
            messages: 消息列表
            response: LLM 响应内容（可选）
            tool_calls: 工具调用列表（可选）
            tokens_used: 使用的 token 数量（可选）
            duration_ms: 执行时长（毫秒）
            error: 错误信息（可选）
        """
        log_file = self.logs_dir / "llm_calls.jsonl"

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "messages": messages,
        }

        if response is not None:
            # 对于大型响应，截断并标记
            if len(str(response)) > 10000:
                log_entry["response"] = str(response)[:10000]
                log_entry["response_truncated"] = True
            else:
                log_entry["response"] = response

        if tool_calls:
            log_entry["tool_calls"] = tool_calls

        if tokens_used is not None:
            log_entry["tokens_used"] = tokens_used

        if duration_ms is not None:
            log_entry["duration_ms"] = duration_ms

        if error:
            log_entry["error"] = error

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False, default=str) + "\n")

        logger.debug(
            f"LLM 调用已记录: {model} (耗时 {duration_ms:.2f}ms)"
            if duration_ms
            else f"LLM 调用已记录: {model}"
        )

    def get_llm_call_history(self) -> List[Dict[str, Any]]:
        """
        获取 LLM 调用历史

        Returns:
            LLM 调用记录列表
        """
        log_file = self.logs_dir / "llm_calls.jsonl"
        if not log_file.exists():
            return []

        history = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    history.append(json.loads(line))

        return history

    # ========== 状态管理 ==========

    async def save_checkpoint(self, state: Dict[str, Any]) -> str:
        """
        保存检查点（异步执行）

        Args:
            state: 状态字典

        Returns:
            检查点文件路径
        """
        import asyncio

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        checkpoint_file = self.state_dir / f"checkpoint_{timestamp}.json"

        def _sync_write():
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2, default=str)

        await asyncio.to_thread(_sync_write)
        logger.info(f"检查点已保存: {checkpoint_file}")
        return str(checkpoint_file)

    async def load_checkpoint(
        self, checkpoint_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        加载检查点（异步执行）

        Args:
            checkpoint_id: 检查点 ID（时间戳），如果为 None 则加载最新的

        Returns:
            状态字典，如果不存在则返回 None
        """
        import asyncio

        if checkpoint_id is None:
            # 加载最新检查点
            checkpoints = sorted(self.state_dir.glob("checkpoint_*.json"))
            if not checkpoints:
                return None
            checkpoint_file = checkpoints[-1]
        else:
            checkpoint_file = self.state_dir / f"checkpoint_{checkpoint_id}.json"

        if not checkpoint_file.exists():
            return None

        def _sync_read():
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                return json.load(f)

        return await asyncio.to_thread(_sync_read)

    # ========== 文件操作 ==========

    def ls(self, path: str = "") -> List[str]:
        """
        列出目录内容（Unix 风格）

        Args:
            path: 目录路径（相对于工作空间根目录）

        Returns:
            文件和目录名列表
        """
        target = self.root / path
        if not target.exists():
            return []
        return sorted([f.name for f in target.iterdir()])

    def write_file(self, relative_path: str, content: str) -> str:
        """
        写入文件到工作空间

        Args:
            relative_path: 相对于工作空间根目录的路径
            content: 文件内容

        Returns:
            文件的完整路径
        """
        file_path = self.root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return str(file_path)

    def read_file(self, relative_path: str) -> str:
        """
        从工作空间读取文件

        Args:
            relative_path: 相对于工作空间根目录的路径

        Returns:
            文件内容
        """
        file_path = self.root / relative_path
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        return file_path.read_text(encoding="utf-8")

    def read_file_lines(
        self,
        relative_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """
        读取文件指定行范围

        Args:
            relative_path: 相对于工作空间根目录的路径
            start_line: 起始行号（1-indexed，可选）
            end_line: 结束行号（1-indexed，可选）

        Returns:
            文件内容（指定行范围）
        """
        content = self.read_file(relative_path)
        lines = content.split("\n")

        start = (start_line - 1) if start_line else 0
        end = end_line if end_line else len(lines)

        return "\n".join(lines[start:end])

    def append_file(self, relative_path: str, content: str) -> str:
        """
        追加内容到文件

        Args:
            relative_path: 相对于工作空间根目录的路径
            content: 追加的内容

        Returns:
            文件的完整路径
        """
        file_path = self.root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(content)
        return str(file_path)

    def edit_file(self, relative_path: str, old_content: str, new_content: str) -> str:
        """
        编辑文件（替换指定内容）

        Args:
            relative_path: 相对于工作空间根目录的路径
            old_content: 要替换的旧内容
            new_content: 新内容

        Returns:
            文件的完整路径
        """
        file_path = self.root / relative_path
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        content = file_path.read_text(encoding="utf-8")
        if old_content not in content:
            raise ValueError(f"未找到要替换的内容: {old_content[:50]}...")

        new_file_content = content.replace(old_content, new_content, 1)
        file_path.write_text(new_file_content, encoding="utf-8")
        return str(file_path)

    def delete_file(self, relative_path: str) -> bool:
        """
        删除文件

        Args:
            relative_path: 相对于工作空间根目录的路径

        Returns:
            是否成功删除
        """
        file_path = self.root / relative_path
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def list_files(self, pattern: str = "*") -> List[str]:
        """
        列出工作空间中的文件

        Args:
            pattern: 文件匹配模式（glob）

        Returns:
            文件路径列表（相对路径）
        """
        files = []
        for file_path in self.root.rglob(pattern):
            if file_path.is_file():
                relative_path = file_path.relative_to(self.root)
                files.append(str(relative_path))
        return sorted(files)

    # ========== 子工作空间 ==========

    def create_sub_workspace(
        self,
        sub_task_id: str,
        isolation_level: Optional[Union[str, "IsolationLevel"]] = None,
        resource_limits: Optional["ResourceLimits"] = None,
        shared_context: Optional[List[str]] = None,
    ) -> "AgentWorkspace":
        """
        创建子工作空间

        为子 Agent 创建具有适当隔离级别的工作空间。

        Args:
            sub_task_id: 子任务ID
            isolation_level: 隔离级别 (none/soft/strict)，默认 soft
            resource_limits: 资源限制配置
            shared_context: 需要共享的上下文文件列表

        Returns:
            AgentWorkspace: 子工作空间实例
        """
        from .isolation import (
            IsolationLevel,
            IsolationManager,
            ResourceLimits,
            IsolatedWorkspaceBuilder,
        )

        # 解析隔离级别
        if isolation_level is None:
            level = IsolationLevel.SOFT
        elif isinstance(isolation_level, str):
            level = IsolationLevel(isolation_level)
        else:
            level = isolation_level

        # 使用构建器创建隔离子工作空间
        builder = IsolatedWorkspaceBuilder(self)
        sub_workspace, isolation_manager = builder.build(
            sub_task_id=sub_task_id,
            isolation_level=level,
            resource_limits=resource_limits or ResourceLimits(),
            shared_context=shared_context,
            inherit_config=True,
        )

        # 将隔离管理器附加到子工作空间
        sub_workspace._isolation_manager = isolation_manager

        logger.info(
            f"创建子工作空间: {sub_workspace.root}, " f"隔离级别: {level.value}"
        )
        return sub_workspace

    def create_sub_workspace_simple(self, sub_task_id: str) -> "AgentWorkspace":
        """
        创建简单子工作空间（无隔离）

        兼容旧接口，创建无隔离限制的子工作空间。

        Args:
            sub_task_id: 子任务ID

        Returns:
            AgentWorkspace: 子工作空间实例
        """
        sub_config = WorkspaceConfig(
            base_path=str(self.root / "sub_agents"),
            task_id=sub_task_id,
            auto_create=True,
            preserve_files=self.config.preserve_files,
        )
        sub_workspace = AgentWorkspace(sub_config)
        logger.info(f"创建子工作空间: {sub_workspace.root}")
        return sub_workspace

    def list_sub_workspaces(self) -> List[str]:
        """
        列出所有子工作空间

        Returns:
            子工作空间ID列表
        """
        sub_agents_dir = self.root / "sub_agents"
        if not sub_agents_dir.exists():
            return []
        return [d.name for d in sub_agents_dir.iterdir() if d.is_dir()]

    def get_sub_workspace(self, sub_task_id: str) -> Optional["AgentWorkspace"]:
        """
        获取已存在的子工作空间

        Args:
            sub_task_id: 子任务ID

        Returns:
            AgentWorkspace 或 None（如果不存在）
        """
        sub_workspace_path = self.root / "sub_agents" / sub_task_id
        if sub_workspace_path.exists():
            sub_workspace = AgentWorkspace.from_path(str(sub_workspace_path))

            # 尝试加载隔离配置
            isolation_config_path = sub_workspace_path / ".isolation_config.json"
            if isolation_config_path.exists():
                try:
                    from .isolation import (
                        IsolationManager,
                        IsolationLevel,
                        ResourceLimits,
                    )

                    with open(isolation_config_path, "r") as f:
                        isolation_state = json.load(f)

                    # 重建隔离管理器
                    level = IsolationLevel(isolation_state.get("level", "soft"))
                    limits_data = isolation_state.get("limits", {})
                    limits = ResourceLimits(
                        max_files=limits_data.get("max_files", 1000),
                        max_total_size=limits_data.get(
                            "max_total_size", 100 * 1024 * 1024
                        ),
                        max_file_size=limits_data.get(
                            "max_file_size", 10 * 1024 * 1024
                        ),
                        max_depth=limits_data.get("max_depth", 10),
                        allowed_extensions=set(
                            limits_data.get("allowed_extensions", [])
                        ),
                        blocked_extensions=set(
                            limits_data.get("blocked_extensions", [])
                        ),
                    )

                    sub_workspace._isolation_manager = IsolationManager(
                        parent_root=self.root,
                        child_root=sub_workspace_path,
                        level=level,
                        limits=limits,
                    )
                    sub_workspace._isolation_manager.load_state(isolation_state)
                except Exception as e:
                    logger.warning(f"加载隔离配置失败: {e}")

            return sub_workspace
        return None

    # ========== 隔离相关方法 ==========

    @property
    def isolation_manager(self) -> Optional["IsolationManager"]:
        """获取隔离管理器"""
        return self._isolation_manager

    @property
    def is_isolated(self) -> bool:
        """检查是否是隔离的子工作空间"""
        return self._isolation_manager is not None

    def get_resource_usage(self) -> Optional[Dict[str, Any]]:
        """
        获取资源使用统计

        Returns:
            资源使用信息，非隔离工作空间返回 None
        """
        if self._isolation_manager:
            return self._isolation_manager.get_usage().to_dict()
        return None

    def validate_path(self, relative_path: str) -> Path:
        """
        验证路径安全性

        如果工作空间有隔离管理器，使用隔离管理器验证；
        否则只做基本的路径规范化。

        Args:
            relative_path: 相对路径

        Returns:
            规范化后的绝对路径
        """
        if self._isolation_manager:
            return self._isolation_manager.validate_path(relative_path)

        # 基本路径验证
        normalized = Path(relative_path)
        if ".." in str(normalized):
            raise ValueError(f"路径包含不安全模式: {relative_path}")

        return (self.root / normalized).resolve()

    def safe_write_file(self, relative_path: str, content: str) -> str:
        """
        安全写入文件（带隔离检查）

        Args:
            relative_path: 相对路径
            content: 文件内容

        Returns:
            文件的完整路径
        """
        if self._isolation_manager:
            file_path = self._isolation_manager.safe_write(relative_path, content)
            return str(file_path)
        else:
            return self.write_file(relative_path, content)

    def safe_read_file(self, relative_path: str) -> str:
        """
        安全读取文件（带隔离检查）

        如果是隔离的子工作空间，会按照隔离规则处理：
        - 优先读取子工作空间的文件
        - 如果允许，回退到父工作空间

        Args:
            relative_path: 相对路径

        Returns:
            文件内容
        """
        if self._isolation_manager:
            return self._isolation_manager.safe_read(relative_path)
        else:
            return self.read_file(relative_path)

    def copy_from_parent(
        self, relative_path: str, target_path: Optional[str] = None
    ) -> str:
        """
        从父工作空间复制文件（写时复制）

        Args:
            relative_path: 父工作空间中的相对路径
            target_path: 目标路径（可选）

        Returns:
            复制后的文件路径

        Raises:
            RuntimeError: 非隔离工作空间或隔离级别不允许
        """
        if not self._isolation_manager:
            raise RuntimeError("非隔离工作空间不支持此操作")

        file_path = self._isolation_manager.copy_from_parent(relative_path, target_path)
        return str(file_path)

    # ========== 清理 ==========

    def cleanup(self, keep_output: bool = True):
        """
        清理工作空间

        Args:
            keep_output: 是否保留输出目录
        """
        import shutil

        if not self.config.preserve_files:
            for directory in [
                self.scratch_dir,
                self.context_dir,
                self.logs_dir,
                self.state_dir,
            ]:
                if directory.exists():
                    shutil.rmtree(directory)

            if not keep_output and self.output_dir.exists():
                shutil.rmtree(self.output_dir)

            logger.info(f"工作空间已清理: {self.root}")

"""
工作空间接口定义
"""

from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional, List, Tuple, runtime_checkable


@runtime_checkable
class IWorkspace(Protocol):
    """
    工作空间接口

    定义文件系统交互的标准接口
    """

    # ========== 任务管理 ==========

    def write_task(
        self, task_description: str, input_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """写入任务描述和输入数据"""
        ...

    def read_task(self) -> Tuple[str, Optional[Dict[str, Any]]]:
        """读取任务描述和输入数据"""
        ...

    # ========== 结果管理 ==========

    def write_result(self, result: Dict[str, Any]) -> None:
        """写入执行结果"""
        ...

    def read_result(self) -> Optional[Dict[str, Any]]:
        """读取执行结果"""
        ...

    # ========== 草稿管理 ==========

    def write_draft(self, content: str, version: Optional[int] = None) -> str:
        """写入草稿"""
        ...

    def read_draft(self, version: Optional[int] = None) -> Optional[str]:
        """读取草稿"""
        ...

    def list_drafts(self) -> List[Dict[str, Any]]:
        """列出所有草稿"""
        ...

    # ========== 上下文管理 ==========

    def save_gathered_context(self, context: str) -> None:
        """保存收集的上下文"""
        ...

    def get_gathered_context(self) -> Optional[str]:
        """获取收集的上下文"""
        ...

    # ========== 日志管理 ==========

    def log_action(self, action: str, details: Optional[Dict[str, Any]] = None) -> None:
        """记录操作日志"""
        ...

    def log_error(self, error: str, details: Optional[Dict[str, Any]] = None) -> None:
        """记录错误日志"""
        ...

    def log_tool_call(
        self,
        tool_id: str,
        input_params: Dict[str, Any],
        output: Any = None,
        error: str = None,
        phase: str = "complete",
        duration_ms: float = None,
    ) -> None:
        """记录工具调用日志"""
        ...

    def log_llm_call(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        response: str = None,
        tool_calls: List[Dict[str, Any]] = None,
        tokens_used: int = None,
        duration_ms: float = None,
        error: str = None,
    ) -> None:
        """记录 LLM 调用日志"""
        ...

    # ========== 状态管理 ==========

    async def save_checkpoint(self, state: Dict[str, Any]) -> str:
        """保存检查点（异步执行）"""
        ...

    async def load_checkpoint(
        self, checkpoint_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """加载检查点（异步执行）"""
        ...

    # ========== 文件操作 ==========

    def ls(self, path: str = "") -> List[str]:
        """列出目录内容"""
        ...

    def write_file(self, relative_path: str, content: str) -> str:
        """写入文件"""
        ...

    def read_file(self, relative_path: str) -> str:
        """读取文件"""
        ...

    def read_file_lines(
        self,
        relative_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """读取文件指定行范围"""
        ...

    def list_files(self, pattern: str = "*") -> List[str]:
        """列出工作空间中的文件"""
        ...


class IWorkspaceFactory(ABC):
    """
    工作空间工厂接口
    """

    @abstractmethod
    def create(
        self, base_path: str, task_id: str, auto_create: bool = True
    ) -> IWorkspace:
        """
        创建工作空间

        Args:
            base_path: 基础路径
            task_id: 任务 ID
            auto_create: 是否自动创建目录

        Returns:
            工作空间实例
        """
        ...

    @abstractmethod
    def from_path(self, workspace_path: str) -> IWorkspace:
        """
        从现有路径加载工作空间

        Args:
            workspace_path: 工作空间路径

        Returns:
            工作空间实例
        """
        ...

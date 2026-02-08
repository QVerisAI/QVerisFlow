"""
工作流相关接口定义
"""

from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional, List, runtime_checkable
from enum import Enum


class WorkflowStatus(Enum):
    """工作流状态"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@runtime_checkable
class IWorkflowNode(Protocol):
    """
    工作流节点接口
    """

    @property
    def node_id(self) -> str:
        """节点 ID"""
        ...

    @property
    def node_type(self) -> str:
        """节点类型"""
        ...

    @property
    def dependencies(self) -> List[str]:
        """依赖的节点 ID 列表"""
        ...

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行节点

        Args:
            context: 执行上下文

        Returns:
            执行结果
        """
        ...


@runtime_checkable
class IWorkflowResult(Protocol):
    """
    工作流执行结果接口
    """

    @property
    def workflow_id(self) -> str:
        """工作流 ID"""
        ...

    @property
    def status(self) -> WorkflowStatus:
        """执行状态"""
        ...

    @property
    def node_results(self) -> Dict[str, Any]:
        """各节点执行结果"""
        ...

    @property
    def final_output(self) -> Optional[Any]:
        """最终输出"""
        ...

    @property
    def error(self) -> Optional[str]:
        """错误信息"""
        ...


class IWorkflowEngine(ABC):
    """
    工作流引擎抽象接口

    负责工作流的执行和管理
    """

    @abstractmethod
    async def execute(
        self, workflow_definition: Any, initial_context: Optional[Dict[str, Any]] = None
    ) -> IWorkflowResult:
        """
        执行工作流

        Args:
            workflow_definition: 工作流定义
            initial_context: 初始上下文

        Returns:
            工作流执行结果
        """
        ...

    @abstractmethod
    async def cancel(self, workflow_id: str) -> bool:
        """
        取消工作流执行

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否成功取消
        """
        ...

    @abstractmethod
    async def pause(self, workflow_id: str) -> bool:
        """
        暂停工作流执行

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否成功暂停
        """
        ...

    @abstractmethod
    async def resume_execution(self, workflow_id: str) -> bool:
        """
        恢复已暂停的工作流执行

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否成功恢复
        """
        ...

    @abstractmethod
    async def get_status(self, workflow_id: str) -> WorkflowStatus:
        """
        获取工作流状态

        Args:
            workflow_id: 工作流 ID

        Returns:
            工作流状态
        """
        ...

    @abstractmethod
    async def resume(
        self, workflow_id: str, checkpoint_id: Optional[str] = None
    ) -> IWorkflowResult:
        """
        恢复工作流执行

        Args:
            workflow_id: 工作流 ID
            checkpoint_id: 检查点 ID（可选）

        Returns:
            工作流执行结果
        """
        ...


class ISubAgentManager(ABC):
    """
    子 Agent 管理器接口

    负责管理和协调多个子 Agent
    """

    @abstractmethod
    async def spawn(
        self, agent_definition: Any, task: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        创建并启动子 Agent

        Args:
            agent_definition: Agent 定义
            task: 任务描述
            context: 任务上下文

        Returns:
            子 Agent ID
        """
        ...

    @abstractmethod
    async def wait(
        self, agent_id: str, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        等待子 Agent 完成

        Args:
            agent_id: 子 Agent ID
            timeout: 超时时间（秒）

        Returns:
            执行结果
        """
        ...

    @abstractmethod
    async def wait_all(
        self, agent_ids: List[str], timeout: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        等待所有子 Agent 完成

        Args:
            agent_ids: 子 Agent ID 列表
            timeout: 超时时间（秒）

        Returns:
            执行结果列表
        """
        ...

    @abstractmethod
    async def cancel(self, agent_id: str) -> bool:
        """
        取消子 Agent 执行

        Args:
            agent_id: 子 Agent ID

        Returns:
            是否成功取消
        """
        ...

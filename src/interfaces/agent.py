"""
Agent 相关接口定义
"""

from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional, List, runtime_checkable


@runtime_checkable
class IAgentState(Protocol):
    """
    Agent 状态接口

    定义 Agent 执行过程中的状态结构
    """

    @property
    def agent_id(self) -> str:
        """Agent ID"""
        ...

    @property
    def task_id(self) -> str:
        """任务 ID"""
        ...

    @property
    def iteration(self) -> int:
        """当前迭代次数"""
        ...

    @property
    def phase(self) -> str:
        """当前执行阶段"""
        ...

    @property
    def gathered_context(self) -> str:
        """收集的上下文"""
        ...

    @property
    def verification_passed(self) -> bool:
        """验证是否通过"""
        ...

    @property
    def result(self) -> Optional[Dict[str, Any]]:
        """执行结果"""
        ...

    @property
    def errors(self) -> List[Dict[str, Any]]:
        """错误列表"""
        ...


class IAgentExecutor(ABC):
    """
    Agent 执行器抽象接口

    所有 Agent 实现必须继承此接口
    """

    @abstractmethod
    async def run(
        self,
        task_description: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        运行 Agent

        Args:
            task_description: 任务描述
            input_data: 输入数据

        Returns:
            执行结果字典，包含：
            - success: 是否成功
            - result: 执行结果
            - iterations: 迭代次数
            - error: 错误信息（如果有）
        """
        ...

    @abstractmethod
    async def resume(self, checkpoint_id: str) -> Dict[str, Any]:
        """
        从检查点恢复执行

        Args:
            checkpoint_id: 检查点 ID

        Returns:
            执行结果
        """
        ...

    @property
    @abstractmethod
    def agent_id(self) -> str:
        """获取 Agent ID"""
        ...

    @property
    @abstractmethod
    def definition(self) -> Any:
        """获取 Agent 定义"""
        ...


@runtime_checkable
class IAgentFactory(Protocol):
    """
    Agent 工厂接口

    用于创建 Agent 实例
    """

    def create(self, definition: Any, workspace: Any, **kwargs) -> IAgentExecutor:
        """
        创建 Agent 实例

        Args:
            definition: Agent 定义
            workspace: 工作空间
            **kwargs: 其他参数

        Returns:
            Agent 执行器实例
        """
        ...

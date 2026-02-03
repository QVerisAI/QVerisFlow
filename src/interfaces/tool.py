"""
工具相关接口定义
"""

from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional, List, Callable, runtime_checkable


@runtime_checkable
class ITool(Protocol):
    """
    工具接口

    定义工具的基本结构
    """

    @property
    def tool_id(self) -> str:
        """工具 ID"""
        ...

    @property
    def name(self) -> str:
        """工具名称"""
        ...

    @property
    def description(self) -> str:
        """工具描述"""
        ...

    @property
    def input_schema(self) -> Dict[str, Any]:
        """输入 JSON Schema"""
        ...

    async def execute(
        self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        执行工具

        Args:
            params: 输入参数
            context: 执行上下文

        Returns:
            执行结果
        """
        ...


class IToolRegistry(ABC):
    """
    工具注册表抽象接口

    管理工具的注册、查找和执行
    """

    @abstractmethod
    def register(self, definition: Any, implementation: Callable) -> None:
        """
        注册工具

        Args:
            definition: 工具定义
            implementation: 工具实现函数
        """
        ...

    @abstractmethod
    def get(self, tool_id: str) -> Optional[Any]:
        """
        获取工具定义

        Args:
            tool_id: 工具 ID

        Returns:
            工具定义，不存在返回 None
        """
        ...

    @abstractmethod
    def get_by_alias(self, alias: str) -> Optional[Any]:
        """
        通过别名获取工具定义

        Args:
            alias: 工具别名

        Returns:
            工具定义，不存在返回 None
        """
        ...

    @abstractmethod
    async def execute(
        self,
        tool_id: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        执行工具

        Args:
            tool_id: 工具 ID
            params: 参数字典
            context: 执行上下文

        Returns:
            执行结果
        """
        ...

    @abstractmethod
    def list_all(self) -> List[Dict[str, Any]]:
        """
        列出所有工具

        Returns:
            工具摘要列表
        """
        ...

    @abstractmethod
    def get_by_category(self, category: Any) -> List[Any]:
        """
        按分类获取工具

        Args:
            category: 工具分类

        Returns:
            工具定义列表
        """
        ...


@runtime_checkable
class IToolAdapter(Protocol):
    """
    工具适配器接口

    用于将框架工具转换为其他格式（如 LangChain）
    """

    def convert(self, tool_definition: Any, tool_impl: Callable) -> Any:
        """
        转换工具

        Args:
            tool_definition: 工具定义
            tool_impl: 工具实现

        Returns:
            转换后的工具
        """
        ...

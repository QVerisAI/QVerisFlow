"""
内置工具模块

提供 Agent 框架的核心工具：
- 文件系统工具 (file_ls, file_read, file_write, file_edit)
- Bash 执行工具 (bash_execute)
"""

from typing import TYPE_CHECKING

from .file_tools import (
    file_ls,
    file_read,
    file_write,
    file_edit,
    file_append,
)
from .bash_tools import bash_execute, bash_execute_safe

if TYPE_CHECKING:
    from ..registry import ToolRegistry


def register_builtin_tools(registry: "ToolRegistry") -> None:
    """
    将所有内置工具注册到指定的工具注册表

    内置工具在模块导入时会自动注册到默认的全局注册表 (ToolRegistry.get_default())。
    如果你创建了自定义的 ToolRegistry 实例，需要调用此函数将内置工具注册到你的实例中。

    示例:
    ```python
    from src.tools import ToolRegistry
    from src.tools.builtin import register_builtin_tools

    # 创建自定义注册表
    my_registry = ToolRegistry()

    # 注册所有内置工具
    register_builtin_tools(my_registry)

    # 现在 my_registry 包含所有内置工具
    print(my_registry.list_all())
    ```

    Args:
        registry: 目标工具注册表
    """
    # 所有使用 @tool 装饰器的函数都会有 _tool_definition 属性
    builtin_tools = [
        file_ls,
        file_read,
        file_write,
        file_edit,
        file_append,
        bash_execute,
        bash_execute_safe,
    ]

    for tool_func in builtin_tools:
        if hasattr(tool_func, "_tool_definition"):
            definition = tool_func._tool_definition
            # 注册到目标 registry
            registry.register(definition, tool_func)


__all__ = [
    # 文件系统工具
    "file_ls",
    "file_read",
    "file_write",
    "file_edit",
    "file_append",
    # Bash 工具
    "bash_execute",
    "bash_execute_safe",
    # 注册辅助函数
    "register_builtin_tools",
]

"""
文件系统工具

提供 Agent 与文件系统交互的核心工具，是"文件系统作为交互总线"设计理念的核心实现。

工具列表：
- file_ls: 列出目录内容
- file_read: 读取文件内容
- file_write: 写入文件
- file_edit: 编辑文件（替换内容）
- file_append: 追加内容到文件
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from ..registry import tool, ToolRegistry
from ...definitions import ToolCategory


@tool(
    tool_id="file_ls",
    name="列出目录",
    alias="列出目录",
    description=(
        "List files and directories in a workspace path. "
        "ALWAYS use this BEFORE file_read to verify files exist! "
        "Workspace structure: input/ (task.md, input.json), output/ (results), "
        "scratch/ (drafts), context/ (gathered data), logs/, state/. "
        "Use path='' for root, 'input' for input folder."
    ),
    category=ToolCategory.FILE_SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Directory path relative to workspace. "
                    "Examples: '' (root), 'input' (input files), 'output' (results). "
                    "Default is '' (workspace root)."
                ),
            }
        },
        "required": [],
    },
    output_schema={
        "type": "array",
        "items": {"type": "string"},
        "description": "文件和目录名列表",
    },
    is_async=True,
)
async def file_ls(path: str = "", _context: Dict = None) -> List[str]:
    """
    列出目录内容

    Args:
        path: 目录路径（相对于工作空间）
        _context: 执行上下文（包含 workspace）

    Returns:
        文件和目录名列表
    """
    workspace = _context.get("workspace") if _context else None

    if workspace and hasattr(workspace, "ls"):
        return workspace.ls(path)

    # 回退到直接文件系统操作
    target = Path(path) if path else Path(".")
    if not target.exists():
        return []
    return sorted([f.name for f in target.iterdir()])


@tool(
    tool_id="file_read",
    name="读取文件",
    alias="读取文件",
    description=(
        "Read file contents from the workspace. IMPORTANT: "
        "1) Always use file_ls FIRST to check what files exist; "
        "2) Task description is in 'input/task.md'; "
        "3) Cannot read directories - use file_ls instead. "
        "Workspace structure: input/, output/, scratch/, context/, logs/, state/"
    ),
    category=ToolCategory.FILE_SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "File path relative to workspace (e.g., 'input/task.md'). "
                    "Cannot be a directory. Use file_ls to list available files first."
                ),
            },
            "start_line": {
                "type": "integer",
                "description": "起始行号（1-indexed，可选）",
            },
            "end_line": {
                "type": "integer",
                "description": "结束行号（1-indexed，可选）",
            },
        },
        "required": ["path"],
    },
    output_schema={"type": "string", "description": "文件内容"},
    is_async=True,
)
async def file_read(
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    _context: Dict = None,
) -> str:
    """
    读取文件内容

    Args:
        path: 文件路径
        start_line: 起始行号（1-indexed）
        end_line: 结束行号（1-indexed）
        _context: 执行上下文

    Returns:
        文件内容
    """
    workspace = _context.get("workspace") if _context else None

    # 检查是否尝试读取目录
    if workspace:
        check_path = (
            Path(workspace.root) / path if hasattr(workspace, "root") else Path(path)
        )
    else:
        check_path = Path(path)

    if check_path.exists() and check_path.is_dir():
        raise IsADirectoryError(
            f"'{path}' 是一个目录，不能用 file_read 读取。请使用 file_ls 来列出目录内容。"
        )

    if workspace:
        if start_line is not None or end_line is not None:
            if hasattr(workspace, "read_file_lines"):
                return workspace.read_file_lines(path, start_line, end_line)
        if hasattr(workspace, "read_file"):
            return workspace.read_file(path)

    # 回退到直接文件系统操作
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(
            f"文件不存在: {path}。请先使用 file_ls 查看工作空间中有哪些文件。"
        )

    content = file_path.read_text(encoding="utf-8")

    if start_line is not None or end_line is not None:
        lines = content.split("\n")
        start = (start_line - 1) if start_line else 0
        end = end_line if end_line else len(lines)
        return "\n".join(lines[start:end])

    return content


@tool(
    tool_id="file_write",
    name="写入文件",
    alias="写入文件",
    description="写入内容到文件。如果文件已存在则覆盖，不存在则创建。",
    category=ToolCategory.FILE_SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对于工作空间）"},
            "content": {"type": "string", "description": "要写入的内容"},
        },
        "required": ["path", "content"],
    },
    output_schema={"type": "string", "description": "写入的文件完整路径"},
    is_async=True,
)
async def file_write(path: str, content: str, _context: Dict = None) -> str:
    """
    写入文件

    Args:
        path: 文件路径
        content: 文件内容
        _context: 执行上下文

    Returns:
        文件的完整路径
    """
    workspace = _context.get("workspace") if _context else None

    if workspace and hasattr(workspace, "write_file"):
        return workspace.write_file(path, content)

    # 回退到直接文件系统操作
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return str(file_path.absolute())


@tool(
    tool_id="file_edit",
    name="编辑文件",
    alias="编辑文件",
    description="编辑现有文件，将指定的旧内容替换为新内容。适用于局部修改。",
    category=ToolCategory.FILE_SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对于工作空间）"},
            "old_content": {
                "type": "string",
                "description": "要替换的旧内容（必须精确匹配）",
            },
            "new_content": {"type": "string", "description": "替换后的新内容"},
        },
        "required": ["path", "old_content", "new_content"],
    },
    output_schema={"type": "string", "description": "编辑后的文件完整路径"},
    is_async=True,
)
async def file_edit(
    path: str, old_content: str, new_content: str, _context: Dict = None
) -> str:
    """
    编辑文件（替换内容）

    Args:
        path: 文件路径
        old_content: 要替换的旧内容
        new_content: 新内容
        _context: 执行上下文

    Returns:
        文件的完整路径
    """
    workspace = _context.get("workspace") if _context else None

    if workspace and hasattr(workspace, "edit_file"):
        return workspace.edit_file(path, old_content, new_content)

    # 回退到直接文件系统操作
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    content = file_path.read_text(encoding="utf-8")
    if old_content not in content:
        raise ValueError(f"未找到要替换的内容: {old_content[:50]}...")

    new_file_content = content.replace(old_content, new_content, 1)
    file_path.write_text(new_file_content, encoding="utf-8")
    return str(file_path.absolute())


@tool(
    tool_id="file_append",
    name="追加文件",
    alias="追加文件",
    description="追加内容到文件末尾。如果文件不存在则创建。",
    category=ToolCategory.FILE_SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对于工作空间）"},
            "content": {"type": "string", "description": "要追加的内容"},
        },
        "required": ["path", "content"],
    },
    output_schema={"type": "string", "description": "追加后的文件完整路径"},
    is_async=True,
)
async def file_append(path: str, content: str, _context: Dict = None) -> str:
    """
    追加内容到文件

    Args:
        path: 文件路径
        content: 要追加的内容
        _context: 执行上下文

    Returns:
        文件的完整路径
    """
    workspace = _context.get("workspace") if _context else None

    if workspace and hasattr(workspace, "append_file"):
        return workspace.append_file(path, content)

    # 回退到直接文件系统操作
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(content)
    return str(file_path.absolute())


def register_file_tools(registry: ToolRegistry = None):
    """
    注册所有文件系统工具到指定的注册表

    如果不指定 registry，则使用默认的单例注册表。
    工具在导入时会自动注册到默认注册表。

    Args:
        registry: 工具注册表（可选）
    """
    # 工具已通过装饰器自动注册到默认注册表
    # 此函数主要用于文档说明和可能的自定义注册场景
    pass

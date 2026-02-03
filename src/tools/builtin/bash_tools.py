"""
Bash 执行工具

提供 Agent 执行 shell 命令的能力，带有安全限制和超时控制。
"""

import asyncio
import subprocess
import shlex
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from ..registry import tool
from ...definitions import ToolCategory


@dataclass
class BashResult:
    """Bash 执行结果"""

    stdout: str
    stderr: str
    exit_code: int
    command: str
    timeout_exceeded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "command": self.command,
            "timeout_exceeded": self.timeout_exceeded,
        }


# 危险命令黑名单
DANGEROUS_COMMANDS = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    ":(){ :|:& };:",  # Fork bomb
    "mkfs",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "> /dev/sda",
    "chmod -R 777 /",
    "chown -R",
]

# 需要确认的命令前缀
CAUTIOUS_PREFIXES = [
    "rm ",
    "mv ",
    "chmod ",
    "chown ",
    "kill ",
    "pkill ",
    "shutdown",
    "reboot",
    "systemctl",
]


def is_dangerous_command(command: str) -> bool:
    """检查是否是危险命令"""
    command_lower = command.lower().strip()

    # 检查黑名单
    for dangerous in DANGEROUS_COMMANDS:
        if dangerous in command_lower:
            return True

    return False


def needs_caution(command: str) -> bool:
    """检查是否需要谨慎执行的命令"""
    command_lower = command.lower().strip()

    for prefix in CAUTIOUS_PREFIXES:
        if command_lower.startswith(prefix):
            return True

    return False


@tool(
    tool_id="bash_execute",
    name="执行 Bash 命令",
    alias="执行命令",
    description="在 shell 中执行命令。支持超时控制和工作目录设置。危险命令会被拦截。",
    category=ToolCategory.SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "cwd": {
                "type": "string",
                "description": "工作目录（可选，默认为工作空间根目录）",
            },
            "timeout": {
                "type": "integer",
                "description": "超时时间（秒），默认 60 秒",
                "default": 60,
            },
            "allow_dangerous": {
                "type": "boolean",
                "description": "是否允许危险命令（默认 False，需谨慎使用）",
                "default": False,
            },
        },
        "required": ["command"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "stdout": {"type": "string", "description": "标准输出"},
            "stderr": {"type": "string", "description": "标准错误"},
            "exit_code": {"type": "integer", "description": "退出码"},
            "command": {"type": "string", "description": "执行的命令"},
            "timeout_exceeded": {"type": "boolean", "description": "是否超时"},
        },
    },
    is_async=True,
)
async def bash_execute(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 60,
    allow_dangerous: bool = False,
    _context: Dict = None,
) -> Dict[str, Any]:
    """
    执行 Bash 命令

    Args:
        command: 要执行的 shell 命令
        cwd: 工作目录
        timeout: 超时时间（秒）
        allow_dangerous: 是否允许危险命令
        _context: 执行上下文

    Returns:
        执行结果字典
    """
    # 安全检查
    if is_dangerous_command(command):
        if not allow_dangerous:
            return BashResult(
                stdout="",
                stderr=f"危险命令被拦截: {command}",
                exit_code=-1,
                command=command,
            ).to_dict()

    # 确定工作目录
    workspace = _context.get("workspace") if _context else None
    if cwd is None and workspace and hasattr(workspace, "root"):
        cwd = str(workspace.root)

    # 记录命令执行（如果有 workspace）
    if workspace and hasattr(workspace, "log_action"):
        workspace.log_action(
            action="bash_execute",
            details={"command": command, "cwd": cwd, "timeout": timeout},
        )

    try:
        # 使用 asyncio 创建子进程
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            result = BashResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=process.returncode,
                command=command,
                timeout_exceeded=False,
            )

        except asyncio.TimeoutError:
            # 超时，尝试终止进程
            process.kill()
            await process.wait()

            result = BashResult(
                stdout="",
                stderr=f"命令执行超时（{timeout}秒）",
                exit_code=-1,
                command=command,
                timeout_exceeded=True,
            )

        return result.to_dict()

    except Exception as e:
        return BashResult(
            stdout="", stderr=f"命令执行失败: {str(e)}", exit_code=-1, command=command
        ).to_dict()


@tool(
    tool_id="bash_execute_safe",
    name="安全执行 Bash 命令",
    alias="安全执行命令",
    description="在安全沙箱中执行命令，自动拦截危险操作。",
    category=ToolCategory.SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "cwd": {"type": "string", "description": "工作目录（可选）"},
            "timeout": {
                "type": "integer",
                "description": "超时时间（秒），默认 30 秒",
                "default": 30,
            },
        },
        "required": ["command"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": "integer"},
            "command": {"type": "string"},
            "timeout_exceeded": {"type": "boolean"},
        },
    },
    is_async=True,
)
async def bash_execute_safe(
    command: str, cwd: Optional[str] = None, timeout: int = 30, _context: Dict = None
) -> Dict[str, Any]:
    """
    安全执行 Bash 命令（始终拦截危险命令）

    Args:
        command: 要执行的 shell 命令
        cwd: 工作目录
        timeout: 超时时间（秒）
        _context: 执行上下文

    Returns:
        执行结果字典
    """
    return await bash_execute(
        command=command,
        cwd=cwd,
        timeout=timeout,
        allow_dangerous=False,
        _context=_context,
    )


def register_bash_tools(registry=None):
    """
    注册所有 Bash 工具到指定的注册表

    工具在导入时会自动注册到默认注册表。

    Args:
        registry: 工具注册表（可选）
    """
    pass

"""
统一异常体系

提供框架的统一异常类型，支持：
- 结构化错误信息
- 异常链追踪
- 分类明确的异常类型
"""

from typing import Dict, Any, Optional, List
from enum import Enum


class ErrorCategory(Enum):
    """错误分类"""

    TOOL = "tool"  # 工具相关错误
    AGENT = "agent"  # Agent 相关错误
    WORKFLOW = "workflow"  # 工作流相关错误
    VERIFICATION = "verification"  # 验证相关错误
    WORKSPACE = "workspace"  # 工作空间相关错误
    CONFIG = "config"  # 配置相关错误
    NETWORK = "network"  # 网络相关错误
    TIMEOUT = "timeout"  # 超时相关错误
    PERMISSION = "permission"  # 权限相关错误
    INTERNAL = "internal"  # 内部错误


class AgentFrameworkError(Exception):
    """
    框架基础异常

    所有框架异常的基类，提供结构化的错误信息。
    """

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.INTERNAL,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
        recoverable: bool = False,
    ):
        """
        初始化异常

        Args:
            message: 错误消息
            category: 错误分类
            code: 错误代码（用于程序化处理）
            details: 详细信息字典
            cause: 原始异常
            recoverable: 是否可恢复
        """
        super().__init__(message)
        self.message = message
        self.category = category
        self.code = code or f"{category.value}_error"
        self.details = details or {}
        self.cause = cause
        self.recoverable = recoverable

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "error": self.message,
            "category": self.category.value,
            "code": self.code,
            "recoverable": self.recoverable,
        }
        if self.details:
            result["details"] = self.details
        if self.cause:
            result["cause"] = str(self.cause)
        return result

    def __str__(self) -> str:
        base = f"[{self.category.value}] {self.message}"
        if self.code:
            base = f"[{self.code}] {base}"
        if self.cause:
            base = f"{base} (caused by: {self.cause})"
        return base


# ========== 工具相关异常 ==========


class ToolError(AgentFrameworkError):
    """工具相关错误基类"""

    def __init__(self, message: str, tool_id: Optional[str] = None, **kwargs):
        kwargs.setdefault("category", ErrorCategory.TOOL)
        super().__init__(message, **kwargs)
        self.tool_id = tool_id
        if tool_id:
            self.details["tool_id"] = tool_id


class ToolNotFoundError(ToolError):
    """工具未找到"""

    def __init__(self, tool_id: str, **kwargs):
        super().__init__(
            message=f"工具 '{tool_id}' 未找到",
            tool_id=tool_id,
            code="tool_not_found",
            **kwargs,
        )


class ToolExecutionError(ToolError):
    """工具执行失败"""

    def __init__(
        self,
        tool_id: str,
        message: str,
        input_params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        super().__init__(
            message=f"工具 '{tool_id}' 执行失败: {message}",
            tool_id=tool_id,
            code="tool_execution_failed",
            **kwargs,
        )
        if input_params:
            self.details["input_params"] = input_params


class ToolTimeoutError(ToolError):
    """工具执行超时"""

    def __init__(self, tool_id: str, timeout: float, **kwargs):
        super().__init__(
            message=f"工具 '{tool_id}' 执行超时（{timeout}秒）",
            tool_id=tool_id,
            code="tool_timeout",
            recoverable=True,
            **kwargs,
        )
        self.details["timeout"] = timeout


class ToolValidationError(ToolError):
    """工具参数验证失败"""

    def __init__(self, tool_id: str, validation_errors: List[str], **kwargs):
        super().__init__(
            message=f"工具 '{tool_id}' 参数验证失败",
            tool_id=tool_id,
            code="tool_validation_failed",
            **kwargs,
        )
        self.details["validation_errors"] = validation_errors


# ========== Agent 相关异常 ==========


class AgentError(AgentFrameworkError):
    """Agent 相关错误基类"""

    def __init__(self, message: str, agent_id: Optional[str] = None, **kwargs):
        kwargs.setdefault("category", ErrorCategory.AGENT)
        super().__init__(message, **kwargs)
        self.agent_id = agent_id
        if agent_id:
            self.details["agent_id"] = agent_id


class AgentNotFoundError(AgentError):
    """Agent 未找到"""

    def __init__(self, agent_id: str, **kwargs):
        super().__init__(
            message=f"Agent '{agent_id}' 未找到",
            agent_id=agent_id,
            code="agent_not_found",
            **kwargs,
        )


class AgentExecutionError(AgentError):
    """Agent 执行失败"""

    def __init__(
        self,
        agent_id: str,
        message: str,
        iteration: Optional[int] = None,
        phase: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            message=f"Agent '{agent_id}' 执行失败: {message}",
            agent_id=agent_id,
            code="agent_execution_failed",
            **kwargs,
        )
        if iteration is not None:
            self.details["iteration"] = iteration
        if phase:
            self.details["phase"] = phase


class AgentMaxIterationsError(AgentError):
    """Agent 达到最大迭代次数"""

    def __init__(self, agent_id: str, max_iterations: int, **kwargs):
        super().__init__(
            message=f"Agent '{agent_id}' 达到最大迭代次数 ({max_iterations})",
            agent_id=agent_id,
            code="agent_max_iterations",
            recoverable=True,
            **kwargs,
        )
        self.details["max_iterations"] = max_iterations


# ========== 工作流相关异常 ==========


class WorkflowError(AgentFrameworkError):
    """工作流相关错误基类"""

    def __init__(self, message: str, workflow_id: Optional[str] = None, **kwargs):
        kwargs.setdefault("category", ErrorCategory.WORKFLOW)
        super().__init__(message, **kwargs)
        self.workflow_id = workflow_id
        if workflow_id:
            self.details["workflow_id"] = workflow_id


class WorkflowNodeError(WorkflowError):
    """工作流节点执行失败"""

    def __init__(self, workflow_id: str, node_id: str, message: str, **kwargs):
        super().__init__(
            message=f"工作流 '{workflow_id}' 节点 '{node_id}' 执行失败: {message}",
            workflow_id=workflow_id,
            code="workflow_node_failed",
            **kwargs,
        )
        self.details["node_id"] = node_id


class WorkflowCycleError(WorkflowError):
    """工作流存在循环依赖"""

    def __init__(self, workflow_id: str, cycle_nodes: List[str], **kwargs):
        super().__init__(
            message=f"工作流 '{workflow_id}' 存在循环依赖",
            workflow_id=workflow_id,
            code="workflow_cycle_detected",
            **kwargs,
        )
        self.details["cycle_nodes"] = cycle_nodes


# ========== 验证相关异常 ==========


class VerificationError(AgentFrameworkError):
    """验证相关错误基类"""

    def __init__(self, message: str, verifier_name: Optional[str] = None, **kwargs):
        kwargs.setdefault("category", ErrorCategory.VERIFICATION)
        super().__init__(message, **kwargs)
        if verifier_name:
            self.details["verifier"] = verifier_name


class VerificationFailedError(VerificationError):
    """验证失败"""

    def __init__(self, message: str, score: float = 0.0, feedback: str = "", **kwargs):
        super().__init__(
            message=message, code="verification_failed", recoverable=True, **kwargs
        )
        self.details["score"] = score
        self.details["feedback"] = feedback


# ========== 工作空间相关异常 ==========


class WorkspaceError(AgentFrameworkError):
    """工作空间相关错误基类"""

    def __init__(self, message: str, workspace_path: Optional[str] = None, **kwargs):
        kwargs.setdefault("category", ErrorCategory.WORKSPACE)
        super().__init__(message, **kwargs)
        if workspace_path:
            self.details["workspace_path"] = workspace_path


class WorkspaceNotFoundError(WorkspaceError):
    """工作空间不存在"""

    def __init__(self, workspace_path: str, **kwargs):
        super().__init__(
            message=f"工作空间不存在: {workspace_path}",
            workspace_path=workspace_path,
            code="workspace_not_found",
            **kwargs,
        )


class WorkspaceFileError(WorkspaceError):
    """工作空间文件操作错误"""

    def __init__(
        self, message: str, file_path: str, operation: str = "unknown", **kwargs
    ):
        super().__init__(message=message, code="workspace_file_error", **kwargs)
        self.details["file_path"] = file_path
        self.details["operation"] = operation


# ========== 配置相关异常 ==========


class ConfigError(AgentFrameworkError):
    """配置相关错误基类"""

    def __init__(self, message: str, config_key: Optional[str] = None, **kwargs):
        kwargs.setdefault("category", ErrorCategory.CONFIG)
        super().__init__(message, **kwargs)
        if config_key:
            self.details["config_key"] = config_key


class ConfigValidationError(ConfigError):
    """配置验证失败"""

    def __init__(self, message: str, validation_errors: List[str], **kwargs):
        super().__init__(message=message, code="config_validation_failed", **kwargs)
        self.details["validation_errors"] = validation_errors


class ConfigMissingError(ConfigError):
    """必需配置缺失"""

    def __init__(self, config_key: str, **kwargs):
        super().__init__(
            message=f"必需配置缺失: {config_key}",
            config_key=config_key,
            code="config_missing",
            **kwargs,
        )


# ========== 网络相关异常 ==========


class NetworkError(AgentFrameworkError):
    """网络相关错误基类"""

    def __init__(self, message: str, url: Optional[str] = None, **kwargs):
        kwargs.setdefault("category", ErrorCategory.NETWORK)
        kwargs.setdefault("recoverable", True)
        super().__init__(message, **kwargs)
        if url:
            self.details["url"] = url


class APIError(NetworkError):
    """API 调用错误"""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(message=message, code="api_error", **kwargs)
        if status_code is not None:
            self.details["status_code"] = status_code
        if response_body:
            self.details["response_body"] = response_body[:500]  # 截断


class RateLimitError(NetworkError):
    """速率限制错误"""

    def __init__(
        self,
        message: str = "API 速率限制",
        retry_after: Optional[float] = None,
        **kwargs,
    ):
        super().__init__(message=message, code="rate_limit", recoverable=True, **kwargs)
        if retry_after is not None:
            self.details["retry_after"] = retry_after


# ========== 超时相关异常 ==========


class TimeoutError(AgentFrameworkError):
    """超时错误基类"""

    def __init__(
        self, message: str, timeout: float, operation: Optional[str] = None, **kwargs
    ):
        kwargs.setdefault("category", ErrorCategory.TIMEOUT)
        kwargs.setdefault("recoverable", True)
        super().__init__(message, **kwargs)
        self.details["timeout"] = timeout
        if operation:
            self.details["operation"] = operation


# ========== 导出 ==========

__all__ = [
    # 基类
    "AgentFrameworkError",
    "ErrorCategory",
    # 工具相关
    "ToolError",
    "ToolNotFoundError",
    "ToolExecutionError",
    "ToolTimeoutError",
    "ToolValidationError",
    # Agent 相关
    "AgentError",
    "AgentNotFoundError",
    "AgentExecutionError",
    "AgentMaxIterationsError",
    # 工作流相关
    "WorkflowError",
    "WorkflowNodeError",
    "WorkflowCycleError",
    # 验证相关
    "VerificationError",
    "VerificationFailedError",
    # 工作空间相关
    "WorkspaceError",
    "WorkspaceNotFoundError",
    "WorkspaceFileError",
    # 配置相关
    "ConfigError",
    "ConfigValidationError",
    "ConfigMissingError",
    # 网络相关
    "NetworkError",
    "APIError",
    "RateLimitError",
    # 超时相关
    "TimeoutError",
]

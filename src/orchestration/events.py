"""
工作流执行事件定义

统一定义所有执行事件类型，减少遗漏风险。
"""

from enum import Enum
from typing import Set
import uuid
from datetime import datetime


class ExecutionEventType(str, Enum):
    """工作流执行事件类型"""

    # 工作流级别事件
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"
    WORKFLOW_CANCELLED = "workflow_cancelled"

    # 节点级别事件
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_SKIPPED = "node_skipped"
    NODE_PROGRESS = "node_progress"  # 节点执行中间状态（如工具调用）
    NODE_THINKING = "node_thinking"  # Agent 推理/思考 token 流
    NODE_STREAM = "node_stream"  # Agent 内容 token 流
    NODE_ACTIVITY = "node_activity"  # 富活动更新（工具使用、决策等）

    # 进度更新事件
    PROGRESS_UPDATE = "progress_update"

    # 兼容旧事件名（逐步废弃）
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"


# 所有执行事件类型的集合（用于快速判断）
EXECUTION_EVENT_TYPES: Set[str] = {e.value for e in ExecutionEventType}

# 需要转发到前端的执行事件类型
FRONTEND_EXECUTION_EVENTS: Set[str] = {
    ExecutionEventType.WORKFLOW_STARTED.value,
    ExecutionEventType.WORKFLOW_COMPLETED.value,
    ExecutionEventType.WORKFLOW_FAILED.value,
    ExecutionEventType.WORKFLOW_PAUSED.value,
    ExecutionEventType.WORKFLOW_RESUMED.value,
    ExecutionEventType.WORKFLOW_CANCELLED.value,
    ExecutionEventType.NODE_STARTED.value,
    ExecutionEventType.NODE_COMPLETED.value,
    ExecutionEventType.NODE_FAILED.value,
    ExecutionEventType.NODE_SKIPPED.value,
    ExecutionEventType.NODE_PROGRESS.value,
    ExecutionEventType.NODE_THINKING.value,
    ExecutionEventType.NODE_STREAM.value,
    ExecutionEventType.NODE_ACTIVITY.value,
    ExecutionEventType.PROGRESS_UPDATE.value,
    # 兼容旧事件名
    ExecutionEventType.EXECUTION_STARTED.value,
    ExecutionEventType.EXECUTION_COMPLETED.value,
    ExecutionEventType.EXECUTION_FAILED.value,
}


def is_execution_event(event_type: str) -> bool:
    """
    判断是否为执行事件类型

    Args:
        event_type: 事件类型字符串

    Returns:
        是否为执行事件
    """
    return event_type in EXECUTION_EVENT_TYPES


class EventSequenceGenerator:
    """
    事件序列号生成器

    为每个工作流实例生成递增的事件序列号，用于：
    1. 检测事件丢失
    2. 保证事件顺序
    3. 支持事件重放
    """

    def __init__(self):
        # workflow_id -> 当前序列号
        self._sequences: dict[str, int] = {}

    def next(self, workflow_id: str) -> int:
        """
        获取下一个序列号

        Args:
            workflow_id: 工作流 ID

        Returns:
            递增的序列号（从 1 开始）
        """
        if workflow_id not in self._sequences:
            self._sequences[workflow_id] = 0
        self._sequences[workflow_id] += 1
        return self._sequences[workflow_id]

    def current(self, workflow_id: str) -> int:
        """获取当前序列号（不递增）"""
        return self._sequences.get(workflow_id, 0)

    def reset(self, workflow_id: str) -> None:
        """重置工作流的序列号"""
        if workflow_id in self._sequences:
            del self._sequences[workflow_id]


def generate_event_id() -> str:
    """
    生成唯一的事件 ID

    Returns:
        格式: evt_{timestamp}_{uuid6}
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"evt_{timestamp}_{short_uuid}"

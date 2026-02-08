"""
工作流执行状态机（ExecutionFSM）

为每个工作流执行实例提供集中式的状态管理，作为唯一的事实源（Single Source of Truth）。

状态图：
    IDLE ──start──▶ RUNNING ──pause──▶ PAUSED
                    │                    │
                    ├──complete──▶ COMPLETED
                    ├──fail─────▶ FAILED
                    └──stop─────▶ CANCELLED
                                 ▲
                    PAUSED ──stop─┘
                    PAUSED ──resume──▶ RUNNING
"""

import asyncio
from enum import Enum
from typing import Dict, Optional, Callable, List, Tuple

from src.utils.logger import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExecutionState(str, Enum):
    """工作流执行状态"""

    IDLE = "idle"  # 未执行
    RUNNING = "running"  # 执行中
    PAUSED = "paused"  # 已暂停
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 已失败
    CANCELLED = "cancelled"  # 已取消


class ExecutionEvent(str, Enum):
    """触发状态跳转的事件"""

    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    COMPLETE = "complete"
    FAIL = "fail"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidTransitionError(Exception):
    """非法状态跳转"""

    def __init__(
        self,
        current_state: ExecutionState,
        event: ExecutionEvent,
        message: Optional[str] = None,
    ):
        self.current_state = current_state
        self.event = event
        if message is None:
            message = (
                f"非法状态跳转: 当前状态 {current_state.value}, "
                f"事件 {event.value} 不被允许"
            )
        super().__init__(message)


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------

# 状态转移表（静态，所有实例共享）
TRANSITIONS: Dict[ExecutionState, Dict[ExecutionEvent, ExecutionState]] = {
    ExecutionState.IDLE: {
        ExecutionEvent.START: ExecutionState.RUNNING,
    },
    ExecutionState.RUNNING: {
        ExecutionEvent.PAUSE: ExecutionState.PAUSED,
        ExecutionEvent.STOP: ExecutionState.CANCELLED,
        ExecutionEvent.COMPLETE: ExecutionState.COMPLETED,
        ExecutionEvent.FAIL: ExecutionState.FAILED,
    },
    ExecutionState.PAUSED: {
        ExecutionEvent.RESUME: ExecutionState.RUNNING,
        ExecutionEvent.STOP: ExecutionState.CANCELLED,
    },
    # 终态：不接受任何事件
    ExecutionState.COMPLETED: {},
    ExecutionState.FAILED: {},
    ExecutionState.CANCELLED: {},
}

# 终态集合
TERMINAL_STATES = frozenset(
    {ExecutionState.COMPLETED, ExecutionState.FAILED, ExecutionState.CANCELLED}
)


class ExecutionFSM:
    """
    工作流执行状态机

    为单个工作流执行实例管理状态，提供：
    - 严格的状态转移验证
    - 集成的 asyncio.Event 用于暂停/恢复协调
    - asyncio.Lock 保护并发状态变更
    - 可选的转移回调通知
    """

    def __init__(self, workflow_id: str):
        """
        初始化状态机

        Args:
            workflow_id: 工作流执行 ID
        """
        self.workflow_id = workflow_id
        self._state = ExecutionState.IDLE
        self._lock = asyncio.Lock()

        # 暂停/恢复协调事件
        # - set() 表示「未暂停，可以继续执行」
        # - clear() 表示「已暂停，执行循环应 await 此事件」
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # 初始为非暂停状态

        # 状态转移历史（用于调试）
        self._history: List[Tuple[ExecutionState, ExecutionEvent, ExecutionState]] = []

        # 转移回调列表
        self._listeners: List[
            Callable[
                [ExecutionState, ExecutionEvent, ExecutionState],
                None,
            ]
        ] = []

    # ── 属性 ────────────────────────────────────────

    @property
    def state(self) -> ExecutionState:
        """当前状态"""
        return self._state

    @property
    def pause_event(self) -> asyncio.Event:
        """暂停/恢复协调事件（执行循环应 await 此事件）"""
        return self._pause_event

    @property
    def is_terminal(self) -> bool:
        """是否处于终态"""
        return self._state in TERMINAL_STATES

    @property
    def is_running(self) -> bool:
        """是否处于运行状态"""
        return self._state == ExecutionState.RUNNING

    @property
    def is_paused(self) -> bool:
        """是否处于暂停状态"""
        return self._state == ExecutionState.PAUSED

    @property
    def is_idle(self) -> bool:
        """是否处于空闲状态"""
        return self._state == ExecutionState.IDLE

    # ── 查询方法 ────────────────────────────────────

    def can_transition(self, event: ExecutionEvent) -> bool:
        """
        检查当前状态是否允许指定事件

        Args:
            event: 要检查的事件

        Returns:
            是否允许
        """
        allowed = TRANSITIONS.get(self._state, {})
        return event in allowed

    # ── 状态变更 ────────────────────────────────────

    async def transition(self, event: ExecutionEvent) -> ExecutionState:
        """
        执行状态跳转（异步，带锁保护）

        Args:
            event: 触发事件

        Returns:
            跳转后的新状态

        Raises:
            InvalidTransitionError: 非法跳转
        """
        async with self._lock:
            return self._transition_unlocked(event)

    def transition_sync(self, event: ExecutionEvent) -> ExecutionState:
        """
        同步版本的状态跳转（仅在已经持有锁或确定无并发时使用）

        Args:
            event: 触发事件

        Returns:
            跳转后的新状态

        Raises:
            InvalidTransitionError: 非法跳转
        """
        return self._transition_unlocked(event)

    def _transition_unlocked(self, event: ExecutionEvent) -> ExecutionState:
        """内部：不加锁的状态跳转实现"""
        allowed = TRANSITIONS.get(self._state, {})
        if event not in allowed:
            raise InvalidTransitionError(self._state, event)

        old_state = self._state
        new_state = allowed[event]
        self._state = new_state

        # 记录历史
        self._history.append((old_state, event, new_state))

        # 管理 pause_event
        self._update_pause_event(event, new_state)

        logger.debug(
            f"[FSM] workflow={self.workflow_id}: "
            f"{old_state.value} --{event.value}--> {new_state.value}"
        )

        # 通知监听者
        for listener in self._listeners:
            try:
                listener(old_state, event, new_state)
            except Exception as e:
                logger.warning(f"[FSM] 监听者回调失败: {e}")

        return new_state

    def _update_pause_event(
        self, event: ExecutionEvent, new_state: ExecutionState
    ) -> None:
        """根据状态跳转自动管理 pause_event"""
        if new_state == ExecutionState.PAUSED:
            # 暂停 → 清除事件，让执行循环阻塞
            self._pause_event.clear()
        elif event == ExecutionEvent.RESUME:
            # 恢复 → 设置事件，让执行循环继续
            self._pause_event.set()
        elif event == ExecutionEvent.STOP and not self._pause_event.is_set():
            # 从暂停态取消 → 设置事件，唤醒执行循环以便退出
            self._pause_event.set()
        elif new_state == ExecutionState.RUNNING and event == ExecutionEvent.START:
            # 开始执行 → 确保事件已设置
            self._pause_event.set()

    # ── 监听者管理 ──────────────────────────────────

    def add_listener(
        self,
        listener: Callable[
            [ExecutionState, ExecutionEvent, ExecutionState],
            None,
        ],
    ) -> None:
        """
        添加状态转移监听者

        Args:
            listener: 回调函数，接收 (old_state, event, new_state)
        """
        self._listeners.append(listener)

    def remove_listener(
        self,
        listener: Callable[
            [ExecutionState, ExecutionEvent, ExecutionState],
            None,
        ],
    ) -> None:
        """移除监听者"""
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    # ── 调试 ────────────────────────────────────────

    @property
    def history(
        self,
    ) -> List[Tuple[ExecutionState, ExecutionEvent, ExecutionState]]:
        """状态转移历史"""
        return list(self._history)

    def __repr__(self) -> str:
        return (
            f"ExecutionFSM(workflow_id={self.workflow_id!r}, "
            f"state={self._state.value})"
        )

"""
子 Agent 管理器

提供子 Agent 的生命周期管理、并行执行和结果聚合功能。
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)

from src.utils.logger import get_logger

logger = get_logger()


class SubAgentStatus(str, Enum):
    """子 Agent 状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SubAgentResult:
    """子 Agent 执行结果"""

    task_id: str
    status: SubAgentStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    retries: int = 0

    @property
    def duration_seconds(self) -> Optional[float]:
        """执行耗时（秒）"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    @property
    def is_success(self) -> bool:
        """是否成功"""
        return self.status == SubAgentStatus.COMPLETED


@dataclass
class SubAgentTask:
    """子 Agent 任务定义"""

    task_id: str
    agent_class: Type  # Type[BaseAgent]
    task_description: str
    input_data: Optional[Dict[str, Any]] = None
    agent_kwargs: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # 优先级，数值越大优先级越高
    timeout: Optional[float] = None  # 超时时间（秒）
    max_retries: int = 0


class SubAgentManager:
    """
    子 Agent 管理器

    负责管理子 Agent 的生命周期、并行执行和结果聚合。

    特性：
    - 基于信号量的并行度控制
    - 自动创建隔离的子工作空间
    - 支持超时和重试
    - 支持任务优先级
    - 支持批量并行执行
    - 支持任务取消

    用法：
        ```python
        manager = SubAgentManager(parent_workspace, max_parallel=5)

        # 单个子任务
        result = await manager.spawn(
            agent_class=MyAgent,
            task_description="处理数据",
            input_data={"data": [1, 2, 3]}
        )

        # 批量并行执行
        tasks = [
            {"agent_class": AgentA, "task_description": "任务1"},
            {"agent_class": AgentB, "task_description": "任务2"},
        ]
        results = await manager.spawn_parallel(tasks)
        ```
    """

    def __init__(
        self,
        parent_workspace: Any,  # AgentWorkspace
        max_parallel: int = 5,
        default_timeout: Optional[float] = None,
    ):
        """
        初始化子 Agent 管理器

        Args:
            parent_workspace: 父工作空间
            max_parallel: 最大并行数
            default_timeout: 默认超时时间（秒）
        """
        self.parent_workspace = parent_workspace
        self.max_parallel = max_parallel
        self.default_timeout = default_timeout

        # 信号量控制并行度
        self._semaphore = asyncio.Semaphore(max_parallel)

        # 活动的子 Agent
        self._active_agents: Dict[str, Any] = {}  # task_id -> BaseAgent
        self._active_tasks: Dict[str, asyncio.Task] = {}  # task_id -> asyncio.Task

        # 结果存储
        self._results: Dict[str, SubAgentResult] = {}

        # 取消标志
        self._cancelled = False

        logger.info(f"SubAgentManager 初始化完成，最大并行数: {max_parallel}")

    async def spawn(
        self,
        agent_class: Type,  # Type[BaseAgent]
        task_description: str,
        input_data: Optional[Dict[str, Any]] = None,
        sub_task_id: Optional[str] = None,
        timeout: Optional[float] = None,
        **agent_kwargs,
    ) -> SubAgentResult:
        """
        生成并执行单个子 Agent

        Args:
            agent_class: Agent 类
            task_description: 任务描述
            input_data: 输入数据
            sub_task_id: 子任务ID（可选，自动生成）
            timeout: 超时时间（秒）
            **agent_kwargs: 传递给 Agent 构造函数的额外参数

        Returns:
            SubAgentResult: 执行结果
        """
        task_id = sub_task_id or f"subtask_{uuid.uuid4().hex[:8]}"
        task = SubAgentTask(
            task_id=task_id,
            agent_class=agent_class,
            task_description=task_description,
            input_data=input_data,
            agent_kwargs=agent_kwargs,
            timeout=timeout or self.default_timeout,
        )

        return await self._execute_task(task)

    async def spawn_parallel(
        self,
        tasks: List[Dict[str, Any]],
        fail_fast: bool = False,
    ) -> List[SubAgentResult]:
        """
        批量并行执行多个子 Agent

        Args:
            tasks: 任务列表，每个任务是一个字典，包含：
                - agent_class: Agent 类
                - task_description: 任务描述
                - input_data: 输入数据（可选）
                - sub_task_id: 子任务ID（可选）
                - timeout: 超时时间（可选）
                - **kwargs: 其他 Agent 参数
            fail_fast: 是否在第一个失败时立即停止

        Returns:
            List[SubAgentResult]: 所有任务的执行结果
        """
        if self._cancelled:
            raise RuntimeError("SubAgentManager 已取消")

        # 转换为 SubAgentTask 对象
        sub_tasks = []
        for i, task_dict in enumerate(tasks):
            task_id = task_dict.get("sub_task_id") or f"subtask_{uuid.uuid4().hex[:8]}"
            sub_task = SubAgentTask(
                task_id=task_id,
                agent_class=task_dict["agent_class"],
                task_description=task_dict["task_description"],
                input_data=task_dict.get("input_data"),
                agent_kwargs={
                    k: v
                    for k, v in task_dict.items()
                    if k
                    not in {
                        "agent_class",
                        "task_description",
                        "input_data",
                        "sub_task_id",
                        "timeout",
                        "priority",
                        "max_retries",
                    }
                },
                priority=task_dict.get("priority", 0),
                timeout=task_dict.get("timeout") or self.default_timeout,
                max_retries=task_dict.get("max_retries", 0),
            )
            sub_tasks.append(sub_task)

        # 按优先级排序（高优先级先执行）
        sub_tasks.sort(key=lambda t: t.priority, reverse=True)

        logger.info(f"开始并行执行 {len(sub_tasks)} 个子任务")

        # 创建所有任务的协程
        async def execute_with_error_handling(task: SubAgentTask) -> SubAgentResult:
            try:
                return await self._execute_task(task)
            except Exception as e:
                logger.error(f"子任务 {task.task_id} 执行异常: {e}")
                return SubAgentResult(
                    task_id=task.task_id,
                    status=SubAgentStatus.FAILED,
                    error=str(e),
                    end_time=datetime.now(),
                )

        if fail_fast:
            # 使用 gather 并设置 return_exceptions=False
            async_tasks = [execute_with_error_handling(t) for t in sub_tasks]
            results = await asyncio.gather(*async_tasks)
        else:
            # 收集所有结果，即使有失败
            async_tasks = [execute_with_error_handling(t) for t in sub_tasks]
            results = await asyncio.gather(*async_tasks, return_exceptions=True)
            # 将异常转换为失败结果
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed_results.append(
                        SubAgentResult(
                            task_id=sub_tasks[i].task_id,
                            status=SubAgentStatus.FAILED,
                            error=str(result),
                            end_time=datetime.now(),
                        )
                    )
                else:
                    processed_results.append(result)
            results = processed_results

        success_count = sum(1 for r in results if r.is_success)
        logger.info(f"并行执行完成: {success_count}/{len(results)} 成功")

        return results

    async def spawn_with_retry(
        self,
        agent_class: Type,  # Type[BaseAgent]
        task_description: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        input_data: Optional[Dict[str, Any]] = None,
        sub_task_id: Optional[str] = None,
        timeout: Optional[float] = None,
        **agent_kwargs,
    ) -> SubAgentResult:
        """
        带重试的子 Agent 执行

        Args:
            agent_class: Agent 类
            task_description: 任务描述
            max_retries: 最大重试次数
            retry_delay: 重试间隔（秒）
            input_data: 输入数据
            sub_task_id: 子任务ID
            timeout: 超时时间（秒）
            **agent_kwargs: 传递给 Agent 构造函数的额外参数

        Returns:
            SubAgentResult: 执行结果
        """
        task_id = sub_task_id or f"subtask_{uuid.uuid4().hex[:8]}"
        task = SubAgentTask(
            task_id=task_id,
            agent_class=agent_class,
            task_description=task_description,
            input_data=input_data,
            agent_kwargs=agent_kwargs,
            timeout=timeout or self.default_timeout,
            max_retries=max_retries,
        )

        result = None
        last_error = None

        for attempt in range(max_retries + 1):
            if self._cancelled:
                return SubAgentResult(
                    task_id=task_id,
                    status=SubAgentStatus.CANCELLED,
                    error="Manager was cancelled",
                    retries=attempt,
                )

            try:
                result = await self._execute_task(task)
                if result.is_success:
                    result.retries = attempt
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"子任务 {task_id} 第 {attempt + 1} 次执行失败: {last_error}"
                )

            if attempt < max_retries:
                logger.info(f"子任务 {task_id} 将在 {retry_delay}s 后重试")
                await asyncio.sleep(retry_delay)

        # 所有重试都失败
        return SubAgentResult(
            task_id=task_id,
            status=SubAgentStatus.FAILED,
            error=f"所有 {max_retries + 1} 次尝试都失败。最后错误: {last_error}",
            retries=max_retries,
            end_time=datetime.now(),
        )

    async def _execute_task(self, task: SubAgentTask) -> SubAgentResult:
        """
        执行单个子任务

        Args:
            task: 子任务定义

        Returns:
            SubAgentResult: 执行结果
        """
        if self._cancelled:
            return SubAgentResult(
                task_id=task.task_id,
                status=SubAgentStatus.CANCELLED,
                error="Manager was cancelled",
            )

        result = SubAgentResult(
            task_id=task.task_id,
            status=SubAgentStatus.PENDING,
            start_time=datetime.now(),
        )

        async with self._semaphore:
            result.status = SubAgentStatus.RUNNING
            logger.debug(f"开始执行子任务: {task.task_id}")

            try:
                # 创建子工作空间
                sub_workspace = self.parent_workspace.create_sub_workspace(task.task_id)

                # 创建 Agent 实例
                agent = task.agent_class(
                    workspace=sub_workspace,
                    **task.agent_kwargs,
                )
                self._active_agents[task.task_id] = agent

                # 写入任务
                sub_workspace.write_task(task.task_description, task.input_data)

                # 执行任务（带超时）
                if task.timeout:
                    agent_result = await asyncio.wait_for(
                        agent.run(task.task_description, task.input_data),
                        timeout=task.timeout,
                    )
                else:
                    agent_result = await agent.run(
                        task.task_description, task.input_data
                    )

                result.status = SubAgentStatus.COMPLETED
                result.result = agent_result
                logger.info(f"子任务 {task.task_id} 执行成功")

            except asyncio.TimeoutError:
                result.status = SubAgentStatus.FAILED
                result.error = f"任务超时（{task.timeout}秒）"
                logger.warning(f"子任务 {task.task_id} 超时")

            except asyncio.CancelledError:
                result.status = SubAgentStatus.CANCELLED
                result.error = "任务被取消"
                logger.info(f"子任务 {task.task_id} 被取消")

            except Exception as e:
                result.status = SubAgentStatus.FAILED
                result.error = str(e)
                logger.error(f"子任务 {task.task_id} 失败: {e}")

            finally:
                result.end_time = datetime.now()
                self._results[task.task_id] = result
                self._active_agents.pop(task.task_id, None)

        return result

    def get_active_agents(self) -> Dict[str, Any]:
        """获取当前活动的子 Agent"""
        return dict(self._active_agents)

    def get_results(self) -> Dict[str, SubAgentResult]:
        """获取所有已完成任务的结果"""
        return dict(self._results)

    def get_result(self, task_id: str) -> Optional[SubAgentResult]:
        """获取指定任务的结果"""
        return self._results.get(task_id)

    async def cancel_all(self) -> None:
        """取消所有正在执行的任务"""
        self._cancelled = True
        logger.info("正在取消所有子任务...")

        # 取消所有活动的 asyncio 任务
        for task_id, async_task in list(self._active_tasks.items()):
            if not async_task.done():
                async_task.cancel()
                logger.debug(f"已取消任务: {task_id}")

        # 等待所有任务完成取消
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)

        self._active_tasks.clear()
        self._active_agents.clear()
        logger.info("所有子任务已取消")

    def reset(self) -> None:
        """重置管理器状态"""
        self._cancelled = False
        self._results.clear()
        self._active_agents.clear()
        self._active_tasks.clear()
        logger.debug("SubAgentManager 已重置")

    @property
    def is_cancelled(self) -> bool:
        """是否已取消"""
        return self._cancelled

    @property
    def active_count(self) -> int:
        """当前活动任务数"""
        return len(self._active_agents)

    def get_summary(self) -> Dict[str, Any]:
        """获取执行摘要"""
        results = list(self._results.values())
        completed = [r for r in results if r.status == SubAgentStatus.COMPLETED]
        failed = [r for r in results if r.status == SubAgentStatus.FAILED]
        cancelled = [r for r in results if r.status == SubAgentStatus.CANCELLED]

        total_duration = sum(
            r.duration_seconds for r in results if r.duration_seconds is not None
        )

        return {
            "total_tasks": len(results),
            "completed": len(completed),
            "failed": len(failed),
            "cancelled": len(cancelled),
            "success_rate": len(completed) / len(results) if results else 0,
            "total_duration_seconds": total_duration,
            "average_duration_seconds": total_duration / len(results) if results else 0,
            "is_cancelled": self._cancelled,
        }


class ResultAggregator:
    """
    结果聚合器

    用于聚合多个子 Agent 的执行结果。
    """

    @staticmethod
    def merge_results(
        results: List[SubAgentResult],
        strategy: str = "all",
    ) -> Dict[str, Any]:
        """
        合并结果

        Args:
            results: 子 Agent 结果列表
            strategy: 合并策略
                - "all": 返回所有结果
                - "success_only": 仅返回成功的结果
                - "first_success": 返回第一个成功的结果

        Returns:
            合并后的结果字典
        """
        if strategy == "all":
            return {
                "results": [r.result for r in results if r.result],
                "errors": [
                    {"task_id": r.task_id, "error": r.error} for r in results if r.error
                ],
                "summary": {
                    "total": len(results),
                    "success": sum(1 for r in results if r.is_success),
                    "failed": sum(1 for r in results if not r.is_success),
                },
            }

        elif strategy == "success_only":
            successful = [r for r in results if r.is_success]
            return {
                "results": [r.result for r in successful],
                "count": len(successful),
            }

        elif strategy == "first_success":
            for r in results:
                if r.is_success:
                    return {"result": r.result, "task_id": r.task_id}
            return {"result": None, "error": "No successful results"}

        else:
            raise ValueError(f"未知的合并策略: {strategy}")

    @staticmethod
    def reduce_results(
        results: List[SubAgentResult],
        reducer: Callable[[List[Any]], Any],
    ) -> Any:
        """
        使用自定义 reducer 函数聚合结果

        Args:
            results: 子 Agent 结果列表
            reducer: 聚合函数，接收结果列表，返回聚合值

        Returns:
            聚合后的值
        """
        successful_results = [r.result for r in results if r.is_success and r.result]
        return reducer(successful_results)

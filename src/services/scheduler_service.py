"""
定时任务调度服务

使用 APScheduler 实现工作流的定时执行功能。
支持 cron 表达式配置和时区设置。
"""

import asyncio
import os
from datetime import datetime
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field

from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class ScheduledJob:
    """定时任务信息"""
    workflow_db_id: str
    workflow_id: str
    schedule_config: Dict[str, Any]
    job_id: Optional[str] = None
    next_run_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None
    last_run_status: Optional[str] = None


class WorkflowSchedulerService:
    """
    工作流定时任务调度服务
    
    负责管理工作流的定时执行，包括：
    - 添加/移除定时任务
    - 解析 cron 表达式
    - 触发工作流执行
    - 管理任务生命周期
    """
    
    def __init__(self):
        self._scheduler = None
        self._jobs: Dict[str, ScheduledJob] = {}  # workflow_db_id -> ScheduledJob
        self._execution_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
        self._initialized = False
        self._sio = None  # Socket.IO 实例，用于广播事件
        
    def set_sio(self, sio) -> None:
        """
        设置 Socket.IO 实例
        
        Args:
            sio: Socket.IO 服务器实例
        """
        self._sio = sio
        logger.info("SchedulerService: Socket.IO 实例已设置")
        
    async def initialize(self) -> None:
        """初始化调度器"""
        if self._initialized:
            return
            
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
            
            self._scheduler = AsyncIOScheduler(
                timezone=os.getenv("TZ", "Asia/Shanghai"),
            )
            self._scheduler.start()
            self._initialized = True
            logger.info("定时任务调度器已启动")
            
            # 从数据库加载已有的定时任务
            await self._load_scheduled_workflows()
            
        except ImportError:
            logger.warning(
                "APScheduler 未安装，定时任务功能不可用。"
                "请安装: pip install apscheduler"
            )
        except Exception as e:
            logger.error(f"初始化定时任务调度器失败: {e}", exc_info=True)
    
    async def _load_scheduled_workflows(self) -> None:
        """从数据库加载已有的定时任务"""
        try:
            from src.services import WorkflowService
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import (
                WorkflowDefinitionRepository,
                WorkflowExecutionRepository,
            )
            from src.storage.config import PostgreSQLConfig
            
            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()
            
            try:
                workflow_repo = WorkflowDefinitionRepository(db._session_factory)
                execution_repo = WorkflowExecutionRepository(db._session_factory)
                service = WorkflowService(workflow_repo, execution_repo)
                
                scheduled_workflows = await service.get_scheduled_workflows()
                
                for workflow in scheduled_workflows:
                    if workflow.schedule_config and workflow.schedule_config.get("enabled"):
                        await self.add_workflow_schedule(
                            workflow_db_id=workflow.id,
                            workflow_id=workflow.workflow_id,
                            schedule_config=workflow.schedule_config,
                        )
                
                logger.info(f"已加载 {len(scheduled_workflows)} 个定时任务")
                
            finally:
                await db.close()
                
        except Exception as e:
            logger.error(f"加载定时任务失败: {e}", exc_info=True)
    
    def set_execution_callback(
        self, 
        callback: Callable[[str, str], Awaitable[None]]
    ) -> None:
        """
        设置工作流执行回调
        
        Args:
            callback: 异步回调函数，接收 (workflow_db_id, workflow_id) 参数
        """
        self._execution_callback = callback
    
    async def add_workflow_schedule(
        self,
        workflow_db_id: str,
        workflow_id: str,
        schedule_config: Dict[str, Any],
    ) -> bool:
        """
        添加工作流定时任务
        
        Args:
            workflow_db_id: 工作流数据库 ID
            workflow_id: 工作流 ID
            schedule_config: 定时任务配置
            
        Returns:
            是否添加成功
        """
        if not self._initialized or not self._scheduler:
            logger.warning("调度器未初始化，无法添加定时任务")
            return False
            
        try:
            from apscheduler.triggers.cron import CronTrigger
            
            # 如果已存在，先移除
            if workflow_db_id in self._jobs:
                await self.remove_workflow_schedule(workflow_db_id)
            
            # 检查是否启用
            if not schedule_config.get("enabled", True):
                logger.info(f"定时任务未启用: {workflow_db_id}")
                return True
            
            # 解析 cron 表达式
            cron_expression = schedule_config.get("cronExpression", "0 8 * * *")
            timezone = schedule_config.get("timezone", "Asia/Shanghai")
            
            # 解析 cron 表达式为触发器
            trigger = self._parse_cron_expression(cron_expression, timezone)
            if not trigger:
                logger.error(f"无效的 cron 表达式: {cron_expression}")
                return False
            
            # 创建任务
            job = self._scheduler.add_job(
                self._execute_workflow,
                trigger=trigger,
                args=[workflow_db_id, workflow_id],
                id=f"workflow_{workflow_db_id}",
                name=f"Workflow {workflow_id}",
                replace_existing=True,
            )
            
            # 记录任务信息
            self._jobs[workflow_db_id] = ScheduledJob(
                workflow_db_id=workflow_db_id,
                workflow_id=workflow_id,
                schedule_config=schedule_config,
                job_id=job.id,
                next_run_time=job.next_run_time,
            )
            
            logger.info(
                f"已添加定时任务: workflow={workflow_id}, "
                f"cron={cron_expression}, next_run={job.next_run_time}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"添加定时任务失败: {e}", exc_info=True)
            return False
    
    def _parse_cron_expression(
        self, 
        cron_expression: str, 
        timezone_str: str = "Asia/Shanghai"
    ):
        """
        解析 cron 表达式为 APScheduler 触发器
        
        支持标准 5 字段 cron 格式: minute hour day month day_of_week
        """
        try:
            from apscheduler.triggers.cron import CronTrigger
            from zoneinfo import ZoneInfo
            
            parts = cron_expression.strip().split()
            if len(parts) != 5:
                logger.error(f"Cron 表达式格式错误，需要 5 个字段: {cron_expression}")
                return None
            
            minute, hour, day, month, day_of_week = parts
            
            # 使用 Python 3.9+ 内置的 zoneinfo 模块
            try:
                tz = ZoneInfo(timezone_str)
            except Exception:
                tz = ZoneInfo("Asia/Shanghai")
            
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=tz,
            )
            
        except Exception as e:
            logger.error(f"解析 cron 表达式失败: {cron_expression}, error={e}")
            return None
    
    async def _execute_workflow(
        self, 
        workflow_db_id: str, 
        workflow_id: str
    ) -> None:
        """
        执行工作流（由调度器触发）
        
        Args:
            workflow_db_id: 工作流数据库 ID
            workflow_id: 工作流 ID
        """
        logger.info(f"定时任务触发: workflow={workflow_id}, db_id={workflow_db_id}")
        
        # 更新最后执行时间
        if workflow_db_id in self._jobs:
            self._jobs[workflow_db_id].last_run_time = datetime.now()
        
        try:
            if self._execution_callback:
                await self._execution_callback(workflow_db_id, workflow_id)
                if workflow_db_id in self._jobs:
                    self._jobs[workflow_db_id].last_run_status = "success"
            else:
                # 默认执行方式：通过 WebSocket 触发
                await self._default_execute_workflow(workflow_db_id, workflow_id)
                
        except Exception as e:
            logger.error(f"定时执行工作流失败: {workflow_id}, error={e}", exc_info=True)
            if workflow_db_id in self._jobs:
                self._jobs[workflow_db_id].last_run_status = "failed"
    
    async def _default_execute_workflow(
        self, 
        workflow_db_id: str, 
        workflow_id: str
    ) -> None:
        """
        默认的工作流执行方式
        
        使用 ScheduledWorkflowExecutor 在后台异步执行工作流。
        """
        try:
            from src.services import WorkflowService
            from src.services.scheduled_executor import ScheduledWorkflowExecutor
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import (
                WorkflowDefinitionRepository,
                WorkflowExecutionRepository,
            )
            from src.storage.config import PostgreSQLConfig
            
            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()
            
            try:
                workflow_repo = WorkflowDefinitionRepository(db._session_factory)
                execution_repo = WorkflowExecutionRepository(db._session_factory)
                service = WorkflowService(workflow_repo, execution_repo)
                
                # 获取工作流定义
                workflow_detail = await service.get_workflow_by_id(workflow_db_id)
                if not workflow_detail:
                    logger.error(f"找不到工作流: {workflow_db_id}")
                    return
                
                # 创建执行记录
                execution = await service.create_execution(
                    workflow_id=workflow_id,
                    input_data={"triggered_by": "scheduler"},
                )
                
                if not execution:
                    logger.error(f"创建执行记录失败: workflow={workflow_id}")
                    return
                    
                execution_id = execution.get('id')
                logger.info(
                    f"定时任务已创建执行记录: workflow={workflow_id}, "
                    f"execution_id={execution_id}"
                )
                
                # 使用 ScheduledWorkflowExecutor 在后台执行工作流
                if self._sio:
                    executor = ScheduledWorkflowExecutor(self._sio)
                    success = await executor.execute_in_background(
                        workflow_db_id=workflow_db_id,
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        workflow_definition=workflow_detail.definition,
                    )
                    
                    if success:
                        logger.info(
                            f"定时任务已启动后台执行: workflow={workflow_id}, "
                            f"execution_id={execution_id}"
                        )
                    else:
                        logger.warning(
                            f"定时任务启动失败: workflow={workflow_id}, "
                            f"execution_id={execution_id}"
                        )
                else:
                    logger.warning(
                        f"Socket.IO 未配置，无法执行定时任务: workflow={workflow_id}. "
                        "请确保在初始化时调用 set_sio() 方法。"
                    )
                    
            finally:
                await db.close()
                
        except Exception as e:
            logger.error(f"默认执行工作流失败: {e}", exc_info=True)
            raise
    
    async def remove_workflow_schedule(self, workflow_db_id: str) -> bool:
        """
        移除工作流定时任务
        
        Args:
            workflow_db_id: 工作流数据库 ID
            
        Returns:
            是否移除成功
        """
        if not self._initialized or not self._scheduler:
            return False
            
        try:
            job_id = f"workflow_{workflow_db_id}"
            
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
            
            if workflow_db_id in self._jobs:
                del self._jobs[workflow_db_id]
            
            logger.info(f"已移除定时任务: {workflow_db_id}")
            return True
            
        except Exception as e:
            logger.error(f"移除定时任务失败: {e}")
            return False
    
    def get_job_info(self, workflow_db_id: str) -> Optional[ScheduledJob]:
        """获取任务信息"""
        return self._jobs.get(workflow_db_id)
    
    def get_all_jobs(self) -> Dict[str, ScheduledJob]:
        """获取所有任务"""
        return self._jobs.copy()
    
    async def shutdown(self) -> None:
        """关闭调度器"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("定时任务调度器已关闭")


# 全局调度器实例
scheduler_service = WorkflowSchedulerService()


__all__ = [
    "WorkflowSchedulerService",
    "ScheduledJob", 
    "scheduler_service",
]

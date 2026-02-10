"""
定时任务工作流执行器

直接调用 WorkflowEngine 执行工作流，不依赖 Socket.IO session。
使用 asyncio.create_task 在后台异步执行，不阻塞主进程。
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Set

from socketio import AsyncServer

from src.definitions import WorkflowDefinition
from src.orchestration.workflow_engine import WorkflowEngine
from src.registry import AgentRegistry
from src.tools import ToolRegistry
from src.utils.logger import get_logger
from src.utils.timestamp import utc_now_iso_z

logger = get_logger()


@dataclass
class ScheduledExecutionInfo:
    """定时执行信息"""
    
    execution_id: str
    workflow_id: str
    workflow_db_id: str
    started_at: datetime
    task: Optional[asyncio.Task] = None
    status: str = "running"
    error: Optional[str] = None


class ScheduledWorkflowExecutor:
    """
    定时任务工作流执行器
    
    直接调用 WorkflowEngine 执行工作流，不依赖 Socket.IO session。
    使用 asyncio.create_task 在后台异步执行，不阻塞主进程。
    """
    
    # 类级别的并发控制
    _running_executions: Dict[str, ScheduledExecutionInfo] = {}
    _max_concurrent: int = 5
    _execution_timeout: int = 3600  # 60 分钟
    
    def __init__(self, sio: AsyncServer):
        """
        初始化执行器
        
        Args:
            sio: Socket.IO 服务器实例，用于广播事件
        """
        self.sio = sio
        
    @classmethod
    def get_running_count(cls) -> int:
        """获取当前运行中的任务数量"""
        return len(cls._running_executions)
    
    @classmethod
    def get_running_executions(cls) -> Dict[str, ScheduledExecutionInfo]:
        """获取所有运行中的执行信息"""
        return cls._running_executions.copy()
    
    @classmethod
    def is_workflow_running(cls, workflow_id: str) -> bool:
        """检查指定工作流是否正在运行"""
        for info in cls._running_executions.values():
            if info.workflow_id == workflow_id and info.status == "running":
                return True
        return False
        
    async def execute_in_background(
        self, 
        workflow_db_id: str, 
        workflow_id: str,
        execution_id: str,
        workflow_definition: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        在后台启动工作流执行
        
        使用 asyncio.create_task，与手动执行保持一致的异步模型。
        
        Args:
            workflow_db_id: 工作流数据库 ID
            workflow_id: 工作流 ID
            execution_id: 执行记录 ID
            workflow_definition: 可选的工作流定义（如果不传则从数据库加载）
            
        Returns:
            是否成功启动
        """
        # 并发检查
        if len(self._running_executions) >= self._max_concurrent:
            logger.warning(
                f"定时任务并发数已达上限 {self._max_concurrent}, "
                f"跳过执行: {workflow_id}"
            )
            await self._broadcast_event(workflow_id, workflow_db_id, execution_id, {
                "event_type": "workflow_failed",
                "error": f"并发任务数已达上限 ({self._max_concurrent})",
                "message": "定时任务启动失败：系统繁忙",
            })
            return False
        
        # 检查同一工作流是否已在运行
        if self.is_workflow_running(workflow_id):
            logger.warning(f"工作流 {workflow_id} 已在运行中，跳过本次定时执行")
            await self._broadcast_event(workflow_id, workflow_db_id, execution_id, {
                "event_type": "workflow_skipped",
                "message": "工作流已在运行中，跳过本次定时执行",
            })
            return False
            
        # 创建执行信息
        exec_info = ScheduledExecutionInfo(
            execution_id=execution_id,
            workflow_id=workflow_id,
            workflow_db_id=workflow_db_id,
            started_at=datetime.now(),
        )
        
        # 创建后台任务
        task = asyncio.create_task(
            self._execute_with_timeout(
                workflow_db_id, 
                workflow_id, 
                execution_id,
                workflow_definition,
            )
        )
        exec_info.task = task
        self._running_executions[execution_id] = exec_info
        
        # 任务完成后清理
        def cleanup_callback(t: asyncio.Task):
            if execution_id in self._running_executions:
                info = self._running_executions[execution_id]
                try:
                    if t.exception():
                        info.status = "failed"
                        info.error = str(t.exception())
                    else:
                        info.status = "completed"
                except asyncio.CancelledError:
                    info.status = "cancelled"
                # 延迟清理，保留一段时间供查询
                asyncio.get_event_loop().call_later(
                    300,  # 5 分钟后清理
                    lambda: self._running_executions.pop(execution_id, None)
                )
                
        task.add_done_callback(cleanup_callback)
        
        logger.info(
            f"定时任务已启动后台执行: workflow={workflow_id}, "
            f"execution_id={execution_id}"
        )
        return True
        
    async def _execute_with_timeout(
        self, 
        workflow_db_id: str, 
        workflow_id: str,
        execution_id: str,
        workflow_definition: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """带超时保护的执行"""
        try:
            return await asyncio.wait_for(
                self._execute(
                    workflow_db_id, 
                    workflow_id, 
                    execution_id,
                    workflow_definition,
                ),
                timeout=self._execution_timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"定时任务执行超时: {workflow_id}, execution_id={execution_id}")
            
            # 更新执行状态
            if execution_id in self._running_executions:
                self._running_executions[execution_id].status = "failed"
                self._running_executions[execution_id].error = "执行超时"
            
            # 广播超时事件
            await self._broadcast_event(workflow_id, workflow_db_id, execution_id, {
                "event_type": "workflow_failed",
                "error": f"执行超时（超过 {self._execution_timeout // 60} 分钟）",
                "message": "定时任务执行超时",
            })
            
            # 更新数据库执行记录
            await self._update_execution_status(execution_id, "failed", "执行超时")
            
            return {"status": "timeout", "error": "执行超时"}
        except Exception as e:
            logger.error(f"定时任务执行异常: {workflow_id}, error={e}", exc_info=True)
            
            # 更新执行状态
            if execution_id in self._running_executions:
                self._running_executions[execution_id].status = "failed"
                self._running_executions[execution_id].error = str(e)
            
            # 广播失败事件
            await self._broadcast_event(workflow_id, workflow_db_id, execution_id, {
                "event_type": "workflow_failed",
                "error": str(e),
                "message": f"定时任务执行失败: {str(e)}",
            })
            
            # 更新数据库执行记录
            await self._update_execution_status(execution_id, "failed", str(e))
            
            raise
            
    async def _execute(
        self, 
        workflow_db_id: str, 
        workflow_id: str,
        execution_id: str,
        workflow_definition_dict: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """实际执行工作流"""
        logger.info(f"开始执行定时任务: workflow={workflow_id}, execution_id={execution_id}")
        
        try:
            # 加载工作流定义
            if workflow_definition_dict:
                definition_dict = workflow_definition_dict
            else:
                definition_dict = await self._load_workflow_definition(workflow_db_id)
                
            if not definition_dict:
                raise ValueError(f"无法加载工作流定义: {workflow_db_id}")
            
            # 转换为 WorkflowDefinition 对象
            workflow_def = WorkflowDefinition(**definition_dict)
            
            # 广播开始事件
            await self._broadcast_event(workflow_id, workflow_db_id, execution_id, {
                "event_type": "workflow_started",
                "workflow_name": workflow_def.name,
                "total_nodes": len(workflow_def.nodes),
                "message": f"定时任务开始执行: {workflow_def.name}",
            })
            
            # 更新数据库执行记录状态
            await self._update_execution_status(execution_id, "running")
            
            # 创建执行引擎
            executions_path = self._get_executions_path()
            
            # 加载应用层工作流配置
            try:
                from src.config import get_app_config_loader
                app_wf_config = get_app_config_loader().get_workflow_config()
            except Exception:
                app_wf_config = {}
            
            engine = WorkflowEngine(
                agent_registry=AgentRegistry.get_default(),
                tool_registry=ToolRegistry.get_default(),
                workspace_base_path=str(executions_path),
                app_workflow_config=app_wf_config,
            )
            
            # 定义事件回调 - 广播给所有客户端
            async def event_callback(event: Dict[str, Any]) -> None:
                # 添加定时任务标识
                event["triggered_by"] = "scheduler"
                event["execution_id"] = execution_id
                
                # 广播事件
                await self._broadcast_event(
                    workflow_id, 
                    workflow_db_id, 
                    execution_id, 
                    event
                )
            
            # 执行工作流
            result = await engine.execute_with_streaming(
                workflow_definition=workflow_def,
                initial_context={"triggered_by": "scheduler"},
                event_callback=event_callback,
            )
            
            # 处理执行结果
            status = result.status.value if hasattr(result.status, 'value') else str(result.status)
            
            # 更新数据库执行记录
            await self._update_execution_status(
                execution_id, 
                "completed" if status == "completed" else "failed",
                error=None if status == "completed" else "执行未成功完成"
            )
            
            # 构建返回结果
            nodes_completed = len([r for r in result.node_results.values() if r.status == "success"])
            nodes_failed = len([r for r in result.node_results.values() if r.status == "failed"])
            
            return {
                "status": status,
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "total_duration_ms": result.total_duration_ms,
                "nodes_completed": nodes_completed,
                "nodes_failed": nodes_failed,
                "total_nodes": len(result.node_results),
            }
            
        except Exception as e:
            logger.error(f"执行定时任务失败: {workflow_id}, error={e}", exc_info=True)
            raise
        
    async def _load_workflow_definition(self, workflow_db_id: str) -> Optional[Dict[str, Any]]:
        """从数据库加载工作流定义"""
        try:
            from src.services import WorkflowService
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import (
                WorkflowDefinitionRepository,
                WorkflowExecutionRepository,
            )
            
            # AsyncDatabaseManager 会自动从环境变量读取配置（支持 Docker 部署模式）
            db = AsyncDatabaseManager()
            await db.connect()
            
            try:
                workflow_repo = WorkflowDefinitionRepository(db._session_factory)
                execution_repo = WorkflowExecutionRepository(db._session_factory)
                service = WorkflowService(workflow_repo, execution_repo)
                
                # 获取工作流详情
                workflow_detail = await service.get_workflow_by_id(workflow_db_id)
                
                if workflow_detail:
                    return workflow_detail.definition
                else:
                    logger.error(f"找不到工作流: {workflow_db_id}")
                    return None
                    
            finally:
                await db.close()
                
        except Exception as e:
            logger.error(f"加载工作流定义失败: {e}", exc_info=True)
            return None
    
    async def _update_execution_status(
        self, 
        execution_id: str, 
        status: str,
        error: Optional[str] = None
    ) -> None:
        """更新数据库中的执行记录状态"""
        try:
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import WorkflowExecutionRepository
            
            # AsyncDatabaseManager 会自动从环境变量读取配置（支持 Docker 部署模式）
            db = AsyncDatabaseManager()
            await db.connect()
            
            try:
                execution_repo = WorkflowExecutionRepository(db._session_factory)
                
                updates = {"status": status}
                # 当状态变为 running 时，确保设置 started_at（如果之前未设置）
                if status == "running":
                    updates["started_at"] = datetime.now()
                if status in ("completed", "failed"):
                    updates["completed_at"] = datetime.now()
                if error:
                    updates["error"] = error  # 修复：字段名应为 error，不是 error_message
                    
                await execution_repo.update(execution_id, updates)
                logger.debug(f"更新执行记录状态: {execution_id} -> {status}")
                
            finally:
                await db.close()
                
        except Exception as e:
            logger.error(f"更新执行记录状态失败: {e}", exc_info=True)
        
    async def _broadcast_event(
        self, 
        workflow_id: str,
        workflow_db_id: str,
        execution_id: str, 
        event: Dict[str, Any]
    ) -> None:
        """广播事件给所有在线客户端"""
        try:
            await self.sio.emit(
                "scheduled_execution_event",
                {
                    "workflow_id": workflow_id,
                    "workflow_db_id": workflow_db_id,
                    "execution_id": execution_id,
                    "triggered_by": "scheduler",
                    "event": event,
                    "timestamp": utc_now_iso_z(),
                }
            )
        except Exception as e:
            logger.error(f"广播事件失败: {e}", exc_info=True)
    
    def _get_executions_path(self) -> str:
        """
        获取执行记录存储路径
        
        优先级：
        1. 配置文件中的 workflow.scheduled_execution.workspace_path
        2. 环境变量 SCHEDULED_EXECUTION_PATH
        3. 默认值 ./data/scheduled_executions
        """
        try:
            from src.config import get_scheduled_execution_config
            config = get_scheduled_execution_config()
            workspace_path = config.get("workspace_path", "./data/scheduled_executions")
            # 确保路径存在
            os.makedirs(workspace_path, exist_ok=True)
            return workspace_path
        except Exception as e:
            logger.warning(f"获取定时执行配置失败，使用默认路径: {e}")
            default_path = os.getenv("SCHEDULED_EXECUTION_PATH", "./data/scheduled_executions")
            os.makedirs(default_path, exist_ok=True)
            return default_path


# 创建全局执行器实例的工厂函数
def create_scheduled_executor(sio: AsyncServer) -> ScheduledWorkflowExecutor:
    """
    创建定时任务执行器实例
    
    Args:
        sio: Socket.IO 服务器实例
        
    Returns:
        ScheduledWorkflowExecutor 实例
    """
    return ScheduledWorkflowExecutor(sio)

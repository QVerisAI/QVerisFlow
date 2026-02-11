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
        
        node_results_dict: Dict[str, Any] = {}
        result = None
        
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
            
            # ========== 加载并注册工作流引用的 Agents ==========
            # 手动执行时，load_saved_workflow 会注册 Agents；
            # 定时任务需要在此处自行完成，否则 WorkflowEngine 找不到 Agent
            await self._ensure_agents_registered(workflow_def)
            
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
            
            # 增量跟踪节点执行结果（用于中间持久化到数据库）
            partial_node_results: Dict[str, Any] = {}
            
            # 定义事件回调 - 广播给所有客户端 + 增量保存节点结果
            async def event_callback(event: Dict[str, Any]) -> None:
                # 添加定时任务标识
                event["triggered_by"] = "scheduler"
                event["execution_id"] = execution_id
                
                # 增量更新 node_results 到数据库（确保中途查看详情时能获取已完成节点）
                evt_type = event.get("event_type", "")
                node_id = event.get("node_id", "")
                if evt_type == "node_started" and node_id:
                    partial_node_results[node_id] = {
                        "status": "running",
                        "node_name": event.get("node_name", node_id),
                    }
                elif evt_type == "node_completed" and node_id:
                    data = event.get("data", {})
                    partial_node_results[node_id] = {
                        "status": "success",
                        "node_name": event.get("node_name", node_id),
                        "duration_ms": data.get("duration_ms"),
                        "output": data.get("output"),
                    }
                    # 节点完成时持久化到数据库，保证查看详情时能看到已完成的节点
                    try:
                        await self._update_execution_status(
                            execution_id, "running",
                            node_results=dict(partial_node_results),
                        )
                    except Exception as e:
                        logger.warning(f"增量保存 node_results 失败: {e}")
                elif evt_type == "node_failed" and node_id:
                    data = event.get("data", {})
                    partial_node_results[node_id] = {
                        "status": "failed",
                        "node_name": event.get("node_name", node_id),
                        "error": data.get("error"),
                    }
                    try:
                        await self._update_execution_status(
                            execution_id, "running",
                            node_results=dict(partial_node_results),
                        )
                    except Exception as e:
                        logger.warning(f"增量保存 node_results 失败: {e}")
                
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
            
            # 构建节点执行结果字典（用于保存到数据库）
            # 从工作流定义构建 node_id -> 中文名称 的映射
            node_name_map = {n.node_id: n.name for n in workflow_def.nodes}
            
            node_results_dict = {}
            for node_id, node_result in result.node_results.items():
                # 处理 started_at 和 completed_at（可能是 datetime 对象或已经是字符串）
                started_at = getattr(node_result, 'started_at', None)
                if started_at is not None:
                    started_at = started_at.isoformat() if hasattr(started_at, 'isoformat') else str(started_at)
                
                completed_at = getattr(node_result, 'completed_at', None)
                if completed_at is not None:
                    completed_at = completed_at.isoformat() if hasattr(completed_at, 'isoformat') else str(completed_at)
                
                # 处理 output（可能是大对象，序列化为 JSON 兼容格式）
                raw_output = getattr(node_result, 'output', None)
                serialized_output = None
                if raw_output is not None:
                    try:
                        import json
                        json.dumps(raw_output)  # 测试是否可序列化
                        serialized_output = raw_output
                    except (TypeError, ValueError):
                        serialized_output = str(raw_output)  # 不可序列化时转字符串
                
                node_results_dict[node_id] = {
                    "status": node_result.status if isinstance(node_result.status, str) else (
                        node_result.status.value if hasattr(node_result.status, 'value') else str(node_result.status)
                    ),
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "duration_ms": getattr(node_result, 'duration_ms', None),
                    "error": getattr(node_result, 'error', None),
                    "node_name": node_name_map.get(node_id, node_id),
                    "output": serialized_output,
                }
            
            # 更新数据库执行记录（包含完整的节点执行结果）
            await self._update_execution_status(
                execution_id, 
                "completed" if status == "completed" else "failed",
                error=None if status == "completed" else "执行未成功完成",
                node_results=node_results_dict,
                total_duration_ms=result.total_duration_ms,
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
            # 执行失败时也尝试保存已有的 node_results 到数据库
            try:
                await self._update_execution_status(
                    execution_id,
                    "failed",
                    error=str(e),
                    node_results=node_results_dict if node_results_dict else None,
                    total_duration_ms=getattr(result, 'total_duration_ms', None) if result else None,
                )
            except Exception as save_err:
                logger.warning(f"保存失败状态时出错: {save_err}")
            raise
        
    async def _ensure_agents_registered(self, workflow_def: WorkflowDefinition) -> None:
        """
        确保工作流引用的所有 Agent 都已注册到 AgentRegistry。
        
        手动执行时，load_saved_workflow 会注册 Agents；
        定时任务需要在执行前自行从数据库加载并注册。
        """
        # 1. 收集工作流中所有引用的 agent_id
        agent_ids: Set[str] = set()
        for node in workflow_def.nodes:
            if node.agent_id:
                agent_ids.add(node.agent_id)
            if node.config and node.config.get("agent_id"):
                agent_ids.add(node.config["agent_id"])
        
        if not agent_ids:
            return
        
        # 2. 过滤出尚未注册的 agent_id
        registry = AgentRegistry.get_default()
        missing_ids = [aid for aid in agent_ids if not registry.get_definition(aid)]
        
        if not missing_ids:
            logger.debug(f"所有 {len(agent_ids)} 个 Agent 已注册")
            return
        
        logger.info(f"定时任务需要加载 {len(missing_ids)} 个未注册的 Agent: {missing_ids}")
        
        # 3. 从数据库加载并注册缺失的 Agent
        try:
            from src.definitions import AgentDefinition
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import AgentRepository
            
            db = AsyncDatabaseManager()
            await db.connect()
            
            try:
                agent_repo = AgentRepository(db._session_factory)
                loaded_count = 0
                
                for agent_id in missing_ids:
                    try:
                        agent_model = await agent_repo.get_by_agent_id(agent_id)
                        if agent_model and agent_model.definition_json:
                            agent_def = AgentDefinition(**agent_model.definition_json)
                            registry.register_definition(agent_def)
                            loaded_count += 1
                            logger.debug(f"已注册 Agent: {agent_id}")
                        else:
                            logger.warning(f"Agent 不存在于数据库: {agent_id}")
                    except Exception as agent_err:
                        logger.warning(f"加载 Agent {agent_id} 失败: {agent_err}")
                
                logger.info(f"定时任务 Agent 注册完成: {loaded_count}/{len(missing_ids)}")
            finally:
                await db.close()
                
        except Exception as e:
            logger.error(f"加载 Agents 失败: {e}", exc_info=True)
    
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
        error: Optional[str] = None,
        node_results: Optional[Dict[str, Any]] = None,
        total_duration_ms: Optional[float] = None,
    ) -> None:
        """
        更新数据库中的执行记录状态
        
        Args:
            execution_id: 执行记录 ID
            status: 状态 (running, completed, failed)
            error: 错误信息（可选）
            node_results: 节点执行结果（可选）
            total_duration_ms: 总执行时长（毫秒，可选）
        """
        try:
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import WorkflowExecutionRepository
            
            # AsyncDatabaseManager 会自动从环境变量读取配置（支持 Docker 部署模式）
            db = AsyncDatabaseManager()
            await db.connect()
            
            try:
                execution_repo = WorkflowExecutionRepository(db._session_factory)
                
                updates = {"status": status}
                # 当状态变为 running 且非增量更新时，设置 started_at
                # node_results 非空说明是增量保存节点结果，不应覆盖 started_at
                if status == "running" and node_results is None:
                    updates["started_at"] = datetime.now()
                if status in ("completed", "failed"):
                    updates["completed_at"] = datetime.now()
                if error:
                    updates["error"] = error
                # 保存节点执行结果
                if node_results is not None:
                    updates["node_results"] = node_results
                # 保存总执行时长
                if total_duration_ms is not None:
                    updates["total_duration_ms"] = total_duration_ms
                    
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
        """广播事件给所有在线客户端（使用标准 WSMessage 格式）"""
        try:
            # 必须使用 {type, payload, timestamp} 格式，与 SocketIOHandler.emit 保持一致
            # 前端 dispatch 依赖 message.type 路由到对应的 handler
            await self.sio.emit(
                "scheduled_execution_event",
                {
                    "type": "scheduled_execution_event",
                    "payload": {
                        "workflow_id": workflow_id,
                        "workflow_db_id": workflow_db_id,
                        "execution_id": execution_id,
                        "triggered_by": "scheduler",
                        "event": event,
                        "timestamp": utc_now_iso_z(),
                    },
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

"""
FastAPI 应用入口

对话式工作流构建器 Web UI 后端。
支持 Socket.IO 和传统 WebSocket 两种通信方式。
"""

# Load .env file FIRST before any other imports that might use environment variables
from dotenv import load_dotenv

load_dotenv()

from typing import Optional, Any, Dict
from pathlib import Path
from contextlib import asynccontextmanager
import asyncio
import uuid
import traceback
import time

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse
    import socketio
except ImportError:
    raise ImportError("请安装 web 依赖: pip install -e '.[web]'")

from src.utils.logger import get_logger, setup_uvicorn_logging
from src.utils.timestamp import utc_now_iso_z

logger = get_logger()

# Socket.IO 服务器实例（全局）
sio: Optional[socketio.AsyncServer] = None
sio_manager: Optional[Any] = None
sio_handlers: Dict[str, Any] = {}

# 全局依赖（延迟初始化）
_meta_agent: Optional[Any] = None
_tool_registry: Optional[Any] = None
_llm_client: Optional[Any] = None
_workflow_engine: Optional[Any] = None
_config_loader: Optional[Any] = None
_storage_service: Optional[Any] = None


def get_meta_agent():
    return _meta_agent


def get_tool_registry():
    return _tool_registry


def get_llm_client():
    return _llm_client


def get_workflow_engine():
    return _workflow_engine


def get_storage_service():
    return _storage_service


async def init_dependencies():
    """初始化依赖"""
    global _meta_agent, _tool_registry, _llm_client, _workflow_engine, _config_loader, _storage_service

    logger.info("正在初始化依赖...")

    try:
        from src.config import AppConfigLoader, create_qveris_adapter
        from src.tools.registry import ToolRegistry
        from src.tools.builtin import register_builtin_tools
        from src.evolution.meta_agent import MetaAgent
        from src.orchestration.workflow_engine import WorkflowEngine
        from src.storage.service import StorageService

        # 加载配置
        _config_loader = AppConfigLoader()
        _config_loader.load()

        # ---- 初始化存储服务 ----
        storage_config = _config_loader.get_storage_config()
        _storage_service = StorageService.get_instance()
        await _storage_service.initialize(storage_config)
        logger.info(f"✅ 存储服务已初始化 ({_storage_service})")

        # 初始化工具注册表 - 使用全局默认实例，确保所有组件共享同一个注册表
        _tool_registry = ToolRegistry.get_default()

        # 注册内置工具（file_ls, file_read, file_write, file_edit, file_append 等）
        register_builtin_tools(_tool_registry)
        logger.info("✅ 内置工具已注册")

        # 注册 QVeris 工具
        qveris_adapter = create_qveris_adapter(_tool_registry)
        if qveris_adapter:
            qveris_adapter.register_meta_tools()
            logger.info("✅ QVeris 工具已注册 (qveris_search_tools, qveris_execute_tool)")

        # 初始化 LLM 客户端
        _llm_client = _config_loader.create_llm_client()
        logger.info(f"✅ LLM 客户端已初始化")

        # 初始化 MetaAgent
        _meta_agent = MetaAgent(
            llm_client=_llm_client,
            tool_registry=_tool_registry,
        )
        logger.info("✅ MetaAgent 已初始化")

        # 初始化 WorkflowEngine（传入应用层工作流配置）
        # 使用存储配置中的工作空间路径
        _workflow_config = _config_loader.get_workflow_config()
        workspace_path = Path(storage_config.local.workspace_dir)
        _workflow_engine = WorkflowEngine(
            llm_client=_llm_client,
            tool_registry=_tool_registry,
            workspace_base_path=workspace_path,
            app_workflow_config=_workflow_config,
        )
        logger.info(
            f"✅ WorkflowEngine 已初始化"
            f"（default_data_format={_workflow_config.get('default_data_format', 'json')}）"
        )

        logger.info("✅ 所有依赖初始化完成")

    except Exception as e:
        logger.error(f"初始化依赖失败: {e}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 统一 uvicorn 日志到框架 handler（使 uvicorn 日志也输出到文件）
    setup_uvicorn_logging()
    # 启动时初始化
    await init_dependencies()
    
    # 修复僵尸 running 状态的执行记录（服务重启后，内存中的执行状态丢失）
    try:
        from src.storage.database import AsyncDatabaseManager
        from src.storage.repositories.workflow_repository import WorkflowExecutionRepository
        
        db = AsyncDatabaseManager()
        await db.connect()
        execution_repo = WorkflowExecutionRepository(db._session_factory)
        fixed_count = await execution_repo.fix_stale_running_executions()
        if fixed_count > 0:
            logger.info(f"✅ 已修复 {fixed_count} 个僵尸 running 状态的执行记录")
        else:
            logger.debug("无需修复僵尸执行记录")
        await db.close()
    except Exception as e:
        logger.warning(f"修复僵尸执行记录失败: {e}")
    
    # 初始化定时任务调度器
    try:
        from src.services.scheduler_service import scheduler_service
        # 设置 Socket.IO 实例，用于广播定时任务执行事件
        if sio:
            scheduler_service.set_sio(sio)
        await scheduler_service.initialize()
        logger.info("✅ 定时任务调度器已初始化")
    except Exception as e:
        logger.warning(f"定时任务调度器初始化失败（功能不可用）: {e}")
    
    # 初始化并执行首次清理，然后注册定期清理任务
    try:
        from src.services.workspace_cleanup import get_cleanup_service, cleanup_scheduled_executions
        from src.config import get_scheduled_execution_config
        
        cleanup_config = get_scheduled_execution_config()
        retention = cleanup_config.get("retention", {})
        cleanup_interval_hours = int(retention.get("cleanup_interval_hours", 24))
        
        if cleanup_interval_hours > 0:
            # 启动时执行一次清理
            logger.info("执行启动时清理...")
            cleanup_result = await cleanup_scheduled_executions()
            logger.info(f"✅ 启动清理完成: 删除 {cleanup_result['directories_removed']} 个目录")
            
            # 注册定期清理任务
            from src.services.scheduler_service import scheduler_service
            if scheduler_service._scheduler:
                # 添加清理任务到 APScheduler
                scheduler_service._scheduler.add_job(
                    cleanup_scheduled_executions,
                    'interval',
                    hours=cleanup_interval_hours,
                    id='workspace_cleanup',
                    name='定时任务执行记录清理',
                    replace_existing=True,
                )
                logger.info(f"✅ 已注册定期清理任务（每 {cleanup_interval_hours} 小时执行）")
        else:
            logger.info("定期清理已禁用（cleanup_interval_hours=0）")
    except Exception as e:
        logger.warning(f"清理服务初始化失败（功能不可用）: {e}")
    
    yield
    
    # 关闭时清理
    logger.info("应用正在关闭...")
    
    # 关闭定时任务调度器
    try:
        from src.services.scheduler_service import scheduler_service
        await scheduler_service.shutdown()
    except Exception:
        pass
    
    # 优雅关闭存储服务
    if _storage_service and _storage_service.is_initialized:
        await _storage_service.shutdown()


def create_app():
    """创建 FastAPI 应用（包装为 Socket.IO ASGI 应用）"""
    global sio, sio_manager, sio_handlers

    # =============== Socket.IO 配置 ===============
    sio = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins="*",
        ping_interval=25,  # Socket.IO 内置心跳间隔（秒）
        ping_timeout=60,  # 心跳超时时间（秒）
        max_http_buffer_size=10 * 1024 * 1024,  # 10MB
        logger=False,
        engineio_logger=False,
    )

    # 导入 Socket.IO 相关模块
    from src.web.socketio.manager import SocketIOConnectionManager
    from src.web.socketio.handlers import SocketIOHandler, session_manager
    from src.evolution.conversational_builder import ConversationalWorkflowBuilder

    sio_manager = SocketIOConnectionManager(sio)
    sio_handlers = {}

    # =============== Socket.IO 事件注册 ===============

    @sio.event
    async def connect(sid, environ, auth):
        """Socket.IO 连接事件"""
        # 获取 session_id
        session_id = None
        if auth:
            session_id = auth.get("session_id")

        if not session_id:
            # 从 query string 获取
            query = environ.get("QUERY_STRING", "")
            for param in query.split("&"):
                if param.startswith("session_id="):
                    session_id = param.split("=")[1]
                    break

        if not session_id:
            # 生成新的 session_id
            from datetime import datetime

            session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        user_id = auth.get("user_id") if auth else None

        # 注册连接
        await sio_manager.connect(sid, session_id, user_id)

        # 获取或创建会话
        builder = await session_manager.get_session(session_id)
        is_reconnect = builder is not None

        if not builder:
            # 使用存储配置中的工作空间路径
            base_ws = Path("./data/workspaces")
            if _storage_service and _storage_service.config:
                base_ws = Path(_storage_service.config.local.workspace_dir)
            storage_path = base_ws / session_id
            builder = ConversationalWorkflowBuilder(
                meta_agent=_meta_agent,
                tool_registry=_tool_registry,
                llm_client=_llm_client,
                workflow_engine=_workflow_engine,
                storage_path=storage_path,
                session_id=session_id,
            )
            await builder.init_dependencies()
            await session_manager.create_session(session_id, builder)
            logger.info(f"Socket.IO 创建新会话: {session_id}")
        else:
            if not builder._initialized:
                await builder.init_dependencies()
            logger.debug(f"Socket.IO 复用现有会话: {session_id}")

        # 创建 handler
        handler = SocketIOHandler(sio, sio_manager, sid, session_id, builder)
        sio_handlers[sid] = handler

        # 发送连接成功消息
        history_count = len(builder.conversation_history)
        await sio.emit(
            "connected",
            {
                "type": "connected",
                "payload": {
                    "session_id": session_id,
                    "message": "连接成功" if not is_reconnect else "重新连接成功",
                    "is_reconnect": is_reconnect,
                    "history_count": history_count,
                    "mode": builder.mode.value if hasattr(builder, "mode") else "idle",
                },
                "timestamp": utc_now_iso_z(),
            },
            room=sid,
        )

        # 发送初始工作流状态
        initial_state = builder._get_workflow_state()
        if initial_state:
            await sio.emit(
                "workflow_update",
                {
                    "type": "workflow_update",
                    "payload": initial_state,
                    "timestamp": utc_now_iso_z(),
                },
                room=sid,
            )

        logger.info(f"Socket.IO 连接: sid={sid}, session={session_id}")

    @sio.event
    async def disconnect(sid):
        """Socket.IO 断开事件"""
        if sid in sio_handlers:
            await sio_handlers[sid].cleanup()
            del sio_handlers[sid]
        await sio_manager.disconnect(sid)
        logger.info(f"Socket.IO 断开: sid={sid}")

    # =============== 业务事件路由 ===============

    @sio.on("chat_message")
    async def on_chat_message(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_chat_message(data)

    @sio.on("user_action")
    async def on_user_action(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_user_action(data)

    @sio.on("load_workflow")
    async def on_load_workflow(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_load_workflow(data)

    @sio.on("save_workflow")
    async def on_save_workflow(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_save_workflow(data)

    @sio.on("list_workflows")
    async def on_list_workflows(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_list_workflows(data)

    @sio.on("delete_workflow")
    async def on_delete_workflow(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_delete_workflow(data)

    @sio.on("update_agent")
    async def on_update_agent(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_update_agent(data)

    @sio.on("optimize_prompt")
    async def on_optimize_prompt(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_optimize_prompt(data)

    @sio.on("list_agents")
    async def on_list_agents(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_list_agents(data)

    @sio.on("reuse_agent")
    async def on_reuse_agent(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_reuse_agent(data)

    @sio.on("get_agent_templates")
    async def on_get_agent_templates(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_get_agent_templates(data)

    @sio.on("get_execution_history")
    async def on_get_execution_history(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_get_execution_history(data)

    @sio.on("get_execution_detail")
    async def on_get_execution_detail(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_get_execution_detail(data)

    @sio.on("sync_messages")
    async def on_sync_messages(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_sync_messages(data)

    @sio.on("subscribe")
    async def on_subscribe(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_subscribe(data)

    @sio.on("unsubscribe")
    async def on_unsubscribe(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_unsubscribe(data)

    # =============== 定时任务管理事件 ===============

    @sio.on("schedule_workflow")
    async def on_schedule_workflow(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_schedule_workflow(data)

    @sio.on("unschedule_workflow")
    async def on_unschedule_workflow(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_unschedule_workflow(data)

    @sio.on("get_workflow_schedules")
    async def on_get_workflow_schedules(sid, data):
        if sid in sio_handlers:
            await sio_handlers[sid].handle_get_workflow_schedules(data)

    # =============== FastAPI 应用 ===============

    app = FastAPI(
        title="对话式工作流构建器",
        description="基于自然语言的工作流构建和执行平台",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS 配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制来源
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    from src.web.routers import (
        sessions_router,
        workflows_router,
        execution_router,
        agents_router,
        executions_router,
    )

    app.include_router(sessions_router, prefix="/api")
    app.include_router(workflows_router, prefix="/api")
    app.include_router(execution_router, prefix="/api")
    app.include_router(agents_router, prefix="/api")
    app.include_router(executions_router, prefix="/api")

    # =============== 保留传统 WebSocket 端点（向后兼容）===============

    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(
        websocket: WebSocket,
        session_id: str,
        user_id: Optional[str] = Query(None),
    ):
        """传统 WebSocket 连接端点（向后兼容）"""
        from src.web.websocket.manager import manager
        from src.web.websocket.handlers import (
            WebSocketHandler,
            session_manager as ws_session_manager,
        )
        from src.evolution.conversational_builder import ConversationalWorkflowBuilder

        # 连接
        await manager.connect(websocket, session_id, user_id)

        try:
            # 获取或创建会话
            builder = await ws_session_manager.get_session(session_id)

            if not builder:
                # 创建新的构建器
                base_ws = Path("./data/workspaces")
                if _storage_service and _storage_service.config:
                    base_ws = Path(_storage_service.config.local.workspace_dir)
                storage_path = base_ws / session_id
                builder = ConversationalWorkflowBuilder(
                    meta_agent=_meta_agent,
                    tool_registry=_tool_registry,
                    llm_client=_llm_client,
                    workflow_engine=_workflow_engine,
                    storage_path=storage_path,
                    session_id=session_id,
                )
                await builder.init_dependencies()
                await ws_session_manager.create_session(session_id, builder)
                logger.info(f"WebSocket 创建新会话: {session_id}")
            else:
                if not builder._initialized:
                    await builder.init_dependencies()
                logger.debug(f"WebSocket 复用现有会话: {session_id}")

            # 创建处理器并处理连接
            handler = WebSocketHandler(
                websocket=websocket,
                session_id=session_id,
                builder=builder,
                connection_manager=manager,
            )

            await handler.handle_connection()

        except WebSocketDisconnect:
            logger.info(f"WebSocket 断开: {session_id}")
        except Exception as e:
            logger.error(f"WebSocket 错误: {e}, traceback: {traceback.format_exc()}")
        finally:
            await manager.disconnect(session_id)

    @app.websocket("/ws/new")
    async def websocket_new_session(
        websocket: WebSocket,
        user_id: Optional[str] = Query(None),
    ):
        """创建新会话的 WebSocket 端点"""
        from datetime import datetime

        session_id = (
            f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )

        await websocket_endpoint(websocket, session_id, user_id)

    # 健康检查
    @app.get("/health")
    async def health_check():
        """健康检查"""
        result = {
            "status": "healthy",
            "meta_agent": _meta_agent is not None,
            "tool_registry": _tool_registry is not None,
            "llm_client": _llm_client is not None,
            "workflow_engine": _workflow_engine is not None,
            "socketio": sio is not None,
        }
        # 附加存储健康状态
        if _storage_service and _storage_service.is_initialized:
            try:
                storage_health = await _storage_service.health_check()
                result["storage"] = storage_health
            except Exception as e:
                result["storage"] = {"error": str(e)}
        return result

    # 静态文件（前端）
    frontend_path = Path(__file__).parent.parent.parent / "web-ui" / "dist"
    if frontend_path.exists():
        app.mount(
            "/", StaticFiles(directory=str(frontend_path), html=True), name="static"
        )
    else:
        # 开发模式：返回简单的 HTML 页面
        @app.get("/", response_class=HTMLResponse)
        async def root():
            return """
            <!DOCTYPE html>
            <html>
            <head>
                <title>对话式工作流构建器</title>
                <style>
                    body {
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        height: 100vh;
                        margin: 0;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    }
                    .container {
                        text-align: center;
                        color: white;
                        padding: 40px;
                        background: rgba(255,255,255,0.1);
                        border-radius: 20px;
                        backdrop-filter: blur(10px);
                    }
                    h1 { font-size: 2.5em; margin-bottom: 10px; }
                    p { font-size: 1.2em; opacity: 0.9; }
                    .links { margin-top: 30px; }
                    a {
                        color: white;
                        text-decoration: none;
                        padding: 10px 20px;
                        border: 2px solid white;
                        border-radius: 5px;
                        margin: 0 10px;
                        transition: all 0.3s;
                    }
                    a:hover {
                        background: white;
                        color: #764ba2;
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🚀 对话式工作流构建器</h1>
                    <p>基于自然语言的 AI 工作流构建和执行平台</p>
                    <div class="links">
                        <a href="/docs">📚 API 文档</a>
                        <a href="/health">💓 健康检查</a>
                    </div>
                    <p style="margin-top: 30px; font-size: 0.9em; opacity: 0.7;">
                        前端开发模式: cd web-ui && npm run dev
                    </p>
                </div>
            </body>
            </html>
            """

    # 【关键】包装为 Socket.IO ASGI 应用
    socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

    return socket_app


# 应用实例
app = create_app()


def main():
    """命令行入口"""
    import argparse
    import os
    import uvicorn
    from src.utils.logger import setup_logging

    parser = argparse.ArgumentParser(description="对话式工作流构建器 Web 服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式（自动重载）")
    parser.add_argument("--workers", type=int, default=1, help="工作进程数")

    args = parser.parse_args()

    # 显式初始化文件日志（确保 uvicorn 启动前日志已就绪）
    log_level = os.getenv("LOG_LEVEL", "INFO")
    setup_logging(level=log_level, file_output=True)

    uvicorn.run(
        "src.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=["src", "config"] if args.reload else None,
        reload_excludes=(
            ["data/*", "logs/*", "*.pyc", "__pycache__"] if args.reload else None
        ),
        workers=args.workers,
        log_level=log_level.lower(),
    )


if __name__ == "__main__":
    main()

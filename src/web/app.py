"""
FastAPI 应用入口

对话式工作流构建器 Web UI 后端。
"""

# Load .env file FIRST before any other imports that might use environment variables
from dotenv import load_dotenv

load_dotenv()

from typing import Optional, Any
from pathlib import Path
from contextlib import asynccontextmanager
import asyncio
import uuid
import traceback

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse
except ImportError:
    raise ImportError("请安装 web 依赖: pip install -e '.[web]'")

from src.utils.logger import get_logger

logger = get_logger()

# 全局依赖（延迟初始化）
_meta_agent: Optional[Any] = None
_tool_registry: Optional[Any] = None
_llm_client: Optional[Any] = None
_workflow_engine: Optional[Any] = None
_config_loader: Optional[Any] = None


def get_meta_agent():
    return _meta_agent


def get_tool_registry():
    return _tool_registry


def get_llm_client():
    return _llm_client


def get_workflow_engine():
    return _workflow_engine


async def init_dependencies():
    """初始化依赖"""
    global _meta_agent, _tool_registry, _llm_client, _workflow_engine, _config_loader

    logger.info("正在初始化依赖...")

    try:
        from src.config import AppConfigLoader, create_qveris_adapter
        from src.tools.registry import ToolRegistry
        from src.tools.builtin import register_builtin_tools
        from src.evolution.meta_agent import MetaAgent
        from src.orchestration.workflow_engine import WorkflowEngine

        # 加载配置
        _config_loader = AppConfigLoader()

        # 初始化工具注册表
        _tool_registry = ToolRegistry()

        # 注册内置工具（file_ls, file_read, file_write, file_edit, file_append 等）
        register_builtin_tools(_tool_registry)
        logger.info("✅ 内置工具已注册")

        # 注册 QVeris 工具
        qveris_adapter = create_qveris_adapter(_tool_registry)
        if qveris_adapter:
            qveris_adapter.register_meta_tools()
            logger.info("✅ QVeris 工具已注册")

        # 初始化 LLM 客户端
        _llm_client = _config_loader.create_llm_client()
        logger.info(f"✅ LLM 客户端已初始化")

        # 初始化 MetaAgent
        _meta_agent = MetaAgent(
            llm_client=_llm_client,
            tool_registry=_tool_registry,
        )
        logger.info("✅ MetaAgent 已初始化")

        # 初始化 WorkflowEngine
        _workflow_engine = WorkflowEngine(
            llm_client=_llm_client,
            tool_registry=_tool_registry,
            workspace_base_path=Path("/tmp/agent_workflows"),
        )
        logger.info("✅ WorkflowEngine 已初始化")

        logger.info("✅ 所有依赖初始化完成")

    except Exception as e:
        logger.error(f"初始化依赖失败: {e}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    await init_dependencies()
    yield
    # 关闭时清理
    logger.info("应用正在关闭...")


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""

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

    # WebSocket 端点
    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(
        websocket: WebSocket,
        session_id: str,
        user_id: Optional[str] = Query(None),
    ):
        """WebSocket 连接端点"""
        from src.web.websocket.manager import manager
        from src.web.websocket.handlers import WebSocketHandler, session_manager
        from src.evolution.conversational_builder import ConversationalWorkflowBuilder

        # 连接
        await manager.connect(websocket, session_id, user_id)

        try:
            # 获取或创建会话
            builder = await session_manager.get_session(session_id)

            if not builder:
                # 创建新的构建器（传入 session_id 以便从数据库恢复）
                storage_path = Path("./workspaces") / session_id
                builder = ConversationalWorkflowBuilder(
                    meta_agent=_meta_agent,
                    tool_registry=_tool_registry,
                    llm_client=_llm_client,
                    workflow_engine=_workflow_engine,
                    storage_path=storage_path,
                    session_id=session_id,  # 传入 session_id 用于数据库恢复
                )
                # 异步初始化（从数据库加载会话历史）
                await builder.init_dependencies()
                await session_manager.create_session(session_id, builder)
                logger.info(f"创建新会话: {session_id}")
            else:
                # 已有会话，确保已初始化
                if not builder._initialized:
                    await builder.init_dependencies()
                logger.debug(f"复用现有会话: {session_id}")

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

    # 快速创建会话的 WebSocket 端点
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

        # 重定向到带 session_id 的端点
        await websocket_endpoint(websocket, session_id, user_id)

    # 健康检查
    @app.get("/health")
    async def health_check():
        """健康检查"""
        return {
            "status": "healthy",
            "meta_agent": _meta_agent is not None,
            "tool_registry": _tool_registry is not None,
            "llm_client": _llm_client is not None,
            "workflow_engine": _workflow_engine is not None,
        }

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

    return app


# 应用实例
app = create_app()


def main():
    """命令行入口"""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="对话式工作流构建器 Web 服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式（自动重载）")
    parser.add_argument("--workers", type=int, default=1, help="工作进程数")

    args = parser.parse_args()

    uvicorn.run(
        "src.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level="info",
    )


if __name__ == "__main__":
    main()

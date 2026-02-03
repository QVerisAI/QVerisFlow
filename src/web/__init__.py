"""
Web UI 模块

提供 FastAPI Web 服务，支持：
- 对话式工作流构建
- 实时工作流可视化
- 工作流执行监控
"""

from .app import create_app

__all__ = ["create_app"]

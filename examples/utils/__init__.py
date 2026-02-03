"""
示例工具模块

所有核心功能应从 src 模块导入，不要在 examples 中重复实现。

使用方式:
    # 创建 LLM 客户端
    from src.config import create_llm_client
    client = create_llm_client(tier="default")

    # 获取配置加载器
    from src.config import get_app_config_loader
    loader = get_app_config_loader()
    loader.load()

    # 使用 UnifiedLLMClient
    from src.utils.llm_client import UnifiedLLMClient
"""

__all__ = []

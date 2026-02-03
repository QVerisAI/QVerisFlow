"""
配置中心

提供框架的统一配置管理，支持：
- 环境变量加载
- 配置文件加载（YAML/JSON）
- 配置验证
- 默认值管理
- 热重载（可选）
"""

from typing import Dict, Any, Optional, List, Type, Union
from dataclasses import dataclass, field
from pathlib import Path
import os
import json

from pydantic import BaseModel, Field, validator
from pydantic_settings import BaseSettings

from src.utils.logger import get_logger

logger = get_logger()


# ========== LLM 配置 ==========


class LLMProviderConfig(BaseModel):
    """LLM 提供商配置"""

    provider: str = Field(default="openrouter", description="提供商类型")
    base_url: str = Field(
        default="https://openrouter.ai/api/v1", description="API 基础 URL"
    )
    api_key: str = Field(default="", description="API Key（建议通过环境变量设置）")
    model: str = Field(default="deepseek/deepseek-chat", description="默认模型")
    max_tokens: int = Field(default=4096, description="最大 token 数")
    temperature: float = Field(default=0.7, description="温度参数")
    timeout: int = Field(default=120, description="请求超时时间（秒）")
    max_retries: int = Field(default=3, description="最大重试次数")


# ========== Agent 配置 ==========


class AgentConfig(BaseModel):
    """Agent 配置"""

    max_iterations: int = Field(default=10, description="最大迭代次数")
    default_timeout: int = Field(default=300, description="默认超时时间（秒）")
    enable_checkpointing: bool = Field(default=True, description="是否启用检查点")
    checkpoint_interval: int = Field(default=1, description="检查点间隔（迭代次数）")


# ========== 工具配置 ==========


class ToolConfig(BaseModel):
    """工具配置"""

    default_timeout: int = Field(default=60, description="默认工具超时时间（秒）")
    max_retries: int = Field(default=2, description="默认重试次数")
    enable_logging: bool = Field(default=True, description="是否记录工具调用日志")
    dangerous_commands_blocked: bool = Field(
        default=True, description="是否拦截危险命令"
    )


# ========== QVeris 配置 ==========


class QVerisConfig(BaseModel):
    """
    QVeris 远程工具配置

    配置 QVeris 工具搜索和执行服务的连接参数。
    API 文档: https://qveris.ai/docs
    """

    enabled: bool = Field(default=False, description="是否启用 QVeris 集成")
    api_key: str = Field(
        default="", description="QVeris API Key（建议通过 QVERIS_API_KEY 环境变量设置）"
    )
    base_url: str = Field(
        default="https://qveris.ai/api/v1", description="QVeris API 基础 URL"
    )
    default_limit: int = Field(default=20, description="默认搜索结果数量（1-100）")
    cache_ttl: int = Field(default=3600, description="搜索结果缓存时间（秒）")
    max_response_size: int = Field(
        default=20480, description="最大响应大小（字节），超出时截断并提供下载链接"
    )
    timeout: int = Field(default=60, description="API 请求超时时间（秒）")
    max_retries: int = Field(default=3, description="API 请求最大重试次数")
    auto_register_discovered: bool = Field(
        default=True, description="是否自动将发现的工具注册到 ToolRegistry"
    )


# ========== 工作空间配置 ==========


class WorkspaceConfigSettings(BaseModel):
    """工作空间配置"""

    base_path: str = Field(
        default="/tmp/agent_workspaces", description="工作空间基础路径"
    )
    auto_cleanup: bool = Field(default=False, description="是否自动清理")
    cleanup_after_days: int = Field(default=7, description="清理多少天前的工作空间")
    max_draft_versions: int = Field(default=10, description="最大草稿版本数")


# ========== 工作流配置 ==========


class WorkflowConfig(BaseModel):
    """工作流配置"""

    max_parallel_nodes: int = Field(default=5, description="最大并行节点数")
    default_timeout: int = Field(default=600, description="默认工作流超时时间（秒）")
    continue_on_error: bool = Field(default=False, description="节点失败时是否继续")


# ========== 可观测性配置 ==========


class ObservabilityConfig(BaseModel):
    """可观测性配置"""

    enable_tracing: bool = Field(default=True, description="是否启用追踪")
    enable_metrics: bool = Field(default=True, description="是否启用指标")
    enable_structured_logging: bool = Field(
        default=True, description="是否启用结构化日志"
    )
    log_level: str = Field(default="INFO", description="日志级别")
    export_spans_to_console: bool = Field(
        default=True, description="是否输出 span 到控制台"
    )


# ========== 存储配置 ==========


class StorageConfig(BaseModel):
    """存储配置"""

    # PostgreSQL
    postgres_host: str = Field(default="localhost", description="PostgreSQL 主机")
    postgres_port: int = Field(default=5432, description="PostgreSQL 端口")
    postgres_db: str = Field(default="agent_framework", description="数据库名")
    postgres_user: str = Field(default="postgres", description="用户名")
    postgres_password: str = Field(default="", description="密码")

    # Redis
    redis_host: str = Field(default="localhost", description="Redis 主机")
    redis_port: int = Field(default=6379, description="Redis 端口")
    redis_db: int = Field(default=0, description="Redis 数据库号")
    redis_password: str = Field(default="", description="Redis 密码")

    # OSS
    oss_enabled: bool = Field(default=False, description="是否启用 OSS")
    oss_endpoint: str = Field(default="", description="OSS Endpoint")
    oss_access_key: str = Field(default="", description="OSS Access Key")
    oss_secret_key: str = Field(default="", description="OSS Secret Key")
    oss_bucket: str = Field(default="", description="OSS Bucket")


# ========== 主配置类 ==========


class FrameworkConfig(BaseSettings):
    """
    框架主配置

    支持从环境变量和配置文件加载
    """

    # 基础配置
    environment: str = Field(default="development", description="运行环境")
    debug: bool = Field(default=False, description="调试模式")

    # 子配置
    llm: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    tool: ToolConfig = Field(default_factory=ToolConfig)
    workspace: WorkspaceConfigSettings = Field(default_factory=WorkspaceConfigSettings)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    qveris: QVerisConfig = Field(default_factory=QVerisConfig)

    class Config:
        env_prefix = "AGENT_FRAMEWORK_"
        env_nested_delimiter = "__"
        case_sensitive = False

    @classmethod
    def from_yaml(cls, path: str) -> "FrameworkConfig":
        """从 YAML 文件加载配置"""
        import yaml

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(**data)

    @classmethod
    def from_json(cls, path: str) -> "FrameworkConfig":
        """从 JSON 文件加载配置"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return cls(**data)

    @classmethod
    def from_env(cls) -> "FrameworkConfig":
        """从环境变量加载配置"""
        return cls()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()

    def to_yaml(self, path: str) -> None:
        """保存为 YAML 文件"""
        import yaml

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False)

    def to_json(self, path: str) -> None:
        """保存为 JSON 文件"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


# ========== 配置管理器 ==========


class ConfigManager:
    """
    配置管理器

    提供配置的集中管理和访问
    """

    _instance: Optional["ConfigManager"] = None
    _config: Optional[FrameworkConfig] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ConfigManager":
        """获取配置管理器实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def config(self) -> FrameworkConfig:
        """获取当前配置"""
        if self._config is None:
            self._config = self._load_config()
        return self._config

    def _load_config(self) -> FrameworkConfig:
        """加载配置"""
        # 1. 先从环境变量加载基础配置
        config = FrameworkConfig.from_env()

        # 2. 检查是否指定了配置文件
        config_file = os.environ.get("AGENT_FRAMEWORK_CONFIG_FILE")

        if config_file:
            path = Path(config_file)
            if path.exists():
                if path.suffix in [".yaml", ".yml"]:
                    file_config = FrameworkConfig.from_yaml(str(path))
                elif path.suffix == ".json":
                    file_config = FrameworkConfig.from_json(str(path))
                else:
                    logger.warning(f"不支持的配置文件格式: {path.suffix}")
                    file_config = None

                if file_config:
                    # 合并配置（环境变量优先）
                    config = self._merge_configs(file_config, config)
                    logger.info(f"已加载配置文件: {config_file}")
            else:
                logger.warning(f"配置文件不存在: {config_file}")

        return config

    def _merge_configs(
        self, base: FrameworkConfig, override: FrameworkConfig
    ) -> FrameworkConfig:
        """合并配置（override 优先）"""
        base_dict = base.to_dict()
        override_dict = override.to_dict()

        def deep_merge(base: Dict, override: Dict) -> Dict:
            result = base.copy()
            for key, value in override.items():
                if (
                    key in result
                    and isinstance(result[key], dict)
                    and isinstance(value, dict)
                ):
                    result[key] = deep_merge(result[key], value)
                elif value is not None:
                    result[key] = value
            return result

        merged = deep_merge(base_dict, override_dict)
        return FrameworkConfig(**merged)

    def reload(self) -> FrameworkConfig:
        """重新加载配置"""
        self._config = self._load_config()
        logger.info("配置已重新加载")
        return self._config

    def update(self, updates: Dict[str, Any]) -> FrameworkConfig:
        """更新配置"""
        current = self.config.to_dict()

        def deep_update(base: Dict, updates: Dict) -> Dict:
            for key, value in updates.items():
                if (
                    key in base
                    and isinstance(base[key], dict)
                    and isinstance(value, dict)
                ):
                    deep_update(base[key], value)
                else:
                    base[key] = value
            return base

        updated = deep_update(current, updates)
        self._config = FrameworkConfig(**updated)
        return self._config

    # 便捷访问方法
    @property
    def llm(self) -> LLMProviderConfig:
        return self.config.llm

    @property
    def agent(self) -> AgentConfig:
        return self.config.agent

    @property
    def tool(self) -> ToolConfig:
        return self.config.tool

    @property
    def workspace(self) -> WorkspaceConfigSettings:
        return self.config.workspace

    @property
    def workflow(self) -> WorkflowConfig:
        return self.config.workflow

    @property
    def observability(self) -> ObservabilityConfig:
        return self.config.observability

    @property
    def storage(self) -> StorageConfig:
        return self.config.storage

    @property
    def qveris(self) -> QVerisConfig:
        return self.config.qveris


# ========== 全局访问函数 ==========


def get_config() -> FrameworkConfig:
    """获取全局配置"""
    return ConfigManager.get_instance().config


def get_config_manager() -> ConfigManager:
    """获取配置管理器"""
    return ConfigManager.get_instance()


# ========== App 配置加载（支持 app_config.yaml） ==========


class AppConfigLoader:
    """
    App 配置加载器

    专门用于加载 config/app_config.yaml 格式的配置，
    并创建 UnifiedLLMClient 实例。

    配置文件格式示例:
    ```yaml
    openai:
      api_key: ${OPENAI_API_KEY:default_key}
      base_url: https://openrouter.ai/api/v1
      models:
        default:
          name: gpt-4o-mini
          max_tokens: 4096
          temperature: 0.1
        light:
          name: gpt-3.5-turbo
          ...
    ```
    """

    _instance: Optional["AppConfigLoader"] = None
    _config: Optional[Dict[str, Any]] = None
    _config_path: Optional[str] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "AppConfigLoader":
        """获取配置加载器单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _resolve_env_var(self, value: str) -> str:
        """
        解析环境变量占位符

        支持格式: ${VAR_NAME:default_value}
        """
        import re

        pattern = r"\$\{([^}:]+)(?::([^}]*))?\}"

        def replace(match):
            var_name = match.group(1)
            default_value = match.group(2) or ""
            return os.environ.get(var_name, default_value)

        return re.sub(pattern, replace, value) if isinstance(value, str) else value

    def _resolve_env_vars_recursive(self, config: Any) -> Any:
        """递归解析配置中的所有环境变量"""
        if isinstance(config, dict):
            return {k: self._resolve_env_vars_recursive(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._resolve_env_vars_recursive(v) for v in config]
        elif isinstance(config, str):
            return self._resolve_env_var(config)
        return config

    def load(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """
        加载配置文件

        Args:
            config_path: 配置文件路径，默认为 config/app_config.yaml

        Returns:
            解析后的配置字典
        """
        import yaml

        # 确定配置文件路径
        if config_path is None:
            # 默认查找 config/app_config.yaml
            project_root = Path(__file__).parent.parent
            config_path = str(project_root / "config" / "app_config.yaml")

        # 如果已加载且路径相同，返回缓存
        if self._config is not None and self._config_path == config_path:
            return self._config

        # 加载配置
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_file, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)

        # 解析环境变量
        self._config = self._resolve_env_vars_recursive(raw_config)
        self._config_path = config_path

        logger.info(f"✅ 已加载配置文件: {config_path}")
        return self._config

    def get_openai_config(self) -> Dict[str, Any]:
        """获取 OpenAI 配置部分"""
        if self._config is None:
            self.load()
        return self._config.get("openai", {})

    def get_model_config(self, tier: str = "default") -> Dict[str, Any]:
        """
        获取指定 tier 的模型配置

        Args:
            tier: 模型 tier（default, light, medium, strong）

        Returns:
            模型配置字典，包含 name, max_tokens, temperature 等
        """
        openai_config = self.get_openai_config()
        models = openai_config.get("models", {})

        if tier not in models:
            available = list(models.keys())
            raise ValueError(f"未知的模型 tier: {tier}。可用: {available}")

        return models[tier]

    def create_llm_client(
        self,
        model_name: str = None,
        tier: str = "default",
        client_type: str = "langchain",
        **override_kwargs,
    ):
        """
        创建 UnifiedLLMClient 实例
        
        支持三种方式（按优先级）：
        1. 指定 model_name（使用 models 配置）
        2. 使用 model_selection.default（如果配置了）
        3. 旧方式：使用 tier（使用 openai.models 配置，向后兼容）

        Args:
            model_name: 模型名称（如 "qwen-plus", "deepseek-v3"），优先使用
            tier: 模型 tier（default, light, medium, strong），向后兼容
            client_type: 客户端类型（async_openai, langchain, litellm）
            **override_kwargs: 覆盖默认配置的参数

        Returns:
            UnifiedLLMClient 实例
        """
        from src.utils.llm_client import UnifiedLLMClient
        
        # 如果未指定 model_name，尝试从 model_selection.default 获取
        if not model_name and self.has_models_config():
            model_selection = self.get_model_selection_config()
            default_model = model_selection.get("default")
            if default_model:
                model_name = default_model
        
        # 使用新的 model_name 方式
        if model_name and self.has_models_config():
            models_config = self.get_models_config()
            
            # 查找模型配置
            model_config = None
            if model_name in models_config:
                model_config = models_config[model_name]
            else:
                # 尝试模糊匹配
                for key, config in models_config.items():
                    if config.get("model_name") == model_name or key in model_name:
                        model_config = config
                        break
            
            if model_config:
                # 使用新格式配置
                kwargs = {
                    "provider": self._get_provider_from_url(model_config.get("base_url", "")),
                    "base_url": model_config.get("base_url", ""),
                    "api_key": model_config.get("api_key", ""),
                    "model_name": model_config.get("model_name", model_name),
                    "client_type": client_type,
                    "temperature": model_config.get("temperature", 0.3),
                    "max_tokens": model_config.get("max_tokens", 4096),
                    "max_retries": model_config.get("max_retries", 3),
                }
                kwargs.update(override_kwargs)
                return UnifiedLLMClient(**kwargs)
        
        # 回退到旧的 tier 方式
        openai_config = self.get_openai_config()
        model_config = self.get_model_config(tier)
        http_config = openai_config.get("http_client", {})
        
        # 从 URL 推断 provider，而不是硬编码
        base_url = openai_config.get("base_url", "https://openrouter.ai/api/v1")
        provider = self._get_provider_from_url(base_url)

        # 构建参数
        kwargs = {
            "provider": provider,
            "base_url": base_url,
            "api_key": openai_config.get("api_key", ""),
            "model_name": model_config.get("name", "gpt-4o-mini"),
            "client_type": client_type,
            "temperature": model_config.get("temperature", 0.1),
            "max_tokens": model_config.get("max_tokens", 4096),
            "timeout": http_config.get("timeout", {}).get("read", 300.0),
            "max_retries": http_config.get("retries", 3),
            "http_config": http_config,
        }

        # 应用覆盖参数
        kwargs.update(override_kwargs)

        return UnifiedLLMClient(**kwargs)
    
    def _get_provider_from_url(self, base_url: str) -> str:
        """从 URL 推断提供商"""
        if "dashscope" in base_url:
            return "dashscope"
        elif "openrouter" in base_url:
            return "openrouter"
        elif "bigmodel" in base_url:
            return "zhipu"
        elif "siliconflow" in base_url:
            return "siliconflow"
        else:
            return "openai_compatible"

    def get_available_tiers(self) -> List[str]:
        """获取所有可用的模型 tier"""
        openai_config = self.get_openai_config()
        return list(openai_config.get("models", {}).keys())

    def get_models_config(self) -> Dict[str, Any]:
        """
        获取多模型配置部分（新格式）
        
        Returns:
            模型配置字典，键为模型名称，值为模型配置
        """
        if self._config is None:
            self.load()
        return self._config.get("models", {})
    
    def get_model_selection_config(self) -> Dict[str, Any]:
        """
        获取模型选择策略配置
        
        Returns:
            模型选择策略配置字典
        """
        if self._config is None:
            self.load()
        return self._config.get("model_selection", {})
    
    def has_models_config(self) -> bool:
        """检查是否存在新格式的 models 配置"""
        if self._config is None:
            self.load()
        models = self._config.get("models", {})
        # 检查是否是新格式（包含 api_key 字段）
        if models:
            first_model = next(iter(models.values()), {})
            return "api_key" in first_model or "base_url" in first_model
        return False

    def get_qveris_config(self) -> Dict[str, Any]:
        """
        获取 QVeris 配置部分

        Returns:
            QVeris 配置字典，包含:
            - enabled: 是否启用
            - api_key: API Key
            - base_url: API 基础 URL
            - default_limit: 默认搜索结果数量
            - cache_ttl: 缓存时间
            - timeout: 超时时间
            - max_retries: 最大重试次数
            - auto_register_discovered: 是否自动注册发现的工具
        """
        if self._config is None:
            self.load()
        return self._config.get("qveris", {})

    def create_qveris_adapter(
        self,
        tool_registry: Any,
        session_id: Optional[str] = None,
        **override_kwargs,
    ) -> Any:
        """
        创建 QVeris 工具适配器

        Args:
            tool_registry: 工具注册表实例
            session_id: 会话 ID（用于追踪）
            **override_kwargs: 覆盖默认配置的参数

        Returns:
            QVerisToolAdapter 实例，如果 QVeris 未启用则返回 None
        """
        from .tools.qveris_adapter import QVerisToolAdapter

        qveris_config = self.get_qveris_config()

        # 检查是否启用
        if not qveris_config.get("enabled", False):
            logger.info("QVeris 未启用，跳过适配器创建")
            return None

        # 检查 API Key
        api_key = qveris_config.get("api_key", "")
        if not api_key:
            logger.warning("QVeris API Key 未配置，QVeris 功能可能不可用")

        # 构建参数
        # 注意：auto_register_discovered 默认为 False
        # 让 Agent 按照 QVeris 设计模式工作：search_tools -> execute_tool
        # 自动注册可能导致工具名称过长（超过 LLM 的 64 字符限制）
        kwargs = {
            "api_key": api_key,
            "base_url": qveris_config.get("base_url", "https://qveris.ai"),
            "cache_ttl": qveris_config.get("cache_ttl", 3600),
            "auto_register_discovered": qveris_config.get(
                "auto_register_discovered", False
            ),
            "session_id": session_id,
        }

        # 应用覆盖参数
        kwargs.update(override_kwargs)

        return QVerisToolAdapter(tool_registry, **kwargs)

    def reload(self) -> Dict[str, Any]:
        """重新加载配置"""
        self._config = None
        return self.load(self._config_path)


def get_app_config_loader() -> AppConfigLoader:
    """获取 App 配置加载器"""
    return AppConfigLoader.get_instance()


# ========== 模型注册表（支持多模型配置） ==========


class ModelRegistry:
    """
    模型注册表 - 管理多个 LLM 模型配置
    
    支持：
    - 每个模型独立的 api_key、base_url 配置
    - 按模型名称创建 LLM 客户端
    - 客户端缓存（避免重复创建）
    - 智能模型选择（根据任务复杂度和能力需求）
    
    配置格式示例（config/app_config.yaml）:
    ```yaml
    models:
      qwen-plus:
        api_key: "sk-xxx"
        base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model_name: "qwen-plus"
        type: "language"
        capabilities: [reasoning, coding]
        cost_tier: "low"
      gpt-4o:
        api_key: "sk-or-xxx"
        base_url: "https://openrouter.ai/api/v1"
        model_name: "openai/gpt-4o"
        type: "multimodal"
        capabilities: [reasoning, coding, vision]
        cost_tier: "high"
    ```
    """
    
    _instance: Optional["ModelRegistry"] = None
    
    def __init__(self, models_config: Dict[str, Any], selection_config: Dict[str, Any] = None):
        """
        初始化模型注册表
        
        Args:
            models_config: 模型配置字典
            selection_config: 模型选择策略配置
        """
        self._models = models_config
        self._selection_config = selection_config or {}
        self._clients: Dict[str, Any] = {}  # 客户端缓存
        
        logger.info(f"✅ ModelRegistry 初始化完成，可用模型: {list(self._models.keys())}")
    
    @classmethod
    def get_instance(cls) -> "ModelRegistry":
        """获取模型注册表单例"""
        if cls._instance is None:
            loader = get_app_config_loader()
            loader.load()
            models_config = loader.get_models_config()
            selection_config = loader.get_model_selection_config()
            cls._instance = cls(models_config, selection_config)
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None
    
    def get_model_config(self, model_name: str) -> Dict[str, Any]:
        """
        获取指定模型的配置
        
        Args:
            model_name: 模型名称（如 "qwen-plus", "deepseek-v3"）
            
        Returns:
            模型配置字典
            
        Raises:
            ValueError: 如果模型不存在
        """
        # 尝试直接匹配
        if model_name in self._models:
            return self._models[model_name]
        
        # 尝试模糊匹配（支持带前缀的模型名，如 "deepseek/deepseek-v3"）
        for key, config in self._models.items():
            if config.get("model_name") == model_name:
                return config
            # 检查模型名是否包含在 key 中
            if key in model_name or model_name in key:
                return config
        
        available = list(self._models.keys())
        raise ValueError(f"未知的模型: {model_name}。可用模型: {available}")
    
    def get_available_models(
        self,
        type_filter: str = None,
        capability_filter: List[str] = None,
    ) -> List[str]:
        """
        获取符合条件的可用模型列表
        
        Args:
            type_filter: 类型过滤（如 "language", "multimodal", "embedding"）
            capability_filter: 能力过滤（如 ["reasoning", "coding"]）
            
        Returns:
            符合条件的模型名称列表
        """
        result = []
        for name, config in self._models.items():
            # 排除 embedding 模型（除非明确请求）
            if config.get("type") == "embedding" and type_filter != "embedding":
                continue
                
            # 类型过滤
            if type_filter and config.get("type") != type_filter:
                continue
            
            # 能力过滤
            if capability_filter:
                capabilities = config.get("capabilities", [])
                if not all(cap in capabilities for cap in capability_filter):
                    continue
            
            result.append(name)
        
        return result
    
    def create_client(
        self,
        model_name: str,
        client_type: str = "langchain",
        use_cache: bool = True,
        **override_kwargs,
    ) -> Any:
        """
        为指定模型创建 LLM 客户端
        
        Args:
            model_name: 模型名称
            client_type: 客户端类型（async_openai, langchain, litellm）
            use_cache: 是否使用缓存
            **override_kwargs: 覆盖默认配置的参数
            
        Returns:
            UnifiedLLMClient 实例
        """
        from src.utils.llm_client import UnifiedLLMClient
        
        # 缓存键
        cache_key = f"{model_name}:{client_type}"
        
        # 检查缓存
        if use_cache and cache_key in self._clients:
            return self._clients[cache_key]
        
        # 获取模型配置
        try:
            config = self.get_model_config(model_name)
        except ValueError:
            # 如果找不到模型，使用默认模型
            default_model = self._selection_config.get("default", "qwen-plus")
            logger.warning(f"模型 {model_name} 未配置，使用默认模型 {default_model}")
            config = self.get_model_config(default_model)
        
        # 构建参数
        kwargs = {
            "provider": self._get_provider_from_url(config.get("base_url", "")),
            "base_url": config.get("base_url", ""),
            "api_key": config.get("api_key", ""),
            "model_name": config.get("model_name", model_name),
            "client_type": client_type,
            "temperature": config.get("temperature", 0.3),
            "max_tokens": config.get("max_tokens", 4096),
            "max_retries": config.get("max_retries", 3),
        }
        
        # 应用覆盖参数
        kwargs.update(override_kwargs)
        
        # 创建客户端
        client = UnifiedLLMClient(**kwargs)
        
        # 缓存
        if use_cache:
            self._clients[cache_key] = client
        
        logger.info(f"✅ 创建 LLM 客户端: {model_name} ({client_type})")
        return client
    
    def _get_provider_from_url(self, base_url: str) -> str:
        """从 URL 推断提供商"""
        if "dashscope" in base_url:
            return "dashscope"
        elif "openrouter" in base_url:
            return "openrouter"
        elif "bigmodel" in base_url:
            return "zhipu"
        elif "siliconflow" in base_url:
            return "siliconflow"
        else:
            return "openai_compatible"
    
    def select_model(
        self,
        task_complexity: str = "medium",
        required_capabilities: List[str] = None,
        prefer_low_cost: bool = None,
    ) -> str:
        """
        智能选择合适的模型
        
        Args:
            task_complexity: 任务复杂度（"simple", "medium", "complex", "multimodal"）
            required_capabilities: 所需能力列表
            prefer_low_cost: 是否优先选择低成本模型
            
        Returns:
            推荐的模型名称
        """
        # 使用配置中的偏好设置
        if prefer_low_cost is None:
            prefer_low_cost = self._selection_config.get("prefer_low_cost", True)
        
        # 首先检查复杂度映射
        complexity_mapping = self._selection_config.get("complexity_mapping", {})
        if task_complexity in complexity_mapping:
            suggested = complexity_mapping[task_complexity]
            if suggested in self._models:
                return suggested
        
        # 根据能力过滤
        candidates = self.get_available_models(capability_filter=required_capabilities)
        
        if not candidates:
            # 回退到默认模型
            return self._selection_config.get("default", "qwen-plus")
        
        # 按成本排序
        if prefer_low_cost:
            cost_order = {"low": 0, "medium": 1, "high": 2}
            candidates.sort(
                key=lambda m: cost_order.get(
                    self._models.get(m, {}).get("cost_tier", "medium"), 1
                )
            )
        
        return candidates[0]
    
    def get_default_model(self) -> str:
        """获取默认模型名称"""
        return self._selection_config.get("default", "qwen-plus")
    
    def get_fallback_model(self) -> str:
        """获取备用模型名称"""
        return self._selection_config.get("fallback", "deepseek-v3")
    
    def get_models_info(self) -> List[Dict[str, Any]]:
        """
        获取所有模型的信息列表（用于提示模板）
        
        Returns:
            模型信息列表，包含名称、类型、能力、成本等
        """
        result = []
        for name, config in self._models.items():
            if config.get("type") == "embedding":
                continue
            result.append({
                "name": name,
                "model_name": config.get("model_name", name),
                "type": config.get("type", "language"),
                "capabilities": config.get("capabilities", []),
                "cost_tier": config.get("cost_tier", "medium"),
                "max_tokens": config.get("max_tokens", 4096),
            })
        return result
    
    def clear_cache(self) -> None:
        """清除客户端缓存"""
        self._clients.clear()
        logger.info("已清除 ModelRegistry 客户端缓存")


def get_model_registry() -> ModelRegistry:
    """获取模型注册表单例"""
    return ModelRegistry.get_instance()


def create_llm_client_by_name(
    model_name: str,
    client_type: str = "langchain",
    config_path: Optional[str] = None,
    **kwargs,
) -> Any:
    """
    便捷函数：按模型名创建 LLM 客户端
    
    Args:
        model_name: 模型名称（如 "qwen-plus", "deepseek-v3"）
        client_type: 客户端类型
        config_path: 配置文件路径（可选）
        **kwargs: 覆盖默认配置
        
    Returns:
        UnifiedLLMClient 实例
    """
    if config_path:
        get_app_config_loader().load(config_path)
        ModelRegistry.reset_instance()
    
    return get_model_registry().create_client(model_name, client_type, **kwargs)


def create_llm_client(
    tier: str = "default",
    client_type: str = "langchain",
    config_path: Optional[str] = None,
    **kwargs,
):
    """
    便捷函数：创建 LLM 客户端

    从 config/app_config.yaml 加载配置并创建 UnifiedLLMClient。

    Args:
        tier: 模型 tier（default, light, medium, strong）
        client_type: 客户端类型（async_openai, langchain, litellm）
        config_path: 配置文件路径（可选）
        **kwargs: 覆盖默认配置的参数

    Returns:
        UnifiedLLMClient 实例

    Example:
        ```python
        from src.config import create_llm_client

        # 使用默认模型
        client = create_llm_client()

        # 使用高性能模型
        client = create_llm_client(tier="strong")

        # 自定义配置
        client = create_llm_client(
            tier="default",
            client_type="async_openai",
            temperature=0.5,
        )
        ```
    """
    loader = get_app_config_loader()
    if config_path:
        loader.load(config_path)
    return loader.create_llm_client(tier=tier, client_type=client_type, **kwargs)


def get_qveris_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    便捷函数：获取 QVeris 配置

    从 config/app_config.yaml 加载 QVeris 配置。

    Args:
        config_path: 配置文件路径（可选）

    Returns:
        QVeris 配置字典
    """
    loader = get_app_config_loader()
    if config_path:
        loader.load(config_path)
    return loader.get_qveris_config()


def create_qveris_adapter(
    tool_registry: Any,
    session_id: Optional[str] = None,
    config_path: Optional[str] = None,
    **kwargs,
) -> Any:
    """
    便捷函数：创建 QVeris 工具适配器

    从 config/app_config.yaml 加载配置并创建 QVerisToolAdapter。

    Args:
        tool_registry: 工具注册表实例
        session_id: 会话 ID（用于追踪）
        config_path: 配置文件路径（可选）
        **kwargs: 覆盖默认配置的参数

    Returns:
        QVerisToolAdapter 实例，如果 QVeris 未启用或配置错误则返回 None

    Example:
        ```python
        from src.config import create_qveris_adapter
        from src.tools import ToolRegistry

        registry = ToolRegistry()
        adapter = create_qveris_adapter(registry)
        if adapter:
            adapter.register_meta_tools()
        ```
    """
    loader = get_app_config_loader()
    if config_path:
        loader.load(config_path)
    return loader.create_qveris_adapter(
        tool_registry=tool_registry, session_id=session_id, **kwargs
    )


# ========== 导出 ==========

__all__ = [
    # 配置模型
    "LLMProviderConfig",
    "AgentConfig",
    "ToolConfig",
    "QVerisConfig",
    "WorkspaceConfigSettings",
    "WorkflowConfig",
    "ObservabilityConfig",
    "StorageConfig",
    "FrameworkConfig",
    # 配置管理
    "ConfigManager",
    "get_config",
    "get_config_manager",
    # App 配置加载（app_config.yaml）
    "AppConfigLoader",
    "get_app_config_loader",
    "create_llm_client",
    # 模型注册表（多模型支持）
    "ModelRegistry",
    "get_model_registry",
    "create_llm_client_by_name",
    # QVeris 配置
    "get_qveris_config",
    "create_qveris_adapter",
]

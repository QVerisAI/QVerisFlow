"""
存储配置

提供存储层的统一配置模型，包括：
- 本地文件存储配置
- PostgreSQL 配置
- Redis 配置
- OSS 配置
- 检查点存储配置
- 追踪存储配置

支持两种加载方式：
1. 从环境变量加载（StorageConfig.from_env()）
2. 从 app_config.yaml 的 storage 字典加载（StorageConfig.from_app_config()）
"""

from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class DeployMode(str, Enum):
    """部署模式"""

    BARE_METAL = "bare-metal"
    DOCKER = "docker"


class CheckpointerType(str, Enum):
    """检查点存储类型"""

    MEMORY = "memory"
    REDIS = "redis"
    POSTGRESQL = "postgresql"
    FILE = "file"


class LocalStorageConfig(BaseModel):
    """本地文件存储配置"""

    data_dir: str = Field(default="./data", description="数据根目录")
    workspace_dir: str = Field(default="./data/workspaces", description="工作空间目录")
    storage_dir: str = Field(default="./data/storage", description="文件存储目录")
    log_dir: str = Field(default="./data/logs", description="日志目录")
    temp_dir: str = Field(default="./data/temp", description="临时文件目录")


class PostgreSQLConfig(BaseModel):
    """PostgreSQL 配置"""

    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    database: str = Field(default="agent_framework")
    user: str = Field(default="postgres")
    password: str = Field(default="")
    pool_size: int = Field(default=10)
    max_overflow: int = Field(default=20)
    pool_pre_ping: bool = Field(default=True)

    def _encode_password(self) -> str:
        """URL 编码密码（处理特殊字符）"""
        from urllib.parse import quote_plus

        return quote_plus(self.password) if self.password else ""

    @property
    def url(self) -> str:
        """获取同步连接 URL"""
        if self.password:
            encoded_password = self._encode_password()
            return f"postgresql://{self.user}:{encoded_password}@{self.host}:{self.port}/{self.database}"
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.database}"

    @property
    def async_url(self) -> str:
        """获取异步连接 URL (asyncpg)"""
        if self.password:
            encoded_password = self._encode_password()
            return f"postgresql+asyncpg://{self.user}:{encoded_password}@{self.host}:{self.port}/{self.database}"
        return (
            f"postgresql+asyncpg://{self.user}@{self.host}:{self.port}/{self.database}"
        )

    @property
    def asyncpg_url(self) -> str:
        """获取纯 asyncpg 连接 URL (不带 driver 前缀)"""
        if self.password:
            encoded_password = self._encode_password()
            return f"postgresql://{self.user}:{encoded_password}@{self.host}:{self.port}/{self.database}"
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.database}"


class RedisConfig(BaseModel):
    """Redis 配置"""

    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    password: Optional[str] = Field(default=None)
    db: int = Field(default=0)
    max_connections: int = Field(default=20)
    ssl: bool = Field(default=False)
    key_prefix: str = Field(default="qveris:", description="键前缀（多项目隔离）")

    @property
    def url(self) -> str:
        """获取 Redis URL"""
        scheme = "rediss" if self.ssl else "redis"
        if self.password:
            return f"{scheme}://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"{scheme}://{self.host}:{self.port}/{self.db}"


class OSSConfig(BaseModel):
    """OSS 配置"""

    provider: str = Field(default="minio", description="minio 或 aliyun")
    endpoint: str = Field(default="localhost:9000")
    access_key: str = Field(default="")
    secret_key: str = Field(default="")
    bucket_name: str = Field(default="agent-framework")
    secure: bool = Field(default=False)
    console_port: int = Field(default=9001, description="MinIO 控制台端口")
    # 阿里云 OSS 配置
    aliyun_endpoint: str = Field(default="", description="阿里云 OSS Endpoint")
    aliyun_access_key_id: str = Field(default="", description="阿里云 Access Key ID")
    aliyun_access_key_secret: str = Field(
        default="", description="阿里云 Access Key Secret"
    )
    aliyun_bucket: str = Field(default="", description="阿里云 Bucket 名称")


class CheckpointStorageConfig(BaseModel):
    """检查点存储配置"""

    type: CheckpointerType = Field(
        default=CheckpointerType.MEMORY,
        description="检查点存储类型",
    )
    # Redis 特定配置
    redis_prefix: str = Field(
        default="langgraph:checkpoint:",
        description="Redis 键前缀",
    )
    redis_ttl: Optional[int] = Field(
        default=None,
        description="Redis 过期时间（秒），None 表示永不过期",
    )
    # PostgreSQL 特定配置
    postgres_table: str = Field(
        default="langgraph_checkpoints",
        description="PostgreSQL 表名",
    )
    # 文件系统特定配置
    file_path: str = Field(
        default="./data/checkpoints",
        description="文件系统检查点目录",
    )
    # 序列化配置
    serializer: str = Field(
        default="json",
        description="序列化方式: json 或 pickle",
    )


class TraceStorageConfig(BaseModel):
    """追踪存储配置"""

    type: str = Field(
        default="file",
        description="追踪存储类型: file, database, oss",
    )
    # 文件系统配置
    file_path: str = Field(
        default="./data/traces",
        description="追踪文件存储目录",
    )
    # 数据库配置
    postgres_table_prefix: str = Field(
        default="trace_",
        description="PostgreSQL 表名前缀",
    )
    # OSS 配置
    oss_prefix: str = Field(
        default="traces/",
        description="OSS 对象前缀",
    )
    # 保留配置
    retention_days: int = Field(
        default=30,
        description="追踪数据保留天数",
    )


class StorageConfig(BaseModel):
    """
    统一存储配置

    整合所有存储相关配置，包括：
    - 部署模式（bare-metal / docker）
    - 本地文件存储
    - 数据库 (PostgreSQL)
    - 缓存 (Redis)
    - 对象存储 (OSS)
    - 检查点存储
    - 追踪存储
    """

    deploy_mode: DeployMode = Field(
        default=DeployMode.BARE_METAL,
        description="部署模式: bare-metal 或 docker",
    )
    local: LocalStorageConfig = Field(default_factory=LocalStorageConfig)
    postgres: PostgreSQLConfig = Field(default_factory=PostgreSQLConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    oss: OSSConfig = Field(default_factory=OSSConfig)
    checkpoint: CheckpointStorageConfig = Field(default_factory=CheckpointStorageConfig)
    trace: TraceStorageConfig = Field(default_factory=TraceStorageConfig)

    # 文件存储配置（向后兼容）
    base_storage_path: str = Field(default="./data/storage")

    # 功能开关
    enable_oss: bool = Field(default=False, description="是否启用 OSS")
    enable_redis: bool = Field(default=False, description="是否启用 Redis")
    enable_postgres: bool = Field(default=False, description="是否启用 PostgreSQL")

    @classmethod
    def from_env(cls) -> "StorageConfig":
        """从环境变量创建配置"""
        import os

        deploy_mode_str = os.getenv("DEPLOY_MODE", "bare-metal")
        try:
            deploy_mode = DeployMode(deploy_mode_str)
        except ValueError:
            deploy_mode = DeployMode.BARE_METAL

        # Docker 模式下，默认使用容器服务名
        is_docker = deploy_mode == DeployMode.DOCKER
        default_pg_host = "postgres" if is_docker else "localhost"
        default_redis_host = "redis" if is_docker else "localhost"
        default_minio_endpoint = "minio:9000" if is_docker else "localhost:9000"

        return cls(
            deploy_mode=deploy_mode,
            local=LocalStorageConfig(
                data_dir=os.getenv("LOCAL_DATA_DIR", "./data"),
                workspace_dir=os.getenv("WORKSPACE_DIR", "./data/workspaces"),
                storage_dir=os.getenv("STORAGE_DIR", "./data/storage"),
                log_dir=os.getenv("LOG_DIR", "./data/logs"),
                temp_dir=os.getenv("TEMP_DIR", "./data/temp"),
            ),
            postgres=PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", default_pg_host),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
                pool_size=int(os.getenv("POSTGRES_POOL_SIZE", "10")),
                max_overflow=int(os.getenv("POSTGRES_MAX_OVERFLOW", "20")),
            ),
            redis=RedisConfig(
                host=os.getenv("REDIS_HOST", default_redis_host),
                port=int(os.getenv("REDIS_PORT", "6379")),
                password=os.getenv("REDIS_PASSWORD") or None,
                db=int(os.getenv("REDIS_DB", "0")),
                max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "20")),
                key_prefix=os.getenv("REDIS_KEY_PREFIX", "qveris:"),
            ),
            oss=OSSConfig(
                provider=os.getenv("OSS_PROVIDER", "minio"),
                endpoint=os.getenv("MINIO_ENDPOINT", default_minio_endpoint),
                access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
                secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
                bucket_name=os.getenv("MINIO_BUCKET", "agent-framework"),
                secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
                aliyun_endpoint=os.getenv("ALIYUN_OSS_ENDPOINT", ""),
                aliyun_access_key_id=os.getenv("ALIYUN_OSS_ACCESS_KEY_ID", ""),
                aliyun_access_key_secret=os.getenv("ALIYUN_OSS_ACCESS_KEY_SECRET", ""),
                aliyun_bucket=os.getenv("ALIYUN_OSS_BUCKET", ""),
            ),
            checkpoint=CheckpointStorageConfig(
                type=CheckpointerType(os.getenv("CHECKPOINT_TYPE", "memory")),
                redis_prefix=os.getenv(
                    "CHECKPOINT_REDIS_PREFIX", "langgraph:checkpoint:"
                ),
                redis_ttl=(
                    int(os.getenv("CHECKPOINT_REDIS_TTL"))
                    if os.getenv("CHECKPOINT_REDIS_TTL")
                    else None
                ),
                file_path=os.getenv("CHECKPOINT_FILE_PATH", "./data/checkpoints"),
            ),
            trace=TraceStorageConfig(
                type=os.getenv("TRACE_STORAGE_TYPE", "file"),
                file_path=os.getenv("TRACE_FILE_PATH", "./data/traces"),
                retention_days=int(os.getenv("TRACE_RETENTION_DAYS", "30")),
            ),
            enable_postgres=os.getenv("ENABLE_POSTGRES", "false").lower() == "true",
            enable_redis=os.getenv("ENABLE_REDIS", "false").lower() == "true",
            enable_oss=os.getenv("ENABLE_OSS", "false").lower() == "true",
            base_storage_path=os.getenv("STORAGE_DIR", "./data/storage"),
        )

    @classmethod
    def from_app_config(cls, config_dict: Dict[str, Any]) -> "StorageConfig":
        """
        从 app_config.yaml 的 storage 部分创建配置

        Args:
            config_dict: app_config.yaml 中 storage 键对应的字典
                         （环境变量已由 AppConfigLoader 解析完毕）

        Returns:
            StorageConfig 实例
        """
        if not config_dict:
            # 没有 storage 配置，回退到环境变量
            return cls.from_env()

        deploy_mode_str = config_dict.get("deploy_mode", "bare-metal")
        try:
            deploy_mode = DeployMode(deploy_mode_str)
        except ValueError:
            deploy_mode = DeployMode.BARE_METAL

        # 解析本地存储
        local_cfg = config_dict.get("local", {})
        local = LocalStorageConfig(
            data_dir=local_cfg.get("data_dir", "./data"),
            workspace_dir=local_cfg.get("workspace_dir", "./data/workspaces"),
            storage_dir=local_cfg.get("storage_dir", "./data/storage"),
            log_dir=local_cfg.get("log_dir", "./data/logs"),
            temp_dir=local_cfg.get("temp_dir", "./data/temp"),
        )

        # 解析 PostgreSQL
        pg_cfg = config_dict.get("postgres", {})
        pg_enabled_raw = pg_cfg.get("enabled", "false")
        pg_enabled = (
            pg_enabled_raw
            if isinstance(pg_enabled_raw, bool)
            else str(pg_enabled_raw).lower() == "true"
        )
        postgres = PostgreSQLConfig(
            host=pg_cfg.get("host", "localhost"),
            port=int(pg_cfg.get("port", 5432)),
            database=pg_cfg.get("database", "agent_framework"),
            user=pg_cfg.get("user", "postgres"),
            password=pg_cfg.get("password", ""),
            pool_size=int(pg_cfg.get("pool_size", 10)),
            max_overflow=int(pg_cfg.get("max_overflow", 20)),
            pool_pre_ping=(
                pg_cfg.get("pool_pre_ping", True)
                if isinstance(pg_cfg.get("pool_pre_ping", True), bool)
                else str(pg_cfg.get("pool_pre_ping", "true")).lower() == "true"
            ),
        )

        # 解析 Redis
        redis_cfg = config_dict.get("redis", {})
        redis_enabled_raw = redis_cfg.get("enabled", "false")
        redis_enabled = (
            redis_enabled_raw
            if isinstance(redis_enabled_raw, bool)
            else str(redis_enabled_raw).lower() == "true"
        )
        redis_password = redis_cfg.get("password", None)
        if redis_password == "" or redis_password is None:
            redis_password = None
        redis = RedisConfig(
            host=redis_cfg.get("host", "localhost"),
            port=int(redis_cfg.get("port", 6379)),
            password=redis_password,
            db=int(redis_cfg.get("db", 0)),
            max_connections=int(redis_cfg.get("max_connections", 20)),
            ssl=(
                redis_cfg.get("ssl", False)
                if isinstance(redis_cfg.get("ssl", False), bool)
                else str(redis_cfg.get("ssl", "false")).lower() == "true"
            ),
            key_prefix=redis_cfg.get("key_prefix", "qveris:"),
        )

        # 解析 OSS
        oss_cfg = config_dict.get("oss", {})
        oss_enabled_raw = oss_cfg.get("enabled", "false")
        oss_enabled = (
            oss_enabled_raw
            if isinstance(oss_enabled_raw, bool)
            else str(oss_enabled_raw).lower() == "true"
        )
        aliyun_cfg = oss_cfg.get("aliyun", {})
        oss_secure_raw = oss_cfg.get("secure", False)
        oss_secure = (
            oss_secure_raw
            if isinstance(oss_secure_raw, bool)
            else str(oss_secure_raw).lower() == "true"
        )
        oss = OSSConfig(
            provider=oss_cfg.get("provider", "minio"),
            endpoint=oss_cfg.get("endpoint", "localhost:9000"),
            access_key=oss_cfg.get("access_key", "minioadmin"),
            secret_key=oss_cfg.get("secret_key", "minioadmin"),
            bucket_name=oss_cfg.get("bucket", "agent-framework"),
            secure=oss_secure,
            console_port=int(oss_cfg.get("console_port", 9001)),
            aliyun_endpoint=aliyun_cfg.get("endpoint", ""),
            aliyun_access_key_id=aliyun_cfg.get("access_key_id", ""),
            aliyun_access_key_secret=aliyun_cfg.get("access_key_secret", ""),
            aliyun_bucket=aliyun_cfg.get("bucket", ""),
        )

        # 解析检查点配置
        ckpt_cfg = config_dict.get("checkpoint", {})
        ckpt_type_str = ckpt_cfg.get("type", "memory")
        try:
            ckpt_type = CheckpointerType(ckpt_type_str)
        except ValueError:
            ckpt_type = CheckpointerType.MEMORY

        redis_ttl_raw = ckpt_cfg.get("redis_ttl")
        redis_ttl = int(redis_ttl_raw) if redis_ttl_raw not in (None, "") else None

        checkpoint = CheckpointStorageConfig(
            type=ckpt_type,
            redis_prefix=ckpt_cfg.get("redis_prefix", "langgraph:checkpoint:"),
            redis_ttl=redis_ttl,
            postgres_table=ckpt_cfg.get("postgres_table", "langgraph_checkpoints"),
            file_path=ckpt_cfg.get("file_path", "./data/checkpoints"),
        )

        # 解析追踪配置
        trace_cfg = config_dict.get("trace", {})
        trace = TraceStorageConfig(
            type=trace_cfg.get("type", "file"),
            file_path=trace_cfg.get("file_path", "./data/traces"),
            postgres_table_prefix=trace_cfg.get("postgres_table_prefix", "trace_"),
            oss_prefix=trace_cfg.get("oss_prefix", "traces/"),
            retention_days=int(trace_cfg.get("retention_days", 30)),
        )

        return cls(
            deploy_mode=deploy_mode,
            local=local,
            postgres=postgres,
            redis=redis,
            oss=oss,
            checkpoint=checkpoint,
            trace=trace,
            enable_postgres=pg_enabled,
            enable_redis=redis_enabled,
            enable_oss=oss_enabled,
            base_storage_path=local.storage_dir,
        )


# 导出
__all__ = [
    "DeployMode",
    "CheckpointerType",
    "LocalStorageConfig",
    "PostgreSQLConfig",
    "RedisConfig",
    "OSSConfig",
    "CheckpointStorageConfig",
    "TraceStorageConfig",
    "StorageConfig",
]

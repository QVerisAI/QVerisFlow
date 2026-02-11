"""
Alembic 迁移环境配置

支持：
- 自动从环境变量读取数据库 URL
- 自动检测模型变更
- 在线和离线迁移模式
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# 导入数据库模型的 Base
from src.storage.models.db_models import Base

# Alembic Config 对象
config = context.config

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置目标元数据（用于自动生成迁移）
target_metadata = Base.metadata


# 从环境变量覆盖数据库 URL
def get_url():
    """获取数据库 URL"""
    # 优先使用环境变量
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    # 从配置组合
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "agent_framework")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "")

    if password:
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    # 回退到配置文件中的 URL
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """
    离线模式运行迁移

    生成 SQL 脚本而不实际执行
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式运行迁移

    直接连接数据库执行迁移
    """
    # 覆盖配置中的 URL
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

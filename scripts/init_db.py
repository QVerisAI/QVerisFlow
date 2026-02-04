#!/usr/bin/env python3
"""
数据库初始化脚本

功能：
1. 检查数据库连接
2. 运行 Alembic 迁移
3. 创建初始数据（可选）

使用方法：
    python scripts/init_db.py [--drop] [--seed]

参数：
    --drop: 删除所有表后重新创建
    --seed: 创建初始示例数据
"""

import os
import sys
import argparse
import asyncio
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# 加载环境变量
load_dotenv(project_root / ".env")


def check_environment():
    """检查必要的环境变量"""
    required_vars = []

    # 检查是否启用了 PostgreSQL
    if os.getenv("ENABLE_POSTGRES", "false").lower() == "true":
        # 如果没有 DATABASE_URL，检查各个配置
        if not os.getenv("DATABASE_URL"):
            required_vars.extend(
                [
                    "POSTGRES_HOST",
                    "POSTGRES_PORT",
                    "POSTGRES_DB",
                    "POSTGRES_USER",
                ]
            )

    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print(f"❌ 缺少环境变量: {', '.join(missing)}")
        print("请检查 .env 文件或环境变量配置")
        return False

    return True


async def check_postgres_connection():
    """检查 PostgreSQL 连接"""
    print("\n🔍 检查 PostgreSQL 连接...")

    try:
        from src.storage.database import AsyncDatabaseManager
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

        if await db.health_check():
            print(
                f"✅ PostgreSQL 连接成功: {config.host}:{config.port}/{config.database}"
            )
            await db.close()
            return True
        else:
            print("❌ PostgreSQL 健康检查失败")
            await db.close()
            return False

    except Exception as e:
        print(f"❌ PostgreSQL 连接失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def check_redis_connection():
    """检查 Redis 连接"""
    if os.getenv("ENABLE_REDIS", "false").lower() != "true":
        print("\n⏭️  Redis 未启用，跳过检查")
        return True

    print("\n🔍 检查 Redis 连接...")

    try:
        from src.storage.redis_client import RedisClient

        client = RedisClient(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            db=int(os.getenv("REDIS_DB", "0")),
        )

        await client.connect()

        if await client.ping():
            print(f"✅ Redis 连接成功: {client.host}:{client.port}")
            await client.close()
            return True
        else:
            print("❌ Redis 健康检查失败")
            await client.close()
            return False

    except Exception as e:
        print(f"❌ Redis 连接失败: {e}")
        return False


def check_minio_connection():
    """检查 MinIO 连接"""
    if os.getenv("ENABLE_OSS", "false").lower() != "true":
        print("\n⏭️  OSS 未启用，跳过检查")
        return True

    print("\n🔍 检查 MinIO 连接...")

    try:
        from minio import Minio

        endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
        access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
        secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
        bucket = os.getenv("MINIO_BUCKET", "agent-framework")

        client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

        # 检查存储桶是否存在
        if not client.bucket_exists(bucket):
            print(f"📦 创建存储桶: {bucket}")
            client.make_bucket(bucket)

        print(f"✅ MinIO 连接成功: {endpoint}, 存储桶: {bucket}")
        return True

    except ImportError:
        print("⚠️  minio 库未安装，跳过 MinIO 检查")
        print("   安装: pip install minio")
        return True
    except Exception as e:
        print(f"❌ MinIO 连接失败: {e}")
        return False


def run_migrations(drop_existing: bool = False):
    """运行数据库迁移"""
    print("\n🔄 运行数据库迁移...")

    try:
        from alembic.config import Config
        from alembic import command

        # 找到 alembic.ini
        alembic_ini = project_root / "alembic.ini"
        if not alembic_ini.exists():
            print("❌ 未找到 alembic.ini")
            return False

        alembic_cfg = Config(str(alembic_ini))

        # 设置脚本位置
        migrations_dir = project_root / "src" / "storage" / "migrations"
        alembic_cfg.set_main_option("script_location", str(migrations_dir))

        if drop_existing:
            print("⚠️  删除所有表...")
            command.downgrade(alembic_cfg, "base")

        # 运行迁移
        print("📦 应用迁移...")
        command.upgrade(alembic_cfg, "head")

        print("✅ 数据库迁移完成")
        return True

    except Exception as e:
        print(f"❌ 数据库迁移失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def init_database_direct(drop_existing: bool = False):
    """直接初始化数据库（不使用 Alembic）"""
    print("\n🔄 直接初始化数据库表...")

    try:
        from src.storage.database import AsyncDatabaseManager
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
        await db.init_db(drop_existing=drop_existing)
        await db.close()

        print("✅ 数据库表创建完成")
        return True

    except Exception as e:
        print(f"❌ 数据库初始化失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def seed_data():
    """创建初始示例数据"""
    print("\n🌱 创建初始数据...")

    try:
        from src.storage.database import AsyncDatabaseManager
        from src.storage.config import PostgreSQLConfig
        from src.storage.repositories.agent_repository import AgentDefinitionRepository
        from src.storage.repositories.workflow_repository import (
            WorkflowDefinitionRepository,
        )

        config = PostgreSQLConfig(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "agent_framework"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
        )

        db = AsyncDatabaseManager(config)
        await db.connect()

        # 创建示例 Agent
        agent_repo = AgentDefinitionRepository(db._session_factory)

        sample_agent = {
            "agent_id": "sample_analyst",
            "name": "SampleAnalyst",
            "description": "示例分析 Agent",
            "definition_json": {
                "agent_id": "sample_analyst",
                "name": "SampleAnalyst",
                "description": "示例分析 Agent",
                "version": "1.0.0",
                "execution_type": "executor",
                "domain_type": "general",
                "background_instruction": {
                    "role_description": "你是一个通用分析助手",
                    "capabilities": ["数据分析", "报告生成"],
                },
                "output_instruction": {
                    "format": "markdown",
                    "structure": ["分析结果", "建议"],
                },
                "user_instruction": {
                    "task_description": "分析用户提供的数据",
                },
                "llm_config": {
                    "model_name": "deepseek/deepseek-v3",
                    "temperature": 0.3,
                    "max_tokens": 4096,
                },
            },
            "status": "active",
            "model_name": "deepseek/deepseek-v3",
            "tags": ["sample", "analysis"],
            "author": "system",
        }

        await agent_repo.create(sample_agent)
        print("  ✅ 创建示例 Agent: SampleAnalyst")

        await db.close()
        print("✅ 初始数据创建完成")
        return True

    except Exception as e:
        print(f"❌ 创建初始数据失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    parser = argparse.ArgumentParser(description="Agent Framework 数据库初始化")
    parser.add_argument("--drop", action="store_true", help="删除所有表后重新创建")
    parser.add_argument("--seed", action="store_true", help="创建初始示例数据")
    parser.add_argument(
        "--direct", action="store_true", help="直接创建表（不使用 Alembic）"
    )
    parser.add_argument("--check-only", action="store_true", help="仅检查连接")

    args = parser.parse_args()

    print("=" * 50)
    print("🚀 Agent Framework 数据库初始化")
    print("=" * 50)

    # 检查环境变量
    if not check_environment():
        sys.exit(1)

    # 检查连接
    pg_ok = await check_postgres_connection()
    redis_ok = await check_redis_connection()
    minio_ok = check_minio_connection()

    if args.check_only:
        if pg_ok and redis_ok and minio_ok:
            print("\n✅ 所有连接检查通过")
            sys.exit(0)
        else:
            print("\n❌ 部分连接检查失败")
            sys.exit(1)

    if not pg_ok:
        print("\n❌ PostgreSQL 连接失败，无法继续")
        sys.exit(1)

    # 运行迁移或直接创建表
    if args.direct:
        if not await init_database_direct(args.drop):
            sys.exit(1)
    else:
        if not run_migrations(args.drop):
            # 如果 Alembic 失败，尝试直接创建表
            print("\n⚠️  Alembic 迁移失败，尝试直接创建表...")
            if not await init_database_direct(args.drop):
                sys.exit(1)

    # 创建初始数据
    if args.seed:
        if not await seed_data():
            sys.exit(1)

    print("\n" + "=" * 50)
    print("🎉 数据库初始化完成!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())

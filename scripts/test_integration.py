#!/usr/bin/env python3
"""
集成测试脚本

测试持久化存储功能是否正常工作。

使用方法：
    python scripts/test_integration.py
"""

import os
import sys
import asyncio
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# 加载环境变量
load_dotenv(project_root / ".env")


async def test_database_connection():
    """测试数据库连接"""
    print("\n🧪 测试 PostgreSQL 连接...")

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
            print("✅ PostgreSQL 连接成功")
            await db.close()
            return True
        else:
            print("❌ PostgreSQL 健康检查失败")
            await db.close()
            return False

    except Exception as e:
        print(f"❌ PostgreSQL 测试失败: {e}")
        return False


async def test_redis_connection():
    """测试 Redis 连接"""
    print("\n🧪 测试 Redis 连接...")

    try:
        from src.storage.redis_client import RedisClient

        client = RedisClient(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            db=int(os.getenv("REDIS_DB", "0")),
        )

        await client.connect()

        # 测试基本操作
        test_key = "test:integration"
        await client.set(test_key, "hello", ttl=60)
        value = await client.get(test_key)
        await client.delete(test_key)

        if value == "hello":
            print("✅ Redis 连接成功")
            await client.close()
            return True
        else:
            print("❌ Redis 数据验证失败")
            await client.close()
            return False

    except Exception as e:
        print(f"❌ Redis 测试失败: {e}")
        return False


async def test_workflow_service():
    """测试工作流服务"""
    print("\n🧪 测试工作流服务...")

    try:
        from src.services import WorkflowService
        from src.storage.database import AsyncDatabaseManager
        from src.storage.repositories import (
            WorkflowDefinitionRepository,
            WorkflowExecutionRepository,
        )
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

        workflow_repo = WorkflowDefinitionRepository(db._session_factory)
        execution_repo = WorkflowExecutionRepository(db._session_factory)
        service = WorkflowService(workflow_repo, execution_repo)

        # 测试创建工作流
        test_workflow = {
            "workflow_id": f"test_workflow_{int(asyncio.get_event_loop().time() * 1000)}",
            "name": "测试工作流",
            "description": "集成测试创建的工作流",
            "version": "1.0.0",
            "nodes": [],
            "edges": [],
            "entry_node": "start",
            "exit_nodes": ["end"],
        }

        created = await service.create_workflow_from_dict(test_workflow, author="test")
        print(f"  ✅ 创建工作流: {created.workflow_id}")

        # 测试获取工作流
        retrieved = await service.get_workflow(created.workflow_id)
        if retrieved:
            print(f"  ✅ 获取工作流: {retrieved.name}")
        else:
            print("  ❌ 获取工作流失败")
            return False

        # 测试列出工作流
        workflows = await service.list_workflows()
        print(f"  ✅ 列出工作流: 共 {len(workflows)} 个")

        # 测试删除工作流
        deleted = await service.delete_workflow(created.workflow_id)
        if deleted:
            print(f"  ✅ 删除工作流: {created.workflow_id}")

        await db.close()
        print("✅ 工作流服务测试通过")
        return True

    except Exception as e:
        print(f"❌ 工作流服务测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_agent_service():
    """测试 Agent 服务"""
    print("\n🧪 测试 Agent 服务...")

    try:
        from src.services import AgentService
        from src.storage.database import AsyncDatabaseManager
        from src.storage.repositories import AgentRepository
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

        agent_repo = AgentRepository(db._session_factory)
        service = AgentService(agent_repo)

        # 测试创建 Agent
        test_agent = {
            "agent_id": f"test_agent_{int(asyncio.get_event_loop().time() * 1000)}",
            "name": "TestAgent",
            "description": "集成测试创建的 Agent",
            "version": "1.0.0",
            "execution_type": "executor",
            "domain_type": "general",
            "background_instruction": {
                "role_description": "测试助手",
            },
            "output_instruction": {
                "format_type": "text",
            },
            "user_instruction": {
                "task_description": "测试任务",
            },
            "llm_config": {
                "model_name": "gpt-4",
                "temperature": 0.3,
            },
        }

        created = await service.create_agent_from_dict(test_agent, author="test")
        print(f"  ✅ 创建 Agent: {created.agent_id}")

        # 测试获取 Agent
        retrieved = await service.get_agent(created.agent_id)
        if retrieved:
            print(f"  ✅ 获取 Agent: {retrieved.name}")
        else:
            print("  ❌ 获取 Agent 失败")
            return False

        # 测试列出 Agent
        agents = await service.list_agents()
        print(f"  ✅ 列出 Agent: 共 {len(agents)} 个")

        # 测试删除 Agent
        deleted = await service.delete_agent(created.agent_id)
        if deleted:
            print(f"  ✅ 删除 Agent: {created.agent_id}")

        await db.close()
        print("✅ Agent 服务测试通过")
        return True

    except Exception as e:
        print(f"❌ Agent 服务测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    print("=" * 50)
    print("🚀 Agent Framework 集成测试")
    print("=" * 50)

    results = []

    # 运行测试
    results.append(("PostgreSQL 连接", await test_database_connection()))
    results.append(("Redis 连接", await test_redis_connection()))
    results.append(("工作流服务", await test_workflow_service()))
    results.append(("Agent 服务", await test_agent_service()))

    # 汇总结果
    print("\n" + "=" * 50)
    print("📊 测试结果汇总")
    print("=" * 50)

    passed = 0
    failed = 0

    for name, result in results:
        status = "✅" if result else "❌"
        print(f"  {status} {name}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\n总计: {passed} 通过, {failed} 失败")

    if failed > 0:
        print("\n⚠️  部分测试失败，请检查配置和服务状态")
        sys.exit(1)
    else:
        print("\n🎉 所有测试通过!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())

#!/bin/bash
# ===========================================
# QVerisFlow Docker 启动入口脚本
# ===========================================
# 功能：
# 1. 等待依赖服务就绪
# 2. 初始化数据库（如果需要）
# 3. 启动应用
#
# 环境变量：
# - SKIP_DB_INIT: 跳过数据库初始化 (default: false)
# - DB_INIT_TIMEOUT: 等待数据库超时时间 (default: 60)
# - POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_DB

set -e

echo "=========================================="
echo "🚀 QVerisFlow 启动中..."
echo "=========================================="

# 显示时区信息
echo "🕐 时区配置: TZ=${TZ:-未设置}"
echo "🕐 当前时间: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=========================================="

# 默认配置
DB_INIT_TIMEOUT=${DB_INIT_TIMEOUT:-60}
SKIP_DB_INIT=${SKIP_DB_INIT:-false}

# ---- 函数定义 ----

wait_for_postgres() {
    echo "⏳ 等待 PostgreSQL 就绪..."
    local host="${POSTGRES_HOST:-postgres}"
    local port="${POSTGRES_PORT:-5432}"
    local timeout=$DB_INIT_TIMEOUT
    local count=0

    while [ $count -lt $timeout ]; do
        if python -c "
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1)
result = sock.connect_ex(('$host', $port))
sock.close()
exit(result)
" 2>/dev/null; then
            echo "✅ PostgreSQL 已就绪 ($host:$port)"
            return 0
        fi
        count=$((count + 1))
        echo "  等待中... ($count/$timeout)"
        sleep 1
    done

    echo "❌ PostgreSQL 连接超时"
    return 1
}

wait_for_redis() {
    if [ "${ENABLE_REDIS:-false}" != "true" ]; then
        echo "⏭️  Redis 未启用，跳过"
        return 0
    fi

    echo "⏳ 等待 Redis 就绪..."
    local host="${REDIS_HOST:-redis}"
    local port="${REDIS_PORT:-6379}"
    local timeout=$DB_INIT_TIMEOUT
    local count=0

    while [ $count -lt $timeout ]; do
        if python -c "
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1)
result = sock.connect_ex(('$host', $port))
sock.close()
exit(result)
" 2>/dev/null; then
            echo "✅ Redis 已就绪 ($host:$port)"
            return 0
        fi
        count=$((count + 1))
        sleep 1
    done

    echo "❌ Redis 连接超时"
    return 1
}

init_database() {
    if [ "$SKIP_DB_INIT" = "true" ]; then
        echo "⏭️  跳过数据库初始化 (SKIP_DB_INIT=true)"
        return 0
    fi

    echo "🔄 初始化数据库..."

    # 使用 Python 初始化数据库
    python -c "
import asyncio
import os
import sys

# 设置环境变量
os.environ.setdefault('ENABLE_POSTGRES', 'true')

async def init():
    try:
        from src.storage.database import AsyncDatabaseManager
        from src.storage.config import PostgreSQLConfig

        config = PostgreSQLConfig(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=int(os.getenv('POSTGRES_PORT', '5432')),
            database=os.getenv('POSTGRES_DB', 'agent_framework'),
            user=os.getenv('POSTGRES_USER', 'postgres'),
            password=os.getenv('POSTGRES_PASSWORD', ''),
        )

        db = AsyncDatabaseManager(config)
        await db.connect()

        # 检查表是否存在
        check_sql = '''
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'workflow_definitions'
            );
        '''
        result = await db.fetch_all(check_sql)
        table_exists = result[0][0] if result else False

        if not table_exists:
            print('📦 创建数据库表...')
            await db.init_db(drop_existing=False)
            print('✅ 数据库表创建完成')
        else:
            print('✅ 数据库表已存在，跳过创建')

        await db.close()
        return True
    except Exception as e:
        print(f'❌ 数据库初始化失败: {e}')
        import traceback
        traceback.print_exc()
        return False

success = asyncio.run(init())
sys.exit(0 if success else 1)
"

    if [ $? -eq 0 ]; then
        echo "✅ 数据库初始化完成"
    else
        echo "❌ 数据库初始化失败"
        exit 1
    fi
}

init_directories() {
    echo "📁 初始化目录..."

    # 确保数据目录存在
    mkdir -p /app/data/workspaces \
             /app/data/storage \
             /app/data/logs \
             /app/data/temp \
             /app/data/checkpoints \
             /app/data/traces

    echo "✅ 目录初始化完成"
}

# ---- 主流程 ----

# 1. 初始化目录
init_directories

# 2. 等待依赖服务
if [ "${ENABLE_POSTGRES:-false}" = "true" ]; then
    wait_for_postgres || exit 1
fi

wait_for_redis

# 3. 初始化数据库
if [ "${ENABLE_POSTGRES:-false}" = "true" ]; then
    init_database
fi

echo "=========================================="
echo "🎉 初始化完成，启动应用..."
echo "=========================================="

# 4. 启动应用
exec "$@"

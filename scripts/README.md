# 开发脚本

本目录包含开发和运维相关的脚本。

## 快速开始

### 1. 启动开发环境

```bash
# 一键启动 PostgreSQL + Redis + MinIO
./scripts/dev_setup.sh

# 或者分步执行
docker compose up -d
python scripts/init_db.py
```

### 2. 环境配置

首次使用前，复制环境变量模板：

```bash
cp .env.example .env
```

然后根据需要修改 `.env` 文件中的配置。

## 脚本说明

### dev_setup.sh

开发环境一键启动脚本。

```bash
# 启动所有服务
./scripts/dev_setup.sh

# 停止服务
./scripts/dev_setup.sh stop

# 重启服务
./scripts/dev_setup.sh restart

# 查看服务状态
./scripts/dev_setup.sh status

# 查看日志
./scripts/dev_setup.sh logs [service_name]

# 仅初始化数据库
./scripts/dev_setup.sh init-db
```

### init_db.py

数据库初始化脚本。

```bash
# 检查连接并创建表
python scripts/init_db.py

# 仅检查连接
python scripts/init_db.py --check-only

# 删除所有表后重新创建
python scripts/init_db.py --drop

# 创建初始示例数据
python scripts/init_db.py --seed

# 直接创建表（不使用 Alembic）
python scripts/init_db.py --direct
```

### test_integration.py

集成测试脚本，验证所有服务是否正常工作。

```bash
python scripts/test_integration.py
```

测试内容：
- PostgreSQL 连接
- Redis 连接
- 工作流服务 CRUD
- Agent 服务 CRUD

### init_postgres.sql

PostgreSQL 初始化 SQL 脚本，在容器首次启动时自动执行。

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| PostgreSQL | 5432 | 数据库 |
| Redis | 6379 | 缓存 |
| MinIO API | 9000 | 对象存储 API |
| MinIO Console | 9001 | 对象存储控制台 |
| Web API | 8000 | 后端服务 |
| Web UI | 5173 | 前端开发服务 |

## 启动应用服务

### 使用启动脚本

```bash
# 启动所有服务（后端 + 前端）
./scripts/start_services.sh

# 仅启动后端
./scripts/start_services.sh backend

# 仅启动前端
./scripts/start_services.sh frontend

# 查看状态
./scripts/start_services.sh status

# 停止服务
./scripts/start_services.sh stop
```

### 手动启动

**终端 1 - 后端服务:**

```bash
cd /path/to/agent_framework
uv run uvicorn src.web.app:app --host 0.0.0.0 --port 8000 --reload
```

**终端 2 - 前端服务:**

```bash
cd /path/to/agent_framework/web-ui
npm install  # 首次运行
npm run dev
```

## MinIO 控制台

访问 http://localhost:9001

- 用户名: `minioadmin`
- 密码: `minioadmin`

## 常见问题

### 1. 数据库连接失败

检查 PostgreSQL 是否正常运行：

```bash
docker compose ps postgres
docker compose logs postgres
```

### 2. Redis 连接失败

检查 Redis 是否正常运行：

```bash
docker compose ps redis
docker compose logs redis
```

### 3. MinIO 存储桶不存在

MinIO 初始化容器会自动创建存储桶。如果失败，可以手动创建：

```bash
docker compose exec minio mc mb myminio/agent-framework
```

或者通过 MinIO 控制台创建。

### 4. 数据持久化

所有数据存储在 Docker volumes 中：

- `postgres_data`: PostgreSQL 数据
- `redis_data`: Redis 数据
- `minio_data`: MinIO 对象数据

清除所有数据：

```bash
docker compose down -v
```

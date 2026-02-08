# ===========================================
# QVerisFlow 后端 API Dockerfile
# ===========================================
# 多阶段构建：构建阶段安装依赖，运行阶段最小化镜像体积
#
# 构建：docker build -t qveris-api .
# 运行：docker run -p 8000:8000 --env-file .env qveris-api

# ---- 构建阶段 ----
FROM python:3.11-slim AS builder

WORKDIR /build

# 安装系统构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（高性能 Python 包管理器）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 先复制依赖声明文件，利用 Docker 缓存层
COPY pyproject.toml ./

# 使用 uv 安装依赖到虚拟环境
RUN uv venv /build/.venv && \
    . /build/.venv/bin/activate && \
    uv pip install -e ".[web,oss]"

# 复制项目源码
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY alembic.ini ./
COPY __init__.py ./

# ---- 运行阶段 ----
FROM python:3.11-slim AS runtime

WORKDIR /app

# 安装运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r qveris && useradd -r -g qveris -d /app -s /sbin/nologin qveris

# 从构建阶段复制虚拟环境和源码
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/src /app/src
COPY --from=builder /build/config /app/config
COPY --from=builder /build/scripts /app/scripts
COPY --from=builder /build/alembic.ini /app/alembic.ini
COPY --from=builder /build/__init__.py /app/__init__.py
COPY --from=builder /build/pyproject.toml /app/pyproject.toml

# 设置环境变量
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 默认配置
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8000 \
    LOG_LEVEL=INFO \
    LOG_FILE=true \
    LOG_DIR=/app/data/logs

# 创建数据目录
RUN mkdir -p /app/data/workspaces /app/data/storage /app/data/logs /app/data/temp /app/data/checkpoints /app/data/traces \
    && chown -R qveris:qveris /app

# 切换到非 root 用户
USER qveris

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["uvicorn", "src.web.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]

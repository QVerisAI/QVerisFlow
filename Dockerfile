# ===========================================
# QVerisFlow 后端 API Dockerfile
# ===========================================
# 多阶段构建：构建阶段安装依赖，运行阶段最小化镜像体积
#
# 构建：docker build -t qveris-api .
# 运行：docker run -p 8000:8000 --env-file .env qveris-api

# ---- 构建阶段 ----
FROM qveris-ai-registry.cn-beijing.cr.aliyuncs.com/qveris_ai/python:3.11-slim AS builder

WORKDIR /build

# 使用清华 apt 镜像源（直接覆盖，确保不走 deb.debian.org）
# 原 sed 仅匹配 http://，Debian 12 默认用 https://，导致未生效
RUN rm -f /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security/ bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list

# 安装系统构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（高性能 Python 包管理器）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 复制项目文件（uv.lock 必须存在才能使用 uv sync）
COPY pyproject.toml uv.lock README.md __init__.py ./
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY alembic.ini ./

# 使用 uv pip install 直接安装到系统 Python（无需 venv）
# 使用清华 PyPI 镜像源加速
# 注意：uv sync 默认创建 .venv，在 Docker 中我们直接安装到系统更简洁
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN uv pip install --system -e ".[web,oss]"

# 验证关键依赖已安装
RUN python -m uvicorn --version && \
    which uvicorn && \
    python -c "import fastapi; print('FastAPI OK')"

# ---- 运行阶段 ----
FROM qveris-ai-registry.cn-beijing.cr.aliyuncs.com/qveris_ai/python:3.11-slim AS runtime

WORKDIR /app

# 设置时区为上海（在安装 tzdata 之前设置，避免交互式提示）
ENV TZ=Asia/Shanghai
ENV DEBIAN_FRONTEND=noninteractive

# 使用清华 apt 镜像源（直接覆盖，确保不走 deb.debian.org）
RUN rm -f /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security/ bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list

# 安装运行时系统依赖（包含时区数据）
# 使用重试机制处理网络不稳定问题
RUN for i in 1 2 3; do \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    tzdata \
    gosu \
    && break || sleep 5; \
    done \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r qveris && useradd -r -g qveris -d /app -s /sbin/nologin qveris

# 从构建阶段复制已安装的 Python 包和可执行文件
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /usr/local/bin/alembic /usr/local/bin/alembic

# 复制项目源码和配置
COPY --from=builder /build/src /app/src
COPY --from=builder /build/config /app/config
COPY --from=builder /build/scripts /app/scripts
COPY --from=builder /build/alembic.ini /app/alembic.ini
COPY --from=builder /build/__init__.py /app/__init__.py
COPY --from=builder /build/pyproject.toml /app/pyproject.toml

# 设置环境变量
ENV PYTHONPATH="/app:$PYTHONPATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8000 \
    LOG_LEVEL=INFO \
    LOG_FILE=true \
    LOG_DIR=/app/data/logs

# 设置入口脚本权限（数据目录由 entrypoint 在挂载后创建并 chown，避免宿主机 root 创建的 ./data 导致权限不足）
RUN chmod +x /app/scripts/docker_entrypoint.sh \
    && chown -R qveris:qveris /app

# 不在此处切换 USER：entrypoint 以 root 启动，创建挂载目录并 chown 后通过 gosu 切换到 qveris 运行应用

# 暴露端口
EXPOSE 8000

# 健康检查（增加启动等待时间，因为需要初始化数据库）
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 入口脚本：等待依赖、初始化数据库、启动应用
ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]

# 默认启动命令
CMD ["python", "-m", "uvicorn", "src.web.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]

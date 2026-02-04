#!/bin/bash
# ===========================================
# Agent Framework 开发环境一键启动脚本
# ===========================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}🚀 Agent Framework 开发环境启动${NC}"
echo -e "${BLUE}================================================${NC}"

# 检查 Docker 是否安装
check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker 未安装，请先安装 Docker${NC}"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        echo -e "${RED}❌ Docker 未运行，请启动 Docker${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Docker 已就绪${NC}"
}

# 检查 .env 文件
check_env() {
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}⚠️  .env 文件不存在，从 .env.example 创建...${NC}"
        cp .env.example .env
        echo -e "${GREEN}✅ 已创建 .env 文件${NC}"
    else
        echo -e "${GREEN}✅ .env 文件已存在${NC}"
    fi
}

# 启动 Docker 服务
start_services() {
    echo -e "\n${BLUE}📦 启动 Docker 服务...${NC}"
    
    # 停止旧容器（如果存在）
    docker compose down --remove-orphans 2>/dev/null || true
    
    # 启动服务
    docker compose up -d
    
    echo -e "${GREEN}✅ Docker 服务已启动${NC}"
}

# 等待服务就绪
wait_for_services() {
    echo -e "\n${BLUE}⏳ 等待服务就绪...${NC}"
    
    # 等待 PostgreSQL
    echo -n "  PostgreSQL: "
    for i in {1..30}; do
        if docker compose exec -T postgres pg_isready -U postgres &>/dev/null; then
            echo -e "${GREEN}就绪${NC}"
            break
        fi
        if [ $i -eq 30 ]; then
            echo -e "${RED}超时${NC}"
            exit 1
        fi
        sleep 1
        echo -n "."
    done
    
    # 等待 Redis
    echo -n "  Redis: "
    for i in {1..30}; do
        if docker compose exec -T redis redis-cli ping &>/dev/null; then
            echo -e "${GREEN}就绪${NC}"
            break
        fi
        if [ $i -eq 30 ]; then
            echo -e "${RED}超时${NC}"
            exit 1
        fi
        sleep 1
        echo -n "."
    done
    
    # 等待 MinIO
    echo -n "  MinIO: "
    for i in {1..30}; do
        if curl -s http://localhost:9000/minio/health/live &>/dev/null; then
            echo -e "${GREEN}就绪${NC}"
            break
        fi
        if [ $i -eq 30 ]; then
            echo -e "${RED}超时${NC}"
            exit 1
        fi
        sleep 1
        echo -n "."
    done
}

# 初始化数据库
init_database() {
    echo -e "\n${BLUE}🔧 初始化数据库...${NC}"
    
    # 确保 Python 环境
    if [ -f "pyproject.toml" ]; then
        # 使用 uv 或 pip
        if command -v uv &> /dev/null; then
            uv run python scripts/init_db.py --direct
        elif [ -d ".venv" ]; then
            .venv/bin/python scripts/init_db.py --direct
        else
            python scripts/init_db.py --direct
        fi
    fi
    
    echo -e "${GREEN}✅ 数据库初始化完成${NC}"
}

# 显示服务信息
show_info() {
    echo -e "\n${BLUE}================================================${NC}"
    echo -e "${GREEN}🎉 开发环境已就绪!${NC}"
    echo -e "${BLUE}================================================${NC}"
    echo -e ""
    echo -e "${YELLOW}服务地址:${NC}"
    echo -e "  PostgreSQL: localhost:5432"
    echo -e "  Redis:      localhost:6379"
    echo -e "  MinIO API:  localhost:9000"
    echo -e "  MinIO 控制台: http://localhost:9001"
    echo -e ""
    echo -e "${YELLOW}MinIO 登录凭证:${NC}"
    echo -e "  用户名: minioadmin"
    echo -e "  密码:   minioadmin"
    echo -e ""
    echo -e "${YELLOW}启动后端服务:${NC}"
    echo -e "  uv run uvicorn src.web.app:create_app --factory --reload --port 8000"
    echo -e ""
    echo -e "${YELLOW}启动前端开发服务:${NC}"
    echo -e "  cd web-ui && npm run dev"
    echo -e ""
    echo -e "${YELLOW}停止所有服务:${NC}"
    echo -e "  docker compose down"
    echo -e ""
}

# 主函数
main() {
    case "${1:-}" in
        start)
            check_docker
            check_env
            start_services
            wait_for_services
            init_database
            show_info
            ;;
        stop)
            echo -e "${BLUE}🛑 停止所有服务...${NC}"
            docker compose down
            echo -e "${GREEN}✅ 服务已停止${NC}"
            ;;
        restart)
            echo -e "${BLUE}🔄 重启服务...${NC}"
            docker compose restart
            wait_for_services
            echo -e "${GREEN}✅ 服务已重启${NC}"
            ;;
        status)
            echo -e "${BLUE}📊 服务状态:${NC}"
            docker compose ps
            ;;
        logs)
            docker compose logs -f ${2:-}
            ;;
        init-db)
            init_database
            ;;
        *)
            check_docker
            check_env
            start_services
            wait_for_services
            init_database
            show_info
            ;;
    esac
}

main "$@"

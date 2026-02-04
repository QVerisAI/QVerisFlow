#!/bin/bash
# ===========================================
# Agent Framework 服务启动脚本
# ===========================================
# 启动后端 API 和前端 UI 开发服务器

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 日志函数
log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }

# 检查依赖服务
check_services() {
    log_info "检查依赖服务..."
    
    # 检查 PostgreSQL
    if ! docker compose ps postgres 2>/dev/null | grep -q "running"; then
        log_warning "PostgreSQL 未运行，正在启动..."
        docker compose up -d postgres
        sleep 3
    fi
    
    # 检查 Redis
    if ! docker compose ps redis 2>/dev/null | grep -q "running"; then
        log_warning "Redis 未运行，正在启动..."
        docker compose up -d redis
        sleep 2
    fi
    
    log_success "依赖服务已就绪"
}

# 检查环境变量
check_env() {
    if [ ! -f ".env" ]; then
        log_warning ".env 文件不存在，从模板创建..."
        cp .env.example .env
        log_info "请根据需要修改 .env 文件"
    fi
    source .env 2>/dev/null || true
}

# 启动后端服务
start_backend() {
    log_info "启动后端 API 服务..."
    
    # 检查 uv 是否安装
    if ! command -v uv &> /dev/null; then
        log_error "uv 未安装，请先安装: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    
    # 设置 Python 路径
    export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
    
    # 启动 uvicorn
    echo ""
    log_info "后端服务地址: http://localhost:${WEB_PORT:-8000}"
    log_info "API 文档: http://localhost:${WEB_PORT:-8000}/docs"
    echo ""
    
    uv run uvicorn src.web.app:app \
        --host ${WEB_HOST:-0.0.0.0} \
        --port ${WEB_PORT:-8000} \
        --reload \
        --log-level info
}

# 启动前端服务
start_frontend() {
    log_info "启动前端 UI 服务..."
    
    cd "$PROJECT_ROOT/web-ui"
    
    # 检查 node_modules
    if [ ! -d "node_modules" ]; then
        log_warning "node_modules 不存在，正在安装依赖..."
        npm install
    fi
    
    echo ""
    log_info "前端服务地址: http://localhost:5173"
    echo ""
    
    npm run dev
}

# 同时启动所有服务
start_all() {
    log_info "启动所有服务..."
    
    check_env
    check_services
    
    # 使用 tmux 或后台进程
    if command -v tmux &> /dev/null; then
        # 使用 tmux
        tmux new-session -d -s agent-framework -n backend
        tmux send-keys -t agent-framework:backend "cd $PROJECT_ROOT && PYTHONPATH=$PROJECT_ROOT uv run uvicorn src.web.app:app --host 0.0.0.0 --port ${WEB_PORT:-8000} --reload" C-m
        
        tmux new-window -t agent-framework -n frontend
        tmux send-keys -t agent-framework:frontend "cd $PROJECT_ROOT/web-ui && npm run dev" C-m
        
        log_success "服务已在 tmux 会话 'agent-framework' 中启动"
        log_info "使用 'tmux attach -t agent-framework' 查看日志"
        log_info "使用 'tmux kill-session -t agent-framework' 停止所有服务"
        
        echo ""
        echo "=============================================="
        echo "  🚀 Agent Framework 服务已启动"
        echo "=============================================="
        echo ""
        echo "  后端 API:  http://localhost:${WEB_PORT:-8000}"
        echo "  API 文档:  http://localhost:${WEB_PORT:-8000}/docs"
        echo "  前端 UI:   http://localhost:5173"
        echo ""
        echo "  PostgreSQL: localhost:5432"
        echo "  Redis:      localhost:6379"
        echo "  MinIO:      http://localhost:9001 (控制台)"
        echo ""
        echo "=============================================="
    else
        log_warning "tmux 未安装，请手动在两个终端中分别启动服务"
        echo ""
        echo "终端 1 (后端):"
        echo "  cd $PROJECT_ROOT"
        echo "  uv run uvicorn src.web.app:app --host 0.0.0.0 --port 8000 --reload"
        echo ""
        echo "终端 2 (前端):"
        echo "  cd $PROJECT_ROOT/web-ui"
        echo "  npm run dev"
    fi
}

# 停止所有服务
stop_all() {
    log_info "停止所有服务..."
    
    # 停止 tmux 会话
    if tmux has-session -t agent-framework 2>/dev/null; then
        tmux kill-session -t agent-framework
        log_success "tmux 会话已停止"
    fi
    
    # 停止可能的后台进程
    pkill -f "uvicorn src.web.app:app" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
    
    log_success "服务已停止"
}

# 显示帮助
show_help() {
    echo "Agent Framework 服务启动脚本"
    echo ""
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  start       启动所有服务 (默认)"
    echo "  backend     仅启动后端服务"
    echo "  frontend    仅启动前端服务"
    echo "  stop        停止所有服务"
    echo "  status      查看服务状态"
    echo "  help        显示帮助"
    echo ""
    echo "示例:"
    echo "  $0              # 启动所有服务"
    echo "  $0 backend      # 仅启动后端"
    echo "  $0 frontend     # 仅启动前端"
    echo "  $0 stop         # 停止服务"
}

# 查看状态
show_status() {
    echo "=============================================="
    echo "  Agent Framework 服务状态"
    echo "=============================================="
    echo ""
    
    # Docker 服务
    echo "Docker 服务:"
    docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  Docker Compose 未运行"
    echo ""
    
    # 后端进程
    echo "后端服务:"
    if pgrep -f "uvicorn src.web.app:app" > /dev/null; then
        echo "  ✅ 运行中 (http://localhost:${WEB_PORT:-8000})"
    else
        echo "  ❌ 未运行"
    fi
    echo ""
    
    # 前端进程
    echo "前端服务:"
    if pgrep -f "vite" > /dev/null; then
        echo "  ✅ 运行中 (http://localhost:5173)"
    else
        echo "  ❌ 未运行"
    fi
    echo ""
    
    # tmux 会话
    if tmux has-session -t agent-framework 2>/dev/null; then
        echo "tmux 会话: ✅ 活跃 (使用 'tmux attach -t agent-framework' 连接)"
    fi
}

# 主函数
main() {
    case "${1:-start}" in
        start)
            start_all
            ;;
        backend)
            check_env
            check_services
            start_backend
            ;;
        frontend)
            start_frontend
            ;;
        stop)
            stop_all
            ;;
        status)
            show_status
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "未知命令: $1"
            show_help
            exit 1
            ;;
    esac
}

main "$@"

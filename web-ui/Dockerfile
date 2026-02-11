# ===========================================
# QVerisFlow 前端 Dockerfile
# ===========================================
# 多阶段构建：Node.js 构建 + Nginx 提供静态文件
#
# 构建：docker build -t qveris-web ./web-ui
# 运行：docker run -p 3000:80 qveris-web

# ---- 构建阶段 ----
FROM node:20-alpine AS builder

WORKDIR /build

# 使用清华 Alpine apk 镜像源（直接覆盖，确保不走 dl-cdn.alpinelinux.org）
# 从基础镜像自动检测 Alpine 版本（v3.19/v3.20 等），fallback 到 v3.20
RUN ALPINE_VER=$(grep -oE 'v[0-9]+\.[0-9]+' /etc/apk/repositories | head -1) || ALPINE_VER="v3.20" && \
    echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/${ALPINE_VER}/main" > /etc/apk/repositories && \
    echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/${ALPINE_VER}/community" >> /etc/apk/repositories

# 先复制依赖声明文件，利用 Docker 缓存层
COPY package.json package-lock.json ./

# 使用官方 npm 源（清华镜像可能缺失部分包如 zwitch，导致 404）
RUN npm config set registry https://registry.npmjs.org/

# 安装依赖
RUN npm ci

# 复制源码
COPY . .

# 构建生产版本
# VITE_API_URL 可在构建时通过 --build-arg 注入，默认为空（相对路径，由 nginx 反代）
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

# ---- 运行阶段 ----
FROM nginx:alpine AS runtime

# 使用清华 Alpine apk 镜像源（直接覆盖，确保不走 dl-cdn.alpinelinux.org）
RUN ALPINE_VER=$(grep -oE 'v[0-9]+\.[0-9]+' /etc/apk/repositories | head -1) || ALPINE_VER="v3.20" && \
    echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/${ALPINE_VER}/main" > /etc/apk/repositories && \
    echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/${ALPINE_VER}/community" >> /etc/apk/repositories

# 从构建阶段复制产物
COPY --from=builder /build/dist /usr/share/nginx/html

# Nginx 配置：SPA 路由 + 反向代理后端 API
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 暴露端口
EXPOSE 80

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://localhost:80/ || exit 1

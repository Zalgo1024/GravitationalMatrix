# ── 引力力矩 · Docker 镜像 ──
# 单容器：Caddy 反代 + Next.js 前端 + FastAPI 后端（BYOK，PUBLIC_MODE=1）
# 构建：docker build -t triad-workbench .

# ── 阶段 1：构建前端 ──
FROM node:22-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
# 同源部署：API 走相对路径，由 Caddy 反代转发（空字符串 ≠ 未设置，?? 不触发 → API_BASE=""）
ENV NEXT_PUBLIC_API_URL=
RUN npm run build

# ── 阶段 2：运行时（Python 后端 + LibreOffice + Caddy）──
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# LibreOffice（docx→pdf，保留超链接）+ 中文字体（PDF 中文渲染必需）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Caddy（静态编译，从官方镜像拷二进制即可在 debian 运行）
COPY --from=caddy:2-alpine /usr/bin/caddy /usr/bin/caddy

WORKDIR /app

# 引擎（项目根，settings.ENGINE_DIR 默认指向这里）
COPY engine.py parser.py docx_renderer.py pdf_converter.py viz_network.py \
     auto_number.py config.py theory_config.json analysis_prompt.md requirements.txt ./
COPY libs/ libs/

# 后端 + 依赖（backend 与引擎两套依赖装进同一环境）
COPY backend/requirements.txt backend/
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --upgrade pip \
    && /app/.venv/bin/pip install -r requirements.txt -r backend/requirements.txt
COPY backend/app backend/app
RUN mkdir -p /app/backend/data /app/backend/generated

# 前端构建产物（standalone 之外的常规产物：.next + node_modules 全量，直接 next start）
COPY --from=frontend-build /build/frontend/.next frontend/.next
COPY --from=frontend-build /build/frontend/node_modules frontend/node_modules
COPY --from=frontend-build /build/frontend/package.json frontend/package.json
COPY --from=frontend-build /build/frontend/public frontend/public

# 部署配置
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 10000
CMD ["/app/start.sh"]

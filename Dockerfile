# PillClear 单镜像部署：FastAPI 同源服务 /api/v1 与前端构建产物。
# 用法见 README「部署（Docker）」与 docs/superpowers/specs/2026-08-15-docker-deployment-design.md。

# ── 阶段 1：前端构建 ─────────────────────────────────────────────
FROM node:22-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# ── 阶段 2：运行时 ───────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
# 非 editable 安装；uvicorn 不在核心依赖，显式装。
RUN pip install --no-cache-dir . "uvicorn[standard]>=0.30"

# 说明书源文件：仅「重新入库」时需要（运行期不读）；数据卷里的库文件才是运行依赖。
COPY data ./data
COPY --from=web-build /web/dist ./web/dist

# 同源部署：前端相对路径 fetch 直达 /api/v1，无需 CORS。
ENV STATIC_DIR=/app/web/dist \
    DATA_DIR=/data \
    CORS_ORIGINS="" \
    PORT=8000 \
    PYTHONUNBUFFERED=1

# 预置种子库（VACUUM 过的单文件，生成见 scripts/make_seed_db.py）：
# /data 下这份供 compose 命名卷首次挂载自动继承（copy-up），云平台免入库开箱即用；
# /app/seed 下这份不被卷挂载遮蔽，供 seed-refresh 服务刷新已有卷。
COPY seed/pillclear.db /data/pillclear.db
COPY seed/pillclear.db /app/seed/pillclear.db

RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser /data
USER appuser
VOLUME /data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status == 200 else 1)"

# sh -c 展开 ${PORT:-8000}：本地 compose 用 8000，云平台注入 PORT 即生效。
# SQLite 单连接 + RLock 的并发语义要求单 worker（见 app/api/deps.py）。
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]

# 部署路径：Docker 单镜像（API + 前端同源）设计

> 2026-08-15 · 新增部署产物 + 后端可选静态服务（默认关闭）
> 铁律契合：不动 `rules/`/`safety.py`/prompt（golden 不动）；演示数据真实入库（#2 引用强制，不造假说明书）

## 目标

项目此前无任何部署路径（AGENTS.md 已知缺口 #1）。本次交付：

1. `docker compose up` 一条命令得到可用 demo（前端 + API 同源单镜像）；
2. 单镜像可直接投任意云平台（认 `PORT` 环境变量 + 挂持久卷即可），不绑定厂商。

## 已勘察事实（决策依据）

- 前端全部用相对路径 `/api/v1/*` fetch（`web/src/lib/api.ts`），**同源部署零前端改动**，
  也不需要 CORS（镜像内 `CORS_ORIGINS=""` 直接不挂中间件）。
- SQLite schema 由 Python 侧 `open_sqlite()` 的 `init_schema` 惰性建表（`migrations/*.sql`
  仅 Postgres 路径用）→ 容器无需迁移步骤。
- `GET /api/v1/health` 已存在（`app/api/routes.py`）→ 直接用作 HEALTHCHECK。
- SQLite 单连接 + 实例级 RLock（`app/api/deps.py` + `sqlite_repo.py`）→ **单 worker** 是安全选择。
- 规则 YAML 在 `app/rules/data/`，`DEFAULT_RULES_DIR` 按 `__file__` 相对定位；但
  `pillclear.egg-info/SOURCES.txt` 未含这三个 YAML → 非 editable 安装（Docker 即此场景）
  会丢规则文件，规则引擎首次加载即 ValueError（fail-loud，但部署必挂）→ 需补 package-data。
- `uvicorn` 只在 `dev` extra，不在核心依赖 → 镜像需显式安装。
- 入库（`python -m app.knowledge.ingest`）需要真 LLM key 做成分抽取 → 不得在构建期烘焙
  数据库，也不得造假数据（铁律 #2）；做成一次性 compose 服务，运行时用真实 key 灌库。

## 已确认决策

1. **静态服务由新配置 `STATIC_DIR` 门控，默认空串**：空 = `create_app` 不做任何事 →
   开发/测试行为零变化（406 基线不受影响）；容器 ENV 设为 `/app/web/dist`。
   否决「总是自动探测 web/dist」：测试从仓库根运行时目录存在，会悄悄改变默认 app 行为。
2. **SPA 服务方式 = catch-all 路由**（注册在全部路由之后，`/api/v1/*` 与 `/docs`
   按注册顺序优先匹配）：请求路径对应静态文件存在 → `FileResponse`；否则返回
   `index.html`（history 回退，支持 `/chat` 直开与刷新）。路径 resolve 后
   `is_relative_to(静态目录)` 防目录穿越。配置非空但缺 `index.html` → fail fast 抛
   RuntimeError（坏部署不得静默，铁律 #4 同源精神）。
3. **多阶段镜像**：node:22-alpine 构建前端 → python:3.12-slim 运行；
   `pip install . uvicorn[standard]`；非 root 用户；HEALTHCHECK 用 stdlib urllib（镜像无 curl）。
4. **灌库 = compose profile `setup` 的一次性服务**，与 `app` 共享数据卷与 key；
   `DEEPSEEK_API_KEY` 用 `${VAR:?msg}` 语法，缺失即报清晰错误。
5. **数据持久化 = named volume 挂 `/data`**，镜像 ENV `DATA_DIR=/data`。

## 明确不做

- 登录/鉴权、聊天持久化、流式输出（独立缺口，另行立项）；
- Render/Railway 专属配置文件（单镜像 + PORT/卷约定已足够）；
- CI 跑 docker build（成本高收益低，本地验证即可）。

## 影响面与测试

1. `app/config.py` 增字段 `static_dir: str = ""` —— `tests/test_config.py` 既有断言不受影响。
2. `app/main.py:create_app` 尾部增可选 SPA 挂载 —— 新测试文件 `tests/test_static_serving.py`：
   - 默认 app `GET /` 仍 404（守护现状）；
   - 设 `static_dir` 后：`GET /` 与 `GET /chat` → index.html；`GET /assets/app.js` → 文件内容；
     `GET /api/v1/health` → 200 不被吞；目录穿越不逃逸；缺 index.html → RuntimeError。
3. `pyproject.toml` 增 `[tool.setuptools.package-data]` —— 用 `pip install --target`
   人工实证 YAML 随包落位。
4. 新文件 `Dockerfile` / `.dockerignore` / `docker-compose.yml` —— 本地 docker 冒烟。
5. prompt/safety/rules 代码零改动 → golden 与 near-miss 测试预期不动。

## 增补（2026-08-15 同日）：种子库随镜像预置

**背景**：为「方便展示」（云平台 demo）复盘决策 4——PaaS 免费档跑一次性 ingest 服务不便，
且免费实例休眠/重部署后卷可能重置，每次冷启动都重新入库既慢又烧钱。

**改动**（未违反铁律：数据仍是真实入库产物，只是提前在本机生成并提交）：

1. `scripts/make_seed_db.py`：从本机库 `VACUUM INTO seed/pillclear.db`（标准库，单文件无 WAL 附属）。
2. `seed/pillclear.db` 提交入库（135KB，29 药 / 435 chunk）；`.dockerignore` 对 `*.db` 开例外。
3. Dockerfile 双份 COPY：`/data/`（compose 命名卷首次挂载 copy-up 继承，云平台无卷则直接可用）
   + `/app/seed/`（不被卷遮蔽，供 compose `seed-refresh` 服务刷新已有卷，顺带清旧 WAL/SHM）。
4. compose 保留 `ingest` 服务为可选（容器内实时入库新说明书）；日常流程改为
   「本机 ingest → make_seed_db.py → 提交 → 重新构建」。

**取舍**：仓库里多了一个二进制文件；换取 Render 等平台「推上去就能演示」。更新说明书时
种子库需手动再生成（README 已写明流程）。

# Docker 部署路径 实施计划（TDD）

> 配套设计：`docs/superpowers/specs/2026-08-15-docker-deployment-design.md`
> 红线：不碰 prompt/safety/rules 业务逻辑（golden 不动）；默认行为零变化（STATIC_DIR 门控）。

## 任务 1 — 先写失败测试（RED）

新建 `tests/test_static_serving.py`：

- `make_static_dir(tmp_path)`：写 `index.html` + `assets/app.js`。
- 用例：
  1. `test_default_app_does_not_serve_static`：默认 settings（`static_dir=""`）`GET /` → 404。
  2. `test_root_serves_index`：`GET /` → index.html 内容，content-type text/html。
  3. `test_spa_history_fallback`：`GET /chat` → index.html（前端路由刷新不 404）。
  4. `test_static_asset_served`：`GET /assets/app.js` → 文件内容。
  5. `test_api_not_shadowed`：`GET /api/v1/health` → 200 `{"status":"ok"}`。
  6. `test_path_traversal_blocked`：`GET /..%2F..%2Fapp%2Fconfig.py` 等构造不得返回源码。
  7. `test_missing_index_fails_fast`：指向空目录 → `create_app` 抛 RuntimeError。

Settings 构造沿用 `tests/conftest.py` 的 `settings()` fixture 风格（`_env_file=None`）。
运行 `pytest tests/test_static_serving.py -x`：应红（字段/挂载未实现）。

## 任务 2 — 最小实现（GREEN）

1. `app/config.py`：`data_dir` 旁增 `static_dir: str = ""`（注释说明：空=不服务静态文件；
   部署时指向前端构建产物）。
2. `app/main.py`：
   - import `Path` / `FileResponse`；
   - 新增 `_mount_spa(app, static_dir: Path)`：校验 index.html（缺 → RuntimeError）；
     `app.get("/{full_path:path}")` catch-all（resolve + `is_relative_to` 防穿越，
     命中文件 → FileResponse，否则 index.html）；
   - `create_app` 尾部：`if settings.static_dir: _mount_spa(app, Path(settings.static_dir))`。
3. `pyproject.toml`：`[tool.setuptools.package-data] "app.rules" = ["data/*.yaml"]`。

`pytest tests/test_static_serving.py` → 绿；`pytest -q` 全量 → 新基线（406 + 新增用例数）；
`ruff check app tests`。

## 任务 3 — 打包实证

`pip install --target .pkgcheck .` → 断言 `.pkgcheck/app/rules/data/*.yaml` 三个文件在位；
清理临时目录。

## 任务 4 — 部署产物

1. `Dockerfile`（多阶段，见设计决策 3；ENV `STATIC_DIR=/app/web/dist DATA_DIR=/data
   CORS_ORIGINS="" PORT=8000`；CMD `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
   --workers 1`，用 `sh -c` 展开 PORT）。
2. `.dockerignore`：`.env`、`.git`、`**/node_modules`、`web/dist`、`__pycache__/`、
   `*.db*`、`.venv`、`.pytest_cache`、`pillclear.egg-info` 等。
3. `docker-compose.yml`：`app`（build .、ports "8000:8000"、volume
   `pillclear-data:/data`、`DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:?...}`、healthcheck）+
   `ingest`（profiles ["setup"]、一次性、共享卷与 key）。

## 任务 5 — 冒烟验证（需本机 Docker + .env key）

1. `docker compose --profile setup run --rm ingest`；
2. `docker compose up -d --build`；
3. 验证：`/` 出 SPA；`/chat` 刷新不 404；`/api/v1/health` = 200；
   药箱加两种含对乙酰氨基酚的药做 check → 叠加告警（证明规则 YAML + 说明书数据在位）；
4. `docker compose down && docker compose up -d` → 药箱数据仍在（卷持久化）。
   Docker 不可用则如实记录「产物已就绪待验证」。

## 任务 6 — 文档与基线

1. README 增「部署（Docker）」小节（构建/灌库/启动 + 云平台一句话）。
2. AGENTS.md：基线数字更新为实际值；「已知缺口」第 1 项改为已解决；常用命令区可补
   compose 命令一行。CLAUDE.md 同步基线。
3. `.env.example` 无需改（key 字段已有）。

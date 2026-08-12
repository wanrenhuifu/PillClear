# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> PillClear · 年轻人智能用药安全助手（OTC 药 + 保健品，C 端）
> 铁律是硬兜底；业务操作走 project skill。

## 环境与命令

```bash
# 安装依赖
pip install -e ".[dev]"

# 运行全部测试
pytest

# lint（ruff，配置在 pyproject.toml [tool.ruff]）
python -m ruff check app tests

# 运行单个测试文件 / 单个测试
pytest tests/test_ingest.py
pytest tests/test_ingest.py::test_ingest_is_idempotent

# 说明书入库（29 份 .txt 在 data/package_inserts/ 里）
python -m app.knowledge.ingest data/package_inserts          # 写 SQLite
python -m app.knowledge.ingest data/package_inserts --dry-run # 仅看行数/结构

# 启动 API 服务
uvicorn app.main:app --reload

# Web 前端（web/ 目录；开发时 /api 代理到 127.0.0.1:8000）
cd web && npm install && npm run dev    # http://localhost:5173
cd web && npx vitest run                # 前端测试（Vitest + Testing Library）
```

## 技术要点

- **Python 3.12 + FastAPI + Pydantic v2**，配置一律走 `app/config.py:Settings`（pydantic-settings），禁止硬编码
- **默认后端 SQLite**（`%APPDATA%/PillClear/pillclear.db`，WAL 模式），无需 Supabase。设 `DATABASE_URL` 自动切 Postgres + pgvector；`PILLCLEAR_BACKEND`（`""`=自动 / `supabase` / `sqlite`）可显式锁定后端，拼写错误会被 `Settings` 校验直接拒绝
- **检索走关键词精确匹配**（`app/rag/keyword_retriever.py`），不依赖 embedding。药名精确匹配 → 模糊匹配 → 内容搜索，三级降级。embedding 仅 Postgres 路径保留
- **LLM 默认 DeepSeek**（`llm_provider=deepseek`，默认模型 `deepseek-v4-pro`，走 `app/llm/providers.py` 预置）。多厂牌支持：openai / qwen / glm / moonshot / ollama。`Settings` 硬拒绝已废弃模型名 `deepseek-chat` / `deepseek-reasoner`（`config.py:DEPRECATED_MODELS`）
- **Web 前端**：`web/` 是 React 18 + Vite 6 + Tailwind v4 + TanStack Query + react-router 7 的独立应用，Vitest 测试；API 客户端在 `web/src/lib/api.ts`（错误三分类 llm/http/network），用户以 localStorage 里的 `device_id` 标识（与后端药箱同键）。开发时 Vite 代理 `/api`，无需 CORS；`CORS_ORIGINS` 仅服务于直连部署。
- **lint 走 ruff**（配置在 `pyproject.toml [tool.ruff]`：F/E/W/I/UP/B/SIM/PLC/RUF；中文标点误报 RUF001-003 与 E501 已豁免，FastAPI `Depends` 惯用法经 `extend-immutable-calls` 豁免）；质量闸门 = ruff + pytest + golden 比对，CI 由 `.github/workflows/ci.yml` 承担（后端 pytest+ruff / 前端 vitest+build）。
- **改动后的最小验证（每次必做）**：每次完成代码改动后，在交付/提交前必须运行——① 先跑受影响的测试文件，例如 `pytest tests/test_chat_pipeline.py`（替换为实际受影响的文件）；② 通过后按需跑全量 `pytest`（基线 405，低于基线立即排查）；③ golden 文案变红（`tests/test_prompts_golden.py`）= 行为变更，先确认是有意改动，再按下方 golden 条目的重生成流程处理，禁止悄悄改测试凑绿。不引入新工具、不改业务代码；验证就是已有的 pytest + golden 流程。本地 git pre-commit 钩子已把该验证接成提交前必过项（克隆后跑一次 `python scripts/install_hooks.py` 安装；逻辑在 `scripts/pre_commit_check.py`）：自动跑 staged 改动映射出的受影响测试文件 + `ruff check app tests`，任一失败即阻断提交；无法映射时才回退全量。
- **测试全程 mock**，HTTP/LLM 调用一律 mock，不打真实网络：`respx_mock` fixture 由 respx 插件自动提供，`conftest.py` 只有 `make_completion()` 响应构造器和一个 `settings()` fixture（`_env_file=None`，套件与开发机 `.env` 无关）。每个用例自建 `:memory:` SQLite，不落盘。`tests/test_medbox_api.py` 刻意不挂 respx——以「装不了 mock」断言药箱路径全程不碰 LLM。
- **「叠加」有两条独立机制，别混淆**：① `app/medbox/calculator.py` 纯函数（`check_overlap` / `calculate_ingredient_totals`，单位归一化走 `app/core/units.py:to_mg`）按成分求和、对照硬编码 `_DAILY_LIMITS`（对乙酰氨基酚 4000mg 等）算日总摄入量；② `app/rules/data/overlap.yaml` 的规则引擎告警。规则 YAML 共三份：`overlap`（重复成分）/ `interaction`（药-药）/ `alcohol`（药-物质），warning 文案里的 `{count}`/`{total_mg}` 由 `engine.format_warning` 运行期填充（纯代码，无 LLM）。
- **prompt 模板有 golden 逐字比对**（`tests/test_prompts_golden.py` + `tests/golden/`，14 份）：任何文案漂移立刻变红；**有意**改文案时重新生成并在 commit 说明改动（Unix：`PILLCLEAR_REGEN_GOLDEN=1 python -m pytest tests/test_prompts_golden.py`；PowerShell：`$env:PILLCLEAR_REGEN_GOLDEN=1; python -m pytest tests/test_prompts_golden.py; Remove-Item env:PILLCLEAR_REGEN_GOLDEN`）
- **结构化输出一律走 `app/llm/client.py:complete_json`**：它强制 `response_format` JSON mode 并拒绝覆盖；意图分类、成分抽取都经它，别绕过
- **`app/core/safety.py` 有特征化边界用例**（`tests/test_safety.py` 的 `*NearMiss` / `TestFixedMessagesGolden` 组）：锁定当前保守匹配语义与已知盲区（见 `docs/refactor-readiness.md`）；变红 = 行为变更，须显式决策，禁止悄悄改测试

## 环境变量（必填仅一个）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（必填） |
| `DATABASE_URL` | 仅 Postgres 路径需要；留空默认 SQLite |
| `CORS_ORIGINS` | 逗号分隔的允许来源；留空 = 不挂 CORS 中间件（前端走 Vite 代理时不需要） |

LLM 厂牌、模型、端点均可通过 `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` 覆盖，详见 `.env.example`。Embedding 相关配置仅在 Postgres 路径需要。

## 铁律（不可违反）

1. **确定性优先**：药学结论（冲突/重复成分/剂量）必须走 `app/rules/` 规则引擎，**禁止 LLM 直接推断**；成分叠加计算必须是纯函数。
2. **引用强制**：所有用药回答必须携带说明书原文引用，引用为空视为缺陷（`pipeline.py` 代码级追加 `_NO_CITATION_NOTE`）。
3. **能力边界**：处方药、疾病诊断、症状解读、孕妇/哺乳期/儿童/慢病患者 → 不提供服务，引导就医或咨询药师。检测优先级：急症 > 特殊人群 > 诊断 > 处方药 > 放行。入口在 `app/core/safety.py`。
4. **不确定就明说**：拿不准必须说"不确定"并建议咨询药师，**严禁编造**；保健品交互证据不足时保守提示。
5. **语气与免责**：安全提示醒目不打折；每次回答末尾由代码追加固定免责声明（`_DISCLAIMER`，不依赖 prompt）。

## 核心架构

```
POST /api/v1/chat   → routes.py(薄适配器) → pipeline.process_chat(同步编排) → 回答+引用+免责
                                                └─ safety → 意图分类 → RAG检索 → 规则引擎 → LLM → 兜底 → 免责
POST /api/v1/medbox/check、GET/POST/DELETE /api/v1/medbox/{device_id}[/items[/{drug_id}]]
                    → medbox_routes.py → MedboxService → calculator(叠加求和) + 规则引擎(相互作用) + 未入库药品 → CheckReport
GET  /api/v1/drugs  → drug_routes.py → 仓储 list_drugs()（前端药品选择器数据源）
GET/POST/DELETE /api/v1/reminders/{device_id}[/items[/{drug_id}]]
                    → reminder_routes.py → ReminderService → 时刻表 CRUD + next_due(纯函数，调度数据不碰 LLM)
```

**关键分层（跨文件才能看清）**：
- `app/main.py:create_app()` 是工厂：挂三个路由（`routes` / `medbox_routes` / `drug_routes`，前缀 `/api/v1`）+ 可选 CORS 中间件（`cors_origins` 为空则不挂）；模块级 `app = create_app()` 供 uvicorn 使用。
- `app/chat/pipeline.py:process_chat()` 是**纯同步编排器，零 Web 框架依赖**——可直接脱离 HTTP 测试。`app/api/routes.py` 只是薄适配器：`run_in_threadpool` 放入线程池，并把 `LLMRetryExhausted`（定义于 `app/llm/errors.py`）映射为 HTTP 502。
- `app/api/deps.py` 是**后端解析 + 依赖注入的唯一缝隙**：`_resolve_backend()` 按 `DATABASE_URL` 选 sqlite/supabase，工厂据此返回对应实现——检索器 `KeywordRetriever`(默认) / `PgVectorRetriever`+`Embedder`(Postgres) / `NullRetriever`；仓储 `SQLite*` / `Postgres*` / `InMemory*`（药箱仓储跟随药品仓储的后端类型）。换后端只动这里。注意一处**有意分歧**：`get_retriever` 在「后端未显式锁定但设了 `DATABASE_URL`」时仍启用 PgVectorRetriever（代码有注释），与 `_resolve_backend` 的判定不完全同步。
- 数据库 schema 在 `migrations/*.sql`（0001 建表 / 0002 embedding 非空 / 0003 药箱表），非 ORM。
- 药箱以 `device_id` 标识用户（MVP 阶段无登录）。

| 层 | 模块 | 职责 |
|----|------|------|
| 安全边界 | `app/core/safety.py` | 关键词 + LLM 补漏，拦截越界请求 |
| 意图分类 | `app/prompts/intent.py` | LLM JSON mode，提取 drug_names / intent |
| 检索 | `app/rag/keyword_retriever.py` | 药名 → SQL LIKE 搜索章节（无 embedding） |
| 规则引擎 | `app/rules/engine.py` | 纯函数，YAML 规则（叠加+相互作用） |
| 提示词 | `app/prompts/` | chat / ingest / intent / safety 四份模板；`formatters.py` 负责引用/检查报告的 prompt 内格式化，静态骨架在 `templates/` |
| 药箱 | `app/medbox/` | 药箱 CRUD + 成分叠加计算 |
| 提醒 | `app/reminder/` | 用药提醒时刻表 CRUD + 下次提醒计算（同款 Protocol 三实现） |
| 入库 | `app/knowledge/` | 章节解析 → LLM 成分抽取 → 幂等 upsert |
| LLM | `app/llm/` | OpenAI 兼容客户端 + 多厂牌预置 |

**领域词汇**：`CONTEXT.md` 定义了产品/商品名/成分/物质/叠加/相互作用等术语的确切含义和边界。新增概念先查词汇表。架构决策记录在 `docs/adr/`——ADR-0001：保健品按「产品」同构建模、不单列实体；代码里 `Drug`/`drugs` 是「产品」的历史命名（可选重命名，勿当成新实体另起炉灶）。设计 spec 与实施计划按日期归档在 `docs/superpowers/specs/` 和 `docs/superpowers/plans/`（prompt 拆分、web 前端均走此流程，新特性沿用）。

## 用药提醒（app/reminder/）

提醒是**调度数据**：不参与叠加 / 相互作用计算、永不碰 LLM（`tests/test_reminder.py` 刻意不挂 respx 断言此事）。模式完全对齐药箱：`ReminderRepository` Protocol + InMemory/SQLite/Postgres 三实现（SQLite 共享药品仓储连接+锁；Postgres schema 见 `migrations/0004_user_reminders.sql`）；`next_due(times, now)` 是纯函数，显式注入 now 保证可离线测试；每药 1~4 个 `HH:MM` 时刻，按 (user, drug) 覆盖式设置。

## 说明书入库流程

`app/knowledge/ingest.py:ingest_text()` — `parser.py:split_sections` 解析 `【章节】` → `【成份】` 走 LLM 结构化抽取（`complete_json`）→ 纯文本 chunk 落 SQLite。文件名 = 商品名，幂等 upsert。**不用 embedding**——检索走关键词匹配；`ingest_text` 的 `embedder` 参数是历史遗留，chunk 存空向量。`ingredients_verified` 恒为 false（保健品同构，靠规则证据强度区分，见 ADR-0001）。

## 配置的自动化

`.claude/settings.json` 配置了两项：
- **PostToolUse hook**（PowerShell）：Write/Edit 命中 `app/core/safety.py` 或 `app/rules/` 下任一文件 → 自动跑 `python -m pytest tests/ -x --tb=short`
- **skillOverrides**：仅 `pillclear-rule-engine` 与 `pillclear-insert-ingestion` 设为 `user-invocable-only`（开发时不被模型自动加载，仍可 `/skill-name` 手动调用）。`pillclear-safety-review` **有意保持自动加载**——safety.py 重构期间摘下过钩子，`docs/refactor-readiness.md` 记有「重构完成后恢复 user-invocable-only」的待办

## 业务操作（非开发任务）

- **新增/修改药学规则** → `/pillclear-rule-engine`
- **说明书入库（新增药品）** → `/pillclear-insert-ingestion`
- **安全边界回归** → `/pillclear-safety-review`

# AGENTS.md

This file provides guidance to Lingma (lingma.aliyun.com) when working with code in this repository.

> PillClear · 年轻人智能用药安全助手（OTC 药 + 保健品，C 端）。本仓库另有 `CLAUDE.md`（内容等价、更详细）、`CONTEXT.md`（领域词汇表）、`docs/refactor-readiness.md`（重构防护网验收标准）。

## 铁律（不可违反）

1. **确定性优先**：药学结论（冲突/重复成分/剂量）必须走 `app/rules/` 规则引擎，**禁止 LLM 直接推断**；成分叠加计算必须是纯函数（`app/medbox/calculator.py`）。
2. **引用强制**：所有用药回答必须携带说明书原文引用，引用为空视为缺陷（`pipeline.py` 代码级追加 `_NO_CITATION_NOTE`）。
3. **能力边界**：处方药、疾病诊断、症状解读、孕妇/哺乳期/儿童/慢病患者 → 拒绝服务并引导就医。检测优先级固定：急症 > 特殊人群 > 诊断 > 处方药 > 放行。入口 `app/core/safety.py`。
4. **不确定就明说**：拿不准必须说"不确定"并建议咨询药师，严禁编造。
5. **免责声明**：每次回答末尾由代码追加固定免责文案（`_DISCLAIMER`，不依赖 prompt）。

## 常用命令

```bash
pip install -e ".[dev]"          # 安装依赖（Python 3.12+）

pytest                            # 全部测试（基线 405，低于基线立即排查）
pytest tests/test_ingest.py       # 单个测试文件
pytest tests/test_ingest.py::test_ingest_is_idempotent   # 单个用例

ruff check app tests              # lint（ruff 已入 dev 依赖；CI 同样跑这条）

python -m app.knowledge.ingest data/package_inserts           # 说明书入库（成分抽取走 LLM）
python -m app.knowledge.ingest data/package_inserts --dry-run # 只看结构，不联网

uvicorn app.main:app --reload     # 后端 API（:8000）

cd web && npm install && npm run dev   # 前端（:5173，/api 代理到后端）
cd web && npx vitest run               # 前端测试
```

Windows 一键启动：`start.bat`（同时拉起前后端）。

**Lint 只有 ruff**（无 black/mypy/pre-commit），配置在 `pyproject.toml [tool.ruff]`：select F/E/W/I/UP/B/SIM/PLC/RUF；`RUF001-003`（中文标点误报）已 ignore；FastAPI `Depends/Query/Path` 已豁免 B008。提交前跑 `ruff check app tests`。GitHub Actions CI（`.github/workflows/ci.yml`）跑 ruff + pytest + 前端 vitest + build。

### Golden 测试重新生成

prompt 模板有逐字 golden 比对（`tests/test_prompts_golden.py` + `tests/golden/`）。文案变红 = 行为变更，须先确认是有意改动，再重新生成并在 commit 说明：

```powershell
$env:PILLCLEAR_REGEN_GOLDEN=1; python -m pytest tests/test_prompts_golden.py; Remove-Item env:PILLCLEAR_REGEN_GOLDEN
```

同理，`tests/test_safety.py` 的 `*NearMiss` / `TestFixedMessagesGolden` 组锁定了安全边界的保守匹配语义与已知盲区（清单见 `docs/refactor-readiness.md`）；变红必须显式决策，**严禁悄悄改测试凑绿**。

## 环境变量

唯一必填：`DEEPSEEK_API_KEY`。配置一律走 `app/config.py:Settings`（pydantic-settings），禁止硬编码。

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | 留空 = SQLite 默认路径（Windows `%APPDATA%/PillClear/pillclear.db`，WAL）；设值 = Postgres + pgvector |
| `PILLCLEAR_BACKEND` | `""` 自动 / `supabase` / `sqlite`，显式锁定后端，拼写错误被 Settings 拒绝 |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` | LLM 厂牌/模型覆盖；`DEPRECATED_MODELS` 硬拒绝废弃模型名 |
| `CORS_ORIGINS` | 逗号分隔；留空 = 不挂 CORS 中间件（Vite 代理开发时不需要） |

## 核心架构

```
POST /api/v1/chat   → routes.py(薄适配器) → pipeline.process_chat(同步编排)
                        └─ safety → 意图分类 → RAG检索 → 规则引擎 → LLM → 兜底 → 免责
POST /api/v1/medbox/check、GET/POST/DELETE /api/v1/medbox/{device_id}[/items[/{drug_id}]]
                    → medbox_routes.py → MedboxService → calculator(叠加求和) + 规则引擎 + 未入库药品 → CheckReport
GET  /api/v1/drugs  → drug_routes.py → 仓储 list_drugs()
GET/POST/DELETE /api/v1/reminders/{device_id}[/items[/{drug_id}]]
                    → reminder_routes.py → ReminderService → next_due(纯函数)
```

**跨文件才能看清的分层**：

- `app/main.py:create_app()` 是工厂：挂三个路由（前缀 `/api/v1`）+ 可选 CORS；模块级 `app = create_app()` 供 uvicorn 使用。
- `app/chat/pipeline.py:process_chat()` 是**纯同步编排器，零 Web 框架依赖**，可直接脱离 HTTP 测试；`app/api/routes.py` 只是薄适配器（`run_in_threadpool` + `LLMRetryExhausted` → HTTP 502）。
- `app/api/deps.py` 是**后端解析 + 依赖注入的唯一缝隙**：`_resolve_backend()` 按 `DATABASE_URL` 选 sqlite/supabase，工厂返回对应检索器（`KeywordRetriever` 默认 / `PgVectorRetriever`+`Embedder` Postgres / `NullRetriever`）与仓储（`SQLite*` / `Postgres*` / `InMemory*`）。换后端只动这里。注意有意分歧：`get_retriever` 在「未锁定后端但设了 `DATABASE_URL`」时仍启用 PgVectorRetriever。
- 数据库 schema 在 `migrations/*.sql`（0001 建表 / 0002 embedding 非空 / 0003 药箱表 / 0004 提醒表），非 ORM。药箱与提醒均以 `device_id` 标识用户（MVP 无登录）。
- 检索走关键词精确匹配（`app/rag/keyword_retriever.py`）：药名精确 → 模糊 → 内容搜索三级降级，不依赖 embedding；`ingest_text` 的 `embedder` 参数是历史遗留，chunk 存空向量。
- 结构化输出一律走 `app/llm/client.py:complete_json`（强制 JSON mode 且拒绝覆盖），意图分类、成分抽取都经它，别绕过。
- 入库流程：`app/knowledge/ingest.py:ingest_text()` → `parser.py:split_sections` 解析 `【章节】` → `【成份】` 走 LLM 抽取 → 纯文本 chunk 幂等 upsert（文件名 = 商品名）。`ingredients_verified` 恒为 false。

| 层 | 模块 | 职责 |
|----|------|------|
| 安全边界 | `app/core/safety.py` | 关键词 + LLM 补漏，拦截越界请求 |
| 意图分类 | `app/prompts/intent.py` | LLM JSON mode，提取 drug_names / intent |
| 检索 | `app/rag/keyword_retriever.py` | 药名 → SQL LIKE 搜索章节 |
| 规则引擎 | `app/rules/engine.py` | 纯函数 + YAML 规则（overlap / interaction / alcohol） |
| 提示词 | `app/prompts/` | chat / ingest / intent / safety 模板；`formatters.py` 负责引用/检查报告格式化，静态骨架在 `templates/` |
| 药箱 | `app/medbox/` | 药箱 CRUD + 成分叠加计算 |
| 提醒 | `app/reminder/` | 服药时刻 CRUD + `next_due` 纯函数；不碰 LLM |
| LLM | `app/llm/` | OpenAI 兼容客户端 + 多厂牌预置（openai / qwen / glm / moonshot / ollama） |

### 「叠加」的两条独立机制（勿混淆）

1. `app/medbox/calculator.py` 纯函数（`check_overlap` / `calculate_ingredient_totals`，单位归一化走 `app/core/units.py:to_mg`）：按成分求和、对照硬编码 `_DAILY_LIMITS`（对乙酰氨基酚 4000mg 等）算日总摄入量。
2. `app/rules/data/overlap.yaml` 规则引擎告警。warning 文案的 `{count}`/`{total_mg}` 由 `engine.format_warning` 运行期填充（纯代码，无 LLM）。

## 测试约定

- 测试全程 mock，HTTP/LLM 一律 mock，不打真实网络：`respx_mock` 由插件提供；`tests/conftest.py` 的 `settings()` fixture 用 `_env_file=None`，另有 autouse fixture 清掉开发机进程里的 LLM/DATABASE 环境变量，套件与本机 `.env`/环境无关；每个用例自建 `:memory:` SQLite。
- `tests/test_medbox_api.py` / `tests/test_reminder.py` 刻意不挂 respx——以「装不了 mock」断言药箱/提醒路径全程不碰 LLM。
- 新增行为变更先看 `docs/refactor-readiness.md` 的「已知保守行为与盲区」清单。

## 领域词汇与文档

- `CONTEXT.md` 定义产品/商品名/成分/物质/叠加/相互作用等术语的确切边界。新增概念先查词汇表。注意：「叠加」≠「冲突」（冲突专指相互作用）；保健品按「产品」同构建模，不单列实体（ADR-0001，`docs/adr/`）；代码里 `Drug`/`drugs` 是「产品」的历史命名。
- 设计 spec 与实施计划按日期归档在 `docs/superpowers/specs/` 与 `docs/superpowers/plans/`，新特性沿用该流程。
- 用药提醒已落地（`app/reminder/`）：Protocol 仓储三实现（InMemory/SQLite/Postgres），SQLite 共享药箱的连接与锁；时刻校验 `HH:MM`（Pydantic `pattern` 必须挂在 `Annotated` 元素类型上，不能挂 list 字段）；`next_due(times, now)` 显式注入 now 保持纯函数。

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

# 运行单个测试文件 / 单个测试
pytest tests/test_ingest.py
pytest tests/test_ingest.py::test_ingest_is_idempotent

# 说明书入库（29 份 .txt 在 data/package_inserts/ 里）
python -m app.knowledge.ingest data/package_inserts          # 写 SQLite
python -m app.knowledge.ingest data/package_inserts --dry-run # 仅看行数/结构

# 启动 API 服务
uvicorn app.main:app --reload
```

## 技术要点

- **Python 3.12 + FastAPI + Pydantic v2**，配置一律走 `app/config.py:Settings`（pydantic-settings），禁止硬编码
- **默认后端 SQLite**（`%APPDATA%/PillClear/pillclear.db`，WAL 模式），无需 Supabase。设 `DATABASE_URL` 自动切 Postgres + pgvector；`PILLCLEAR_BACKEND`（`""`=自动 / `supabase` / `sqlite`）可显式锁定后端，拼写错误会被 `Settings` 校验直接拒绝
- **检索走关键词精确匹配**（`app/rag/keyword_retriever.py`），不依赖 embedding。药名精确匹配 → 模糊匹配 → 内容搜索，三级降级。embedding 仅 Postgres 路径保留
- **LLM 默认 DeepSeek**（`llm_provider=deepseek`，默认模型 `deepseek-v4-pro`，走 `app/llm/providers.py` 预置）。多厂牌支持：openai / qwen / glm / moonshot / ollama。`Settings` 硬拒绝已废弃模型名 `deepseek-chat` / `deepseek-reasoner`（`config.py:DEPRECATED_MODELS`）
- **测试全程 mock**，HTTP/LLM 调用一律 mock（respx），不打真实网络。测试用 `:memory:` SQLite，不落盘；`conftest.py` 以 `_env_file=None` 构造 Settings，套件与开发机 `.env` 无关。
- **「叠加」有两条独立机制，别混淆**：① `app/medbox/calculator.py` 纯函数按成分求和、对照硬编码 `_DAILY_LIMITS`（对乙酰氨基酚 4000mg 等）算日总摄入量；② `app/rules/data/overlap.yaml` 的规则引擎告警。规则 YAML 共三份：`overlap`（重复成分）/ `interaction`（药-药）/ `alcohol`（药-物质），warning 文案里的 `{count}`/`{total_mg}` 由 `engine.format_warning` 运行期填充（纯代码，无 LLM）。
- **prompt 模板有 golden 逐字比对**（`tests/test_prompts_golden.py` + `tests/golden/`）：任何文案漂移立刻变红；**有意**改文案时用 `PILLCLEAR_REGEN_GOLDEN=1 python -m pytest tests/test_prompts_golden.py` 重新生成，并在 commit 说明改动
- **`app/core/safety.py` 有特征化边界用例**（`tests/test_safety.py` 的 `*NearMiss` / `TestFixedMessagesGolden` 组）：锁定当前保守匹配语义与已知盲区（见 `docs/refactor-readiness.md`）；变红 = 行为变更，须显式决策，禁止悄悄改测试

## 环境变量（只需一个）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（必填） |
| `DATABASE_URL` | 仅 Postgres 路径需要；留空默认 SQLite |

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
```

**关键分层（跨文件才能看清）**：
- `app/chat/pipeline.py:process_chat()` 是**纯同步编排器，零 Web 框架依赖**——可直接脱离 HTTP 测试。`app/api/routes.py` 只是薄适配器：`run_in_threadpool` 放入线程池，并把 `LLMRetryExhausted` 映射为 HTTP 502。
- `app/api/deps.py` 是**后端解析 + 依赖注入的唯一缝隙**：`_resolve_backend()` 按 `DATABASE_URL` 选 sqlite/supabase，工厂据此返回对应实现——检索器 `KeywordRetriever`(默认) / `PgVectorRetriever`+`Embedder`(Postgres) / `NullRetriever`；仓储 `SQLite*` / `Postgres*` / `InMemory*`（药箱仓储跟随药品仓储的后端类型）。换后端只动这里。
- 数据库 schema 在 `migrations/*.sql`（0001 建表 / 0002 embedding 非空 / 0003 药箱表），非 ORM。
- 药箱以 `device_id` 标识用户（MVP 阶段无登录）。

| 层 | 模块 | 职责 |
|----|------|------|
| 安全边界 | `app/core/safety.py` | 关键词 + LLM 补漏，拦截越界请求 |
| 意图分类 | `app/prompts/intent.py` | LLM JSON mode，提取 drug_names / intent |
| 检索 | `app/rag/keyword_retriever.py` | 药名 → SQL LIKE 搜索章节（无 embedding） |
| 规则引擎 | `app/rules/engine.py` | 纯函数，YAML 规则（叠加+相互作用） |
| 提示词 | `app/prompts/` | chat / ingest / intent / safety 四份 |
| 药箱 | `app/medbox/` | 药箱 CRUD + 成分叠加计算 |
| 入库 | `app/knowledge/` | 章节解析 → LLM 成分抽取 → 幂等 upsert |
| LLM | `app/llm/` | OpenAI 兼容客户端 + 多厂牌预置 |

**领域词汇**：`CONTEXT.md` 定义了产品/商品名/成分/物质/叠加/相互作用等术语的确切含义和边界。新增概念先查词汇表。架构决策记录在 `docs/adr/`——ADR-0001：保健品按「产品」同构建模、不单列实体；代码里 `Drug`/`drugs` 是「产品」的历史命名（可选重命名，勿当成新实体另起炉灶）。

`app/reminder/`（用药提醒）目前是空占位、尚未实现，勿假设其存在行为。

## 说明书入库流程

`app/knowledge/ingest.py:ingest_text()` — 解析 `【章节】` → `【成份】` 走 LLM 结构化抽取 → 纯文本 chunk 落 SQLite。文件名 = 商品名，幂等 upsert。**不用 embedding**——检索走关键词匹配。

## 配置的自动化

`.claude/settings.json` 配置了两项：
- **PostToolUse hook**（PowerShell）：Write/Edit 命中 `app/core/safety.py` 或 `app/rules/` 下任一文件 → 自动跑 `python -m pytest tests/ -x --tb=short`
- **skillOverrides**：`pillclear-*` 三个业务 skill 设为 `user-invocable-only`（开发时不被模型自动加载，仍可 `/skill-name` 手动调用）

## 业务操作（非开发任务）

- **新增/修改药学规则** → `/pillclear-rule-engine`
- **说明书入库（新增药品）** → `/pillclear-insert-ingestion`
- **安全边界回归** → `/pillclear-safety-review`

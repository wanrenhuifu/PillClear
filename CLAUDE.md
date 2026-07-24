# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本文件是「年轻人智能用药安全助手」的最高准则，适用于所有后续会话。
> 任何实现都不得违反下述铁律；铁律与其他指令冲突时，以铁律为准。

## 一、产品定位
面向 18-30 岁大学生 / 职场年轻人的 **C 端用药安全助手**，聚焦 **OTC 常用药和保健品**，解决三大痛点：
1. **看不懂说明书** → 把说明书"翻译"成大白话（RAG 检索说明书原文，回答带引用）。
2. **担心药物冲突** → 用户维护个人"药箱"，新增药品 / 保健品时自动做冲突和重复成分检查。
3. **忘记吃药** → 用药提醒（暂不实现，先打前两件事的地基）。

典型场景：两种复方感冒药导致对乙酰氨基酚重复过量、布洛芬与酒精同服、氯雷他定与葡萄柚、褪黑素 / 圣约翰草等保健品与药物相互作用。

## 二、铁律（不可违反）
1. **确定性优先**：所有冲突、重复成分、剂量判断必须落在确定性规则引擎（`app/rules/`，YAML 规则 + 解释器），**禁止让 LLM 直接推断药学结论**；成分叠加计算（如对乙酰氨基酚总量）必须是代码纯函数。
2. **引用强制**：所有用药相关回答必须携带**说明书原文引用**，引用为空视为缺陷。
3. **能力边界**（写死在 `app/core/safety.py`，附固定话术）：
   - 处方药、疾病诊断、症状解读 → 不提供，引导就医 / 咨询药师。
   - 孕妇 / 哺乳期 / 儿童 / 慢病患者用药 → 不提供个性化建议，引导咨询医生。
   - 急症信号（高热不退、严重过敏反应、呼吸困难等）→ 立即提示就医。
   - 检测优先级：**急症 > 特殊人群 > 诊断 > 处方药 > 放行**。
4. **不确定就明说**：拿不准必须明说"不确定"并建议咨询药师，**严禁编造**；保健品相互作用证据不足时按**保守原则**提示。
5. **语气与免责**：年轻人的大白话、简短直接；但安全提示必须**醒目、不打折**；每次用药建议末尾附**固定免责声明**（文案在 `app/api/routes.py` 的 `_DISCLAIMER`，由代码追加，不依赖 prompt）。

## 三、技术栈（已确定，不要更改）
- **LLM**：DeepSeek API，主力 `deepseek-v4-pro`（OpenAI 兼容协议，`base_url=https://api.deepseek.com`）。
  旧模型名 `deepseek-chat` / `deepseek-reasoner` **已废弃，禁止使用**（已在 `app/config.py` 校验拦截）。
- **后端**：Python 3.12 + FastAPI + Pydantic v2。
- **数据库**：双后端——Supabase（Postgres + pgvector，生产）与本地 SQLite（sqlite-vec，无外部依赖的默认后端）。Supabase schema 用 `migrations/` SQL 文件管理（0001 建库、0002 embedding 非空、0003 用户药箱）。
- **规则引擎**：自研 YAML 规则 DSL（规则文件在 `app/rules/data/*.yaml`）。
- **测试**：pytest，TDD 优先。

## 四、常用命令
```bash
# 安装（含开发依赖：uvicorn / pytest / respx / httpx）
pip install -e ".[dev]"

# 全量测试（pyproject 已配 testpaths=tests、pythonpath=.）
pytest

# 单个测试文件 / 单个用例 / 按名字过滤
pytest tests/test_rules_engine.py
pytest tests/test_safety.py::test_某用例
pytest -k "overlap"

# 起本地服务（需 .env 里的 DEEPSEEK_API_KEY；缺 DATABASE_URL 时自动落 SQLite 后端）
uvicorn app.main:app --reload

# 说明书入库（文件名即商品名；--dry-run = 内存仓储 + 全零向量，不写库不联网）
python -m app.knowledge.ingest data/package_inserts
python -m app.knowledge.ingest data/package_inserts --dry-run

# Supabase 建表（或贴进 Supabase SQL Editor）
psql "$DATABASE_URL" -f migrations/0001_init.sql
```
环境变量走 `app/config.Settings`（`.env`，模板 `.env.example`）：`DEEPSEEK_API_KEY`（必填）、`DATABASE_URL`（Supabase 连接串）、`PILLCLEAR_BACKEND`（`""`自动/`supabase`/`sqlite`）、`EMBEDDING_*`（默认硅基流动 BGE-M3，1024 维，须与 DDL `vector(1024)` 一致）。

## 五、架构要点
**`/chat` 是智能体编排，不是裸 LLM 问答**（`app/api/routes.py`）：
安全边界（`app/core/safety.py` 关键词为主 + `check_boundary_with_llm` 补漏，结论回落固定话术）→ 意图四分类（失败降级 `drug_info`）→ 按意图 RAG 检索 → 检查意图走确定性规则引擎，ConflictReport/CheckReport 注入 prompt（**LLM 只翻译结论，不改结论**）→ 代码级兜底（低置信度 < 0.5 追加不确定提示、无引用追加提示，均为代码强制不靠 prompt 自觉）→ 追加免责声明。

**双后端解析**（`app/api/deps.py::_resolve_backend`）：显式 `PILLCLEAR_BACKEND` 优先；否则配了 `DATABASE_URL` 走 Supabase，未配置落本地 SQLite（数据文件在跨平台数据目录 `<data_dir>/pillclear.db`，见 `config.default_data_dir`）。注意一处**不对称**：药品/药箱仓储未配置连接串时跟随自动解析落 SQLite，但**检索器不自动切 SQLite**——未配置且非显式 `pillclear_backend=sqlite` 时仍是 `NullRetriever` 占位（`/chat` 降级语义与既有测试所系）。

**依赖注入陷阱**：`Settings` 是 Pydantic 模型不可哈希，不能 `lru_cache` 依赖它的工厂；deps.py 用**按 `id(settings)` 的单例表且表项钉住 Settings 引用**（否则 Settings 被 GC 后 id 复用会把旧实现错发给新配置）。新增此类工厂照此模式。测试注入用 `create_app(settings=...)` 或 `dependency_overrides`。

**说明书入库管线**（`app/knowledge/`，CLI 在 `ingest.py`）：解析章节（`parser`）→ LLM 抽取结构化成份（JSON mode + Pydantic 校验）→ 章节向量化（`embedder`）→ 按商品名幂等 upsert。新入库 `ingredients_verified` 恒为 `false`，须人工核对后手动置 `true` 才进 D4 检查。

**规则引擎严格性**（`app/rules/engine.py::load_rules`）：坏规则必须响——YAML/模型校验失败、规则 id 全局重复、零条件规则、空规则目录一律 `ValueError`，不得静默上线。匹配语义是 AND：`IngredientCondition` 按「每药品每成分一条」的扁平列表计数（两种药都含对乙酰氨基酚 → 2 条 → `min_count: 2` 命中）；`SubstanceCondition` 对用户自报物质精确匹配。

**领域词汇**：`CONTEXT.md` 是领域词汇表（权威定义）；代码命名遵循它——尤其「产品 (Product)」同构涵盖 OTC 药与保健品（见 `docs/adr/0001`，故 `Drug`/`drugs` 是「产品」的历史命名）、「物质 (Substance)」是无商品名的自报摄入因素（酒精等）、「检查报告」≠「冲突报告」（冲突只是子集）。新 ADR 放 `docs/adr/`。

## 六、当前进度
已完成：项目骨架；`app/llm` 客户端抽象层（JSON mode + Pydantic 校验 + 自动重试 + usage 日志）；`app/core/safety.py` 边界判断（关键词/规则版 + LLM 补漏）；D3 pgvector / sqlite-vec 说明书检索（失败降级为空引用，不炸 `/chat`）；D4 YAML 规则引擎 + 个人药箱（`POST /api/v1/medbox/check` 返回 CheckReport，药箱持久化端点按 `device_id`；成分叠加纯函数 + mg 单位归一化 `app/core/units.py`；未入库药品明示 `unresolved_drugs` 不静默忽略）；D5 `/chat` 智能体化 + 提示词集中管理（`app/prompts/`）；说明书入库管线与双后端（Supabase / SQLite）。单测 230+ 项全绿（HTTP/LLM 层 respx mock）。
待办：用药提醒（`app/reminder/` 仅占位）。

## 七、工作约定
- 新功能先写测试（TDD）；药学结论类逻辑必须有纯函数 + 单测覆盖。
- 涉及 HTTP / LLM 的测试一律 mock，不打真实 API。
- 模型名、密钥、base_url 一律走 `app/config.Settings` 注入，禁止硬编码。
- 新增实体/概念前先查 `CONTEXT.md` 词汇表，命名与领域语言保持一致。

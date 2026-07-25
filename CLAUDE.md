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
- **默认后端 SQLite**（`%APPDATA%/PillClear/pillclear.db`，WAL 模式），无需 Superbase。设 `DATABASE_URL` 则切到 Postgres + pgvector
- **检索走关键词精确匹配**（`app/rag/keyword_retriever.py`），不依赖 embedding。药名精确匹配 → 模糊匹配 → 内容搜索，三级降级。embedding 仅 Postgres 路径保留
- **LLM 默认 DeepSeek**（`llm_provider=deepseek`，走 `app/llm/providers.py` 预置）。多厂牌支持：openai / qwen / glm / moonshot / ollama
- **测试全程 mock**，HTTP/LLM 调用一律 mock，不打真实网络。测试用 `:memory:` SQLite，不落盘。

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
用户请求 → safety.py(能力边界) → pipeline.py(意图分类+检索+规则引擎+LLM) → 回答+引用+免责
```

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

**领域词汇**：`CONTEXT.md` 定义了产品/商品名/成分/物质/叠加/相互作用等术语的确切含义和边界。新增概念先查词汇表。

## 说明书入库流程

`app/knowledge/ingest.py:ingest_text()` — 解析 `【章节】` → `【成份】` 走 LLM 结构化抽取 → 纯文本 chunk 落 SQLite。文件名 = 商品名，幂等 upsert。**不用 embedding**——检索走关键词匹配。

## 配置的自动化

`.claude/settings.json` 配置了两项：
- **PostToolUse hook**：修改 `app/core/safety.py` 或 `app/rules/` 下任一文件 → 自动跑 `pytest tests/ -x`
- **skillOverrides**：`pillclear-*` 三个业务 skill 设为 `user-invocable-only`（开发时不被模型自动加载，仍可 `/skill-name` 手动调用）；`migrate-to-shoehorn` 隐藏

## 业务操作（非开发任务）

- **新增/修改药学规则** → `/pillclear-rule-engine`
- **说明书入库（新增药品）** → `/pillclear-insert-ingestion`
- **安全边界回归** → `/pillclear-safety-review`

# CLAUDE.md — 项目宪法

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
5. **语气与免责**：年轻人的大白话、简短直接；但安全提示必须**醒目、不打折**；每次用药建议末尾附**固定免责声明**。

## 三、技术栈（已确定，不要更改）
- **LLM**：DeepSeek API，主力 `deepseek-v4-pro`（OpenAI 兼容协议，`base_url=https://api.deepseek.com`）。
  旧模型名 `deepseek-chat` / `deepseek-reasoner` **已废弃，禁止使用**（已在 `app/config.py` 校验拦截）。
- **后端**：Python 3.12 + FastAPI + Pydantic v2。
- **数据库**：Supabase（Postgres + pgvector），schema 用 `migrations/` SQL 文件管理。
- **规则引擎**：自研 YAML 规则 DSL。
- **测试**：pytest，TDD 优先。

## 四、当前进度
已完成：项目骨架、`app/llm` 客户端抽象层（JSON mode + Pydantic 校验 + 自动重试 + usage 日志）、`app/core/safety.py` 边界判断 v1（关键词/规则版）、全套单元测试（31 项全绿，HTTP 层用 respx mock）、D3 pgvector 说明书检索（`app/rag/retriever.py::PgVectorRetriever`：cosine `<=>` 近邻检索 `insert_chunks`，excerpt 取 chunk 前 200 字符保证精确子串；连接/查询/向量化失败降级为空引用不炸 /chat；`get_retriever` 按 `database_url` 是否配置在 PgVectorRetriever / NullRetriever 间切换）、D4 YAML 规则引擎 + 个人药箱（`app/rules/`：6 条内置规则 + 确定性解释器，冲突判断零 LLM；`app/medbox/`：成分叠加纯函数 + mg 单位归一化 `app/core/units.py`，`POST /api/v1/medbox/check` 返回 ConflictReport；未入库药品明示 `unresolved_drugs` 不静默忽略）、D5 `/chat` 智能体化 + 提示词集中管理（`app/prompts/`：`chat.py` 系统 prompt 带 `{rag_context}` 注入 + 冲突结论槽位、`intent.py` 四分类意图、`safety.py` 边界 LLM 分类、`ingest.py` 成分抽取；`/chat` 编排＝安全边界（关键词 + LLM 补漏 `check_boundary_with_llm`）→ 意图分类（失败降级 `drug_info`）→ 按意图 RAG 检索 → 冲突意图走确定性规则引擎并把 ConflictReport 注入 prompt（LLM 只翻译不改结论）→ 低置信度/无引用兜底 → 免责声明；`LLMAnswer.citations_used` 记录自报引用；单测累计 184 项全绿）。
待办：用药提醒、Supabase 迁移 SQL。

## 五、工作约定
- 新功能先写测试（TDD）；药学结论类逻辑必须有纯函数 + 单测覆盖。
- 涉及 HTTP / LLM 的测试一律 mock，不打真实 API。
- 模型名、密钥、base_url 一律走 `app/config.Settings` 注入，禁止硬编码。

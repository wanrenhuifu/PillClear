# PillClear · 年轻人智能用药安全助手

面向 18-30 岁年轻人的 C 端用药安全助手，聚焦 OTC 常用药和保健品。

## 核心能力

1. 说明书"翻译"成大白话（原文检索，回答带引用）
2. 药箱冲突 / 重复成分检查（确定性规则引擎）
3. 用药提醒（每日时刻表 + 服务端计算下次提醒）

## 铁律

- 所有药学结论必须走确定性规则引擎，禁止 LLM 直接推断
- 所有用药回答必须携带说明书原文引用
- 能力边界写死在 `app/core/safety.py`（处方药 / 诊断 / 特殊人群 / 急症）
- 拿不准必须明说"不确定"并建议咨询药师，严禁编造

## 技术栈

- **LLM**: OpenAI 兼容协议，多厂牌支持；默认 DeepSeek `deepseek-v4-pro`
- **后端**: Python 3.12 + FastAPI + Pydantic v2
- **数据库**: 默认 SQLite（零配置）；可选 Supabase（Postgres + pgvector）
- **检索**: 关键词精确匹配（无 embedding 依赖）
- **规则引擎**: YAML DSL，纯函数计算
- **测试**: pytest（TDD），HTTP/LLM 层一律 mock；lint 走 ruff，CI 走 GitHub Actions

## 快速开始

```bash
pip install -e ".[dev]"
cp .env.example .env
# 编辑 .env，填 DEEPSEEK_API_KEY（唯一必填项）

pytest   # 405 个测试全部通过
ruff check app tests   # lint
```

## 前端(Web)

响应式 Web 应用位于 `web/`(React + Vite,独立子项目):

```bash
# 1. 先起后端(默认 8000 端口)
uvicorn app.main:app --reload

# 2. 再起前端(默认 5173 端口,/api 自动代理到后端)
cd web
npm install
npm run dev

# 前端测试
cd web && npx vitest run
```

打开 http://localhost:5173 即可使用:聊天问诊 + 药箱检查 + 用药提醒。
跨域部署时通过 `CORS_ORIGINS` 环境变量配置允许来源(逗号分隔,默认已含 Vite 开发端口)。

## 环境变量

只需一个：`DEEPSEEK_API_KEY`。

`DATABASE_URL` 留空则默认 SQLite（数据目录按平台自动解析，Windows `%APPDATA%/PillClear/`）。LLM 厂牌/模型/端点可通过 `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` 覆盖，详见 `.env.example`。Embedding 相关配置仅 Postgres 路径需要。

## 说明书入库

29 份说明书在 `data/package_inserts/`（`.txt`，文件名 = 商品名，`【章节】` 格式）。

```bash
python -m app.knowledge.ingest data/package_inserts           # 写库（成分抽取走 LLM）
python -m app.knowledge.ingest data/package_inserts --dry-run  # 只看行数/结构，不联网
```

入库幂等（按商品名 upsert），`ingredients_verified` 恒为 false。

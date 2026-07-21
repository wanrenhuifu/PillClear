# 年轻人智能用药安全助手 (PillClear)

面向 18-30 岁大学生 / 职场年轻人的 C 端用药安全助手，聚焦 OTC 常用药和保健品。

## 核心能力
1. 说明书"翻译"成大白话（RAG 检索原文，回答带引用）
2. 药箱冲突 / 重复成分检查（确定性规则引擎）
3. 用药提醒（规划中，暂未实现）

## 铁律（详见 CLAUDE.md）
- 所有药学结论必须走确定性规则引擎，禁止 LLM 直接推断
- 所有用药回答必须携带说明书原文引用
- 能力边界写死在 `app/core/safety.py`（处方药 / 诊断 / 特殊人群 / 急症）
- 拿不准必须明说"不确定"并建议咨询药师，严禁编造

## 技术栈
- LLM: DeepSeek API，主力 `deepseek-v4-pro`（OpenAI 兼容协议）
- 后端: Python 3.12 + FastAPI + Pydantic v2
- 数据库: Supabase (Postgres + pgvector)
- 规则引擎: 自研 YAML 规则 DSL
- 测试: pytest (TDD)

## 目录结构
```
app/
  config.py          配置注入
  llm/               LLM 客户端抽象层（DeepSeek）
  core/safety.py     能力边界判断
  api/ rag/ rules/ medbox/ reminder/   （占位，后续实现）
tests/               单元测试
migrations/          数据库 schema SQL
data/package_inserts/  说明书原文语料
```

## 本地启动

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# source .venv/bin/activate     # macOS / Linux

# 2. 安装依赖（含开发依赖）
pip install -e ".[dev]"

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 4. 运行测试
pytest
```

## 环境变量
| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | （必填） | DeepSeek API Key |
| `LLM_MODEL` | `deepseek-v4-pro` | 模型名，禁用已废弃的 deepseek-chat/deepseek-reasoner |
| `LLM_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容 base_url |
| `LLM_MAX_RETRIES` | `2` | JSON 校验失败自动重试次数 |
| `DATABASE_URL` | （入库必填） | Supabase Postgres 连接串 |
| `EMBEDDING_API_KEY` | （入库必填） | Embedding 服务 Key（默认硅基流动） |
| `EMBEDDING_BASE_URL` | `https://api.siliconflow.cn/v1` | Embedding OpenAI 兼容 base_url |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Embedding 模型（1024 维） |
| `EMBEDDING_DIMS` | `1024` | 向量维度，需与 DDL `vector(1024)` 一致 |

## 数据库与说明书入库（D2）

### 1. 连接 Supabase
在 Supabase 项目 Settings → Database 获取连接串，填入 `.env` 的 `DATABASE_URL`：
```
postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres
```

### 2. 建表（启用 pgvector + 创建 drugs / insert_chunks）
```bash
psql "$DATABASE_URL" -f migrations/0001_init.sql
# 或将该 SQL 贴进 Supabase 控制台的 SQL Editor 执行
```

### 3. 说明书入库
把说明书纯文本放到 `data/package_inserts/`（`.txt` 或 `.md`，**文件名即药品商品名**）。

```bash
# 真实入库（写 Supabase + 调用 embedding）
python -m app.knowledge.ingest data/package_inserts

# 离线演示（内存仓储 + 全零向量，不写库、不联网 embedding，仅看行数与成份 JSON 结构）
python -m app.knowledge.ingest data/package_inserts --dry-run
```
入库幂等：以商品名 upsert，重复运行不产生重复数据；`ingredients_verified` 恒为 `false`，等人工核对后（D4 前置）再手动置 `true`。


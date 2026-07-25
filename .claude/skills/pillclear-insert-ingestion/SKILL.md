---
name: pillclear-insert-ingestion
description: Drug label ingestion pipeline into the knowledge base. Use when ingesting new package inserts, adding drug labels, troubleshooting ingestion/chunking issues. SQLite is the default backend — no embedding or external vector service needed. Triggers: "说明书入库", "ingest", "药品入库", "导入说明书", "package insert".
---

# PillClear 说明书入库

本 skill 固化药品说明书从文本文件到可查询知识库的完整流水线。

## 一、管线总览

```
说明书文件 (.txt/.md)
  → parser.py: 按【章节】分块 + 元数据提取
  → LLM (JSON mode): 抽取结构化成分（IngredientList）
  → sqlite_repo.py: 按商品名幂等 upsert（纯文本 chunk，无向量）
```

检索走关键词精确匹配（`KeywordRetriever`），不需要 embedding。

## 二、前置条件

只需一个环境变量：`DEEPSEEK_API_KEY`（LLM 成分抽取用）。

```bash
# 唯一必填
DEEPSEEK_API_KEY=sk-xxx

# SQLite 是默认后端，无需 DATABASE_URL
# 数据目录按平台自动解析（Windows: %APPDATA%/PillClear/）
```

## 三、说明书文件规范

### 3.1 目录与命名

说明书文件放在 `data/package_inserts/`，文件名 = 商品名（用于幂等 upsert 的去重键）：

```
data/package_inserts/
  ├── 泰诺.txt
  ├── 芬必得.txt
  └── 白加黑.txt
```

### 3.2 文本格式

使用国标【】章节格式（`parser.py` 按 `【` 标题拆分）：

```
【药品名称】
通用名称：酚麻美敏片
商品名称：泰诺
【成份】
本品为复方制剂，每片含对乙酰氨基酚325毫克，盐酸伪麻黄碱30毫克，
氢溴酸右美沙芬15毫克，马来酸氯苯那敏2毫克。
【适应症】
用于缓解普通感冒及流行性感冒引起的发热、头痛、四肢酸痛、鼻塞、流涕、咳嗽等症状。
【用法用量】
口服。成人一次1-2片，一日3次。
【不良反应】
偶见困倦、口干、多汗、恶心等。
【注意事项】
用药期间不得饮酒或含酒精饮料。
【药物相互作用】
与其他解热镇痛药同用可增加肾毒性。
```

必须含 `【成份】` 章节（LLM 抽取成分用）。`【主要成份】`（中成药常见写法）也会被识别。

## 四、执行入库

### 正式入库（写 SQLite + LLM 抽取成分）

```bash
python -m app.knowledge.ingest data/package_inserts
```

### Dry-run（内存仓储，不写库不联网）

```bash
python -m app.knowledge.ingest data/package_inserts --dry-run
```

干跑用于验证解析成功、成分抽取完整、章节分块数量。确认无报错后再正式入库。

## 五、入库后检查

### 验证数据写入

```sql
-- SQLite
SELECT brand_name, ingredients_verified,
       (SELECT COUNT(*) FROM insert_chunks WHERE drug_id = drugs.id) AS chunks
FROM drugs
ORDER BY created_at DESC;
```

### 验证检索可用

发送药品相关查询到 `/api/v1/chat`，检查响应中 `citations` 字段是否有引用。关键词检索按"药名精确匹配 → 模糊匹配 → 内容搜索"三级降级，无引用说明药名与查询完全不相关。

### 成分核对（重要！）

入库后 `ingredients_verified` 恒为 `false`，规则引擎的 `check_medbox` 会将其列为 `unresolved_drugs`。须人工核对后手动置 `true`：

```sql
UPDATE drugs SET ingredients_verified = 1 WHERE brand_name = '<商品名>';
```

## 六、故障排查

| 症状 | 可能原因 | 解决 |
|------|----------|------|
| 成分抽取为空 | LLM 未识别成分章节格式 | 检查【成份】是否有标准写法；用 `--dry-run` 调试 |
| `LLMRetryExhausted` | API key 无效或额度不足 | 检查 `DEEPSEEK_API_KEY` |
| `ValueError: 未识别到任何【章节】标题` | 文件格式不是国标【】章节 | 确认章节标题使用中文方括号 `【】` |
| 入库成功但检索无结果 | 查询词与 brand_name 完全无关 | 检查商品名拼写；KeywordRetriever 按药名精确匹配 |
| upsert 重复 | 文件名与已入库商品名冲突 | 按商品名幂等 upsert——同名文件重复跑是安全的（覆盖更新） |
| 检索为空但数据存在 | SQLite 文件在别的目录 | 确认 `data_dir` 指向正确路径 |

## 七、幂等语义

- 按 `brand_name`（= 文件名去掉扩展名）唯一索引 upsert
- 重复入库同一商品名：旧记录 + 旧 chunks **全量替换**
- `ingredients_verified` 每次入库都重置为 `false`（重新抽取的成分需重新核对）
- 不产生重复数据，不需要手动清理

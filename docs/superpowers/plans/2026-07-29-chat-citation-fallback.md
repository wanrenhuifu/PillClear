# chat 引用兜底 实施计划（TDD）

> 配套设计：`docs/superpowers/specs/2026-07-29-chat-citation-fallback-design.md`
> 红线：不改 prompt 文案（golden 不动）；不碰 `safety.py`/`rules/`；每步可跑测试验证。

## 任务 1 — 先写失败测试（RED）

新建 `tests/test_chat_pipeline.py`，直接调 `process_chat`，全 fake、无 HTTP/无真实 DB：

- `FakeLLM.complete_json(messages, schema, **kw)`：`self.calls += 1`，按 `schema is` 分发返回
  预置的 `SafetyLLMResult(category="none", confidence=0.1)` / `IntentResult` / `LLMAnswer`。
- `FakeRetriever.search(query, limit=5)`：记录 `self.terms`，返回 `canned.get(query, [])`。
- `repo` = `InMemoryDrugRepository`，种子：泰诺(对乙酰氨基酚325)、必理通(对乙酰氨基酚500)、
  扶他林_外用、三九感冒灵、感冒灵。`rules = load_rules(DEFAULT_RULES_DIR)`。
- 用例见设计「影响面与测试」①–⑧。

运行 `pytest tests/test_chat_pipeline.py -x`：应**红**（扫描未实现 → effective 为空 →
①②③⑦ 断言失败）。

## 任务 2 — 最小实现（GREEN，新文件）

编辑 `app/chat/pipeline.py`：

1. 顶部加 `import re`（若 `re` 未用；本文件当前未 import re，新增）。
2. 在 `_merge_citations` 之后加 `_brand_patterns` / `_scan_brand_names` / `_effective_drug_names`
   （实现见设计文档）。
3. 改 `_retrieve_citations` 签名为 `(retriever, query, intent, effective_drug_names)`，主体替换为
   设计文档的「检索分支」。
4. `process_chat` 中：`intent` 之后算 `effective = _effective_drug_names(query, intent, drug_repo)`；
   `_retrieve_citations(...)` 传入 `effective`；第 4 步 `items` 改由 `effective` 构造
   （`brand_name` 已 strip，门控仍是 interaction 意图不变）。

运行 `pytest tests/test_chat_pipeline.py -x`：应**绿**。

## 任务 3 — 修 test_api_chat 检索隔离（GREEN，既有文件）

编辑 `tests/test_api_chat.py`：

- 顶部 import 增加 `from app.rag import NullRetriever` 与 `from app.api.deps import get_retriever`
  （`get_drug_repository` 已 import，`get_retriever` 同模块）。
- `app_with_test_settings` 内追加：
  `app.dependency_overrides[get_retriever] = lambda: NullRetriever()`。

运行 `pytest tests/test_api_chat.py -x`：应**绿**（含 `test_citations_empty_adds_no_citation_note`
在本机已入库 DB 下仍绿）。

## 任务 4 — 全量回归 + 提交

- `pytest` 全绿（基线 ≥ 现网通过数；新增 8 用例）。
- 确认 `tests/golden/` 未被改写、`git status` 无 `safety.py`/`rules/` 改动。
- 提交实现 + 测试（文档已在上一提交）。

## 验收清单

- [ ] `test_chat_pipeline.py` 8 用例全绿
- [ ] `test_api_chat.py` 全绿（含 retriever override）
- [ ] `pytest` 全量绿，无新增真实网络调用
- [ ] golden 14 份未变；prompt 文案零改动
- [ ] `process_chat` 放行路径 LLM 调用仍 ≤3

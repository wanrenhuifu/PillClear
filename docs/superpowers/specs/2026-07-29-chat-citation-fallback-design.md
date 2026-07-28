# chat 链路「引用掉 0」加固：确定性商品名扫描兜底

> 2026-07-29 · 行为增强（非重构）：检索更稳，prompt 文案逐字不变，golden 不动
> 铁律契合：#1 确定性优先（用代码扫描补 LLM 漏名）；不改 `safety.py` / `rules/`

## 目标

`/chat` 在 LLM 的 `complete_json`（意图抽取 / 安全补漏）偶发返回空体时，意图降级为
`drug_info` 且 `drug_names=[]`，`_retrieve_citations` 继而用「整句 query」检索 → 0 命中 →
回答「没查到该药」且引用为空。检索层本身健康（`search("泰诺")` = 15 命中）。
本次加一个**确定性的商品名扫描**作为兜底/增强：用 query 直接匹配已知品牌名，把命中的
名字并入检索与规则检查所用名单，使 JSON 空响应时检索不再为空。

## 背景与根因（已定位）

- `app/chat/pipeline.py:_classify_intent` 在任意异常（含空体 `JSONDecodeError char 0`）时
  返回 `IntentResult(DRUG_INFO, confidence=0.0, drug_names=[])`。
- `_retrieve_citations` 对 `drug_info` 走 `retriever.search(query)`；整句既不等于任何
  `brand_name`、`LIKE` 也匹配不到任何 chunk → 0 命中。
- `process_chat` 已注入 `drug_repo: DrugReader`，其 `list_drugs()` 现成返回全部
  `{id, brand_name, generic_name}` → 品牌名集合在编排层**无需新增依赖**即可取得。
- 同一直觉名单还喂给第 4 步 `check_medbox`（相互作用意图下），可顺带补全 LLM 漏名的冲突检测。

## 已确认决策

1. **钩子位置 = pipeline 编排层**：新增纯函数扫描，置于 `_classify_intent` 之后；intent 模块
   无依赖注入，不放。不改 `Retriever` 协议、不改 `deps.py`。
2. **合并语义 = 并集去重保序**：`effective = dedupe(intent.drug_names + scan(query))`。
   LLM 名补 query 没明写的别名；扫描在 LLM 空响应时兜底，且只加 query **字面出现**的高精度名。
   否决「仅 LLM 为空才兜底」——会丢掉 LLM 正常时的增量价值。
3. **CJK 匹配 = 贪心最长匹配**：候选模式 = 每个入库 `brand_name` ＋ 其「去注解核名」
   （`brand_name.split("_",1)[0]`，仅当与原名不同且长度≥2 才作别名，使 `扶他林_外用` 可被
   query 里的「扶他林」命中，映射回存储名）。按模式长度降序，在 query 可变副本上贪心：
   命中即把该跨度置空再试更短模式 → 天然解决「泰诺&白加黑 都真出现→都收」与
   「三九感冒灵 套住 感冒灵→只留长的」。
4. **v1 不扫 generic_name**：通用名一对多，会拉进多个药的章节稀释焦点（用户担心的「误导」
   源头）。保留为单行可开的开关，默认关。注解词（`_` 之后，如「外用」）**不**作匹配模式，
   避免「外用药膏」误命中 `扶他林_外用`。
5. **检索分支调整**：`_retrieve_citations(retriever, query, intent, effective)`——`effective`
   非空 → `_merge_citations(retriever, effective [+ lifestyle 的 substances])`；为空 → 回退
   `retriever.search(query)`（现状不变）。这把 `drug_info` 从「整句搜」升级为「按药名搜」，
   是修引用掉 0 的关键；对 `drug_info` 且 LLM 给了名的情形也是严格改进。
6. **扫描永不阻断**：`list_drugs()` 与扫描各自 `try/except` 降级为空（与流水线「处处降级」
   哲学一致）；扫描是纯函数 + 一次读，**零额外 LLM 调用**（守住 `test_api_chat` 的 ≤3 次断言）。
7. **随本次修一个隐藏测试隔离缺陷**：`tests/test_api_chat.py` 的 `client`/`client_seeded` 只
   override 了 settings 与 drug_repo，**未 override retriever**；在本机（已入库 29 种药）
   `get_retriever` 返回指向真实 `%APPDATA%` DB 的 `KeywordRetriever`，今天能过纯因「整句
   search」永不命中。新扫描会把真实品牌名注入检索，使 `test_citations_empty_adds_no_citation_note`
   （query 含「泰诺」）在本机变红。修法：在 `app_with_test_settings` 把 `get_retriever` override
   成 `NullRetriever`（确定性、与机器入库状态无关）。校验过：该文件无任何断言依赖真实检索内容，
   规则结论来自被 override 的 seeded repo，不受影响。

## 设计

### 数据流（process_chat）

```
intent     = _classify_intent(llm, query)
effective  = _effective_drug_names(query, intent, drug_repo)     # 新增
citations  = _retrieve_citations(retriever, query, intent, effective)   # 改签名
... 第4步 check_medbox 的 items 改由 effective 构造（门控仍是 interaction 意图）...
```

### 新增纯函数

```python
def _brand_patterns(brands):  # -> list[(pattern, stored_brand)]，按 pattern 长度降序
    pairs, seen = [], set()
    for d in brands:
        name = (d.get("brand_name") or "").strip()
        if not name:
            continue
        aliases = [name]
        core = name.split("_", 1)[0].strip()
        if core and core != name and len(core) >= 2:
            aliases.append(core)
        for a in aliases:
            if a not in seen:
                seen.add(a); pairs.append((a, name))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs

def _scan_brand_names(query, brands):  # -> list[stored_brand]，首次命中顺序、去重
    work, found, found_set = query, [], set()
    for pattern, stored in _brand_patterns(brands):
        idx = work.find(pattern)
        if idx >= 0:
            work = work[:idx] + "\x00" * len(pattern) + work[idx + len(pattern):]
            if stored not in found_set:
                found_set.add(stored); found.append(stored)
    return found

def _effective_drug_names(query, intent, drug_repo):
    try:
        brands = drug_repo.list_drugs()
    except Exception:  # noqa: BLE001 - 扫描是增强，失败不得阻断
        brands = []
    seen, out = set(), []
    for n in (*intent.drug_names, *_scan_brand_names(query, brands)):
        n = (n or "").strip()
        if n and n not in seen:
            seen.add(n); out.append(n)
    return out
```

### 检索分支（替换 _retrieve_citations 主体）

```python
terms = list(effective_drug_names)
if intent.intent is IntentCategory.LIFESTYLE_INTERACTION:
    for s in intent.lifestyle_substances:
        s = (s or "").strip()
        if s and s not in terms:
            terms.append(s)
return _merge_citations(retriever, terms) if terms else retriever.search(query)
```

## 影响面与测试

- **不改任何 prompt 文案** → `tests/golden/` 14 份不重生；`tests/test_prompts*` 不受影响。
- **不碰 `safety.py` / `rules/`** → 不触发 PostToolUse 全量回归钩子的非预期面；
  `tests/test_safety` 特征化用例不受影响。
- **新增 `tests/test_chat_pipeline.py`**：直接调 `process_chat`（FakeLLM 按 schema 分发
  `SafetyLLMResult/IntentResult/LLMAnswer`、FakeRetriever 记录检索词并返回 canned 引用、
  种子 `InMemoryDrugRepository`、真实 `load_rules`），覆盖：
  ① LLM 空名 + query 含种子品牌 → 引用非空且检索词 == 该品牌；
  ② LLM 名 ∪ 扫描名 并集去重；
  ③ 嵌套名贪心最长匹配（`三九感冒灵` 不被 `感冒灵` 二次命中；非重叠短名仍收）；
  ④ 去注解核名匹配（`扶他林` → `扶他林_外用`），且注解词「外用」不致误命中；
  ⑤ 全无品牌 → 回退整句 search；
  ⑥ lifestyle 无药名时 substances 仍被检索（回归保护）；
  ⑦ interaction + LLM 空名 + query 两品牌 → 规则引擎对扫描名跑起来（断言缺引用注记被
     `has_findings` 抑制，间接证明 check 收到扫描名）；
  ⑧ 每个放行用例 `llm.calls == 3`（扫描零额外调用）。
- **`tests/test_api_chat.py`**：仅加 `get_retriever → NullRetriever` 的隔离 override；
  现有断言在新检索分支下全绿。

## 不做的事（YAGNI）

generic_name 匹配、品牌列表缓存、改 prompt、动 `safety.py`/`rules/`、改 `Retriever` 协议、
在 `drug_info` 上强行跑药箱检查（over-trigger 风险，留作后续可选项）。

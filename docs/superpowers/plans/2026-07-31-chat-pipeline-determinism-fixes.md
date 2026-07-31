# /chat 流水线确定性修复实施计划（15 条 code review 发现）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉 `/code-review max` 确认的 15 条缺陷——它们全部集中在 `/chat` 流水线的确定性品牌扫描、否定语义、引用预算、检查结论通道四块，全部不改变「关键词/确定性引用检索」的架构方向（用户已拍板：不换语义 RAG）。

**Architecture:** 不动检索架构。把 pipeline.py 的确定性扫描改对（裸名歧义降级、恢复 LLM∪扫描并集、紧邻式否定），把引用预算改成每药公平 + 整句预留 + 提前终止，把启发式披露移出「确定性规则引擎」通道（独立提示槽位），`has_findings` 收敛为单一事实来源，检索器补 `ORDER BY` 与每品牌公平截断，medbox 仓储强制共享锁，start.bat 补前置检查，golden 补组合顺序。

**Tech Stack:** Python 3.12 + FastAPI；pytest（质量闸门，无 linter）；golden 比对（`tests/golden/`，`PILLCLEAR_REGEN_GOLDEN=1` 重生成）；测试全程 mock，无真实网络/DB。

## Global Constraints

- **铁律 #1**：药学结论必须走规则引擎；本计划所有改动不得让 LLM 直接推断药效结论。
- **铁律 #2**：引用为空视为缺陷（`_NO_CITATION_NOTE`）；启发式披露不得压制无引用注记。
- **铁律 #3**：急症/特殊人群/诊断拦截路径（`app/core/safety.py`）**一律不动**（本计划不触碰该文件，避免触发 PostToolUse hook 与特征化测试）。
- **铁律 #4**：不确定就明说；近似匹配必须披露，且不得伪装成确定性结论。
- 测试行为变更须显式决策并在 commit 说明；禁止悄悄改测试。
- 文案变更走 golden：改 prompt 模板/文案后必须重生成 golden 并在 commit 说明改动（PowerShell：`$env:PILLCLEAR_REGEN_GOLDEN=1; python -m pytest tests/test_prompts_golden.py; Remove-Item env:PILLCLEAR_REGEN_GOLDEN`）。
- 全量测试每步后 `pytest tests/<相关文件> -q`，任务收尾跑 `pytest`（142 个用例基线全绿）。
- 工作落在当前分支 `feat/web-frontend`（code review 针对的就是该分支工作区状态）。
- 每任务独立提交，commit message 中文，附 `Co-Authored-By: Claude <noreply@anthropic.com>`。

## 发现 → 任务映射

| 发现 # | 文件:行 | 任务 |
|--------|---------|------|
| 8 | keyword_retriever.py:29/37/45 | **T1** 检索器确定性截断 + 每品牌公平 |
| 9 | sqlite_medbox_repo.py:42 | **T2** 共享连接强制共享锁 |
| 15 | start.bat:26 | **T3** 前置 node/npm 检查 |
| 1 | pipeline.py:189 | **T4** 裸名歧义降级 |
| 2 | pipeline.py:257 | **T5** 恢复 LLM∪扫描并集 + 规范映射 |
| 3/4/10 | pipeline.py:84/199 | **T6** 紧邻式否定重写 |
| 5/11/14 | pipeline.py:293-295 | **T7** 引用预算公平分配 |
| 6/7/12/13 | pipeline.py:359-369, chat.py, formatters.py, golden | **T8** 检查结论通道分离 + has_findings 单一来源 |
| — | 全部 | **T9** 全量回归 + 文档收尾 |

---

### Task 1: 检索器确定性截断 + 每品牌公平

**Files:**
- Modify: `app/rag/keyword_retriever.py:24-99`（三条 SQL + `_search`）
- Modify: `tests/test_keyword_retriever_limits.py`（新增两个测试）
- Modify: `tests/test_sqlite_repo.py:113-119, 145-152`（改 stale docstring）

**Interfaces:**
- Consumes: `search(query: str, limit: int = 5) -> list[Citation]`（签名不变）
- Produces: 三条 SQL 都加 `ORDER BY c.id`；LIKE 品牌阶段改为「先全量拉取按 id 排序的命中行，Python 侧每品牌轮转分配，总量 ≤ limit」。`_fair_alloc(rows, limit)` 私有方法。

**现状（已核实）：** 三条 SQL 的 `LIMIT ?` 无 `ORDER BY`（任意 12 行子集）；LIKE 多药命中时第一个药吃满预算。

- [ ] **Step 1: 写失败测试**（`tests/test_keyword_retriever_limits.py`）

```python
def _seed(repo, brand, n_chunks, section_prefix="章节"):
    """自包含 seed：一个药品 n_chunks 个章节（chunk 无 embedding，_NO_EMBEDDING=[]）。"""
    drug_id = repo.upsert_drug(
        DrugRecord(brand_name=brand, ingredients=[Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")])
    )
    repo.replace_chunks(drug_id, [(f"{section_prefix}{i}", f"内容{i}", []) for i in range(n_chunks)])
    return drug_id


def test_exact_brand_match_keeps_document_order(self, retriever):
    """精确命中也按说明书章节顺序截断（ORDER BY id），而非任意子集。"""
    repo = SQLiteDrugRepository(":memory:")
    _seed(repo, "泰诺", 13)
    r = KeywordRetriever(connection=repo.connection)
    got = r.search("泰诺", limit=12)
    assert [c.section for c in got] == [f"章节{i}" for i in range(12)]

def test_like_match_across_drugs_allocates_fairly(self):
    """多药模糊命中时每药都有份额（轮转分配），而不是第一个药吃满。"""
    repo = SQLiteDrugRepository(":memory:")
    for brand in ("泰诺林片", "泰诺胶囊", "泰诺颗粒"):
        _seed(repo, brand, 4)
    r = KeywordRetriever(connection=repo.connection)
    got = r.search("泰诺", limit=6)
    brands = [c.brand_name for c in got]
    assert "泰诺林片" in brands and "泰诺胶囊" in brands and "泰诺颗粒" in brands
    assert len(got) == 6
```

（`DrugRecord`/`Ingredient`/`SQLiteDrugRepository`/`KeywordRetriever` 按文件现有 import 方式引入；`replace_chunks` 的第三参为空列表 = 无 embedding，沿用 `test_sqlite_repo.py:106` 的 `_NO_EMBEDDING` 惯用含义。）

- [ ] **Step 2: 跑测试确认失败**
  Run: `pytest tests/test_keyword_retriever_limits.py -q` — Expected: 新测试 FAIL（当前无 ORDER BY、无公平分配）。

- [ ] **Step 3: 实现**

三条 SQL 各加 `ORDER BY c.id`（`insert_chunks.id` 是 identity 主键，见 `migrations/0001_init.sql:33`，保持章节文档顺序）：

```python
_SEARCH_BY_BRAND_EXACT = """
SELECT d.brand_name, c.section, c.content
FROM insert_chunks c
JOIN drugs d ON d.id = c.drug_id
WHERE d.brand_name = ?
ORDER BY c.id
LIMIT ?
"""
_SEARCH_BY_BRAND_LIKE = """
SELECT d.brand_name, c.section, c.content
FROM insert_chunks c
JOIN drugs d ON d.id = c.drug_id
WHERE d.brand_name LIKE ?
ORDER BY c.id
"""
_SEARCH_BY_CONTENT = """
SELECT d.brand_name, c.section, c.content
FROM insert_chunks c
JOIN drugs d ON d.id = c.drug_id
WHERE c.content LIKE ? OR c.section LIKE ?
ORDER BY c.id
LIMIT ?
"""
```

`_search` 的 LIKE 分支改为拉全量后轮转分配（去掉 LIKE SQL 的 LIMIT；content 分支保留 LIMIT，语义不变）：

```python
    # 2. 模糊匹配品牌名：全量按 id 序拉取，Python 侧每品牌轮转分配。
    #    多药命中（泰诺 → 泰诺林片/泰诺胶囊/泰诺颗粒）时每药都有份额，
    #    不因入库顺序让第一个药吃满预算（code review 修复）。
    rows = conn.execute(_SEARCH_BY_BRAND_LIKE, (f"%{term}%",)).fetchall()
    if rows:
        return self._fair_alloc(rows, limit)

    # 3. 降级到章节内容搜索
    like_term = f"%{term}%"
    rows = conn.execute(
        _SEARCH_BY_CONTENT, (like_term, like_term, limit)
    ).fetchall()
    return self._rows_to_citations(rows)
```

新增私有方法：

```python
    @staticmethod
    def _fair_alloc(rows: list[tuple], limit: int) -> list[Citation]:
        """多品牌行按 c.id 序轮转分配，直到 limit：每品牌至少一份（确定性）。"""
        groups: dict[str, list] = {}
        order: list[str] = []
        for brand, section, content in rows:
            if brand not in groups:
                groups[brand] = []
                order.append(brand)
            groups[brand].append((brand, section, content))
        out: list[tuple] = []
        idx = 0
        while len(out) < limit and any(len(g) > idx for g in groups.values()):
            for brand in order:
                if idx < len(groups[brand]) and len(out) < limit:
                    out.append(groups[brand][idx])
            idx += 1
        return [
            Citation(brand_name=b, section=s, excerpt=c[:_EXCERPT_MAX_LEN])
            for b, s, c in out
        ]
```

（精确分支保持单药 `LIMIT ?`：`drugs.brand_name` 唯一，只可能命中一个药。）

- [ ] **Step 4: 跑测试确认通过**
  Run: `pytest tests/test_keyword_retriever_limits.py tests/test_sqlite_repo.py -q` — Expected: 新测试 PASS，现有 `test_keyword_retriever_limits.py` 五个用例仍 PASS（轮转分配下 `limit=5/2/3` 断言不变，已核对：`test_like_brand_match_across_drugs_honors_limit` 两药 4+4 章 limit=5 → a1,b1,a2,b2,a3=5 仍成立）。

- [ ] **Step 5: 修 stale docstring**（`tests/test_sqlite_repo.py`）
  - `:114`「返回该药所有 chunk」→「返回该药匹配到的 chunk（受 limit 约束，按章节顺序截断）」
  - `:146`「limit 仅在 content fallback 路径生效」→「limit 在三级降级一律生效；content 分支语义不变」

- [ ] **Step 6: 提交**
  ```bash
  git add app/rag/keyword_retriever.py tests/test_keyword_retriever_limits.py tests/test_sqlite_repo.py
  git commit -m "fix(retrieval): 检索 LIMIT 加 ORDER BY 保文档序，多药命中每品牌公平分配"
  ```

---

### Task 2: SQLiteUserMedboxRepository 共享连接强制共享锁

**Files:**
- Modify: `app/medbox/sqlite_medbox_repo.py:31-42`
- Modify: `tests/test_sqlite_repo.py:175, 185, 196`
- Modify: `tests/test_sqlite_concurrency.py`（保持现状——已正确传锁，作回归保护）

**Interfaces:**
- Consumes: 构造签名 `(db_path_or_connection: str | sqlite3.Connection = ":memory:", *, lock: threading.RLock | None = None)`
- Produces: 传入 `sqlite3.Connection` 且 `lock is None` → 构造时 `ValueError`（fail-fast，不再静默建私有锁）。

**现状（已核实）：** `self._lock = lock if lock is not None else threading.RLock()` 让「共享连接不传锁」与正确用法不可区分；测试 fixture 复刻了错误模式（`check_same_thread=False` 连接 + 两把独立锁）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_sqlite_concurrency.py`）

```python
def test_shared_connection_without_lock_raises():
    """共享连接必须显式传共享锁：静默自建私有锁会复刻两锁一连接交错（code review #13 回归）。"""
    repo = SQLiteDrugRepository(":memory:")
    with pytest.raises(ValueError, match="共享.*锁"):
        SQLiteUserMedboxRepository(repo.connection)
```

（文件需 import `pytest`、`SQLiteDrugRepository`、`SQLiteUserMedboxRepository`。）

- [ ] **Step 2: 跑测试确认失败**
  Run: `pytest tests/test_sqlite_concurrency.py -q` — Expected: FAIL（当前不抛异常）。

- [ ] **Step 3: 实现**

```python
        if isinstance(db_path_or_connection, sqlite3.Connection):
            if lock is None:
                raise ValueError(
                    "共享 sqlite3.Connection 必须同时传入共享 lock"
                    "（同连接的两把锁会交错撕裂事务，见 code review #13）"
                )
            self._conn = db_path_or_connection
        else:
            # 独立连接：FK 关闭，药箱仓储可独立于药品库使用（见模块头注）。
            self._conn = open_sqlite(db_path_or_connection, foreign_keys=False)
            if lock is None:
                lock = threading.RLock()
        self._lock = lock
```

- [ ] **Step 4: 跑测试确认通过 + 修 fixture**
  - `pytest tests/test_sqlite_concurrency.py -q` — PASS。
  - `tests/test_sqlite_repo.py:175/185/196`：`SQLiteUserMedboxRepository(drugs.connection)` → `SQLiteUserMedboxRepository(drugs.connection, lock=drugs.lock)`（fixture 从复刻坏模式改为示范正确模式）。
  - `pytest tests/test_sqlite_repo.py -q` — PASS。

- [ ] **Step 5: 提交**
  ```bash
  git add app/medbox/sqlite_medbox_repo.py tests/test_sqlite_concurrency.py tests/test_sqlite_repo.py
  git commit -m "fix(medbox): 共享连接不传锁改为构造期 ValueError，fixture 示范正确用法"
  ```

---

### Task 3: start.bat 前置 node/npm 检查

**Files:**
- Modify: `start.bat`（`web\node_modules\.bin\vite.cmd` 检查之前插入）

**Interfaces:** 无（batch 脚本，无单测基建；人工验证）。

- [ ] **Step 1: 修改**（保持 ASCII-only，防 zh-CN cmd 乱码）

在 backend 检查之后、`if exist "web\node_modules\.bin\vite.cmd" goto deps_ok` 之前插入：

```bat
REM -- frontend runtime check --
where node >nul 2>&1
if errorlevel 1 (
    echo [PillClear] ERROR: node not found. Install Node.js LTS from https://nodejs.org/ first, then re-run this script.
    exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [PillClear] ERROR: npm not found. Install Node.js LTS from https://nodejs.org/ first, then re-run this script.
    exit /b 1
)
if not exist "web\package.json" (
    echo [PillClear] ERROR: web\package.json not found. Cannot start the frontend; make sure this is the PillClear repo root.
    exit /b 1
)
```

- [ ] **Step 2: 人工验证**
  - 在 PATH 无 node 的环境跑 `start.bat` → 应提示 node 缺失并退出，而非 `npm install` 报 9009。
  - 正常环境跑 → 行为与原来一致。

- [ ] **Step 3: 提交**
  ```bash
  git add start.bat
  git commit -m "fix(start.bat): 前置 node/npm/package.json 检查，缺 Node 时报可操作错误而非网络误导"
  ```

---

### Task 4: 品牌扫描——裸名与注解兄弟共存时降级

**Files:**
- Modify: `app/chat/pipeline.py:167-194`（`_brand_patterns`）
- Modify: `app/chat/pipeline.py:72-81`（模块注释「语义约定」段）
- Modify: `tests/test_chat_pipeline.py`（新增一个测试）

**Interfaces:**
- Consumes: `_brand_patterns(brands: list[dict]) -> list[tuple[str, str]]`
- Produces: 语义变更——裸名（`扶他林`）与带注解兄弟（`扶他林_外用`）并存时，裸名不作为匹配模式（按 docstring「宁可按整句检索降级，也不静默命中某一个剂型」）。

**现状（已核实）：** 裸名行 `core=None` 未注册进 `core_owners`，`ambiguous_cores` 的 `core in full_names` 覆盖不到它 → 裸名仍是模式且 `term==stored` 不产生披露 → 静默按口服剂型查「扶他林能外用吗」。

- [ ] **Step 1: 写失败测试**（追加到 `TestScanHardening`）

```python
def test_bare_name_with_annotated_sibling_degrades(self, rules):
    """裸名 扶他林 与 扶他林_外用 并存 → 裸名不作模式（静默命中任一个剂型 = bug）。

    「扶他林能外用吗」无法确定剂型：宁可按整句检索降级，也不静默按口服剂型查。
    """
    r = _repo_with(
        ("扶他林", [("双氯芬酸", 25)]),
        ("扶他林_外用", [("双氯芬酸", 10)]),
    )
    _, _, ret = _run("扶他林能外用吗", _empty_intent(), r, rules)
    assert "扶他林" not in ret.terms
    assert "扶他林_外用" not in ret.terms
    assert ret.terms == ["扶他林能外用吗"]  # 整句检索降级
```

- [ ] **Step 2: 跑测试确认失败**
  Run: `pytest tests/test_chat_pipeline.py::TestScanHardening::test_bare_name_with_annotated_sibling_degrades -q` — Expected: FAIL（当前 扶他林 命中）。

- [ ] **Step 3: 实现**

```python
    rows: list[tuple[str, str | None]] = []
    core_owners: dict[str, set[str]] = {}
    for d in brands:
        name = (d.get("brand_name") or "").strip()
        if not name:
            continue
        core = name.split("_", 1)[0].strip()
        if core and len(core) >= 2:
            # 裸名也注册自己的 core：让「裸名 + 注解兄弟」的并存被 ambiguity 捕捉
            core_owners.setdefault(core, set()).add(name)
            rows.append((name, core if core != name else None))
        else:
            rows.append((name, None))
    # 一个 core 有多个 owner（含裸名自身）→ 歧义，只保留全名模式
    ambiguous_cores = {
        core for core, owners in core_owners.items() if len(owners) > 1
    }
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, core in rows:
        if core is None:
            # 裸名：若 core 与注解兄弟共享（歧义），不命中任一剂型 → 降级整句检索
            if name in ambiguous_cores:
                continue
            aliases = (name,)
        elif core in ambiguous_cores:
            aliases = (name,)
        else:
            aliases = (name, core)
        for a in aliases:
            if a not in seen:
                seen.add(a)
                pairs.append((a, name))
    return pairs
```

（已核对既有用例：仅 `扶他林_外用` → owners=1 不歧义，核名 扶他林 仍是模式（`test_annotation_core_match_and_disclosure` 保持）；`扶他林_外用`+`扶他林_口服` → owners=2 歧义（`test_shared_core_between_siblings_not_scannable` 保持）；裸名单存 `泰诺` → owners=1 不歧义，正常命中。）

- [ ] **Step 4: 跑测试确认通过**
  Run: `pytest tests/test_chat_pipeline.py -q` — Expected: 新测试 PASS，既有 `TestBrandScan`/`TestScanHardening` 全绿（`test_annotation_core_match_and_disclosure`、`test_shared_core_between_siblings_not_scannable` 已核对不变）。

- [ ] **Step 5: 更新模块注释**（`pipeline.py:74-76` 的「仅降级兜底」段与 `_brand_patterns` docstring 的歧义核名说明）
  补一句：裸名与注解兄弟并存时裸名降级不作模式（code review 修复）。

- [ ] **Step 6: 提交**
  ```bash
  git add app/chat/pipeline.py tests/test_chat_pipeline.py
  git commit -m "fix(scan): 裸名与注解兄弟并存时裸名降级不作模式，不静默查错剂型"
  ```

---

### Task 5: 品牌扫描——恢复 LLM∪扫描并集 + 规范映射

**Files:**
- Modify: `app/chat/pipeline.py:244-263`（`_effective_drug_names`）+ `:72-81` 注释
- Modify: `tests/test_chat_pipeline.py`（更新 `test_scan_stays_quiet_when_llm_named_drugs`，新增并集/规范映射测试）
- Modify: `tests/test_chat_pipeline.py:1-13`（模块 docstring）

**Interfaces:**
- Consumes: `_scan_brand_names(query, brands) -> (list[str], list[tuple[str, str]])`（T4 已定型）
- Produces: `_effective_drug_names` 语义变更——**扫描无条件运行**；LLM 药名经「近似匹配规范映射」收敛到存储名后与扫描结果并集去重。返回 `(effective, ambiguous)` 不变。

**现状（已核实）：** `if llm_names: return llm_names, []` 全有或全无——LLM 返回任一药名就跳过扫描，「泰诺和必理通能一起吃吗」被 LLM 只解析出泰诺时必理通从不入检查。

- [ ] **Step 1: 更新既有测试**（锁定并集语义——这是显式行为变更，须在 commit 说明）

`test_scan_stays_quiet_when_llm_named_drugs` → 改为 `test_scan_unions_with_llm_names`：

```python
    def test_scan_unions_with_llm_names(self, repo, rules):
        """LLM 只抽到 泰诺 时，扫描并集补回 query 里被漏的 必理通（code review 修复）。

        全有或全无门控会把半解析交互问题里的药静默丢掉（查不出相互作用）。
        """
        intent = IntentResult(
            intent=IntentCategory.DRUG_INTERACTION,
            confidence=0.9,
            drug_names=["泰诺"],
        )
        _, llm, ret = _run(
            "泰诺和必理通能一起吃吗",
            intent,
            repo,
            rules,
            canned={"泰诺": [_cite("泰诺")], "必理通": [_cite("必理通")]},
        )
        assert "必理通" in ret.terms  # 扫描补回
        assert llm.calls == 3  # 扫描仍是零额外 LLM 调用
```

- [ ] **Step 2: 写新测试（规范映射）**

```python
    def test_llm_bare_name_resolves_to_annotated_stored(self, repo, rules):
        """LLM 说「扶他林」→ 规范映射到存储名 扶他林_外用，不产生「暂未收录」自相矛盾。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INTERACTION,
            confidence=0.9,
            drug_names=["扶他林"],
        )
        result, llm, ret = _run(
            "扶他林能和布洛芬一起吃吗",
            intent,
            repo,
            rules,
            answer_citations=[],
        )
        prompt = _system_prompt(llm)
        assert "扶他林_外用" in prompt
        assert "暂未收录" not in prompt  # 裸名没有以「查不到」形态进入检查
        assert "扶他林_外用" in ret.terms
```

- [ ] **Step 3: 跑测试确认失败**
  Run: `pytest tests/test_chat_pipeline.py::TestBrandScan -q` — Expected: 更新后 `test_scan_unions_with_llm_names` 与 `test_llm_bare_name_resolves_to_annotated_stored` 均 FAIL（当前不并集、裸名直接进检查）。

- [ ] **Step 4: 实现**

```python
def _effective_drug_names(
    query: str, intent: IntentResult, drug_repo: DrugReader
) -> tuple[list[str], list[tuple[str, str]]]:
    """解析有效药名名单：LLM 抽取与确定性扫描并集，规范映射去重。

    扫描无条件运行（修「引用掉 0」，并补回 LLM 半解析漏掉的药）；LLM 药名经
    扫描的近似匹配映射收敛到存储名（扶他林 → 扶他林_外用），避免同一药以
    「用户原文 + 存储名」两种形态进检查（自相矛盾）。子串误命中是已知盲区
    （无分词器不可消除，见 docs/refactor-readiness.md）。

    返回 (有效药名, 近似匹配)。list_drugs / 扫描任何环节失败一律降级为
    空名单，绝不阻断主流程（与流水线「处处降级」哲学一致）。
    """
    llm_names = _dedup_stripped(intent.drug_names)
    try:
        scan_names, ambiguous = _scan_brand_names(query, drug_repo.list_drugs())
    except Exception:  # noqa: BLE001 - 扫描是增强，失败不得阻断
        logger.warning("品牌名扫描失败，降级为空名单", exc_info=True)
        scan_names, ambiguous = [], []
    # 规范映射：近似匹配 (term→stored) 与精确命中 (name→name) 都用于收敛 LLM 名
    canonical = {term: stored for term, stored in ambiguous}
    canonical.update({n: n for n in scan_names})
    effective = list(scan_names)
    seen = set(scan_names)
    for name in llm_names:
        resolved = canonical.get(name, name)
        if resolved not in seen:
            seen.add(resolved)
            effective.append(resolved)
    return effective, ambiguous
```

- [ ] **Step 5: 跑测试确认通过 + 更新模块 docstring**
  - `pytest tests/test_chat_pipeline.py -q` — Expected: 全绿（`test_scan_rescues_citations_when_intent_empty` 等空名路径不受影响，已核对）。
  - 更新 `pipeline.py:74-76`「不与 LLM 名并集」注释 → 「LLM∪扫描并集 + 规范映射（code review 修复）」；更新 `tests/test_chat_pipeline.py:6-12` 模块 docstring 同样语义。

- [ ] **Step 6: 提交**
  ```bash
  git add app/chat/pipeline.py tests/test_chat_pipeline.py
  git commit -m "fix(scan): 恢复 LLM∪扫描并集，LLM 药名规范映射到存储名——半解析交互问题不再丢药"
  ```

---

### Task 6: 否定语义——紧邻式重写

**Files:**
- Modify: `app/chat/pipeline.py:83-103, 197-200, 231`（标记常量 + `_is_past_or_negated` + 调用点）
- Modify: `tests/test_chat_pipeline.py`（更新 `test_past_tense_mention_skipped`，新增否定测试）
- Modify: `docs/refactor-readiness.md`（第 6 条扫描语义）

**Interfaces:**
- Consumes: `_scan_brand_names` 内 `_is_past_or_negated(query, m.start(), m.end())`
- Produces: `_PAST_OR_NEGATED_MARKERS`/`_PAST_OR_NEGATED_WINDOW` 删除，替换为 `_NEGATED_PRE_MARKERS`（紧邻药名前）/`_NEGATED_POST_MARKERS`（药名后小窗）/`_NEGATED_POST_WINDOW`。

**现状（已核实）：** 6 字符前置窗口+18 个标记同时「过杀」与「漏杀」——「昨天感冒了，泰诺…」误杀当前用药、「康复后吃康复新液」被药名撞词、「泰诺停了」看不见。与 `safety.py:144-149`（紧邻式）语义分歧（发现 10）。

**设计决策（已与用户确认方向）：保守方向——宁可多查多警告，不漏正在吃的药。** 删除时态标记（昨天/上周/以前/不再…）与健康状态词（康复/痊愈），只保留两类强信号：紧邻药名前的动词否定（不吃/没吃/别吃/停吃/停用/停药/没再吃）+ 药名后小窗内的停药标记（停药/停用/停了/停吃/戒了/戒掉/不吃了/没吃了/没吃）。这使「上周吃泰诺」被保守保留（多警告，安全侧），与铁律 #1 精神一致。

- [ ] **Step 1: 更新既有测试 + 写新测试**

`test_past_tense_mention_skipped` → 改为保守语义（显式行为变更，commit 说明）：

```python
    def test_temporal_mention_kept_conservatively(self, repo, rules):
        """「上周吃泰诺」是时态含糊提及 → 保守保留进检查（宁可多警告，不漏当前用药）。

        旧 6 字符窗口把「昨天感冒了，泰诺…」这类时态词修饰症状而非用药的情况误杀；
        铁律 #1 安全优先：时态标记不再触发跳过。
        """
        _, _, ret = _run(
            "上周吃泰诺，现在吃必理通，有冲突吗",
            _empty_intent(IntentCategory.DRUG_INTERACTION),
            repo,
            rules,
        )
        assert "泰诺" in ret.terms
        assert "必理通" in ret.terms
```

新增测试：

```python
    def test_post_position_stop_marks_dropped(self, repo, rules):
        """后置停药标记（停了/戒了/停药）→ 已停的药不进检查（修发现 4）。"""
        for query in ("泰诺停了", "泰诺我戒了", "泰诺停药了", "已经停用泰诺了"):
            _, _, ret = _run(query, _empty_intent(), repo, rules)
            assert "泰诺" not in ret.terms, query

    def test_adjacent_negation_dropped(self, repo, rules):
        """紧邻药名前的「不吃/没吃」→ 否定语境，跳过。"""
        for query in ("不吃泰诺", "没吃泰诺", "停用泰诺"):
            _, _, ret = _run(query, _empty_intent(), repo, rules)
            assert "泰诺" not in ret.terms, query

    def test_illness_clause_does_not_drop_drug(self, repo, rules):
        """「昨天感冒了，泰诺和必理通能一起吃吗」→ 昨天修饰症状，两药都保留。"""
        _, _, ret = _run(
            "昨天感冒了，泰诺和必理通能一起吃吗",
            _empty_intent(IntentCategory.DRUG_INTERACTION),
            repo,
            rules,
        )
        assert "泰诺" in ret.terms and "必理通" in ret.terms

    def test_marker_collision_with_drug_name_kept(self, rules):
        """「康复后吃康复新液」→ 康复/痊愈 不再是标记，真实药名 康复新液 保留。"""
        r = _repo_with(("康复新液", [("康复新液", 100)]))
        _, _, ret = _run("康复后吃康复新液", _empty_intent(), r, rules)
        assert "康复新液" in ret.terms

    def test_previously_but_still_taking_kept(self, repo, rules):
        """「以前吃泰诺，现在也在吃」→ 现在也在吃，泰诺 保留。"""
        _, _, ret = _run(
            "以前吃泰诺，现在也在吃，能和必理通一起吃吗",
            _empty_intent(IntentCategory.DRUG_INTERACTION),
            repo,
            rules,
        )
        assert "泰诺" in ret.terms
```

- [ ] **Step 2: 跑测试确认失败**
  Run: `pytest tests/test_chat_pipeline.py::TestScanHardening -q` — Expected: 新测试 FAIL，`test_temporal_mention_kept_conservatively` FAIL（当前 泰诺 被跳过）。

- [ ] **Step 3: 实现**

```python
# 否定 / 停药检测（code review 后重写）：只认两类强信号——
# ① 紧邻药名前的动词否定（汉语「动词+宾语」语序：不吃泰诺 / 停用泰诺）；
# ② 药名后小窗内的停药标记（泰诺停了 / 泰诺戒了）。
# 铁律 #1 安全优先：宁可把「上周吃泰诺」这类时态含糊提及保留进检查（多警告），
# 也不漏掉正在吃的药（少警告 = 漏相互作用）。故时态词（昨天/上周/以前…）与
# 健康状态词（康复/痊愈…）一律不作标记——它们常修饰症状而非用药，且会撞药名
# （康复新液）。与 safety.py 的紧邻否定精神一致（那层只管急症拦截，本层只管当前用药）。
_NEGATED_PRE_MARKERS = ("没再吃", "不吃", "没吃", "别吃", "停吃", "停用", "停药")
_NEGATED_POST_MARKERS = (
    "停药", "停用", "停了", "停吃", "戒了", "戒掉", "不吃了", "没吃了", "没吃",
)
_NEGATED_POST_WINDOW = 4
```

```python
def _is_past_or_negated(query: str, start: int, end: int) -> bool:
    """紧邻药名前动词否定 或 药名后小窗内停药标记 → 该提及不表示「现在在吃」。"""
    pre = query[max(0, start - 3):start]  # 最长前标记「没再吃」= 3 字符
    if any(pre.endswith(m) for m in _NEGATED_PRE_MARKERS):
        return True
    post = query[end:end + _NEGATED_POST_WINDOW]
    return any(m in post for m in _NEGATED_POST_MARKERS)
```

调用点（`_scan_brand_names` 内 `for m in alt_re.finditer(query):`）：
```python
        if _is_past_or_negated(query, m.start(), m.end()):
            continue
```

- [ ] **Step 4: 跑测试确认通过**
  Run: `pytest tests/test_chat_pipeline.py -q` — Expected: 全绿。已核对：`test_lifestyle_substances_searched_when_no_drug`（"喝酒要注意什么" 无药名）不受影响；`test_repeated_long_mention_masks_all_occurrences`（"吃过了" 含「吃」但无标记结尾于匹配前）不受影响。

- [ ] **Step 5: 更新 `docs/refactor-readiness.md`** 第 6 条
  把「过去/否定语境窗口过滤（`pipeline._PAST_OR_NEGATED_MARKERS`）」改为「紧邻式否定/停药过滤（`_NEGATED_PRE/POST_MARKERS`，时态标记保守保留，铁律 #1 安全优先）」。

- [ ] **Step 6: 提交**
  ```bash
  git add app/chat/pipeline.py tests/test_chat_pipeline.py docs/refactor-readiness.md
  git commit -m "fix(scan): 否定改紧邻式——只认不吃/停了等强信号，时态与健康词不再误杀当前用药；补后置停药检测"
  ```

---

### Task 7: 引用预算——每药公平 + 整句预留 + 提前终止

**Files:**
- Modify: `app/chat/pipeline.py:105-108, 266-296`（常量 + `_retrieve_citations`）
- Modify: `tests/test_chat_pipeline.py`（新增饥饿/提前终止测试，核对 `test_citations_capped`）

**Interfaces:**
- Consumes: `_retrieve_citations(retriever, query, intent, effective_drug_names)`（签名不变）
- Produces: 预算语义——`drug_pool = _CITATIONS_MAX - _QUERY_SEARCH_RESERVED` 分给各药（每药至少 1 条），整句检索预留份额保证结果永不丢弃；总量满即停止后续检索。

**现状（已核实）：** `_CITATIONS_MAX=15` 全给第一个药（3 药查询第 3 个药 0 引用）；cap 满后剩余 term 与整句搜索照跑、结果全丢弃（发现 5/14）；pgvector 下每 term 一次 embedding（发现 11，本轮以提前终止缓解，真批量化改 Retriever 接口超出范围）。

- [ ] **Step 1: 写失败测试**（追加到 `TestRetrievalAndFindings`）

```python
    def test_citation_budget_fair_across_drugs(self, repo, rules):
        """多药查询每药都有引用份额（不再第一个药吃满、后面的饿死）。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INTERACTION,
            confidence=0.9,
            drug_names=["泰诺", "必理通"],
        )
        result, _, ret = _run(
            "泰诺和必理通能一起吃吗",
            intent,
            repo,
            rules,
            canned={"泰诺": _cites("泰诺", 12), "必理通": _cites("必理通", 12)},
        )
        by_brand = {c.brand_name for c in result.citations}
        assert "泰诺" in by_brand and "必理通" in by_brand
        assert len(result.citations) <= 15

    def test_search_stops_when_budget_filled(self, repo, rules):
        """预算满后不再发起多余检索（修发现 14 的浪费 I/O）。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INFO, confidence=0.9, drug_names=["泰诺"]
        )
        _, _, ret = _run(
            "泰诺一天最多吃几次",
            intent,
            repo,
            rules,
            canned={"泰诺": _cites("泰诺", 20)},
        )
        # 药名检索把预算填满 → 整句检索不再发起（FakeRetriever 无视 limit 的过填充场景）
        assert ret.terms == ["泰诺"]
```

- [ ] **Step 2: 跑测试确认失败**
  Run: `pytest tests/test_chat_pipeline.py::TestRetrievalAndFindings -q` — Expected: `test_search_stops_when_budget_filled` FAIL（当前整句检索总发起）；`test_citation_budget_fair_across_drugs` FAIL（当前第一个药吃满 12）。

- [ ] **Step 3: 实现**

```python
# ── 检索预算（端到端 < 1s 设计目标：prompt 体量必须封顶）────────
_BRAND_TERM_LIMIT = 12  # 单个药名的章节上限
_QUERY_SEARCH_LIMIT = 5  # 整句检索单次上限
_QUERY_SEARCH_RESERVED = 5  # 整句检索预留份额（结果永不丢弃）
_CITATIONS_MAX = 15  # 注入 prompt 的引用总量上限
```

```python
def _retrieve_citations(
    retriever: Retriever,
    query: str,
    intent: IntentResult,
    effective_drug_names: list[str],
) -> list[Citation]:
    """按名检索 ∪ 整句检索，去重合并、总量封顶、每药公平。

    预算分配（code review 修复）：先给整句检索预留 _QUERY_SEARCH_RESERVED
    份额（结果永不丢弃），剩余 drug_pool 在药名间均分，每药至少 1 条——多药
    查询不再第一个药吃满、后面的药 0 引用。总量满即停止后续检索（不再浪费
    SQL 往返 / pgvector embedding）。

    整句检索始终参与：只要预算还有空间就发起（保住非品牌词召回与 pgvector
    语义路径）；药名检索在 FakeRetriever 这类无视 limit 的实现下把预算填满时
    才跳过（避免纯浪费）。
    """
    terms = list(effective_drug_names)
    if intent.intent is IntentCategory.LIFESTYLE_INTERACTION:
        terms = _dedup_stripped((*terms, *intent.lifestyle_substances))
    drug_pool = _CITATIONS_MAX - _QUERY_SEARCH_RESERVED
    per_drug = (
        max(1, min(_BRAND_TERM_LIMIT, drug_pool // len(terms))) if terms else 0
    )
    merged: list[Citation] = []
    seen: set[tuple[str, str, str]] = set()

    def add(citations: list[Citation]) -> None:
        for c in citations:
            if len(merged) >= _CITATIONS_MAX:
                return
            key = (c.brand_name, c.section, c.excerpt)
            if key not in seen:
                seen.add(key)
                merged.append(c)

    for term in terms:
        if len(merged) >= drug_pool:
            break
        add(retriever.search(term, limit=per_drug))
    if len(merged) < _CITATIONS_MAX:
        add(retriever.search(query, limit=_QUERY_SEARCH_LIMIT))
    return merged
```

- [ ] **Step 4: 跑测试确认通过**
  Run: `pytest tests/test_chat_pipeline.py -q` — Expected: 全绿。已核对：`test_citations_capped`（1 药 + 无视 limit 的 fake 过填充 → add 在 15 封顶，`len==15` 保持）；`test_whole_query_always_searched_with_terms`（预算有空间 → 整句照常发起，terms 断言保持）；`test_lifestyle_substances_searched_when_no_drug`（terms 只有酒精 → per_drug=min(12,10)=10，不受影响）。

- [ ] **Step 5: 提交**
  ```bash
  git add app/chat/pipeline.py tests/test_chat_pipeline.py
  git commit -m "fix(retrieval): 引用预算每药公平分配 + 整句预留永不丢弃 + 预算满即停"
  ```

---

### Task 8: 检查结论通道分离 + has_findings 单一来源

**Files:**
- Modify: `app/prompts/formatters.py`（`format_check_report_for_prompt` 去掉 `ambiguities` 参数；新增 `report_has_findings`）
- Modify: `app/prompts/chat.py:26-59`（`build_system_prompt`/`build_chat_messages` 加 `ambiguity_note` 参数）
- Modify: `app/prompts/templates/chat_system.py`（新增 `AMBIGUITY_SECTION_HEADER`）
- Modify: `app/chat/pipeline.py:336-372`（两分支 + has_findings）
- Modify: `tests/test_prompts_golden.py` + `tests/golden/`（删 `report_ambiguous.txt`，增 `chat_system_with_ambiguity_note.txt` 等）
- Modify: `tests/test_chat_pipeline.py`（更新 `test_ambiguous_core_resolution_disclosed_for_interaction`）
- Modify: `docs/refactor-readiness.md`（golden 覆盖声明）

**Interfaces:**
- Consumes: `format_ambiguity_note(ambiguities)`（保留）；`report_has_findings(report) -> bool`（新增）
- Produces: `format_check_report_for_prompt(report: CheckReport)` 不再接收 `ambiguities`；`build_system_prompt(citations=None, check_context=None, ambiguity_note=None)`。系统 prompt 组装顺序：RAG 上下文 → 近似匹配提示（中立标题，无「确定性规则引擎」头、无「不能改写」要求）→ 检查结论（确定性头 + relay 要求）。

**现状（已核实）：** 非检查意图的 `elif ambiguous:` 把 `format_ambiguity_note` 塞进 check_context，被 `build_system_prompt` 用「## 检查结果（来自确定性规则引擎）」+「绝对不能自行判断/否定/改写」包装——伪造规则引擎来源（发现 6），且 `has_findings=True` 压制了零引用回答的无引用注记（发现 7）；`has_findings` 布尔表达式手工镜像 formatter 渲染条件（发现 12）。

**设计决策：** 启发式披露（近似匹配/未收录）一律走独立 `ambiguity_note` 槽位，永不进「确定性规则引擎」通道；`has_findings` 收敛到 `report_has_findings(report)`（四个确定性条件，不含近似匹配）。

- [ ] **Step 1: 改 formatters.py**

```python
def format_check_report_for_prompt(report: CheckReport) -> str:
    """把 CheckReport 渲染为系统提示内的检查结论（确定性内容，铁律 #1）。

    只含确定性结论（触发规则 / 叠加警告 / 共享成分 / 未收录）；近似匹配披露
    由调用方经 format_ambiguity_note 走独立提示槽位，不混入本段
    （code review 修复：启发式披露不得冒充规则引擎结论）。
    """
    lines: list[str] = []
    if report.unresolved_drugs:
        lines.append(
            "以下药品暂未收录，无法检测其成分与相互作用："
            + "、".join(report.unresolved_drugs)
            + "。请在回答中明确告知用户这些药暂时查不到，建议咨询药师。"
        )
    if report.triggered_rules:
        lines.append("规则引擎检测到以下风险（确定性结论，必须原样传达，不得否定或改写）：")
        for rule in report.triggered_rules:
            lines.append(f"- 【{rule.severity}｜{rule.title}】{rule.warning}")
    if report.overlap.warnings:
        lines.append("成分叠加超限警告（代码计算，必须传达）：")
        for warning in report.overlap.warnings:
            lines.append(f"- {warning}")
    shared = [t for t in report.overlap.overlapping if len(t.sources) >= 2]
    if shared:
        lines.append("被多种药品共享的成分（叠加来源）：")
        for t in shared:
            lines.append(
                f"- {t.name}：来自 {'、'.join(t.sources)}，"
                f"每日合计约 {t.total_amount_mg}mg"
            )
    if not lines:
        return "规则引擎未检测到成分叠加或已知相互作用。请如实告知用户目前未检测到风险，但仍提醒按说明书用量服用。"
    return "\n".join(lines)


def report_has_findings(report: CheckReport) -> bool:
    """format_check_report_for_prompt 是否渲染了确定性结论段（单一事实来源）。

    pipeline 的 has_findings 必须调用本函数，禁止在别处复制渲染条件
    （code review 修复：布尔镜像会随 formatter 加分支静默漂移）。
    近似匹配（ambiguities）不算发现——它只是核名提示，不压制无引用注记（铁律 #2）。
    """
    return bool(
        report.triggered_rules
        or report.overlap.warnings
        or report.unresolved_drugs
        or any(len(t.sources) >= 2 for t in report.overlap.overlapping)
    )
```

（删掉 `ambiguities` 分支与 `_ambiguity_lines` 的报告中调用；`_ambiguity_lines` 仅保留给 `format_ambiguity_note` 使用。）

- [ ] **Step 2: 改 prompt 层**

`templates/chat_system.py` 新增：
```python
AMBIGUITY_SECTION_HEADER = "\n\n## 需要向用户确认的近似匹配\n\n"
```

`chat.py`：
```python
def build_system_prompt(
    citations: list[Citation] | None = None,
    check_context: str | None = None,
    ambiguity_note: str | None = None,
) -> str:
    """构造完整的 system prompt：角色 + 规则 + RAG 上下文 +（可选）检查结论 +（可选）近似匹配提示。

    check_context 非 None 时追加规则引擎结论槽位（CHECK_SECTION_HEADER +
    CHECK_RELAY_REQUIREMENTS，铁律 #1：只翻译、不改写）。
    ambiguity_note 非 None 时追加独立近似匹配提示槽位（中立标题，无「确定性」
    头、无「不能改写」要求）——它只是核名披露（铁律 #4），不是规则引擎结论
    （code review 修复：启发式披露不得伪装成确定性结论）。
    """
    rag_context = format_citations_for_prompt(citations or [])
    prompt = _SYSTEM_ROLE_AND_RULES + RAG_SECTION_HEADER + rag_context
    if ambiguity_note:
        prompt += AMBIGUITY_SECTION_HEADER + ambiguity_note
    if check_context:
        prompt += CHECK_SECTION_HEADER + check_context + CHECK_RELAY_REQUIREMENTS
    return prompt
```

`build_chat_messages` 加 `ambiguity_note: str | None = None` 透传（`system = build_system_prompt(citations, check_context=check_context, ambiguity_note=ambiguity_note)`）。

- [ ] **Step 3: 改 pipeline**

```python
    # 4. 检查意图（药-药 / 药-物质相互作用）→ 确定性规则引擎检测
    check_context: str | None = None
    ambiguity_note: str | None = None
    has_findings = False
    if intent.intent in (
        IntentCategory.DRUG_INTERACTION,
        IntentCategory.LIFESTYLE_INTERACTION,
    ):
        items = [
            MedboxItem(drug_id=idx + 1, brand_name=name)
            for idx, name in enumerate(effective)
        ]
        report = check_medbox(
            Medbox(items=items),
            rules,
            drug_repo,
            intent.lifestyle_substances or None,
        )
        check_context = format_check_report_for_prompt(report)
        # 近似匹配披露走独立提示槽位，不冒充「确定性规则引擎」结论（铁律 #4）
        ambiguity_note = format_ambiguity_note(ambiguous) if ambiguous else None
        # 单一事实来源：与 formatter 渲染条件由 report_has_findings 统一
        has_findings = report_has_findings(report)
    elif ambiguous:
        # 非检查意图：未跑规则引擎，近似匹配只能作为独立披露（铁律 #4），
        # 且不得压制无引用注记（铁律 #2，code review 修复：披露不是发现）。
        ambiguity_note = format_ambiguity_note(ambiguous)

    # 5. 构造含 RAG + 冲突结论的 messages 并调用 LLM
    messages = build_chat_messages(
        query,
        citations,
        check_context=check_context,
        ambiguity_note=ambiguity_note,
    )
```

import 增补：`from app.prompts.formatters import format_ambiguity_note, format_check_report_for_prompt, report_has_findings`。

- [ ] **Step 4: 更新 golden 测试**
  - **删除** `tests/golden/report_ambiguous.txt` 与 `test_ambiguous_matches`/`test_ambiguity_note_matches_report_block`（formatter 不再渲染 ambiguity 块，等式断言失去对象）。
  - **新增** `test_ambiguity_note_section`：

```python
    def test_ambiguity_note_section(self):
        """近似匹配提示走独立中立槽位：RAG 之后、检查结论之前，无「确定性」头。"""
        from app.prompts.chat import build_system_prompt
        from app.prompts.formatters import format_ambiguity_note

        prompt = build_system_prompt(
            _citations(),
            ambiguity_note=format_ambiguity_note([("扶他林", "扶他林_外用")]),
        )
        _assert_golden("chat_system_with_ambiguity_note.txt", prompt)
  ```
  - **新增** 组合顺序 golden：`format_check_report_for_prompt(_combo_report())` 已由 `report_combo.txt` 锁定；补一个「check + ambiguity_note 同时存在」的完整 system prompt golden（`chat_system_with_check_and_ambiguity.txt`，组装顺序 RAG→近似匹配→检查）。
  - 重新生成：
    ```powershell
    $env:PILLCLEAR_REGEN_GOLDEN=1; python -m pytest tests/test_prompts_golden.py; Remove-Item env:PILLCLEAR_REGEN_GOLDEN
    ```
    审核生成的 golden 文案（尤其 `chat_system_with_check.txt` 因 formatter 去掉 ambiguity 分支可能变化——现有用例不传 ambiguities 则不变；已核对 `test_ambiguous_matches` 与 `report_ambiguous.txt` 属删除项）。

- [ ] **Step 5: 更新 pipeline 测试**
  - `test_ambiguous_core_resolution_disclosed_for_interaction`（392-406）：该交互报告无任何确定性发现（双氯芬酸+对乙酰氨基酚不共享/不触发），`report_has_findings=False` + `answer_citations=[]` → **无引用注记现在正确追加**（铁律 #2）。改断言：
    ```python
    assert "近似匹配" in prompt
    assert "扶他林_外用" in prompt
    assert "核对" in prompt
    # 近似匹配是披露不是发现（code review 修复）：零引用时无引用注记必须追加（铁律 #2）
    assert "查阅原药品说明书" in result.answer
    ```
  - `test_annotation_core_match_and_disclosure`（265-279）：DRUG_INFO + 披露，prompt 断言「近似匹配/扶他林_外用/核对」经 `ambiguity_note` 槽位仍成立，不改。

- [ ] **Step 6: 更新 `docs/refactor-readiness.md`** golden 覆盖声明（第 20 行「全七分支…组合报告渲染顺序」）改为：formatter 五段确定性渲染 + 独立近似匹配槽位（新增 golden 覆盖）。

- [ ] **Step 7: 提交**
  ```bash
  git add app/prompts/ tests/golden/ app/chat/pipeline.py tests/test_prompts_golden.py tests/test_chat_pipeline.py docs/refactor-readiness.md
  git commit -m "fix(prompt): 近似匹配披露移出『确定性规则引擎』通道——独立中立槽位；has_findings 收敛单一来源，零引用注记不再被披露压制"
  ```

---

### Task 9: 全量回归 + 文档收尾

**Files:**
- Verify: 全量 `pytest`
- Modify: `docs/refactor-readiness.md`（第 6 条扫描语义 + 否定语义 + golden 覆盖声明，若 T4/T5/T6/T8 未覆盖到的残留表述）
- Archive: 本计划 → `docs/superpowers/plans/2026-07-31-chat-pipeline-determinism-fixes.md`

**Interfaces:** 无新接口。

- [ ] **Step 1: 全量测试**
  Run: `pytest` — Expected: 全绿（基线 142 + 新增）。任一变红先定位：是既有测试锁了旧行为 → 按本计划各任务声明更新并 commit 说明；是真正回归 → 修复后再继续。

- [ ] **Step 2: golden 复核**
  Run: `pytest tests/test_prompts_golden.py -q` — Expected: PASS。核对 `tests/golden/` 最终文件清单与 `docs/refactor-readiness.md` 声称一致（无 `report_ambiguous.txt`，有新增 `chat_system_with_ambiguity_note.txt` 等）。

- [ ] **Step 3: 更新 `docs/refactor-readiness.md`**
  - 第 6 条：扫描语义 = 裸名歧义降级 + LLM∪扫描并集 + 紧邻式否定（引用本计划 commit）。
  - 补一条「已知盲区」：无分词器下「泰诺林里的泰诺」子串误命中仍不可消除（LLM 正常路径不受影响）。
  - 检查「待办」区无遗留。

- [ ] **Step 4: 归档计划**
  ```bash
  git add docs/refactor-readiness.md
  git commit -m "docs: refactor-readiness 同步扫描/否定/golden 语义（chat 流水线确定性修复收尾）"
  ```
  将本计划内容复制为 `docs/superpowers/plans/2026-07-31-chat-pipeline-determinism-fixes.md` 一并提交。

## 验证方式（端到端）

1. **全量单测**：`pytest`（无网络、无落盘，基线 142 + 新增全部通过）。
2. **golden 重生成纪律**：任何 prompt/文案改动只经 `PILLCLEAR_REGEN_GOLDEN=1` 重生成并逐字审核 diff 后 commit。
3. **行为回归**：`tests/test_chat_pipeline.py` 针对五类查询断言 `FakeRetriever.terms` 与 prompt 内容——验证「泰诺和必理通能一起吃吗」两药都进检查、「泰诺停药了」不进、「昨天感冒了…」两药保留、近似匹配走独立槽位、零引用注记不被披露压制。
4. **架构不变**：不改 `Retriever` 接口、不改 `app/core/safety.py`、不引入 embedding/新依赖；pgvector 仍是可选部署路径。

## Execution Handoff

计划完成。两种执行方式：

**1. Subagent-Driven（推荐）**——每任务派独立 subagent 实现，任务间两段式审查，快速迭代。

**2. Inline Execution**——本会话用 executing-plans 批量执行，带检查点。

选哪种？（T1→T9 顺序执行；T4/T5/T6/T8 有测试断言依赖，不宜并行。）

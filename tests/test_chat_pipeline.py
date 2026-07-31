"""app/chat/pipeline.py 编排层单测：确定性商品名扫描兜底（引用掉 0 加固）。

直接调 process_chat（纯函数），全 fake、无 HTTP、无真实 DB、无 respx。
FakeLLM 按目标 schema 分发预置对象，便于精确断言「扫描不增加 LLM 调用」。

扫描语义（code review 修复后定型）：
- 扫描无条件运行，与 LLM 抽取结果取并集去重；LLM 裸名经近似匹配规范映射
  收敛到存储名（扶他林→扶他林_外用），同一药不以「用户原文 + 存储名」双形态进检查；
- 最左优先、同位最长优先、不重叠、覆盖所有出现位置；
- 紧邻否定/停药语境（「不吃/停了…」）里的提及不参与检测；时态含糊提及保守保留；
- 核名解析到带注解存储名（扶他林→扶他林_外用）属近似匹配，必须在 prompt 披露；
- 整句检索始终参与（非品牌词召回 + pgvector 语义路径），引用总量封顶。
"""

from __future__ import annotations

import pytest

from app.api.schemas import LLMAnswer
from app.chat.pipeline import process_chat
from app.knowledge.repository import InMemoryDrugRepository
from app.knowledge.schemas import Citation, DrugRecord, Ingredient
from app.prompts.intent import IntentCategory, IntentResult
from app.prompts.safety import SafetyLLMResult
from app.rules.engine import DEFAULT_RULES_DIR, load_rules


# ── fakes ───────────────────────────────────────────────────


class FakeLLM:
    """complete_json 按目标 schema 返回预置对象，并计数调用次数。

    safety 补漏在关键词放行后调用一次（schema=SafetyLLMResult），故非拦截
    请求的调用顺序固定为 safety → intent → answer = 3 次。
    回答阶段的 messages 被记录到 answer_messages，供 prompt 内容断言。
    """

    def __init__(self, intent: IntentResult, answer: LLMAnswer) -> None:
        self._intent = intent
        self._answer = answer
        self._safety = SafetyLLMResult(category="none", confidence=0.1)
        self.calls = 0
        self.answer_messages: list[dict] | None = None

    def complete_json(self, messages, schema, **kwargs):  # noqa: ARG002
        self.calls += 1
        if schema is SafetyLLMResult:
            return self._safety
        if schema is IntentResult:
            return self._intent
        if schema is LLMAnswer:
            self.answer_messages = messages
            return self._answer
        raise AssertionError(f"unexpected schema: {schema}")


class FakeRetriever:
    """记录每次检索词，按 canned 返回引用。"""

    def __init__(self, canned: dict[str, list[Citation]] | None = None) -> None:
        self.canned = canned or {}
        self.terms: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[Citation]:  # noqa: ARG002
        self.terms.append(query)
        return list(self.canned.get(query, []))


class RaisingRepo:
    """list_drugs 抛异常：模拟仓储故障（降级路径，不得阻断 /chat）。"""

    def list_drugs(self):
        raise RuntimeError("db gone")

    def get_drug_by_brand(self, brand_name: str):
        return None


class BadRowsRepo:
    """brand_name 非字符串：模拟脏目录行（降级路径，不得阻断 /chat）。"""

    def list_drugs(self):
        return [{"brand_name": 123}]

    def get_drug_by_brand(self, brand_name: str):
        return None


def _cite(brand: str) -> Citation:
    return Citation(brand_name=brand, section="用法用量", excerpt=f"{brand} 原文摘录")


def _cites(brand: str, n: int) -> list[Citation]:
    """n 条互不重复的引用（不同章节/摘录，避免去重合并折叠）。"""
    return [
        Citation(brand_name=brand, section=f"章节{i}", excerpt=f"{brand} 摘录{i}")
        for i in range(n)
    ]


def _system_prompt(llm: FakeLLM) -> str:
    assert llm.answer_messages is not None
    return llm.answer_messages[0]["content"]


# ── 种子仓储 / 规则 ─────────────────────────────────────────


@pytest.fixture
def repo() -> InMemoryDrugRepository:
    r = InMemoryDrugRepository()
    r.upsert_drug(
        DrugRecord(
            brand_name="泰诺",
            ingredients=[Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")],
        )
    )
    r.upsert_drug(
        DrugRecord(
            brand_name="必理通",
            ingredients=[Ingredient(name="对乙酰氨基酚", amount=500, unit="mg")],
        )
    )
    r.upsert_drug(
        DrugRecord(
            brand_name="扶他林_外用",
            ingredients=[Ingredient(name="双氯芬酸", amount=10, unit="mg")],
        )
    )
    r.upsert_drug(
        DrugRecord(
            brand_name="三九感冒灵",
            ingredients=[Ingredient(name="对乙酰氨基酚", amount=200, unit="mg")],
        )
    )
    r.upsert_drug(
        DrugRecord(
            brand_name="感冒灵",
            ingredients=[Ingredient(name="对乙酰氨基酚", amount=200, unit="mg")],
        )
    )
    return r


@pytest.fixture
def rules():
    return load_rules(DEFAULT_RULES_DIR)


def _repo_with(*drugs: tuple[str, list[tuple[str, float]]]) -> InMemoryDrugRepository:
    """按 (商品名, [(成分, mg)]) 快速构造仓储。"""
    r = InMemoryDrugRepository()
    for brand, ings in drugs:
        r.upsert_drug(
            DrugRecord(
                brand_name=brand,
                ingredients=[
                    Ingredient(name=n, amount=a, unit="mg") for n, a in ings
                ],
            )
        )
    return r


def _run(query, intent, repo, rules, canned=None, answer_citations=None):
    llm = FakeLLM(
        intent=intent,
        answer=LLMAnswer(
            answer="回答正文。",
            confidence=0.85,
            citations_used=answer_citations or [],
        ),
    )
    retriever = FakeRetriever(canned)
    result = process_chat(query, llm, retriever, rules, repo)
    return result, llm, retriever


def _empty_intent(category=IntentCategory.DRUG_INFO) -> IntentResult:
    """LLM 意图分类失手（空药名）——触发扫描兜底的降级模式。"""
    return IntentResult(intent=category, confidence=0.0, drug_names=[])


# ── 扫描兜底：基础语义 ──────────────────────────────────────


class TestBrandScan:
    def test_scan_rescues_citations_when_intent_empty(self, repo, rules):
        """LLM 意图空名，但 query 含种子品牌 → 扫描兜底，引用非空。"""
        result, llm, ret = _run(
            "泰诺一天最多吃几次",
            _empty_intent(),
            repo,
            rules,
            canned={"泰诺": [_cite("泰诺")]},
        )
        assert result.blocked is False
        # 按名检索之后整句检索始终参与（去重后本例无额外命中）
        assert ret.terms == ["泰诺", "泰诺一天最多吃几次"]
        assert [c.brand_name for c in result.citations] == ["泰诺"]
        assert llm.calls == 3  # safety 补漏 + intent + answer，扫描零额外调用

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

    def test_nested_brand_longest_match(self, repo, rules):
        """三九感冒灵 套住 感冒灵 → 只收最长，不二次命中。"""
        _, _, ret = _run(
            "三九感冒灵怎么吃",
            _empty_intent(),
            repo,
            rules,
            canned={
                "三九感冒灵": [_cite("三九感冒灵")],
                "感冒灵": [_cite("感冒灵")],
            },
        )
        assert ret.terms == ["三九感冒灵", "三九感冒灵怎么吃"]
        assert "感冒灵" not in ret.terms

    def test_repeated_long_mention_masks_all_occurrences(self, repo, rules):
        """长名重复出现时每次出现都要吃掉内嵌短名（不止第一次）。"""
        _, _, ret = _run(
            "三九感冒灵吃过了，还能再吃三九感冒灵和泰诺吗",
            _empty_intent(),
            repo,
            rules,
        )
        assert ret.terms == [
            "三九感冒灵",
            "泰诺",
            "三九感冒灵吃过了，还能再吃三九感冒灵和泰诺吗",
        ]
        # 第二个 三九感冒灵 里的 感冒灵 也不得独立命中（否则叠加计数翻倍）
        assert "感冒灵" not in ret.terms

    def test_non_overlapping_shorter_still_matched(self, repo, rules):
        """感冒灵 与 泰诺 不重叠 → 都收。"""
        _, _, ret = _run(
            "感冒灵和泰诺",
            _empty_intent(),
            repo,
            rules,
            canned={"感冒灵": [_cite("感冒灵")], "泰诺": [_cite("泰诺")]},
        )
        assert set(ret.terms) == {"感冒灵", "泰诺", "感冒灵和泰诺"}

    def test_annotation_core_match_and_disclosure(self, repo, rules):
        """扶他林_外用 可被核名「扶他林」命中；近似匹配必须在 prompt 披露。"""
        _, llm, ret = _run(
            "扶他林能外用吗",
            _empty_intent(),
            repo,
            rules,
            canned={"扶他林_外用": [_cite("扶他林_外用")]},
        )
        assert ret.terms == ["扶他林_外用", "扶他林能外用吗"]
        # 铁律 #4：核名→注解品是近似匹配，prompt 必须要求 LLM 提示核对
        prompt = _system_prompt(llm)
        assert "近似匹配" in prompt
        assert "扶他林_外用" in prompt
        assert "核对" in prompt

    def test_annotation_word_not_a_false_positive(self, repo, rules):
        """注解词「外用」本身不作匹配模式 → 不误命中 扶他林_外用。"""
        result, _, ret = _run("这个外用药膏怎么用", _empty_intent(), repo, rules)
        assert ret.terms == ["这个外用药膏怎么用"]  # 无品牌 → 整句检索
        assert result.citations == []

    def test_no_brand_falls_back_to_whole_query(self, repo, rules):
        """query 不含任何品牌 → 整句检索（单次）。"""
        _, _, ret = _run("感冒了多喝水行吗", _empty_intent(), repo, rules)
        assert ret.terms == ["感冒了多喝水行吗"]

    def test_lifestyle_substances_searched_when_no_drug(self, repo, rules):
        """lifestyle 意图无药名时，substances 仍被检索（回归保护）。"""
        intent = IntentResult(
            intent=IntentCategory.LIFESTYLE_INTERACTION,
            confidence=0.9,
            drug_names=[],
            lifestyle_substances=["酒精"],
        )
        _, _, ret = _run(
            "喝酒要注意什么",
            intent,
            repo,
            rules,
            canned={"酒精": [_cite("酒精")]},
        )
        assert ret.terms == ["酒精", "喝酒要注意什么"]

    def test_interaction_empty_llm_names_runs_check_on_scanned(self, repo, rules):
        """interaction 意图 + LLM 空名 + query 两品牌 → 规则引擎对扫描名跑起来。

        间接证明：answer 自报 citations_used 为空，但因 has_findings，
        「查阅说明书」注记被抑制——即 check_medbox 确实收到了扫描出的两个名字。
        """
        result, llm, ret = _run(
            "泰诺和必理通能一起吃吗",
            _empty_intent(IntentCategory.DRUG_INTERACTION),
            repo,
            rules,
            canned={"泰诺": [_cite("泰诺")], "必理通": [_cite("必理通")]},
            answer_citations=[],
        )
        assert set(ret.terms) == {"泰诺", "必理通", "泰诺和必理通能一起吃吗"}
        assert "查阅原药品说明书" not in result.answer
        assert llm.calls == 3


# ── 扫描兜底：硬化（code review #1/#2/#5/#6/#11/#12）─────────


class TestScanHardening:
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

    def test_scan_exception_degrades_not_raises(self, rules):
        """list_drugs 抛异常 → 降级为空名单，/chat 不 500（docstring 承诺的 invariant）。"""
        result, llm, ret = _run(
            "泰诺一天最多吃几次",
            _empty_intent(),
            RaisingRepo(),
            rules,
        )
        assert result.blocked is False
        assert ret.terms == ["泰诺一天最多吃几次"]
        assert llm.calls == 3

    def test_non_string_brand_row_degrades_not_raises(self, rules):
        """目录行 brand_name 非字符串 → 扫描内部异常也被降级吞掉，不阻断。"""
        result, _, ret = _run(
            "泰诺一天最多吃几次",
            _empty_intent(),
            BadRowsRepo(),
            rules,
        )
        assert result.blocked is False
        assert ret.terms == ["泰诺一天最多吃几次"]

    def test_equal_length_pattern_leftmost_wins(self, rules):
        """等长模式按文本最左位置裁决，而非入库（id）顺序。"""
        # 加黑片 先入库（id 小）；query 里最左的是 白加黑
        r = _repo_with(
            ("加黑片", [("对乙酰氨基酚", 325)]),
            ("白加黑", [("对乙酰氨基酚", 325)]),
        )
        _, _, ret = _run("白加黑片怎么吃", _empty_intent(), r, rules)
        assert ret.terms == ["白加黑", "白加黑片怎么吃"]
        assert "加黑片" not in ret.terms

    def test_shared_core_between_siblings_not_scannable(self, rules):
        """同一核名指向多个存储品（扶他林_外用 / 扶他林_口服）→ 核名不作模式。

        歧义核名的召回不得依赖入库顺序：宁可漏配（走整句检索 + 未收录路径），
        也不得静默命中其中一个剂型。
        """
        r = _repo_with(
            ("扶他林_外用", [("双氯芬酸", 10)]),
            ("扶他林_口服", [("双氯芬酸", 25)]),
        )
        _, _, ret = _run("扶他林空腹吃伤胃吗", _empty_intent(), r, rules)
        assert "扶他林_外用" not in ret.terms
        assert "扶他林_口服" not in ret.terms
        assert ret.terms == ["扶他林空腹吃伤胃吗"]

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

    def test_ambiguous_core_resolution_disclosed_for_interaction(self, repo, rules):
        """interaction 下核名解析到注解品 → prompt 同时带检查结论与近似匹配披露。"""
        result, llm, _ = _run(
            "扶他林和必理通能一起吃吗",
            _empty_intent(IntentCategory.DRUG_INTERACTION),
            repo,
            rules,
            answer_citations=[],
        )
        prompt = _system_prompt(llm)
        assert "近似匹配" in prompt
        assert "扶他林_外用" in prompt
        assert "核对" in prompt
        # 近似匹配披露本身就是确定性发现 → 抑制「查阅说明书」注记
        assert "查阅原药品说明书" not in result.answer


# ── 检索策略与 has_findings（code review #4/#7/#14）──────────


class TestRetrievalAndFindings:
    def test_whole_query_always_searched_with_terms(self, repo, rules):
        """有药名时也保留整句检索：非品牌词召回 + pgvector 语义路径不丢。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INFO, confidence=0.9, drug_names=["泰诺"]
        )
        whole = Citation(brand_name="泰诺", section="注意事项", excerpt="发热患者慎用。")
        result, _, ret = _run(
            "泰诺一天最多吃几次",
            intent,
            repo,
            rules,
            canned={"泰诺": [_cite("泰诺")], "泰诺一天最多吃几次": [whole]},
        )
        assert ret.terms == ["泰诺", "泰诺一天最多吃几次"]
        assert result.citations == [_cite("泰诺"), whole]

    def test_dedup_between_brand_and_query_search(self, repo, rules):
        """按名与整句检索命中同一条引用 → 去重后只出现一次。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INFO, confidence=0.9, drug_names=["泰诺"]
        )
        same = _cite("泰诺")
        result, _, _ = _run(
            "泰诺怎么吃",
            intent,
            repo,
            rules,
            canned={"泰诺": [same], "泰诺怎么吃": [same]},
        )
        assert result.citations == [same]

    def test_citations_capped(self, repo, rules):
        """注入 prompt 的引用总量封顶（压低 token / 延迟）。"""
        result, _, _ = _run(
            "泰诺一天最多吃几次",
            _empty_intent(),
            repo,
            rules,
            canned={"泰诺": _cites("泰诺", 20)},
        )
        assert len(result.citations) == 15

    def test_shared_ingredient_without_warnings_counts_as_findings(self, rules):
        """共享成分（sources≥2）即使无超限警告、无触发规则，也算确定性发现。

        formatter 会渲染共享成分段，has_findings 必须与之对齐，
        否则「没有引用说明书原文」注记会跟在已传达的确定性结论后面自相矛盾。
        """
        r = _repo_with(
            ("复方感冒片", [("马来酸氯苯那敏", 2)]),
            ("鼻炎康片", [("马来酸氯苯那敏", 1)]),
        )
        intent = IntentResult(
            intent=IntentCategory.DRUG_INTERACTION,
            confidence=0.9,
            drug_names=["复方感冒片", "鼻炎康片"],
        )
        result, _, _ = _run(
            "复方感冒片和鼻炎康片能一起吃吗",
            intent,
            r,
            rules,
            answer_citations=[],
        )
        assert "查阅原药品说明书" not in result.answer

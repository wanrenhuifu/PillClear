"""app/chat/pipeline.py 编排层单测：确定性商品名扫描兜底（引用掉 0 加固）。

直接调 process_chat（纯函数），全 fake、无 HTTP、无真实 DB、无 respx。
FakeLLM 按目标 schema 分发预置对象，便于精确断言「扫描不增加 LLM 调用」。
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
    """

    def __init__(self, intent: IntentResult, answer: LLMAnswer) -> None:
        self._intent = intent
        self._answer = answer
        self._safety = SafetyLLMResult(category="none", confidence=0.1)
        self.calls = 0

    def complete_json(self, messages, schema, **kwargs):  # noqa: ARG002
        self.calls += 1
        if schema is SafetyLLMResult:
            return self._safety
        if schema is IntentResult:
            return self._intent
        if schema is LLMAnswer:
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


def _cite(brand: str) -> Citation:
    return Citation(brand_name=brand, section="用法用量", excerpt=f"{brand} 原文摘录")


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


# ── 用例 ────────────────────────────────────────────────────


class TestBrandScan:
    def test_scan_rescues_citations_when_intent_empty(self, repo, rules):
        """LLM 意图空名，但 query 含种子品牌 → 扫描兜底，引用非空。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INFO, confidence=0.0, drug_names=[]
        )
        result, llm, ret = _run(
            "泰诺一天最多吃几次",
            intent,
            repo,
            rules,
            canned={"泰诺": [_cite("泰诺")]},
        )
        assert result.blocked is False
        assert ret.terms == ["泰诺"]
        assert [c.brand_name for c in result.citations] == ["泰诺"]
        assert llm.calls == 3  # safety 补漏 + intent + answer，扫描零额外调用

    def test_union_of_llm_and_scan(self, repo, rules):
        """LLM 只抽到泰诺，扫描补出必理通 → 并集去重，二者都检索。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INTERACTION,
            confidence=0.9,
            drug_names=["泰诺"],
        )
        result, llm, ret = _run(
            "泰诺和必理通能一起吃吗",
            intent,
            repo,
            rules,
            canned={"泰诺": [_cite("泰诺")], "必理通": [_cite("必理通")]},
        )
        assert ret.terms == ["泰诺", "必理通"]
        assert {c.brand_name for c in result.citations} == {"泰诺", "必理通"}
        assert llm.calls == 3

    def test_nested_brand_longest_match(self, repo, rules):
        """三九感冒灵 套住 感冒灵 → 只收最长，不二次命中。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INFO, confidence=0.9, drug_names=[]
        )
        _, _, ret = _run(
            "三九感冒灵怎么吃",
            intent,
            repo,
            rules,
            canned={
                "三九感冒灵": [_cite("三九感冒灵")],
                "感冒灵": [_cite("感冒灵")],
            },
        )
        assert ret.terms == ["三九感冒灵"]

    def test_non_overlapping_shorter_still_matched(self, repo, rules):
        """感冒灵 与 泰诺 不重叠 → 都收。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INFO, confidence=0.9, drug_names=[]
        )
        _, _, ret = _run(
            "感冒灵和泰诺",
            intent,
            repo,
            rules,
            canned={"感冒灵": [_cite("感冒灵")], "泰诺": [_cite("泰诺")]},
        )
        assert set(ret.terms) == {"感冒灵", "泰诺"}

    def test_annotation_core_match(self, repo, rules):
        """扶他林_外用 可被 query 里的核名「扶他林」命中，映射回存储名。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INFO, confidence=0.9, drug_names=[]
        )
        _, _, ret = _run(
            "扶他林能外用吗",
            intent,
            repo,
            rules,
            canned={"扶他林_外用": [_cite("扶他林_外用")]},
        )
        assert ret.terms == ["扶他林_外用"]

    def test_annotation_word_not_a_false_positive(self, repo, rules):
        """注解词「外用」本身不作匹配模式 → 不误命中 扶他林_外用。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INFO, confidence=0.9, drug_names=[]
        )
        result, _, ret = _run("这个外用药膏怎么用", intent, repo, rules)
        assert ret.terms == ["这个外用药膏怎么用"]  # 无品牌 → 回退整句
        assert result.citations == []

    def test_no_brand_falls_back_to_whole_query(self, repo, rules):
        """query 不含任何品牌 → 回退整句检索。"""
        intent = IntentResult(
            intent=IntentCategory.DRUG_INFO, confidence=0.9, drug_names=[]
        )
        _, _, ret = _run("感冒了多喝水行吗", intent, repo, rules)
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
        assert ret.terms == ["酒精"]

    def test_interaction_empty_llm_names_runs_check_on_scanned(self, repo, rules):
        """interaction 意图 + LLM 空名 + query 两品牌 → 规则引擎对扫描名跑起来。

        间接证明：answer 自报 citations_used 为空，但因 has_findings，
        「查阅说明书」注记被抑制——即 check_medbox 确实收到了扫描出的两个名字。
        """
        intent = IntentResult(
            intent=IntentCategory.DRUG_INTERACTION,
            confidence=0.0,
            drug_names=[],
        )
        result, llm, ret = _run(
            "泰诺和必理通能一起吃吗",
            intent,
            repo,
            rules,
            canned={"泰诺": [_cite("泰诺")], "必理通": [_cite("必理通")]},
            answer_citations=[],
        )
        assert set(ret.terms) == {"泰诺", "必理通"}
        assert "查阅原药品说明书" not in result.answer
        assert llm.calls == 3

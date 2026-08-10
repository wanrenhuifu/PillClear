"""app/prompts 提示词模块的单元测试。

提示词是 /chat 智能体的「剧本」，必须可测：
- build_chat_messages / build_intent_messages / build_safety_messages 的结构；
- RAG 上下文按药品分组注入、无引用时的降级提示；
- 检查结论槽位的注入（任务四）与 CheckReport 格式化；
- 意图 / 安全分类的枚举与输出模型。
"""

import pytest
from pydantic import ValidationError

from app.knowledge.schemas import Citation
from app.medbox.schemas import CheckReport, IngredientTotal, OverlapResult
from app.prompts.chat import (
    build_chat_messages,
    build_system_prompt,
)
from app.prompts.formatters import (
    format_check_report_for_prompt,
    format_citations_for_prompt,
)
from app.prompts.intent import (
    IntentCategory,
    IntentResult,
    build_intent_messages,
)
from app.prompts.safety import SafetyLLMResult, build_safety_messages
from app.rules.schemas import IngredientCondition, Rule, RuleConditions

# ── 样例数据 ────────────────────────────────────────────────

def _citations() -> list[Citation]:
    return [
        Citation(brand_name="布洛芬", section="用法用量", excerpt="成人一次1粒，一日2次。"),
        Citation(brand_name="布洛芬", section="不良反应", excerpt="可见恶心、胃烧灼感。"),
        Citation(brand_name="泰诺", section="成份", excerpt="每片含对乙酰氨基酚325毫克。"),
    ]


def _overlap_rule() -> Rule:
    return Rule(
        id="acetaminophen-overlap",
        title="对乙酰氨基酚重复过量",
        severity="danger",
        description="两种药都含对乙酰氨基酚",
        conditions=RuleConditions(
            ingredients=[IngredientCondition(name="对乙酰氨基酚", min_count=2)]
        ),
        warning="⚠️ 你在吃 2 种含对乙酰氨基酚的药，每日合计约 825.0mg。",
        confidence="high",
    )


# ── build_chat_messages ─────────────────────────────────────

class TestBuildChatMessages:

    def test_structure_system_then_user(self):
        msgs = build_chat_messages("布洛芬怎么吃")
        assert [m["role"] for m in msgs] == ["system", "user"]
        assert msgs[-1]["content"] == "布洛芬怎么吃"

    def test_rag_context_injected(self):
        msgs = build_chat_messages("布洛芬怎么吃", _citations())
        system = msgs[0]["content"]
        # 药品名分组 + 章节名 + 原文摘录都在
        assert "布洛芬" in system
        assert "泰诺" in system
        assert "用法用量" in system
        assert "成人一次1粒，一日2次。" in system

    def test_no_citations_shows_fallback_text(self):
        system = build_system_prompt([])
        assert "未检索到" in system

    def test_none_citations_shows_fallback_text(self):
        system = build_system_prompt(None)
        assert "未检索到" in system

    def test_check_context_slot_injected(self):
        msgs = build_chat_messages(
            "泰诺和必理通能一起吃吗",
            check_context="规则引擎检测到对乙酰氨基酚重复过量。",
        )
        system = msgs[0]["content"]
        assert "检查结果" in system
        assert "对乙酰氨基酚重复过量" in system
        # 铁律 #1：明确要求 LLM 只翻译、不改写确定性结论
        assert "改写" in system

    def test_no_check_slot_when_none(self):
        system = build_system_prompt(_citations(), check_context=None)
        assert "检查结果" not in system

    def test_chat_history_inserted_between_system_and_user(self):
        history = [{"role": "assistant", "content": "你好"}]
        msgs = build_chat_messages("再问一个", chat_history=history)
        assert msgs[1] == {"role": "assistant", "content": "你好"}
        assert msgs[-1] == {"role": "user", "content": "再问一个"}


# ── format_citations_for_prompt ─────────────────────────────

class TestFormatCitations:

    def test_groups_by_drug(self):
        text = format_citations_for_prompt(_citations())
        assert "### 布洛芬" in text
        assert "### 泰诺" in text
        # 两条布洛芬引用都在其分组下
        assert "【用法用量】" in text
        assert "【不良反应】" in text

    def test_empty_returns_hint(self):
        text = format_citations_for_prompt([])
        assert "未检索到" in text
        assert "0.5" in text  # 要求置信度不超过 0.5


# ── 意图分类 ────────────────────────────────────────────────

class TestIntent:

    def test_build_intent_messages_structure(self):
        msgs = build_intent_messages("泰诺和芬必得能一起吃吗")
        assert msgs[0]["role"] == "system"
        assert msgs[1] == {"role": "user", "content": "泰诺和芬必得能一起吃吗"}

    def test_intent_prompt_lists_four_categories(self):
        system = build_intent_messages("x")[0]["content"]
        for cat in ("drug_info", "drug_interaction", "lifestyle_interaction", "general_health"):
            assert cat in system

    def test_intent_category_enum_values(self):
        assert IntentCategory.DRUG_INFO.value == "drug_info"
        assert IntentCategory.DRUG_INTERACTION.value == "drug_interaction"
        assert IntentCategory.LIFESTYLE_INTERACTION.value == "lifestyle_interaction"
        assert IntentCategory.GENERAL_HEALTH.value == "general_health"

    def test_intent_result_defaults(self):
        r = IntentResult(intent=IntentCategory.DRUG_INFO)
        assert r.drug_names == []
        assert r.lifestyle_substances == []
        assert r.confidence == 0.5

    def test_intent_result_rejects_bad_intent(self):
        with pytest.raises(ValidationError):
            IntentResult(intent="not_a_real_intent")


# ── 检查报告格式化（任务四）──────────────────────────────────

class TestFormatCheckReport:

    def test_unresolved_drugs_made_explicit(self):
        report = CheckReport(
            overlap=OverlapResult(), unresolved_drugs=["某神秘药"]
        )
        text = format_check_report_for_prompt(report)
        assert "暂未收录" in text
        assert "某神秘药" in text

    def test_triggered_rule_inlined(self):
        report = CheckReport(
            overlap=OverlapResult(), triggered_rules=[_overlap_rule()]
        )
        text = format_check_report_for_prompt(report)
        assert "对乙酰氨基酚重复过量" in text
        assert "825.0mg" in text

    def test_overlap_warning_inlined(self):
        report = CheckReport(
            overlap=OverlapResult(warnings=["⚠️ 对乙酰氨基酚每日合计超限。"])
        )
        text = format_check_report_for_prompt(report)
        assert "对乙酰氨基酚每日合计超限" in text

    def test_shared_ingredient_sources_listed(self):
        report = CheckReport(
            overlap=OverlapResult(
                overlapping=[
                    IngredientTotal(
                        name="对乙酰氨基酚",
                        total_amount_mg=825.0,
                        sources=["泰诺", "必理通"],
                        max_daily_mg=4000.0,
                    )
                ]
            )
        )
        text = format_check_report_for_prompt(report)
        assert "泰诺、必理通" in text

    def test_empty_report_says_no_findings(self):
        report = CheckReport(overlap=OverlapResult())
        text = format_check_report_for_prompt(report)
        assert "未检测到" in text


# ── 安全分类（任务五）────────────────────────────────────────

class TestSafetyPrompt:

    def test_build_safety_messages_structure(self):
        msgs = build_safety_messages("孕妇能吃布洛芬吗")
        assert msgs[0]["role"] == "system"
        assert msgs[1] == {"role": "user", "content": "孕妇能吃布洛芬吗"}

    def test_safety_prompt_lists_categories(self):
        system = build_safety_messages("x")[0]["content"]
        for cat in ("emergency", "special_population", "diagnosis", "prescription", "none"):
            assert cat in system

    def test_safety_result_defaults_to_none(self):
        # 缺字段时默认 none / 0.0 —— 保证非法/残缺输出不会误拦
        r = SafetyLLMResult.model_validate({})
        assert r.category == "none"
        assert r.confidence == 0.0

    def test_safety_result_rejects_bad_confidence(self):
        with pytest.raises(ValidationError):
            SafetyLLMResult(category="none", confidence=1.5)

"""app.core.safety 的单元测试（TDD 先行，20 条）。

覆盖四类越界问题（急症 / 特殊人群 / 诊断 / 处方药）与正常放行，
并验证急症相对特殊人群的优先级。
"""

import pytest

from app.core.safety import (
    BoundaryCategory,
    check_boundary,
    check_boundary_with_llm,
    classify_with_llm,
)
from app.llm.errors import LLMRetryExhausted
from app.prompts.safety import SafetyLLMResult


class TestPrescription:
    """处方药咨询 → 引导就医 / 药师，不提供。"""

    def test_antibiotic_name(self):
        r = check_boundary("阿莫西林一次吃几粒？")
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION
        assert r.message

    def test_doctor_prescribed(self):
        r = check_boundary("医生开的处方药我能自己加量吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION

    def test_buy_prescription_self(self):
        r = check_boundary("处方药能不能自己去药店买")
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION

    def test_prescription_sedative(self):
        r = check_boundary("阿普唑仑这种处方安眠药怎么吃")
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION


class TestDiagnosis:
    """诊断 / 症状解读 → 引导就医，不提供。"""

    def test_am_i_sick(self):
        r = check_boundary("我是不是得了肺炎")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS

    def test_what_disease(self):
        r = check_boundary("我这些症状是什么病")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS

    def test_please_diagnose(self):
        r = check_boundary("帮我诊断一下我的病情")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS

    def test_interpret_lab_report(self):
        r = check_boundary("帮我解读一下这份化验单")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS


class TestSpecialPopulation:
    """孕妇 / 哺乳期 / 儿童 / 慢病 → 不提供个性化建议，引导咨询医生。"""

    def test_pregnant(self):
        r = check_boundary("孕妇能吃布洛芬吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_breastfeeding(self):
        r = check_boundary("哺乳期吃感冒药会不会影响孩子")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_infant(self):
        r = check_boundary("三岁的小孩发烧能吃这个药吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_hypertension_chronic(self):
        r = check_boundary("我有高血压，这个药能一起吃吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_diabetes_chronic(self):
        r = check_boundary("糖尿病人能不能吃这种复方感冒药")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION


class TestEmergency:
    """急症信号 → 立即提示就医。"""

    def test_persistent_high_fever(self):
        r = check_boundary("我高热39度一直不退怎么办")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_breathing_difficulty(self):
        r = check_boundary("吃完药后我感觉呼吸困难")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_severe_allergy(self):
        r = check_boundary("我出现了严重过敏，好像过敏性休克")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_severe_chest_pain(self):
        r = check_boundary("突然剧烈胸痛喘不上气")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_fever_newline_between(self):
        # 发热与"不退"之间夹换行也要命中（多行输入很常见）
        r = check_boundary("发热\n一直不退怎么办")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_fever_with_temperature_gap(self):
        # 中间夹体温读数（>6 字符）也要命中
        r = check_boundary("高烧39.5℃持续不退")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY


class TestPassthrough:
    """正常 OTC 问题 → 放行，不触发边界。"""

    def test_otc_feichufangyao_not_blocked(self):
        # "非处方药"是 OTC，不得被"处方药"关键词误拦
        r = check_boundary("这个是非处方药，怎么吃")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_ibuprofen_empty_stomach(self):
        r = check_boundary("布洛芬能空腹吃吗")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE
        assert r.message is None

    def test_cold_medicine_ingredients(self):
        r = check_boundary("这个复方感冒药都有哪些成分")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_melatonin(self):
        r = check_boundary("褪黑素助眠一次吃多少")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE


class TestNegation:
    """否定语境中的关键词不应触发边界。"""

    def test_compound_word_bucuo_does_not_suppress_emergency(self):
        # "不错"中的"不"不是否定语境，真实急症信号不得漏判
        r = check_boundary("吃了布洛芬效果不错，但现在呼吸困难")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_compound_word_tebie_does_not_suppress_emergency(self):
        # "特别"中的"别"不是否定语境
        r = check_boundary("吃完药感觉特别难受，喘不上气")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_not_emergency_negated(self):
        r = check_boundary("我没有呼吸困难，就是想问问感冒药")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_not_prescription_negated(self):
        r = check_boundary("这个不是处方药吧")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_not_special_population_negated(self):
        r = check_boundary("我没有高血压，能吃布洛芬吗")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_diagnosis_negated_still_blocked_by_other(self):
        # "不是诊断"否定诊断，但"什么病"仍命中
        r = check_boundary("我不是要诊断，就是问问这是什么病")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS


class TestChildAge:
    """儿童年龄检测：仅 0-17 岁触发，成年人年龄不误判。"""

    def test_adult_age_not_blocked(self):
        r = check_boundary("我25岁的朋友感冒了能吃布洛芬吗")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_second_age_match_counts_when_first_negated(self):
        # 首个年龄命中被否定，后一个未否定的儿童年龄仍须触发
        r = check_boundary("不是给1岁用的，是给6岁孩子用的，能吃吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_child_age_blocked_by_keyword(self):
        # "3岁" + "宝宝" 触发特殊人群
        r = check_boundary("3岁的宝宝发烧了能吃泰诺吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_child_age_arabic_blocked(self):
        # 纯数字年龄 5 岁，配合儿童关键词"小孩"
        r = check_boundary("5岁的小孩感冒吃什么药")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION


class TestPriority:
    """急症优先级高于特殊人群：孕妇 + 呼吸困难同时命中时按急症处理。"""

    def test_emergency_over_special_population(self):
        r = check_boundary("孕妇吃完药后呼吸困难了")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY


# ── LLM 二次分类（任务五）────────────────────────────────────


class FakeLLM:
    """可编排的 LLM 替身：返回预设 SafetyLLMResult 或抛异常。"""

    def __init__(self, result: SafetyLLMResult | None = None, exc: Exception | None = None):
        self._result = result
        self._exc = exc
        self.calls: list[dict] = []

    def complete_json(self, messages, response_model, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self._exc is not None:
            raise self._exc
        return self._result


class TestClassifyWithLLM:
    """classify_with_llm：关键词放行后的 LLM 补漏，结论回落枚举 + 固定话术。"""

    def test_high_confidence_boundary_blocks(self):
        llm = FakeLLM(result=SafetyLLMResult(category="prescription", confidence=0.95))
        r = classify_with_llm("这个药怎么吃", llm)
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION
        assert r.message  # 回落到固定话术

    def test_high_confidence_emergency_blocks(self):
        llm = FakeLLM(result=SafetyLLMResult(category="emergency", confidence=0.9))
        r = classify_with_llm("吃完药整个人不对劲", llm)
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY
        assert "120" in r.message

    def test_low_confidence_falls_back_to_none(self):
        """低置信度 → 以关键词结果（NONE）为准，放行。"""
        llm = FakeLLM(result=SafetyLLMResult(category="prescription", confidence=0.3))
        r = classify_with_llm("这个药怎么吃", llm)
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_category_none_passes(self):
        llm = FakeLLM(result=SafetyLLMResult(category="none", confidence=0.99))
        r = classify_with_llm("布洛芬怎么吃", llm)
        assert r.blocked is False

    def test_invalid_category_falls_back_to_none(self):
        """LLM 乱报分类 → 回落 NONE，不得误拦。"""
        llm = FakeLLM(result=SafetyLLMResult(category="galaxy_brain", confidence=0.99))
        r = classify_with_llm("布洛芬怎么吃", llm)
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_llm_exception_degrades_to_none(self):
        """LLM 调用失败 → 降级放行，不阻断。"""
        llm = FakeLLM(exc=LLMRetryExhausted(3, ValueError("boom")))
        r = classify_with_llm("布洛芬怎么吃", llm)
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_uses_low_max_tokens(self):
        """分类调用压低 max_tokens 以控制延迟（设计目标）。"""
        llm = FakeLLM(result=SafetyLLMResult(category="none", confidence=0.9))
        classify_with_llm("布洛芬怎么吃", llm)
        assert llm.calls[0]["kwargs"].get("max_tokens") is not None


class TestCheckBoundaryWithLLM:
    """check_boundary_with_llm：关键词为主，LLM 仅在放行时补漏。"""

    def test_keyword_block_short_circuits_no_llm(self):
        """关键词已拦 → 直接返回，绝不调用 LLM（LLM 无权放行）。"""
        llm = FakeLLM(exc=AssertionError("不应被调用"))
        r = check_boundary_with_llm("孕妇能吃布洛芬吗", llm)
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION
        assert llm.calls == []  # LLM 未被触达

    def test_keyword_pass_then_llm_blocks(self):
        """关键词放行、LLM 高置信度补漏拦截。"""
        llm = FakeLLM(result=SafetyLLMResult(category="diagnosis", confidence=0.9))
        r = check_boundary_with_llm("我这是不是大病", llm)
        # 关键词对「是不是大病」不命中 diagnosis 关键词 → 交给 LLM
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS
        assert len(llm.calls) == 1

    def test_keyword_pass_llm_fail_still_passes(self):
        """关键词放行、LLM 失败 → 维持放行，不阻断 /chat。"""
        llm = FakeLLM(exc=RuntimeError("network down"))
        r = check_boundary_with_llm("布洛芬能空腹吃吗", llm)
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

"""app.core.safety 的单元测试（TDD 先行，20 条）。

覆盖四类越界问题（急症 / 特殊人群 / 诊断 / 处方药）与正常放行，
并验证急症相对特殊人群的优先级。
"""


from app.core.safety import (
    BoundaryCategory,
    check,
)
from app.llm.errors import LLMRetryExhausted
from app.prompts.safety import SafetyLLMResult


class TestPrescription:
    """处方药咨询 → 引导就医 / 药师，不提供。"""

    def test_antibiotic_name(self):
        r = check("阿莫西林一次吃几粒？")
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION
        assert r.message

    def test_doctor_prescribed(self):
        r = check("医生开的处方药我能自己加量吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION

    def test_buy_prescription_self(self):
        r = check("处方药能不能自己去药店买")
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION

    def test_prescription_sedative(self):
        r = check("阿普唑仑这种处方安眠药怎么吃")
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION


class TestDiagnosis:
    """诊断 / 症状解读 → 引导就医，不提供。"""

    def test_am_i_sick(self):
        r = check("我是不是得了肺炎")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS

    def test_what_disease(self):
        r = check("我这些症状是什么病")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS

    def test_please_diagnose(self):
        r = check("帮我诊断一下我的病情")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS

    def test_interpret_lab_report(self):
        r = check("帮我解读一下这份化验单")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS


class TestSpecialPopulation:
    """孕妇 / 哺乳期 / 儿童 / 慢病 → 不提供个性化建议，引导咨询医生。"""

    def test_pregnant(self):
        r = check("孕妇能吃布洛芬吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_breastfeeding(self):
        r = check("哺乳期吃感冒药会不会影响孩子")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_infant(self):
        r = check("三岁的小孩发烧能吃这个药吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_hypertension_chronic(self):
        r = check("我有高血压，这个药能一起吃吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_diabetes_chronic(self):
        r = check("糖尿病人能不能吃这种复方感冒药")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION


class TestEmergency:
    """急症信号 → 立即提示就医。"""

    def test_persistent_high_fever(self):
        r = check("我高热39度一直不退怎么办")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_breathing_difficulty(self):
        r = check("吃完药后我感觉呼吸困难")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_severe_allergy(self):
        r = check("我出现了严重过敏，好像过敏性休克")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_severe_chest_pain(self):
        r = check("突然剧烈胸痛喘不上气")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_fever_newline_between(self):
        # 发热与"不退"之间夹换行也要命中（多行输入很常见）
        r = check("发热\n一直不退怎么办")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_fever_with_temperature_gap(self):
        # 中间夹体温读数（>6 字符）也要命中
        r = check("高烧39.5℃持续不退")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY


class TestPassthrough:
    """正常 OTC 问题 → 放行，不触发边界。"""

    def test_otc_feichufangyao_not_blocked(self):
        # "非处方药"是 OTC，不得被"处方药"关键词误拦
        r = check("这个是非处方药，怎么吃")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_ibuprofen_empty_stomach(self):
        r = check("布洛芬能空腹吃吗")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE
        assert r.message is None

    def test_cold_medicine_ingredients(self):
        r = check("这个复方感冒药都有哪些成分")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_melatonin(self):
        r = check("褪黑素助眠一次吃多少")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE


class TestNegation:
    """否定语境中的关键词不应触发边界。"""

    def test_compound_word_bucuo_does_not_suppress_emergency(self):
        # "不错"中的"不"不是否定语境，真实急症信号不得漏判
        r = check("吃了布洛芬效果不错，但现在呼吸困难")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_compound_word_tebie_does_not_suppress_emergency(self):
        # "特别"中的"别"不是否定语境
        r = check("吃完药感觉特别难受，喘不上气")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY

    def test_not_emergency_negated(self):
        r = check("我没有呼吸困难，就是想问问感冒药")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_not_prescription_negated(self):
        r = check("这个不是处方药吧")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_not_special_population_negated(self):
        r = check("我没有高血压，能吃布洛芬吗")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_diagnosis_negated_still_blocked_by_other(self):
        # "不是诊断"否定诊断，但"什么病"仍命中
        r = check("我不是要诊断，就是问问这是什么病")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS


class TestChildAge:
    """儿童年龄检测：仅 0-17 岁触发，成年人年龄不误判。"""

    def test_adult_age_not_blocked(self):
        r = check("我25岁的朋友感冒了能吃布洛芬吗")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_second_age_match_counts_when_first_negated(self):
        # 首个年龄命中被否定，后一个未否定的儿童年龄仍须触发
        r = check("不是给1岁用的，是给6岁孩子用的，能吃吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_child_age_blocked_by_keyword(self):
        # "3岁" + "宝宝" 触发特殊人群
        r = check("3岁的宝宝发烧了能吃泰诺吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_child_age_arabic_blocked(self):
        # 纯数字年龄 5 岁，配合儿童关键词"小孩"
        r = check("5岁的小孩感冒吃什么药")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION


class TestPriority:
    """急症优先级高于特殊人群：孕妇 + 呼吸困难同时命中时按急症处理。"""

    def test_emergency_over_special_population(self):
        r = check("孕妇吃完药后呼吸困难了")
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


class TestCheckWithLLM:
    """check(text, llm)：关键词放行后的 LLM 补漏，结论回落枚举 + 固定话术。"""

    def test_high_confidence_boundary_blocks(self):
        llm = FakeLLM(result=SafetyLLMResult(category="prescription", confidence=0.95))
        r = check("这个药怎么吃", llm)
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION
        assert r.message  # 回落到固定话术

    def test_high_confidence_emergency_blocks(self):
        llm = FakeLLM(result=SafetyLLMResult(category="emergency", confidence=0.9))
        r = check("吃完药整个人不对劲", llm)
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY
        assert "120" in r.message

    def test_low_confidence_falls_back_to_none(self):
        """低置信度 → 以关键词结果（NONE）为准，放行。"""
        llm = FakeLLM(result=SafetyLLMResult(category="prescription", confidence=0.3))
        r = check("这个药怎么吃", llm)
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_category_none_passes(self):
        llm = FakeLLM(result=SafetyLLMResult(category="none", confidence=0.99))
        r = check("布洛芬怎么吃", llm)
        assert r.blocked is False

    def test_invalid_category_falls_back_to_none(self):
        """LLM 乱报分类 → 回落 NONE，不得误拦。"""
        llm = FakeLLM(result=SafetyLLMResult(category="galaxy_brain", confidence=0.99))
        r = check("布洛芬怎么吃", llm)
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_llm_exception_degrades_to_none(self):
        """LLM 调用失败 → 降级放行，不阻断。"""
        llm = FakeLLM(exc=LLMRetryExhausted(3, ValueError("boom")))
        r = check("布洛芬怎么吃", llm)
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_uses_low_max_tokens(self):
        """分类调用压低 max_tokens 以控制延迟（设计目标）。"""
        llm = FakeLLM(result=SafetyLLMResult(category="none", confidence=0.9))
        check("布洛芬怎么吃", llm)
        assert llm.calls[0]["kwargs"].get("max_tokens") is not None


class TestCheckWithLLMIntegration:
    """check(text, llm)：关键词为主，LLM 仅在放行时补漏。"""

    def test_keyword_block_short_circuits_no_llm(self):
        """关键词已拦 → 直接返回，绝不调用 LLM（LLM 无权放行）。"""
        llm = FakeLLM(exc=AssertionError("不应被调用"))
        r = check("孕妇能吃布洛芬吗", llm)
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION
        assert llm.calls == []  # LLM 未被触达

    def test_keyword_pass_then_llm_blocks(self):
        """关键词放行、LLM 高置信度补漏拦截。"""
        llm = FakeLLM(result=SafetyLLMResult(category="diagnosis", confidence=0.9))
        r = check("我这是不是大病", llm)
        # 关键词对「是不是大病」不命中 diagnosis 关键词 → 交给 LLM
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS
        assert len(llm.calls) == 1

    def test_keyword_pass_llm_fail_still_passes(self):
        """关键词放行、LLM 失败 → 维持放行，不阻断 /chat。"""
        llm = FakeLLM(exc=RuntimeError("network down"))
        r = check("布洛芬能空腹吃吗", llm)
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE


# ── 特征化测试（重构防护）────────────────────────────────────
# 目的：把「当前行为」逐案锁死——不论当前行为是否完美。
# 重构后任何一条变红，都意味着行为发生了改变，必须显式决策
# （有意识地改测试接受新行为，或修回旧行为），不得静默通过。


class TestEmergencyNearMiss:
    """急症类「差一点不命中」的边界：锁定发热组合正则的窗口宽度与否定语义。"""

    def test_plain_fever_not_emergency(self):
        # 单纯发烧（无「不退」组合）不触发急症——普通 OTC 退烧咨询必须放行
        r = check("我发烧了，能吃布洛芬吗")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_fever_without_persistence_not_emergency(self):
        r = check("高烧了怎么办")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_fever_gap_beyond_window_not_emergency(self):
        # 特征化已知盲区：「发热」与「不退」间隔 11 字 > 正则窗口 {0,10}，当前放行。
        # 重构若要收紧窗口，此测试会变红——那是一次明确的行为变更，需单独决策。
        r = check("发热已经持续整整三天了还是不退")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_negation_only_checked_before_keyword(self):
        # 否定检测只看关键词「之前」：「没有」在「发热」之后不构成否定，仍触发。
        # 锁定当前保守语义（铁律 #3：漏判比误判危险）。
        r = check("发热没有不退的情况")
        assert r.blocked is True
        assert r.category is BoundaryCategory.EMERGENCY


class TestSpecialPopulationNearMiss:
    """特殊人群类的边界：子串匹配的保守性与已知未覆盖人群。"""

    def test_future_breastfeeding_still_blocked(self):
        # 特征化：关键词层做子串匹配，「下周要哺乳期」仍命中「哺乳期」——
        # 故意保守（拦截只是引导咨询医生），语义细化是 LLM 补漏层的事。
        r = check("下周要哺乳期了再说")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION

    def test_menstrual_period_not_special_population(self):
        # 特征化已知盲区：「月经期」不在关键词表，当前放行。
        r = check("月经期能吃布洛芬吗")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE

    def test_elderly_not_caught_by_keywords(self):
        # 特征化已知盲区：「老人/老年人」不在关键词表，年龄正则只覆盖 0-17 岁，
        # 关键词层放行；设计上由 LLM 补漏层兜底（safety prompt 里列了老人）。
        r = check("70岁老人吃这个药要注意什么")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE


class TestDiagnosisNearMiss:
    """诊断类的边界：子串匹配的保守命中与纯药品问题放行。"""

    def test_what_disease_treats_still_diagnosis(self):
        # 特征化：「治什么病的」含子串「什么病」→ 命中诊断（保守误拦，锁定现状）。
        r = check("这个药是治什么病的")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS

    def test_side_effect_question_passes(self):
        r = check("我想知道这个药的副作用")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE


class TestPrescriptionNearMiss:
    """处方药类的边界。"""

    def test_asking_if_antibiotic_blocked(self):
        # 特征化：询问「是不是抗生素」也命中处方药关键词（保守，锁定现状）。
        r = check("这个药是抗生素吗")
        assert r.blocked is True
        assert r.category is BoundaryCategory.PRESCRIPTION

    def test_vitamin_c_passes(self):
        r = check("维生素C一天吃多少")
        assert r.blocked is False
        assert r.category is BoundaryCategory.NONE


class TestPriorityCharacterization:
    """分类优先级链的完整锁定：急症 > 特殊人群 > 诊断 > 处方药。"""

    def test_diagnosis_over_prescription(self):
        # 同时命中诊断与处方药关键词时，诊断优先
        r = check("我是不是得了什么病得吃抗生素")
        assert r.blocked is True
        assert r.category is BoundaryCategory.DIAGNOSIS

    def test_special_population_over_diagnosis(self):
        r = check("孕妇是不是得了什么病")
        assert r.blocked is True
        assert r.category is BoundaryCategory.SPECIAL_POPULATION


class TestFixedMessagesGolden:
    """四类固定话术逐字锁定：用户看到的安全文案，重构不得意外改字。"""

    def test_emergency_message_exact(self):
        r = check("我突然呼吸困难")
        assert r.message == (
            "⚠️ 这可能是急症信号，别耽误！请立即拨打 120 或尽快前往最近的急诊。\n"
            "我只是用药安全助手，处理不了紧急情况，你的安全最重要。"
        )

    def test_special_population_message_exact(self):
        r = check("孕妇能吃这个药吗")
        assert r.message == (
            "⚠️ 孕妇、哺乳期、儿童以及有慢性病的人群用药风险特殊，"
            "我没法给出个性化建议。\n"
            "请当面咨询医生或药师，让专业人士结合具体情况判断，别自己拿主意。"
        )

    def test_diagnosis_message_exact(self):
        r = check("帮我诊断一下")
        assert r.message == (
            "⚠️ 我不能帮你诊断疾病，也不能解读症状或检查报告——这得靠医生。\n"
            "如果不舒服，建议尽快去医院或线上问诊，把判断交给专业人士。"
        )

    def test_prescription_message_exact(self):
        r = check("头孢一次吃多少")
        assert r.message == (
            "⚠️ 处方药必须凭医生处方使用，我不提供处方药的用法用量建议。\n"
            "请遵医嘱，或到医院、药店当面咨询医生和药师。"
        )

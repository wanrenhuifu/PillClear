"""能力边界判断模块（v2）。

铁律落实：处方药 / 疾病诊断 / 特殊人群 / 急症信号属于越界问题，
一律不提供个性化用药结论，返回写死的固定话术并引导就医或咨询药师。

公开接口只有一个函数：
    check(text, llm=None) → BoundaryResult
    - llm=None：纯关键词检测（离线 / 测试 / 无 LLM 场景）
    - 传入 llm：关键词放行后用 LLM 补漏，减少漏判
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from app.prompts.safety import SafetyLLMResult, build_safety_messages

if TYPE_CHECKING:
    from app.llm.client import LLMClient

logger = logging.getLogger("app.core.safety")


class BoundaryCategory(StrEnum):
    """越界问题分类。NONE 表示未触发边界，可正常放行。"""

    EMERGENCY = "emergency"
    SPECIAL_POPULATION = "special_population"
    DIAGNOSIS = "diagnosis"
    PRESCRIPTION = "prescription"
    NONE = "none"


@dataclass(frozen=True)
class BoundaryResult:
    """边界判断结果。

    - category: 命中的分类
    - blocked: 是否越界（True 时应使用 message 直接回复用户）
    - message: 固定话术，未越界时为 None
    """

    category: BoundaryCategory
    blocked: bool
    message: str | None


# —— 固定话术（大白话 + 醒目安全提示 + 引导）——

_MESSAGES: dict[BoundaryCategory, str] = {
    BoundaryCategory.EMERGENCY: (
        "⚠️ 这可能是急症信号，别耽误！请立即拨打 120 或尽快前往最近的急诊。\n"
        "我只是用药安全助手，处理不了紧急情况，你的安全最重要。"
    ),
    BoundaryCategory.SPECIAL_POPULATION: (
        "⚠️ 孕妇、哺乳期、儿童以及有慢性病的人群用药风险特殊，"
        "我没法给出个性化建议。\n"
        "请当面咨询医生或药师，让专业人士结合具体情况判断，别自己拿主意。"
    ),
    BoundaryCategory.DIAGNOSIS: (
        "⚠️ 我不能帮你诊断疾病，也不能解读症状或检查报告——这得靠医生。\n"
        "如果不舒服，建议尽快去医院或线上问诊，把判断交给专业人士。"
    ),
    BoundaryCategory.PRESCRIPTION: (
        "⚠️ 处方药必须凭医生处方使用，我不提供处方药的用法用量建议。\n"
        "请遵医嘱，或到医院、药店当面咨询医生和药师。"
    ),
}


# —— 规则表（按分类维护关键词 / 正则）——

# 急症：命中即最高优先级。发热类需"发热 + 不退"组合，避免普通发烧误伤。
_EMERGENCY_KEYWORDS: tuple[str, ...] = (
    "呼吸困难",
    "喘不上气",
    "喘不过气",
    "过敏性休克",
    "严重过敏",
    "剧烈胸痛",
    "抽搐",
    "昏迷",
    "意识不清",
    "大出血",
)
# 发热 + 不退组合：间隔允许换行与体温读数（[\s\S]{0,10}），
# 覆盖"发热\n一直不退""高烧39.5℃持续不退"等常见表述。
_EMERGENCY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(高热|高烧|发烧|发热)[\s\S]{0,10}(不退|退不下|退不了)"),
)

_SPECIAL_POPULATION_KEYWORDS: tuple[str, ...] = (
    "孕妇",
    "怀孕",
    "孕期",
    "备孕",
    "哺乳期",
    "喂奶",
    "母乳",
    "儿童",
    "小孩",
    "小孩子",
    "婴儿",
    "婴幼儿",
    "宝宝",
    "高血压",
    "糖尿病",
    "冠心病",
    "慢性病",
    "慢病",
    "肝病",
    "肾病",
)

_DIAGNOSIS_KEYWORDS: tuple[str, ...] = (
    "是不是得了",
    "得了什么",
    "什么病",
    "诊断",
    "化验单",
    "检查报告",
    "体检报告",
    "验血报告",
    "是什么毛病",
)

_PRESCRIPTION_KEYWORDS: tuple[str, ...] = (
    "处方药",
    "处方",
    "抗生素",
    "阿莫西林",
    "头孢",
    "阿奇霉素",
    "阿普唑仑",
    "地西泮",
    "曲马多",
)

# ── 否定检测 ───────────────────────────────────────────
# 中文否定词：紧邻关键词之前（无间隔）才视为否定语境，避免误判。
# 只认"紧邻"关系：旧版的短窗口子串匹配会把嵌在普通词里的单字否定词
# （不错 / 特别 / 分别 / 无论 …）误当否定语境，从而漏放真实急症信号；
# 铁律 #3 下漏判比误判危险，因此宁可放过"没有明显的呼吸困难"这类
# 远距否定（触发拦截、引导就医）也不漏放真实急症。
# "非"用于放行"非处方药"（OTC 是本产品的核心服务对象）。
_NEGATION_WORDS: tuple[str, ...] = (
    "不", "没", "没有", "不是", "不会", "别", "无", "非",
    "否认", "排除", "并非",
)

# ── 儿童年龄模式 ───────────────────────────────────────
# 替换原来过于宽泛的 "岁的" 关键词，仅匹配 0-17 岁。
_CHILD_AGE_RE = re.compile(r"(?<!\d)(?:1[0-7]|[0-9])\s*岁")

# ── 预编译关键词交替正则（O(N) 单次扫描替代 O(N*K) 多次扫描）──

def _build_alt_re(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """将关键词编译为单个交替正则，按长度降序排列以优先匹配长词。"""
    sorted_kw = sorted(keywords, key=len, reverse=True)
    return re.compile("|".join(re.escape(kw) for kw in sorted_kw))

_EMERGENCY_KW_RE = _build_alt_re(_EMERGENCY_KEYWORDS)
_SPECIAL_POPULATION_KW_RE = _build_alt_re(_SPECIAL_POPULATION_KEYWORDS)
_DIAGNOSIS_KW_RE = _build_alt_re(_DIAGNOSIS_KEYWORDS)
_PRESCRIPTION_KW_RE = _build_alt_re(_PRESCRIPTION_KEYWORDS)


def _is_negated(text: str, idx: int) -> bool:
    """检查 text[idx] 处关键词是否被紧邻其前的否定词否定。"""
    return any(
        idx >= len(neg) and text[idx - len(neg):idx] == neg
        for neg in _NEGATION_WORDS
    )


def _any_keyword_match(text: str, alt_re: re.Pattern[str]) -> bool:
    """交替正则匹配，跳过否定语境中的命中。"""
    return any(not _is_negated(text, m.start()) for m in alt_re.finditer(text))


def _any_pattern_match(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    """正则规则匹配（用于发热等组合模式），跳过否定语境。"""
    for p in patterns:
        for m in p.finditer(text):
            if not _is_negated(text, m.start()):
                return True
    return False


def _detect_category(text: str) -> BoundaryCategory:
    """判定文本所属的越界分类（私有实现）。

    优先级：急症 > 特殊人群 > 诊断 > 处方药 > 放行(NONE)。
    急症最高优先级，确保"孕妇 + 呼吸困难"等复合场景优先提示就医。

    否定检测：关键词紧邻中文否定词时跳过该命中，
    避免"我没有呼吸困难""不是处方药"等误判；
    普通词里嵌的单字（不错 / 特别）不构成否定。
    """

    if _any_keyword_match(text, _EMERGENCY_KW_RE) or _any_pattern_match(
        text, _EMERGENCY_PATTERNS
    ):
        return BoundaryCategory.EMERGENCY
    if _any_keyword_match(text, _SPECIAL_POPULATION_KW_RE) or _any_pattern_match(
        text, (_CHILD_AGE_RE,)
    ):
        return BoundaryCategory.SPECIAL_POPULATION
    if _any_keyword_match(text, _DIAGNOSIS_KW_RE):
        return BoundaryCategory.DIAGNOSIS
    if _any_keyword_match(text, _PRESCRIPTION_KW_RE):
        return BoundaryCategory.PRESCRIPTION
    return BoundaryCategory.NONE


def _check_boundary_keywords(text: str) -> BoundaryResult:
    """关键词边界判断（私有实现：仅被 check() 调用）。"""

    category = _detect_category(text or "")
    if category is BoundaryCategory.NONE:
        return BoundaryResult(category=category, blocked=False, message=None)
    return BoundaryResult(
        category=category, blocked=True, message=_MESSAGES[category]
    )


# ── LLM 二次分类（任务五：关键词放行后补漏，减少漏判）──────────────

# LLM 分类置信度阈值：低于此值视为「拿不准」，回落到关键词结果（NONE）。
# 铁律 #4：宁可不拦也不误拦普通 OTC 咨询——但关键词已拦的绝不会被 LLM 放行
# （见 check 的短路：blocked 直接返回，不进 LLM）。
_LLM_CONFIDENCE_THRESHOLD = 0.7

# 低 max_tokens：分类任务只需输出一个小 JSON，压低生成长度以控制端到端延迟。
_LLM_MAX_TOKENS = 60


def _classify_boundary_with_llm(text: str, llm: LLMClient) -> BoundaryResult:
    """用 LLM 对「关键词放行」的文本做二次越界判断（私有实现：仅被 check() 调用）。

    铁律 #3/#4：
    - LLM 结论必须回落到 BoundaryCategory 枚举 + 固定话术，不自由发挥；
    - 低置信度 / 非法分类 / 调用失败一律回落到 NONE（关键词结果），不阻断 /chat。
    """

    try:
        result = llm.complete_json(
            build_safety_messages(text or ""),
            SafetyLLMResult,
            max_tokens=_LLM_MAX_TOKENS,
        )
    except Exception as exc:
        logger.warning("safety LLM 分类失败，降级到关键词结果（放行）：%s", exc)
        return BoundaryResult(
            category=BoundaryCategory.NONE, blocked=False, message=None
        )

    # 非法 category 字符串 → 回落到 NONE（不得因模型乱报而误拦）
    try:
        category = BoundaryCategory(result.category)
    except ValueError:
        logger.warning("safety LLM 返回非法分类 %r，降级放行", result.category)
        return BoundaryResult(
            category=BoundaryCategory.NONE, blocked=False, message=None
        )

    # none 或低置信度 → 以关键词结果（NONE）为准
    if category is BoundaryCategory.NONE or result.confidence < _LLM_CONFIDENCE_THRESHOLD:
        return BoundaryResult(
            category=BoundaryCategory.NONE, blocked=False, message=None
        )

    # 高置信度命中越界类别 → 回落到固定话术（铁律 #3）
    return BoundaryResult(category=category, blocked=True, message=_MESSAGES[category])


def check(text: str, llm: LLMClient | None = None) -> BoundaryResult:
    """对外唯一入口：判断输入是否越界并返回固定话术。

    - 关键词规则是主防线，命中即拦（绝不交给 LLM 放行）；
    - llm 非 None 时：关键词放行后调用 LLM 补漏，减少漏判；
    - llm 为 None 时：纯关键词检测（离线测试 / 无 LLM 场景）；
    - LLM 失败 / 低置信度 / 非法分类时维持关键词的放行结论，不阻断 /chat。
    """

    keyword_result = _check_boundary_keywords(text)
    if keyword_result.blocked or llm is None:
        return keyword_result
    return _classify_boundary_with_llm(text, llm)


__all__ = ["BoundaryCategory", "BoundaryResult", "check"]

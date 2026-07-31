"""/chat 智能体编排流水线（无 Web 框架依赖，可脱离 HTTP 测试）。

流水线（8 步）：
    安全边界（关键词 + LLM 补漏）→ 意图分类 → 按意图检索 RAG
    →（检查意图）确定性规则引擎检测 → LLM 生成 → 低置信度兜底
    → 引用缺失兜底 → 追加免责声明。

铁律落实：
- #1 叠加 / 相互作用 / 剂量判断走规则引擎，LLM 只翻译结论；
- #2 回答强制带说明书引用，代码对「无引用」兜底；
- #3 能力边界关键词为主、LLM 补漏，结论回落固定话术；
- #4 低置信度 / 未收录药品明说，不静默；
- #5 代码追加固定免责声明。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.api.schemas import LLMAnswer
from app.core.safety import check
from app.knowledge.repository import DrugReader
from app.knowledge.schemas import Citation
from app.llm.client import LLMClient
from app.llm.errors import LLMRetryExhausted
from app.medbox.schemas import Medbox, MedboxItem
from app.medbox.service import check_medbox
from app.prompts.chat import build_chat_messages
from app.prompts.formatters import (
    format_ambiguity_note,
    format_check_report_for_prompt,
)
from app.prompts.intent import (
    IntentCategory,
    IntentResult,
    build_intent_messages,
)
from app.rag.retriever import Retriever
from app.rules.schemas import RuleSet

logger = logging.getLogger("app.chat")

# ── 固定文案 ─────────────────────────────────────────────────

_DISCLAIMER = (
    "\n\n---\n"
    "⚠️ 以上内容仅供参考，不能替代医生或药师的建议。"
    "用药前请仔细阅读说明书。如有不适请立即停药并就医。"
    "如果你对用药有任何疑问，请咨询医生或药师。"
)

# 铁律 #4 的代码兜底：模型自报低置信度时，不能和笃定的回答一样输出，
# 必须显式提示"不确定"并引导咨询药师（不能只靠 prompt 自觉）。
_LOW_CONFIDENCE_THRESHOLD = 0.5
_LOW_CONFIDENCE_NOTE = (
    "\n\n⚠️ 说实话这个问题我把握不大，上面的说法仅供参考，"
    "建议直接咨询药师确认后再用药，别自己拿主意。"
)

# 铁律 #2 代码兜底：LLM 回答带了用药建议但没有引用来源时追加提示。
_NO_CITATION_NOTE = (
    "\n\n⚠️ 我注意到上面的回答没有引用具体的说明书原文，"
    "建议你查阅原药品说明书确认，或咨询药师。"
)

# 意图分类用低 max_tokens 压低延迟（任务三：端到端 < 1s 的设计目标）。
_INTENT_MAX_TOKENS = 150

# ── 确定性商品名扫描（LLM 意图分类失手时的降级兜底）──────────────
# 语义约定（code review 后定型）：
# - 仅降级兜底：LLM 抽到的药名为空时才扫描，不与 LLM 名并集——并集会把
#   同一药以「用户原文 + 存储名」两种形态送进检查（引用了说明书又说
#   暂未收录，自相矛盾），子串误命中还会喂给规则引擎凭空触发 danger 告警。
# - 最左优先 / 同位最长优先 / 不重叠 / 覆盖所有出现位置。
# - 过去 / 否定语境里的提及（「上周吃泰诺」）不表示现在在吃，不参与检测。
# - 核名解析到带注解存储名（扶他林→扶他林_外用）属近似匹配，必须披露。
# 已知盲区（无分词器不可消除，见 docs/refactor-readiness.md）：LLM 完全
# 失手时，未收录长名内嵌已收录短名（泰诺林 里的 泰诺）仍可能误命中。

# 匹配起点前窗口内出现这些标记 → 视为过去 / 否定语境，跳过该提及。
_PAST_OR_NEGATED_MARKERS = (
    "上周",
    "上个",
    "上月",
    "去年",
    "昨天",
    "前天",
    "以前",
    "之前",
    "从前",
    "停药",
    "停了",
    "不吃",
    "没吃",
    "不再",
    "康复",
    "痊愈",
    "戒了",
)
_PAST_OR_NEGATED_WINDOW = 6

# ── 检索预算（端到端 < 1s 设计目标：prompt 体量必须封顶）────────
_BRAND_TERM_LIMIT = 12  # 按药名检索时每个药名的章节上限（单份说明书典型 10-14 章）
_QUERY_SEARCH_LIMIT = 5  # 整句检索上限（沿用原内容搜索语义）
_CITATIONS_MAX = 15  # 注入 prompt 的引用总量上限


@dataclass
class ChatResult:
    """处理完成的聊天结果，可直接映射为 HTTP 响应。

    blocked=True 时 answer/confidence/citations/disclaimer 均为 None/空。
    """

    blocked: bool
    category: str | None = None
    boundary_message: str | None = None
    answer: str | None = None
    confidence: float | None = None
    citations: list[Citation] = field(default_factory=list)
    disclaimer: str | None = None


# ── 编排内部函数 ─────────────────────────────────────────────


def _classify_intent(llm_client: LLMClient, query: str) -> IntentResult:
    """LLM 意图分类（任务三）。失败降级为 drug_info，绝不阻断主流程。"""
    try:
        return llm_client.complete_json(
            build_intent_messages(query),
            IntentResult,
            max_tokens=_INTENT_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 - 分类失败必须降级而非阻断
        logger.warning("意图分类失败，降级为 drug_info：%s", exc)
        return IntentResult(intent=IntentCategory.DRUG_INFO, confidence=0.0)


def _dedup_stripped(names: Iterable[str]) -> list[str]:
    """strip 后过滤空值、去重保序（名单构造的统一习语）。"""
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        n = (n or "").strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _brand_patterns(brands: list[dict]) -> list[tuple[str, str]]:
    """构造 (匹配模式, 存储商品名) 列表。

    模式 = 存储商品名本身 ＋ 去注解核名（下划线前的产品名，如
    扶他林_外用 → 扶他林）。注解词（下划线之后）不作模式，避免
    「外用药膏」误命中。

    歧义核名不作模式：同一核名指向多个存储品（扶他林_外用 / 扶他林_口服），
    或核名本身已是另一个存储品（裸名 扶他林 与 扶他林_外用 并存）时，
    仅凭核名无法确定剂型 → 只保留全名模式。宁可按整句检索降级，
    也不静默命中某一个剂型（召回不得依赖入库顺序）。
    """
    rows: list[tuple[str, str | None]] = []
    full_names: set[str] = set()
    core_owners: dict[str, set[str]] = {}
    for d in brands:
        name = (d.get("brand_name") or "").strip()
        if not name:
            continue
        core = name.split("_", 1)[0].strip()
        if core and core != name and len(core) >= 2:
            core_owners.setdefault(core, set()).add(name)
        else:
            core = None
        rows.append((name, core))
        full_names.add(name)
    ambiguous_cores = {
        core
        for core, owners in core_owners.items()
        if len(owners) > 1 or core in full_names
    }
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, core in rows:
        aliases = (name, core) if core and core not in ambiguous_cores else (name,)
        for a in aliases:
            if a not in seen:
                seen.add(a)
                pairs.append((a, name))
    return pairs


def _is_past_or_negated(query: str, start: int) -> bool:
    """匹配起点前窗口内出现过去 / 否定标记 → 该提及不表示「现在在吃」。"""
    window = query[max(0, start - _PAST_OR_NEGATED_WINDOW) : start]
    return any(marker in window for marker in _PAST_OR_NEGATED_MARKERS)


def _scan_brand_names(
    query: str, brands: list[dict]
) -> tuple[list[str], list[tuple[str, str]]]:
    """确定性扫描 query 中提及的存储商品名（无 LLM，降级兜底专用）。

    长度降序交替正则 + finditer：最左位置优先裁决，同一位置最长模式优先，
    不重叠且覆盖所有出现位置——重复出现的长名每次出现都压住内嵌短名
    （三九感冒灵 出现两次都吃掉 感冒灵），等长模式按文本位置而非入库顺序。

    返回 (去重保序的存储名, 近似匹配 [(用户原文, 存储名)])：命中模式 ≠
    存储名（核名 → 带注解存储名）属近似匹配，剂型未必一致，调用方必须
    向 LLM 披露（铁律 #4：不确定就明说）。
    """
    pairs = _brand_patterns(brands)
    if not query or not pairs:
        return [], []
    alt_re = re.compile(
        "|".join(
            re.escape(p)
            for p, _ in sorted(pairs, key=lambda x: len(x[0]), reverse=True)
        )
    )
    mapping = dict(pairs)
    found: list[str] = []
    found_set: set[str] = set()
    ambiguous: list[tuple[str, str]] = []
    ambiguous_set: set[tuple[str, str]] = set()
    for m in alt_re.finditer(query):
        if _is_past_or_negated(query, m.start()):
            continue
        term = m.group()
        stored = mapping[term]
        if stored not in found_set:
            found_set.add(stored)
            found.append(stored)
        if term != stored and (term, stored) not in ambiguous_set:
            ambiguous_set.add((term, stored))
            ambiguous.append((term, stored))
    return found, ambiguous


def _effective_drug_names(
    query: str, intent: IntentResult, drug_repo: DrugReader
) -> tuple[list[str], list[tuple[str, str]]]:
    """解析有效药名名单：LLM 抽取优先，LLM 空名时确定性扫描兜底。

    扫描仅在 intent.drug_names 为空时触发：它是意图分类失手时的降级兜底
    （修「引用掉 0」），不与 LLM 名并集——并集会让同一药以「用户原文 +
    存储名」两种形态进入检查（自相矛盾），子串误命中还会凭空触发规则告警。

    返回 (有效药名, 近似匹配)。list_drugs / 扫描任何环节失败一律降级为
    空名单，绝不阻断主流程（与流水线「处处降级」哲学一致）。
    """
    llm_names = _dedup_stripped(intent.drug_names)
    if llm_names:
        return llm_names, []
    try:
        return _scan_brand_names(query, drug_repo.list_drugs())
    except Exception:  # noqa: BLE001 - 扫描是增强，失败不得阻断
        logger.warning("品牌名扫描失败，降级为空名单", exc_info=True)
        return [], []


def _retrieve_citations(
    retriever: Retriever,
    query: str,
    intent: IntentResult,
    effective_drug_names: list[str],
) -> list[Citation]:
    """按名检索 ∪ 整句检索，去重合并、总量封顶。

    按名检索修「引用掉 0」（整句搜经常 miss 药名）；整句检索始终参与：
    保住非品牌词（症状 / 用法）的召回，且 Postgres/pgvector 部署下让完整
    问题进入语义排序。总量封顶压低 prompt token 与延迟（< 1s 设计目标）。
    """
    terms = list(effective_drug_names)
    if intent.intent is IntentCategory.LIFESTYLE_INTERACTION:
        terms = _dedup_stripped((*terms, *intent.lifestyle_substances))
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
        add(retriever.search(term, limit=_BRAND_TERM_LIMIT))
    add(retriever.search(query, limit=_QUERY_SEARCH_LIMIT))
    return merged


# ── 主入口 ──────────────────────────────────────────────────


def process_chat(
    query: str,
    llm: LLMClient,
    retriever: Retriever,
    rules: RuleSet,
    drug_repo: DrugReader,
) -> ChatResult:
    """编排 RAG + 规则引擎 + LLM 的完整 /chat 流水线。

    同步函数（LLM / RAG / 规则引擎全部同步调用），HTTP 层负责
    run_in_threadpool 放入线程池。

    可能抛出 LLMRetryExhausted（回答生成阶段重试耗尽），调用方负责
    捕获并映射为 502。
    """

    # 1. 安全边界（铁律 #3：关键词为主、LLM 补漏，结论回落固定话术）
    boundary = check(query, llm)
    if boundary.blocked:
        return ChatResult(
            blocked=True,
            category=boundary.category.value,
            boundary_message=boundary.message,
        )

    # 2. 意图分类（任务三：失败降级 drug_info，不阻断）
    intent = _classify_intent(llm, query)

    # 2.5 药名解析：LLM 抽取优先，空名时确定性扫描兜底（铁律 #1 确定性优先）
    effective, ambiguous = _effective_drug_names(query, intent, drug_repo)

    # 3. 按名 ∪ 整句检索 RAG（铁律 #2：回答必须带引用；总量封顶）
    citations = _retrieve_citations(retriever, query, intent, effective)

    # 4. 检查意图（药-药 / 药-物质相互作用）→ 确定性规则引擎检测
    check_context: str | None = None
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
        check_context = format_check_report_for_prompt(
            report, ambiguities=ambiguous or None
        )
        # 与 format_check_report_for_prompt 的渲染条件严格对齐：触发规则 /
        # 叠加警告 / 未收录 / 近似匹配 / 共享成分（sources≥2）任一进了 prompt，
        # 就算有确定性发现——抑制「无引用」注记，避免与已传达的结论矛盾。
        has_findings = bool(
            report.triggered_rules
            or report.overlap.warnings
            or report.unresolved_drugs
            or ambiguous
            or any(len(t.sources) >= 2 for t in report.overlap.overlapping)
        )
    elif ambiguous:
        # 非检查意图下的近似匹配也必须披露（铁律 #4：不确定就明说，不静默）
        check_context = format_ambiguity_note(ambiguous)
        has_findings = True

    # 5. 构造含 RAG + 冲突结论的 messages 并调用 LLM
    messages = build_chat_messages(query, citations, check_context=check_context)
    llm_answer = llm.complete_json(messages, LLMAnswer)

    # 6. 低置信度兜底（铁律 #4：拿不准必须明说"不确定"）
    full_answer = llm_answer.answer
    if llm_answer.confidence < _LOW_CONFIDENCE_THRESHOLD:
        full_answer += _LOW_CONFIDENCE_NOTE

    # 7. 引用缺失兜底（铁律 #2 代码防线）
    if not llm_answer.citations_used and not has_findings:
        full_answer += _NO_CITATION_NOTE

    # 8. 代码追加固定免责声明（铁律 #5）
    full_answer += _DISCLAIMER

    return ChatResult(
        blocked=False,
        answer=full_answer,
        confidence=llm_answer.confidence,
        citations=citations,
        disclaimer=_DISCLAIMER,
    )


__all__ = ["ChatResult", "process_chat"]

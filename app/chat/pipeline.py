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
from app.prompts.formatters import format_check_report_for_prompt
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


def _merge_citations(retriever: Retriever, terms: list[str]) -> list[Citation]:
    """对多个检索词逐一检索并去重合并（保持首次出现顺序）。"""
    merged: list[Citation] = []
    seen: set[tuple[str, str, str]] = set()
    for term in terms:
        term = term.strip()
        if not term:
            continue
        for c in retriever.search(term):
            key = (c.brand_name, c.section, c.excerpt)
            if key in seen:
                continue
            seen.add(key)
            merged.append(c)
    return merged


def _brand_patterns(brands: list[dict]) -> list[tuple[str, str]]:
    """构造 (匹配模式, 存储商品名) 列表，按模式长度降序。

    模式 = 存储商品名本身 ＋ 去注解核名（下划线前的产品名，如
    扶他林_外用 → 扶他林）。注解词（下划线之后）不作模式，避免
    「外用药膏」误命中。贪心最长匹配靠此排序 + 命中置空实现。
    """
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
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
                seen.add(a)
                pairs.append((a, name))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def _scan_brand_names(query: str, brands: list[dict]) -> list[str]:
    """确定性扫描 query 中提及的存储商品名（无 LLM）。

    在 query 的可变副本上按模式长度降序贪心匹配：命中即把该跨度置空，
    使套在已命中长名里的短名不再二次触发（如「三九感冒灵」吃掉「感冒灵」），
    而不重叠的多个真提及（如「泰诺和白加黑」）各自保留。返回去重保序的存储名。
    """
    if not query:
        return []
    work = query
    found: list[str] = []
    found_set: set[str] = set()
    for pattern, stored in _brand_patterns(brands):
        idx = work.find(pattern)
        if idx >= 0:
            work = work[:idx] + "\x00" * len(pattern) + work[idx + len(pattern) :]
            if stored not in found_set:
                found_set.add(stored)
                found.append(stored)
    return found


def _effective_drug_names(
    query: str, intent: IntentResult, drug_repo: DrugReader
) -> list[str]:
    """LLM 抽取药名 ∪ 确定性扫描药名，去重保序。

    扫描是增强：list_drugs 或匹配失败一律降级为空名单，绝不阻断主流程
    （铁律 #1 确定性优先，且与流水线「处处降级」哲学一致）。
    """
    try:
        brands = drug_repo.list_drugs()
    except Exception:  # noqa: BLE001 - 扫描是增强，失败不得阻断
        logger.warning("品牌名扫描取列表失败，跳过扫描", exc_info=True)
        brands = []
    seen: set[str] = set()
    out: list[str] = []
    for n in (*intent.drug_names, *_scan_brand_names(query, brands)):
        n = (n or "").strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _retrieve_citations(
    retriever: Retriever,
    query: str,
    intent: IntentResult,
    effective_drug_names: list[str],
) -> list[Citation]:
    """按「有效药名名单」选择 RAG 检索策略。

    effective_drug_names = LLM 抽取 ∪ 确定性扫描。非空时按名单合并检索
    （lifestyle 意图再并上自报物质）；完全无名单才回退整句 query 检索。
    这把 drug_info 从「整句搜」升级为「按药名搜」，是修引用掉 0 的关键。
    """
    terms = list(effective_drug_names)
    if intent.intent is IntentCategory.LIFESTYLE_INTERACTION:
        for s in intent.lifestyle_substances:
            s = (s or "").strip()
            if s and s not in terms:
                terms.append(s)
    if terms:
        return _merge_citations(retriever, terms)
    return retriever.search(query)


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

    # 2.5 确定性商品名扫描兜底：LLM 名 ∪ 扫描名（铁律 #1 确定性优先）
    effective = _effective_drug_names(query, intent, drug_repo)

    # 3. 按有效名单检索 RAG（铁律 #2：回答必须带引用）
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
        check_context = format_check_report_for_prompt(report)
        has_findings = bool(
            report.triggered_rules
            or report.overlap.warnings
            or report.unresolved_drugs
        )

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

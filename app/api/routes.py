"""PillClear API 路由：用药咨询 / 健康检查。

/chat 是一个编排 RAG + 规则引擎 + LLM 的智能体，而非裸 LLM 问答：
    安全边界（关键词 + LLM 补漏）→ 意图分类 → 按意图检索 RAG
    →（冲突意图）确定性规则引擎检测 → LLM 生成大白话 → 各级兜底 → 免责声明。

铁律落实：
- #1 冲突 / 剂量判断走规则引擎，LLM 只翻译结论；
- #2 回答强制带说明书引用，代码对「无引用」兜底；
- #3 能力边界关键词为主、LLM 补漏，结论回落固定话术；
- #4 低置信度 / 未收录药品明说，不静默；
- #5 代码追加固定免责声明。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.api.deps import (
    get_llm_client,
    get_medbox_service,
    get_retriever,
    get_settings,
)
from app.api.schemas import Citation, ChatRequest, ChatResponse, LLMAnswer
from app.config import Settings
from app.core.safety import check_boundary_with_llm
from app.llm.client import LLMClient
from app.llm.errors import LLMRetryExhausted
from app.medbox.schemas import ConflictReport, Medbox, MedboxItem
from app.medbox.service import MedboxService
from app.prompts.chat import (
    build_chat_messages,
    format_conflict_report_for_prompt,
)
from app.prompts.intent import (
    IntentCategory,
    IntentResult,
    build_intent_messages,
)
from app.rag.retriever import Retriever

logger = logging.getLogger("app.api")

router = APIRouter()

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
# prompt 已要求模型必须引用，此处是最后一道防线。
_NO_CITATION_NOTE = (
    "\n\n⚠️ 我注意到上面的回答没有引用具体的说明书原文，"
    "建议你查阅原药品说明书确认，或咨询药师。"
)

# 意图分类用低 max_tokens 压低延迟（任务三：端到端 < 1s 的设计目标）。
_INTENT_MAX_TOKENS = 150


# ── 编排辅助函数 ─────────────────────────────────────────────


def _classify_intent(llm_client: LLMClient, query: str) -> IntentResult:
    """LLM 意图分类（任务三）。失败降级为 drug_info，绝不阻断主流程。"""
    try:
        return llm_client.complete_json(
            build_intent_messages(query),
            IntentResult,
            max_tokens=_INTENT_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 - 分类失败必须降级而非 502
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
            key = (c.drug_name, c.section, c.excerpt)
            if key in seen:
                continue
            seen.add(key)
            merged.append(c)
    return merged


def _retrieve_citations(
    retriever: Retriever, query: str, intent: IntentResult
) -> list[Citation]:
    """按意图选择 RAG 检索策略（任务三）。

    - conflict_check：用提取的 drug_names 逐一检索，合并结果；
    - lifestyle_interaction：用 drug_names + lifestyle_substances 检索；
    - drug_info / general_health / 未提取到药名：用原始 query 检索。
    """
    if intent.intent is IntentCategory.CONFLICT_CHECK and intent.drug_names:
        return _merge_citations(retriever, intent.drug_names)
    if intent.intent is IntentCategory.LIFESTYLE_INTERACTION:
        terms = [*intent.drug_names, *intent.lifestyle_substances]
        if terms:
            return _merge_citations(retriever, terms)
    return retriever.search(query)


def _run_conflict_check(
    service: MedboxService, intent: IntentResult
) -> ConflictReport:
    """用意图提取的药名跑确定性规则引擎（任务四，零 LLM，铁律 #1）。

    /chat 场景只有药名、没有 drug_id，而 check_conflicts 按 brand_name 解析成分、
    drug_id 仅作内部 map 键——故以枚举序号占位 drug_id，未入库药品由服务层
    落入 unresolved_drugs 明示（铁律 #4）。
    """
    items = [
        MedboxItem(drug_id=idx + 1, brand_name=name.strip())
        for idx, name in enumerate(intent.drug_names)
        if name.strip()
    ]
    return service.check_conflicts(
        Medbox(items=items), intent.lifestyle_substances or None
    )


# ── 路由 ───────────────────────────────────────────────────

@router.get("/health")
async def health() -> dict[str, str]:
    """健康检查。"""
    return {"status": "ok"}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
    retriever: Retriever = Depends(get_retriever),
    medbox_service: MedboxService = Depends(get_medbox_service),
) -> ChatResponse:
    """用药咨询主入口（编排 RAG + 规则引擎 + LLM）。

    流程：安全边界（关键词 + LLM 补漏）→ 意图分类 → 按意图检索 RAG
    →（冲突意图）规则引擎检测 → LLM 生成 → 低置信度 / 无引用兜底 → 免责声明。
    """

    # 1. 安全边界（铁律 #3：关键词为主、LLM 补漏，结论回落固定话术）
    boundary = await run_in_threadpool(
        check_boundary_with_llm, request.query, llm_client
    )
    if boundary.blocked:
        return ChatResponse(
            blocked=True,
            category=boundary.category.value,
            boundary_message=boundary.message,
            disclaimer=None,
        )

    # 2. 意图分类（任务三：失败降级 drug_info，不阻断）
    intent = await run_in_threadpool(_classify_intent, llm_client, request.query)

    # 3. 按意图检索 RAG（铁律 #2：回答必须带引用）
    citations = await run_in_threadpool(
        _retrieve_citations, retriever, request.query, intent
    )

    # 4. 冲突意图 → 确定性规则引擎检测（任务四，铁律 #1：零 LLM）
    conflict_context: str | None = None
    has_conflict_findings = False
    if intent.intent in (
        IntentCategory.CONFLICT_CHECK,
        IntentCategory.LIFESTYLE_INTERACTION,
    ):
        report = await run_in_threadpool(_run_conflict_check, medbox_service, intent)
        conflict_context = format_conflict_report_for_prompt(report)
        has_conflict_findings = bool(
            report.triggered_rules
            or report.overlap.warnings
            or report.unresolved_drugs
        )

    # 5. 构造含 RAG + 冲突结论的 messages 并调用 LLM
    messages = build_chat_messages(
        request.query, citations, conflict_context=conflict_context
    )

    try:
        llm_answer = await run_in_threadpool(
            llm_client.complete_json, messages, LLMAnswer
        )
    except LLMRetryExhausted as exc:
        raise HTTPException(
            status_code=502,
            detail="AI 服务暂时不可用，请稍后重试。",
        ) from exc

    # 6. 低置信度兜底（铁律 #4：拿不准必须明说"不确定"）
    full_answer = llm_answer.answer
    if llm_answer.confidence < _LOW_CONFIDENCE_THRESHOLD:
        full_answer += _LOW_CONFIDENCE_NOTE

    # 7. 引用缺失兜底（铁律 #2 代码防线）。
    #    若规则引擎已给出确定性冲突结论，则结论来源是规则引擎而非说明书检索，
    #    不再追加「查阅说明书」提示，避免与冲突结论互相打架。
    if not llm_answer.citations_used and not has_conflict_findings:
        full_answer += _NO_CITATION_NOTE

    # 8. 代码追加固定免责声明（铁律 #5）
    full_answer += _DISCLAIMER

    return ChatResponse(
        blocked=False,
        answer=full_answer,
        confidence=llm_answer.confidence,
        citations=citations,
        sources_note=None,
        disclaimer=_DISCLAIMER,
    )

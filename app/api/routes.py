"""PillClear API 路由：用药咨询 / 健康检查。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_llm_client, get_retriever, get_settings
from app.api.schemas import ChatRequest, ChatResponse, LLMAnswer
from app.config import Settings
from app.core.safety import check_boundary
from app.llm.client import LLMClient
from app.llm.errors import LLMRetryExhausted
from app.rag.retriever import Retriever

router = APIRouter()

# ── 提示词 & 固定文案 ──────────────────────────────────────

_CHAT_SYSTEM_PROMPT = (
    "你是 PillClear，一个面向 18-30 岁年轻人的用药安全助手。"
    "你的任务是帮用户理解非处方药（OTC）和保健品的说明书，用大白话解释。\n\n"
    "重要规则：\n"
    "- 语气年轻、简短直接，用日常口语，像朋友在聊天。\n"
    "- 绝不能编造药物信息；拿不准时必须明确说「不确定」并建议咨询药师。\n"
    "- 只回答非处方药和保健品相关问题。\n"
    "- 回答中不要给出诊断，不要推荐处方药。\n"
    "- 如果用户描述的症状听起来紧急（比如呼吸困难、剧烈胸痛），"
    "提醒他们立刻就医，不要只靠吃药。\n\n"
    "请以 JSON 格式输出："
    '{"answer": "你的大白话回答", "confidence": 0.0~1.0 的置信度}'
)

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

_SOURCES_NOTE_RAG_PENDING = (
    "📖 说明书原文检索功能开发中，以上回答仅供参考，请务必查阅原药品说明书。"
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
) -> ChatResponse:
    """用药咨询主入口。

    流程：安全边界检查 → 引用检索 → LLM 生成大白话回答
    → 低置信度兜底 → 追加免责声明。
    """

    # 1. 安全边界检查（铁律 #3）
    boundary = check_boundary(request.query)
    if boundary.blocked:
        return ChatResponse(
            blocked=True,
            category=boundary.category.value,
            boundary_message=boundary.message,
            disclaimer=None,
        )

    # 2. 引用检索（铁律 #2：回答必须带引用）。当前为 NullRetriever 占位，
    #    D3 pgvector 检索就绪后替换 get_retriever 即生效，路由无需改动。
    citations = await run_in_threadpool(retriever.search, request.query)

    # 3. 通过安全边界 → LLM 生成回答
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": request.query},
    ]

    try:
        llm_answer = await run_in_threadpool(
            llm_client.complete_json, messages, LLMAnswer
        )
    except LLMRetryExhausted as exc:
        raise HTTPException(
            status_code=502,
            detail="AI 服务暂时不可用，请稍后重试。",
        ) from exc

    # 4. 低置信度兜底（铁律 #4：拿不准必须明说"不确定"）
    full_answer = llm_answer.answer
    if llm_answer.confidence < _LOW_CONFIDENCE_THRESHOLD:
        full_answer += _LOW_CONFIDENCE_NOTE

    # 5. 代码追加固定免责声明（铁律 #5）
    full_answer += _DISCLAIMER

    return ChatResponse(
        blocked=False,
        answer=full_answer,
        confidence=llm_answer.confidence,
        citations=citations,
        # 有引用即视为 RAG 就绪，不再显示"开发中"提示
        sources_note=None if citations else _SOURCES_NOTE_RAG_PENDING,
        disclaimer=_DISCLAIMER,
    )

"""PillClear API 路由：用药咨询 / 健康检查。

/chat 端点是薄 HTTP 适配器——核心编排逻辑在 app/chat/pipeline.py。
路由层只做：参数解析 → 调用 pipeline → 映射为 HTTP 响应 / 错误。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.api.deps import (
    get_drug_repository,
    get_llm_client,
    get_retriever,
    get_rule_set,
    get_settings,
)
from app.api.schemas import ChatRequest, ChatResponse
from app.chat.pipeline import process_chat
from app.config import Settings
from app.knowledge.repository import DrugReader
from app.llm.client import LLMClient
from app.llm.errors import LLMRetryExhausted
from app.rag.retriever import Retriever
from app.rules.schemas import RuleSet

router = APIRouter()


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
    rules: RuleSet = Depends(get_rule_set),
    drug_repo: DrugReader = Depends(get_drug_repository),
) -> ChatResponse:
    """用药咨询主入口。

    完整编排逻辑见 app/chat/pipeline.py；路由层仅做参数解析与错误映射。
    """

    try:
        result = await run_in_threadpool(
            process_chat, request.query, llm_client, retriever, rules, drug_repo
        )
    except LLMRetryExhausted as exc:
        raise HTTPException(
            status_code=502,
            detail="AI 服务暂时不可用，请稍后重试。",
        ) from exc

    return ChatResponse(
        blocked=result.blocked,
        category=result.category,
        boundary_message=result.boundary_message,
        answer=result.answer,
        confidence=result.confidence,
        citations=result.citations,
        sources_note=None,
        disclaimer=result.disclaimer,
    )

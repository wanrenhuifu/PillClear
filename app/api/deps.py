"""FastAPI 依赖注入：Settings / LLMClient / Retriever 等。"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.config import Settings
from app.llm import LLMClient
from app.rag.retriever import NullRetriever, Retriever


@lru_cache()
def get_settings() -> Settings:
    """全局 Settings 单例（首次调用时从 .env 加载，后续命中缓存）。"""
    return Settings()


# Settings 不可哈希（pydantic BaseModel），不能用 lru_cache 缓存依赖它的工厂；
# 改用按对象 id 的单例表：表项持有 LLMClient → 引用 Settings，键永不复用。
_LLM_CLIENTS: dict[int, LLMClient] = {}


def get_llm_client(
    settings: Settings = Depends(get_settings),
) -> LLMClient:
    """LLMClient 单例（每个 Settings 实例一份）。

    底层 openai/httpx 连接池跨请求复用，避免每请求新建客户端造成的
    TLS 握手与连接池 churn；测试注入不同 Settings 时自然另建一份。
    """
    client = _LLM_CLIENTS.get(id(settings))
    if client is None:
        client = LLMClient(settings)
        _LLM_CLIENTS[id(settings)] = client
    return client


@lru_cache()
def get_retriever() -> Retriever:
    """引用检索器。当前 RAG 未接入（D3），返回 NullRetriever 占位。"""
    return NullRetriever()

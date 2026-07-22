"""FastAPI 依赖注入：Settings / LLMClient / Retriever 等。"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.config import Settings
from app.knowledge.embedder import Embedder
from app.knowledge.repository import (
    DrugRepository,
    InMemoryDrugRepository,
    PostgresDrugRepository,
)
from app.llm import LLMClient
from app.medbox.service import MedboxService
from app.rag.retriever import NullRetriever, PgVectorRetriever, Retriever
from app.rules.engine import DEFAULT_RULES_DIR, load_rules
from app.rules.schemas import RuleSet


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


# 与 _LLM_CLIENTS 同理（Settings 不可哈希）；表项额外持有 Settings 引用：
# NullRetriever 本身不引用 Settings，若不钉住，Settings 被 GC 后 id 复用
# 会把旧占位实现错发给新的非空 database_url 配置。
_RETRIEVERS: dict[int, tuple[Settings, Retriever]] = {}


def get_retriever(
    settings: Settings = Depends(get_settings),
) -> Retriever:
    """引用检索器：配置了 DATABASE_URL → pgvector 检索；未配置 → NullRetriever 占位。"""
    entry = _RETRIEVERS.get(id(settings))
    if entry is not None:
        return entry[1]
    retriever: Retriever = (
        PgVectorRetriever(embedder=Embedder(settings), dsn=settings.database_url)
        if settings.database_url
        else NullRetriever()
    )
    _RETRIEVERS[id(settings)] = (settings, retriever)
    return retriever


@lru_cache()
def get_rule_set() -> RuleSet:
    """全局规则集单例（D4）。规则是纯静态 YAML 数据、无 Settings 依赖，
    lru_cache 安全；测试经 dependency_overrides 整体替换，无隔离陷阱。"""
    return load_rules(DEFAULT_RULES_DIR)


# 同 _LLM_CLIENTS / _RETRIEVERS：Settings 不可哈希，按 id 缓存；
# 表项钉住 Settings——InMemoryDrugRepository 不引用 Settings，不钉住的话
# Settings 被 GC 后 id 复用会把旧仓储错发给新的数据库配置。
_REPOSITORIES: dict[int, tuple[Settings, DrugRepository]] = {}


def get_drug_repository(
    settings: Settings = Depends(get_settings),
) -> DrugRepository:
    """药品仓储：配置了 DATABASE_URL → Postgres；未配置 → 空内存仓储
    （降级：所有药品都会落到 unresolved_drugs，端点仍正常应答）。"""
    entry = _REPOSITORIES.get(id(settings))
    if entry is not None:
        return entry[1]
    repo: DrugRepository = (
        PostgresDrugRepository(settings.database_url)
        if settings.database_url
        else InMemoryDrugRepository()
    )
    _REPOSITORIES[id(settings)] = (settings, repo)
    return repo


def get_medbox_service(
    rules: RuleSet = Depends(get_rule_set),
    repo: DrugRepository = Depends(get_drug_repository),
) -> MedboxService:
    """药箱服务：无状态编排器，每请求新建（D4）。"""
    return MedboxService(rules, repo)

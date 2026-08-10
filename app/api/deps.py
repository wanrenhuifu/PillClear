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
from app.knowledge.sqlite_repo import SQLiteDrugRepository
from app.llm import LLMClient
from app.medbox.repository import (
    InMemoryUserMedboxRepository,
    PostgresUserMedboxRepository,
    UserMedboxRepository,
)
from app.medbox.service import MedboxService
from app.medbox.sqlite_medbox_repo import SQLiteUserMedboxRepository
from app.rag import KeywordRetriever, NullRetriever, PgVectorRetriever, Retriever
from app.reminder.repository import (
    InMemoryReminderRepository,
    PostgresReminderRepository,
    ReminderRepository,
)
from app.reminder.service import ReminderService
from app.reminder.sqlite_reminder_repo import SQLiteReminderRepository
from app.rules.engine import DEFAULT_RULES_DIR, load_rules
from app.rules.schemas import RuleSet


@lru_cache
def get_settings() -> Settings:
    """全局 Settings 单例（首次调用时从 .env 加载，后续命中缓存）。"""
    return Settings()


def _resolve_backend(settings: Settings) -> str:
    """后端选择：显式 pillclear_backend 优先；否则配了 database_url 用 supabase，
    未配置则回落本地 sqlite（B 部分：无外部依赖的默认后端）。"""
    if settings.pillclear_backend:
        return settings.pillclear_backend
    return "supabase" if settings.database_url else "sqlite"


def _resolve_db_path(settings: Settings) -> str:
    """SQLite 数据库文件路径：data_dir（自动按平台解析）/pillclear.db。"""
    data_dir = settings.resolved_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "pillclear.db")


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
    if settings.pillclear_backend == "sqlite" or (
        not settings.pillclear_backend and not settings.database_url
    ):
        # SQLite 后端 → 关键词精确匹配检索（无需 embedding）。
        retriever: Retriever = KeywordRetriever(db_path=_resolve_db_path(settings))
    else:
        # 现有逻辑一字不改：配置 DATABASE_URL → pgvector；未配置 → NullRetriever。
        # 检索器不随 _resolve_backend 自动切 sqlite——无配置时保留「开发中」占位
        # （既有测试与 /chat 降级语义所系），仅在显式 pillclear_backend=sqlite 时启用。
        retriever = (
            PgVectorRetriever(embedder=Embedder(settings), dsn=settings.database_url)
            if settings.database_url
            else NullRetriever()
        )
    _RETRIEVERS[id(settings)] = (settings, retriever)
    return retriever


@lru_cache
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
    """药品仓储：sqlite 后端 → 本地 SQLite；supabase 且配置了 DATABASE_URL →
    Postgres；supabase 但缺连接串 → 空内存仓储降级（所有药品落 unresolved_drugs，
    端点仍正常应答）。"""
    entry = _REPOSITORIES.get(id(settings))
    if entry is not None:
        return entry[1]
    backend = _resolve_backend(settings)
    if backend == "sqlite":
        repo: DrugRepository = SQLiteDrugRepository(_resolve_db_path(settings))
    elif settings.database_url:
        repo = PostgresDrugRepository(settings.database_url)
    else:
        repo = InMemoryDrugRepository()
    _REPOSITORIES[id(settings)] = (settings, repo)
    return repo


# 同 _REPOSITORIES：Settings 不可哈希，按 id 缓存并钉住 Settings 引用。
_USER_REPOSITORIES: dict[int, tuple[Settings, UserMedboxRepository]] = {}


def get_user_medbox_repository(
    settings: Settings = Depends(get_settings),
    drug_repo: DrugRepository = Depends(get_drug_repository),
) -> UserMedboxRepository:
    """药箱仓储：跟随药品仓储的后端类型，保持同一存储一致性。

    - drug_repo 是 SQLiteDrugRepository → SQLite 药箱仓储，共享其连接（FK 已开）；
    - drug_repo 是 PostgresDrugRepository → Postgres 药箱仓储；
    - drug_repo 是 InMemory（测试覆盖 / 降级）→ 内存药箱仓储，避免无谓建文件。
    """
    entry = _USER_REPOSITORIES.get(id(settings))
    if entry is not None:
        return entry[1]
    if isinstance(drug_repo, SQLiteDrugRepository):
        # 共享连接必须共享锁：两仓储在不同线程池 worker 里并发执行，
        # 各持一把锁仍会交错使用同一连接（code review #13）。
        repo: UserMedboxRepository = SQLiteUserMedboxRepository(
            drug_repo.connection, lock=drug_repo.lock
        )
    elif isinstance(drug_repo, PostgresDrugRepository):
        repo = PostgresUserMedboxRepository(settings.database_url)
    else:
        # InMemory（测试覆盖 / 无库降级）：无 drugs 表可 JOIN，brand 回退占位名。
        repo = InMemoryUserMedboxRepository()
    _USER_REPOSITORIES[id(settings)] = (settings, repo)
    return repo


def get_medbox_service(
    user_repo: UserMedboxRepository = Depends(get_user_medbox_repository),
) -> MedboxService:
    """药箱 CRUD 服务：绑定持久化仓储，每请求新建。"""
    return MedboxService(user_repo)


# 同 _USER_REPOSITORIES：Settings 不可哈希，按 id 缓存并钉住 Settings 引用。
_REMINDER_REPOSITORIES: dict[int, tuple[Settings, ReminderRepository]] = {}


def get_reminder_repository(
    settings: Settings = Depends(get_settings),
    drug_repo: DrugRepository = Depends(get_drug_repository),
) -> ReminderRepository:
    """提醒仓储：跟随药品仓储的后端类型（同药箱仓储的选型逻辑）。

    - SQLite → 共享药品仓储的连接 + 锁（code review #13）；
    - Postgres → 自建连接的 Postgres 提醒仓储；
    - InMemory（测试覆盖 / 降级）→ 内存提醒仓储。
    """
    entry = _REMINDER_REPOSITORIES.get(id(settings))
    if entry is not None:
        return entry[1]
    if isinstance(drug_repo, SQLiteDrugRepository):
        repo: ReminderRepository = SQLiteReminderRepository(
            drug_repo.connection, lock=drug_repo.lock
        )
    elif isinstance(drug_repo, PostgresDrugRepository):
        repo = PostgresReminderRepository(settings.database_url)
    else:
        repo = InMemoryReminderRepository()
    _REMINDER_REPOSITORIES[id(settings)] = (settings, repo)
    return repo


def get_reminder_service(
    repo: ReminderRepository = Depends(get_reminder_repository),
) -> ReminderService:
    """提醒 CRUD 服务：绑定持久化仓储，每请求新建。"""
    return ReminderService(repo)

"""RAG 引用检索接口 + pgvector 实现（D3）。

铁律 #2：所有用药相关回答必须携带说明书原文引用。
D3 之前路由注入 NullRetriever（返回空引用 + "开发中"提示），现已由
PgVectorRetriever 接替：按余弦近邻检索 insert_chunks，返回说明书原文引用
（excerpt 取 chunk 内容前 200 字符，保证是原文的精确子串）。

降级语义：连接 / 查询 / 向量化任一失败都返回空引用并记 warning，
路由自动回落"开发中"提示——检索层永不炸掉 /chat。
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from typing import Any, Protocol

from app.knowledge.embedder import Embedder
from app.knowledge.schemas import Citation

logger = logging.getLogger("app.rag")

_EXCERPT_MAX_LEN = 200

_SEARCH_SQL = """
SELECT d.brand_name, c.section, c.content,
       c.embedding <=> %s::vector AS distance
FROM insert_chunks c
JOIN drugs d ON d.id = c.drug_id
ORDER BY c.embedding <=> %s::vector
LIMIT %s
"""


def _default_connect(dsn: str) -> Any:
    """建 psycopg3 autocommit 连接并注册 pgvector 适配器。

    延迟导入 psycopg / pgvector，未安装或未配置 DATABASE_URL 时不影响其余模块导入
    （同 PostgresDrugRepository 模式）。
    """
    try:
        import psycopg  # noqa: PLC0415
        from pgvector.psycopg import register_vector  # noqa: PLC0415
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError(
            "Postgres 后端需要 psycopg + pgvector，请先安装：pip install -e '.[postgres]'"
        ) from exc

    conn = psycopg.connect(dsn, autocommit=True)
    register_vector(conn)
    return conn


class Retriever(Protocol):
    """引用检索器：为用户问题检索说明书原文摘录。"""

    def search(self, query: str, limit: int = 5) -> list[Citation]:
        """返回与 query 相关的说明书原文引用（excerpt 须为 chunk 内容精确子串）。"""
        ...


class NullRetriever:
    """占位实现：恒返回空引用（RAG 未配置 / 缺 DATABASE_URL 时的回落）。"""

    def search(self, query: str, limit: int = 5) -> list[Citation]:
        return []


class PgVectorRetriever:
    """pgvector 余弦近邻检索（D3）。

    构造不触网：连接延迟到首次 search，get_retriever 构造安全且可测。
    连接 / 查询 / 向量化失败一律降级为空引用并记 warning，不炸 /chat。

    search 经 run_in_threadpool 并发执行，而 psycopg3 同步连接禁止重叠操作，
    故 DB 段用锁串行化（向量化在锁外，慢 embedding 不串行）。
    """

    def __init__(
        self,
        embedder: Embedder,
        dsn: str,
        *,
        connect: Callable[[str], Any] | None = None,
    ) -> None:
        self._embedder = embedder
        self._dsn = dsn
        # connect 可注入：测试传假连接，免 monkeypatch（同 Embedder(client=...) 房风）。
        self._connect = connect or _default_connect
        self._conn: Any | None = None
        self._lock = threading.Lock()

    def search(self, query: str, limit: int = 5) -> list[Citation]:
        # 两段式 try/except：向量化失败不丢弃健康的数据库连接。
        try:
            vector = self._embedder.embed([query])[0]
        except Exception:
            logger.warning("RAG 向量化失败，降级为空引用", exc_info=True)
            return []
        try:
            with self._lock:
                conn = self._get_conn()
                with conn.cursor() as cur:
                    cur.execute(_SEARCH_SQL, (vector, vector, limit))
                    rows = cur.fetchall()
        except Exception:
            logger.warning("RAG 检索失败，降级为空引用", exc_info=True)
            self._reset_conn()
            return []
        return [
            Citation(
                brand_name=brand_name,
                section=section,
                excerpt=content[:_EXCERPT_MAX_LEN],
            )
            for brand_name, section, content, _distance in rows
        ]

    def _get_conn(self) -> Any:
        """按需建连。调用方须持有 self._lock。"""
        if self._conn is None:
            self._conn = self._connect(self._dsn)
        return self._conn

    def _reset_conn(self) -> None:
        """丢弃失败连接（best-effort close），下次 search 自动重连。"""
        with self._lock:
            conn, self._conn = self._conn, None
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


__all__ = ["NullRetriever", "PgVectorRetriever", "Retriever"]

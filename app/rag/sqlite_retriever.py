"""SQLite 版引用检索器（B 部分）：sqlite-vec vec0 KNN + cosine 距离。

实现与 PgVectorRetriever 同一个 Retriever Protocol，二者并存：
- PgVector 用 `embedding <=> query` 余弦近邻；
- SQLite 用 vec0 虚拟表 `embedding MATCH query AND k = N`，建表时声明
  distance_metric=cosine，口径与 pgvector 一致。

降级语义与 PgVectorRetriever 完全对齐：向量化 / 查询任一失败都返回空引用
并记 warning，检索层永不炸掉 /chat。WAL 模式自带读写并发，故不需要锁。
"""

from __future__ import annotations

import logging
import sqlite3

from app.knowledge.embedder import Embedder
from app.knowledge.schemas import Citation
from app.knowledge.sqlite_repo import open_sqlite

logger = logging.getLogger("app.rag")

_EXCERPT_MAX_LEN = 200

# vec0 KNN 子查询（rowid + cosine 距离）→ 关联 insert_chunks 取原文 → drugs 取商品名。
_SEARCH_SQL = """
SELECT d.brand_name, c.section, c.content, v.distance
FROM (SELECT rowid, distance FROM vec_chunks WHERE embedding MATCH ? AND k = ?) v
JOIN insert_chunks c ON c.id = v.rowid
JOIN drugs d ON d.id = c.drug_id
ORDER BY v.distance
"""


class SQLiteVectorRetriever:
    """sqlite-vec 余弦近邻检索。构造不触网：连接延迟到首次 search。"""

    def __init__(
        self,
        embedder: Embedder,
        db_path: str = ":memory:",
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self._embedder = embedder
        self._db_path = db_path
        # connection 可注入（与 SQLiteDrugRepository 共享同一数据库）；
        # 未注入则首次 search 时 open_sqlite 延迟建连。
        self._conn: sqlite3.Connection | None = connection

    def search(self, query: str, limit: int = 5) -> list[Citation]:
        from sqlite_vec import serialize_float32  # noqa: PLC0415

        # 两段式 try/except：向量化失败不触碰数据库连接。
        try:
            vector = self._embedder.embed([query])[0]
        except Exception:
            logger.warning("RAG 向量化失败，降级为空引用", exc_info=True)
            return []
        try:
            conn = self._get_conn()
            rows = conn.execute(
                _SEARCH_SQL, (serialize_float32(vector), limit)
            ).fetchall()
        except Exception:
            logger.warning("RAG 检索失败，降级为空引用", exc_info=True)
            return []
        return [
            Citation(
                brand_name=brand_name,
                section=section,
                excerpt=content[:_EXCERPT_MAX_LEN],
            )
            for brand_name, section, content, _distance in rows
        ]

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = open_sqlite(self._db_path)
        return self._conn


__all__ = ["SQLiteVectorRetriever"]

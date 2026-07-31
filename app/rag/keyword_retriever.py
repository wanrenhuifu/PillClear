"""基于关键词/药名的精确匹配检索器（替代向量检索）。

策略：
  1. 先用搜索词精确匹配 drugs.brand_name；
  2. 未命中则用 LIKE 模糊匹配品牌名；
  3. 仍未命中则搜索章节内容（section / content LIKE）。

无 embedding 依赖，无外部服务依赖。
"""

from __future__ import annotations

import logging
import sqlite3
import threading

from app.knowledge.schemas import Citation
from app.knowledge.sqlite_repo import open_sqlite

logger = logging.getLogger("app.rag")

_EXCERPT_MAX_LEN = 200

_SEARCH_BY_BRAND_EXACT = """
SELECT d.brand_name, c.section, c.content
FROM insert_chunks c
JOIN drugs d ON d.id = c.drug_id
WHERE d.brand_name = ?
LIMIT ?
"""

_SEARCH_BY_BRAND_LIKE = """
SELECT d.brand_name, c.section, c.content
FROM insert_chunks c
JOIN drugs d ON d.id = c.drug_id
WHERE d.brand_name LIKE ?
LIMIT ?
"""

_SEARCH_BY_CONTENT = """
SELECT d.brand_name, c.section, c.content
FROM insert_chunks c
JOIN drugs d ON d.id = c.drug_id
WHERE c.content LIKE ? OR c.section LIKE ?
LIMIT ?
"""


class KeywordRetriever:
    """SQLite 关键词检索器：按药名精确匹配 → 模糊匹配 → 全文搜索降级。

    构造不触网：连接延迟到首次 search。
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = connection
        # deps 缓存单实例，search 经 run_in_threadpool 并发执行；
        # check_same_thread=False 单连接必须串行使用（含懒建连本身）。
        self._lock = threading.RLock()

    def search(self, query: str, limit: int = 5) -> list[Citation]:
        term = query.strip()
        if not term:
            return []

        try:
            return self._search(term, limit)
        except Exception:
            logger.warning("关键词检索失败，降级为空引用", exc_info=True)
            return []

    def _search(self, term: str, limit: int) -> list[Citation]:
        with self._lock:
            conn = self._get_conn()

            # 1. 精确匹配品牌名（limit 在三级降级上一律生效，防止全章节倾倒进 prompt）
            rows = conn.execute(_SEARCH_BY_BRAND_EXACT, (term, limit)).fetchall()
            if rows:
                return self._rows_to_citations(rows)

            # 2. 模糊匹配品牌名（搜索词为药名子串；多药命中时同样受 limit 截断）
            rows = conn.execute(
                _SEARCH_BY_BRAND_LIKE, (f"%{term}%", limit)
            ).fetchall()
            if rows:
                return self._rows_to_citations(rows)

            # 3. 降级到章节内容搜索
            like_term = f"%{term}%"
            rows = conn.execute(
                _SEARCH_BY_CONTENT, (like_term, like_term, limit)
            ).fetchall()
            return self._rows_to_citations(rows)

    def _rows_to_citations(self, rows: list[tuple]) -> list[Citation]:
        return [
            Citation(
                brand_name=brand_name,
                section=section,
                excerpt=content[:_EXCERPT_MAX_LEN],
            )
            for brand_name, section, content in rows
        ]

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = open_sqlite(self._db_path)
        return self._conn


__all__ = ["KeywordRetriever"]

"""SQLite 版药品仓储 + 共享 schema / 连接管理。

与 PostgresDrugRepository 实现同一个 DrugRepository Protocol，二者并存：
- Postgres 用 pgvector 的 vector(1024) 列存向量；
- SQLite 不再依赖向量检索——改用关键词精确匹配（app/rag/keyword_retriever.py）。

铁律落实：
- ingredients_verified 写入强制 0（与 Postgres/InMemory 一致）；
- WAL 模式 + foreign_keys=ON（文件库；:memory: 不支持 WAL，自动回落 memory）；
- save_drug 用 BEGIN IMMEDIATE / COMMIT 保证「药品行 + chunks」原子。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.knowledge.schemas import DrugRecord

# 一条 chunk：(section, content)。嵌入存于第 3 位（Postgres 兼容），SQLite 忽略。
ChunkRow = tuple[str, str, list[float]]

# 全部表由本模块统一创建（SQLite 端不需要 migration 文件）。
_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    create table if not exists drugs (
        id integer primary key autoincrement,
        brand_name text not null unique,
        generic_name text,
        otc_category text,
        dosage_form text,
        specification text,
        approval_number text,
        ingredients text not null default '[]',
        ingredients_verified integer not null default 0,
        created_at text not null default (datetime('now'))
    )
    """,
    """
    create table if not exists insert_chunks (
        id integer primary key autoincrement,
        drug_id integer not null references drugs(id) on delete cascade,
        section text not null,
        content text not null
    )
    """,
    """
    create table if not exists users (
        id integer primary key autoincrement,
        device_id text not null unique,
        created_at text not null default (datetime('now'))
    )
    """,
    """
    create table if not exists user_medbox (
        id integer primary key autoincrement,
        user_id integer not null references users(id) on delete cascade,
        drug_id integer not null references drugs(id) on delete cascade,
        dosage_per_day integer,
        added_at text not null default (datetime('now')),
        unique(user_id, drug_id)
    )
    """,
    """
    create table if not exists user_reminders (
        id integer primary key autoincrement,
        user_id integer not null references users(id) on delete cascade,
        drug_id integer not null references drugs(id) on delete cascade,
        time_of_day text not null,
        created_at text not null default (datetime('now')),
        unique(user_id, drug_id, time_of_day)
    )
    """,
)


def init_schema(conn: sqlite3.Connection) -> None:
    """在当前连接上幂等建表（纯 SQLite，无扩展依赖）。"""
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)


def open_sqlite(db_path: str, *, foreign_keys: bool = True) -> sqlite3.Connection:
    """打开 SQLite 连接：开 WAL、按需开 foreign_keys、建表。

    isolation_level=None（autocommit）：单语句自动提交，多语句事务由调用方
    显式 BEGIN IMMEDIATE / COMMIT 管理（见 SQLiteDrugRepository.save_drug）。
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.isolation_level = None
    # WAL：读写并发（:memory: 自动回落 memory，不报错）。
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
    init_schema(conn)
    return conn


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """BEGIN IMMEDIATE / COMMIT，异常回滚（autocommit 连接上的显式事务）。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


class SQLiteDrugRepository:
    """sqlite3 + sqlite-vec 的真实入库实现（本地文件 / :memory:）。

    deps 按 Settings 缓存单实例，/chat、/drugs、/medbox 经 run_in_threadpool
    并发执行。check_same_thread=False 的单连接必须串行使用（同
    PgVectorRetriever 的既有模式）：实例级 RLock 包裹一切公共方法；
    共享本连接的仓储（SQLiteUserMedboxRepository）必须共享同一把锁。
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = open_sqlite(db_path)
        self._lock = threading.RLock()

    @property
    def connection(self) -> sqlite3.Connection:
        """暴露底层连接，供 SQLiteUserMedboxRepository 等共享同一数据库。"""
        return self._conn

    @property
    def lock(self) -> threading.RLock:
        """连接串行化锁：共享 self.connection 的仓储必须传入同一把锁。"""
        return self._lock

    # ── 内部实现（不管事务，供公共方法在事务内复用）────────────────────
    def _upsert_drug(self, record: DrugRecord) -> int:
        ingredients = json.dumps(
            [i.model_dump() for i in record.ingredients], ensure_ascii=False
        )
        # 铁律：ingredients_verified 入库强制 0，即使调用方传 True（等人工核对）。
        cur = self._conn.execute(
            """
            insert into drugs (
                brand_name, generic_name, otc_category, dosage_form,
                specification, approval_number, ingredients, ingredients_verified
            ) values (?, ?, ?, ?, ?, ?, ?, 0)
            on conflict (brand_name) do update set
                generic_name    = excluded.generic_name,
                otc_category    = excluded.otc_category,
                dosage_form     = excluded.dosage_form,
                specification   = excluded.specification,
                approval_number = excluded.approval_number,
                ingredients     = excluded.ingredients,
                -- 成分被新抽取结果替换 → 人工核对状态归零（同 Postgres 实现）
                ingredients_verified = 0
            returning id
            """,
            (
                record.brand_name,
                record.metadata.generic_name,
                record.metadata.otc_category,
                record.metadata.dosage_form,
                record.metadata.specification,
                record.metadata.approval_number,
                ingredients,
            ),
        )
        return cur.fetchone()[0]

    def _replace_chunks(self, drug_id: int, chunks: list[ChunkRow]) -> None:
        # 先删后插：保证幂等（无需 vec_chunks 同步——检索走关键词匹配）。
        self._conn.execute("delete from insert_chunks where drug_id = ?", (drug_id,))
        for section, content, _embedding in chunks:
            self._conn.execute(
                "insert into insert_chunks (drug_id, section, content) values (?, ?, ?)",
                (drug_id, section, content),
            )

    # ── DrugRepository Protocol 公共方法 ─────────────────────────────
    def upsert_drug(self, record: DrugRecord) -> int:
        # autocommit 连接：单语句自动提交。
        with self._lock:
            return self._upsert_drug(record)

    def replace_chunks(self, drug_id: int, chunks: list[ChunkRow]) -> None:
        with self._lock, _transaction(self._conn):
            self._replace_chunks(drug_id, chunks)

    def save_drug(self, record: DrugRecord, chunks: list[ChunkRow]) -> int:
        # 同一显式事务内 upsert + 重写 chunks：同成败，杜绝孤儿行 / stale chunks。
        with self._lock, _transaction(self._conn):
            drug_id = self._upsert_drug(record)
            self._replace_chunks(drug_id, chunks)
        return drug_id

    def count_drugs(self) -> int:
        with self._lock:
            return self._conn.execute("select count(*) from drugs").fetchone()[0]

    def count_chunks(self) -> int:
        with self._lock:
            return self._conn.execute(
                "select count(*) from insert_chunks"
            ).fetchone()[0]

    def get_drug_by_brand(self, brand_name: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "select id, brand_name, generic_name, otc_category, dosage_form,"
                " specification, approval_number, ingredients, ingredients_verified"
                " from drugs where brand_name = ?",
                (brand_name,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            data = dict(zip(cols, row, strict=True))
            data["ingredients"] = json.loads(data["ingredients"])
            return data

    def list_drugs(self) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "select id, brand_name, generic_name from drugs order by id"
            )
            return [
                dict(zip(("id", "brand_name", "generic_name"), row, strict=True))
                for row in cur.fetchall()
            ]


__all__ = ["ChunkRow", "SQLiteDrugRepository", "init_schema", "open_sqlite"]

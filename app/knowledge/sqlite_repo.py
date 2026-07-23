"""SQLite 版药品仓储（B 部分）+ 共享 schema / 连接管理。

与 PostgresDrugRepository 实现同一个 DrugRepository Protocol，二者并存：
- Postgres 用 pgvector 的 vector(1024) 列存向量；
- SQLite 用 sqlite-vec 的 vec0 虚拟表（vec_chunks）存向量，rowid 与
  insert_chunks.id 一一对应，replace_chunks 内两表同步重写——ingest.py
  完全不感知后端差异（仍只调 save_drug/replace_chunks）。

铁律落实：
- ingredients_verified 写入强制 0（与 Postgres/InMemory 一致）；
- WAL 模式 + foreign_keys=ON（文件库；:memory: 不支持 WAL，自动回落 memory）；
- save_drug 用 BEGIN IMMEDIATE / COMMIT 保证「药品行 + chunks」原子。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from app.knowledge.schemas import DrugRecord

# 一条 chunk：(section, content, embedding)
ChunkRow = tuple[str, str, list[float]]

# vec0 向量维度，与 embedding_dims 默认值 / pgvector vector(1024) 对齐。
_VECTOR_DIMS = 1024

# 全部表由本模块统一创建（SQLite 端不需要 migration 文件）。
# vec_chunks 用 cosine 距离，与 PgVectorRetriever 的 <=> 余弦近邻口径一致。
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
    f"""
    create virtual table if not exists vec_chunks using vec0(
        embedding float[{_VECTOR_DIMS}] distance_metric=cosine
    )
    """,
)


def init_schema(conn: sqlite3.Connection) -> None:
    """在当前连接上幂等建表（含 vec0 虚拟表，需已加载 sqlite-vec）。"""
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)


def open_sqlite(db_path: str, *, foreign_keys: bool = True) -> sqlite3.Connection:
    """打开 SQLite 连接：加载 sqlite-vec、开 WAL、按需开 foreign_keys、建表。

    isolation_level=None（autocommit）：单语句自动提交，多语句事务由调用方
    显式 BEGIN IMMEDIATE / COMMIT 管理（见 SQLiteDrugRepository.save_drug）。
    """
    import sqlite_vec  # noqa: PLC0415  延迟导入，未安装不影响其余模块

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.isolation_level = None
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
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
    """sqlite3 + sqlite-vec 的真实入库实现（本地文件 / :memory:）。"""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = open_sqlite(db_path)

    @property
    def connection(self) -> sqlite3.Connection:
        """暴露底层连接，供 SQLiteUserMedboxRepository 等共享同一数据库。"""
        return self._conn

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
        from sqlite_vec import serialize_float32  # noqa: PLC0415

        # vec_chunks.rowid == insert_chunks.id：先删旧向量再删旧 chunk。
        old_ids = [
            row[0]
            for row in self._conn.execute(
                "select id from insert_chunks where drug_id = ?", (drug_id,)
            ).fetchall()
        ]
        for chunk_id in old_ids:
            self._conn.execute("delete from vec_chunks where rowid = ?", (chunk_id,))
        self._conn.execute("delete from insert_chunks where drug_id = ?", (drug_id,))
        for section, content, embedding in chunks:
            cur = self._conn.execute(
                "insert into insert_chunks (drug_id, section, content) values (?, ?, ?)",
                (drug_id, section, content),
            )
            self._conn.execute(
                "insert into vec_chunks (rowid, embedding) values (?, ?)",
                (cur.lastrowid, serialize_float32(embedding)),
            )

    # ── DrugRepository Protocol 公共方法 ─────────────────────────────
    def upsert_drug(self, record: DrugRecord) -> int:
        # autocommit 连接：单语句自动提交。
        return self._upsert_drug(record)

    def replace_chunks(self, drug_id: int, chunks: list[ChunkRow]) -> None:
        with _transaction(self._conn):
            self._replace_chunks(drug_id, chunks)

    def save_drug(self, record: DrugRecord, chunks: list[ChunkRow]) -> int:
        # 同一显式事务内 upsert + 重写 chunks：同成败，杜绝孤儿行 / stale chunks。
        with _transaction(self._conn):
            drug_id = self._upsert_drug(record)
            self._replace_chunks(drug_id, chunks)
        return drug_id

    def count_drugs(self) -> int:
        return self._conn.execute("select count(*) from drugs").fetchone()[0]

    def count_chunks(self) -> int:
        return self._conn.execute("select count(*) from insert_chunks").fetchone()[0]

    def _count_vec_chunks(self) -> int:
        """测试辅助：vec0 虚拟表行数（应与 insert_chunks 同步）。"""
        return self._conn.execute("select count(*) from vec_chunks").fetchone()[0]

    def get_drug_by_brand(self, brand_name: str) -> dict[str, Any] | None:
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
        data = dict(zip(cols, row))
        data["ingredients"] = json.loads(data["ingredients"])
        return data


__all__ = ["SQLiteDrugRepository", "open_sqlite", "init_schema", "ChunkRow"]

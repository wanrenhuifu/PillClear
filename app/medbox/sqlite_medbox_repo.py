"""SQLite 版药箱仓储（B 部分）。

实现与 InMemory/Postgres 同一个 UserMedboxRepository Protocol。
users + user_medbox 表由 app/knowledge/sqlite_repo.init_schema 统一创建。

连接来源二选一：
- 传入已有 sqlite3.Connection（生产环境共享 SQLiteDrugRepository 的连接，
  foreign_keys 已开启；测试共享同一 :memory: 库）；
- 传入 db_path 字符串 → 自建连接。独立连接关闭 foreign_keys：药箱仓储可脱离
  药品库单独使用（如完成标志的 :memory: 冒烟，upsert 未入库的 drug_id 也不报错）；
  生产环境经 deps 共享药品仓储连接，跨表完整性仍由那边的 FK 保证。
"""

from __future__ import annotations

import sqlite3
import threading

from app.knowledge.sqlite_repo import open_sqlite
from app.medbox.repository import placeholder_brand


class SQLiteUserMedboxRepository:
    """sqlite3 药箱仓储。单语句走 autocommit，无需显式事务。

    生产环境经 deps 共享 SQLiteDrugRepository 的连接对象——必须同时共享
    其 lock，否则跨仓储并发仍会交错使用同一连接（code review #13）。
    独立连接（测试 / 冒烟）用自建锁。
    """

    def __init__(
        self,
        db_path_or_connection: "str | sqlite3.Connection" = ":memory:",
        *,
        lock: threading.RLock | None = None,
    ) -> None:
        if isinstance(db_path_or_connection, sqlite3.Connection):
            if lock is None:
                raise ValueError(
                    "共享 sqlite3.Connection 必须同时传入共享 lock"
                    "（同连接的两把锁会交错撕裂事务，见 code review #13）"
                )
            self._conn = db_path_or_connection
        else:
            # 独立连接：FK 关闭，药箱仓储可独立于药品库使用（见模块头注）。
            self._conn = open_sqlite(db_path_or_connection, foreign_keys=False)
            if lock is None:
                lock = threading.RLock()
        self._lock = lock

    def get_or_create_user(self, device_id: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "insert into users (device_id) values (?)"
                " on conflict (device_id) do update set device_id = excluded.device_id"
                " returning id",
                (device_id,),
            )
            return cur.fetchone()[0]

    def get_items(self, user_id: int) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "select m.drug_id, d.brand_name, m.dosage_per_day"
                " from user_medbox m left join drugs d on d.id = m.drug_id"
                " where m.user_id = ? order by m.added_at, m.id",
                (user_id,),
            )
            return [
                {
                    "drug_id": drug_id,
                    "brand_name": brand_name or placeholder_brand(drug_id),
                    "dosage_per_day": dosage,
                }
                for drug_id, brand_name, dosage in cur.fetchall()
            ]

    def upsert_item(
        self, user_id: int, drug_id: int, dosage_per_day: int | None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "insert into user_medbox (user_id, drug_id, dosage_per_day) values (?, ?, ?)"
                " on conflict (user_id, drug_id) do update set"
                " dosage_per_day = excluded.dosage_per_day",
                (user_id, drug_id, dosage_per_day),
            )

    def remove_item(self, user_id: int, drug_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "delete from user_medbox where user_id = ? and drug_id = ?",
                (user_id, drug_id),
            )

    def count_items(self, user_id: int) -> int:
        with self._lock:
            return self._conn.execute(
                "select count(*) from user_medbox where user_id = ?", (user_id,)
            ).fetchone()[0]


__all__ = ["SQLiteUserMedboxRepository"]

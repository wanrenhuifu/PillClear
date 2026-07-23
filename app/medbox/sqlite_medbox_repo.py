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

from app.knowledge.sqlite_repo import open_sqlite
from app.medbox.repository import placeholder_brand


class SQLiteUserMedboxRepository:
    """sqlite3 药箱仓储。单语句走 autocommit，无需显式事务。"""

    def __init__(self, db_path_or_connection: "str | sqlite3.Connection" = ":memory:") -> None:
        if isinstance(db_path_or_connection, sqlite3.Connection):
            self._conn = db_path_or_connection
        else:
            # 独立连接：FK 关闭，药箱仓储可独立于药品库使用（见模块头注）。
            self._conn = open_sqlite(db_path_or_connection, foreign_keys=False)

    def get_or_create_user(self, device_id: str) -> int:
        cur = self._conn.execute(
            "insert into users (device_id) values (?)"
            " on conflict (device_id) do update set device_id = excluded.device_id"
            " returning id",
            (device_id,),
        )
        return cur.fetchone()[0]

    def get_items(self, user_id: int) -> list[dict]:
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

    def upsert_item(self, user_id: int, drug_id: int, dosage_per_day: int | None) -> None:
        self._conn.execute(
            "insert into user_medbox (user_id, drug_id, dosage_per_day) values (?, ?, ?)"
            " on conflict (user_id, drug_id) do update set"
            " dosage_per_day = excluded.dosage_per_day",
            (user_id, drug_id, dosage_per_day),
        )

    def remove_item(self, user_id: int, drug_id: int) -> None:
        self._conn.execute(
            "delete from user_medbox where user_id = ? and drug_id = ?",
            (user_id, drug_id),
        )

    def count_items(self, user_id: int) -> int:
        return self._conn.execute(
            "select count(*) from user_medbox where user_id = ?", (user_id,)
        ).fetchone()[0]


__all__ = ["SQLiteUserMedboxRepository"]

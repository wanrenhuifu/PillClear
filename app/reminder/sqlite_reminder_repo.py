"""SQLite 版用药提醒仓储。

实现与 InMemory/Postgres 同一个 ReminderRepository Protocol。
user_reminders 表由 app/knowledge/sqlite_repo.init_schema 统一创建。

连接来源与药箱仓储同款二选一（见 app/medbox/sqlite_medbox_repo.py）：
共享 SQLiteDrugRepository 的连接（必须同时共享锁，code review #13），
或传 db_path 自建连接（FK 关闭，可独立于药品库使用）。
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from app.knowledge.sqlite_repo import open_sqlite
from app.medbox.repository import placeholder_brand


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """BEGIN IMMEDIATE / COMMIT，异常回滚——覆盖式设置需「删+批量插」原子。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


class SQLiteReminderRepository:
    """sqlite3 提醒仓储。生产经 deps 共享药品仓储的连接 + 锁。"""

    def __init__(
        self,
        db_path_or_connection: str | sqlite3.Connection = ":memory:",
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

    def get_reminders(self, user_id: int) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "select r.drug_id, d.brand_name, r.time_of_day"
                " from user_reminders r left join drugs d on d.id = r.drug_id"
                " where r.user_id = ? order by r.drug_id, r.time_of_day",
                (user_id,),
            )
            rows: dict[int, dict] = {}
            for drug_id, brand_name, time_of_day in cur.fetchall():
                entry = rows.setdefault(
                    drug_id,
                    {
                        "drug_id": drug_id,
                        "brand_name": brand_name or placeholder_brand(drug_id),
                        "times": [],
                    },
                )
                entry["times"].append(time_of_day)
            return list(rows.values())

    def set_reminder(self, user_id: int, drug_id: int, times: list[str]) -> None:
        with self._lock, _transaction(self._conn):
            self._conn.execute(
                "delete from user_reminders where user_id = ? and drug_id = ?",
                (user_id, drug_id),
            )
            self._conn.executemany(
                "insert into user_reminders (user_id, drug_id, time_of_day)"
                " values (?, ?, ?)",
                [(user_id, drug_id, t) for t in sorted(set(times))],
            )

    def remove_reminder(self, user_id: int, drug_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "delete from user_reminders where user_id = ? and drug_id = ?",
                (user_id, drug_id),
            )

    def count_reminders(self, user_id: int) -> int:
        with self._lock:
            return self._conn.execute(
                "select count(distinct drug_id) from user_reminders where user_id = ?",
                (user_id,),
            ).fetchone()[0]


__all__ = ["SQLiteReminderRepository"]

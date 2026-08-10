"""用药提醒仓储层。

- ReminderRepository：提醒 CRUD 依赖的接口（Protocol）。
- InMemoryReminderRepository：离线测试与降级用，字典存储。
- PostgresReminderRepository：psycopg3 真实实现，连 Supabase
  （schema 见 migrations/0004_user_reminders.sql）。

与药箱仓储同款模式（app/medbox/repository.py）：user_reminders 只存
drug_id + time_of_day（每时刻一行）；brand_name 是 drugs 表的展示数据，
get_reminders 负责把它带回来——真实仓储靠 SQL JOIN，内存替身用构造时
注入的 brands 映射。
"""

from __future__ import annotations

import threading
from typing import Protocol

from app.medbox.repository import placeholder_brand


class ReminderRepository(Protocol):
    """用药提醒仓储接口。"""

    def get_or_create_user(self, device_id: str) -> int:
        """按 device_id 幂等取/建用户，返回 user_id。"""
        ...

    def get_reminders(self, user_id: int) -> list[dict]:
        """返回 [{"drug_id":1, "brand_name":"泰诺", "times":["08:00","20:00"]}, ...]。

        times 按时刻升序；brand_name 由 JOIN drugs 得到（药品被删时为占位名）。
        """
        ...

    def set_reminder(self, user_id: int, drug_id: int, times: list[str]) -> None:
        """按 (user_id, drug_id) 覆盖式设置时刻表（幂等）。"""
        ...

    def remove_reminder(self, user_id: int, drug_id: int) -> None:
        """按 drug_id 移除（不存在则为 no-op，幂等）。"""
        ...

    def count_reminders(self, user_id: int) -> int:
        """该用户设置的提醒药品数（按 drug_id 计，非时刻行数）。"""
        ...


class InMemoryReminderRepository:
    """内存实现：用于单测与降级。

    无 drugs 表可 JOIN，brand_name 取自构造时注入的 brands 映射；
    未登记的 drug_id 回退占位名（同药箱内存替身的模式）。
    """

    def __init__(self, brands: dict[int, str] | None = None) -> None:
        self._brands = brands or {}
        self._users: dict[str, int] = {}  # device_id -> user_id
        # user_id -> {drug_id: [times]}
        self._reminders: dict[int, dict[int, list[str]]] = {}
        self._next_user_id = 1

    def get_or_create_user(self, device_id: str) -> int:
        uid = self._users.get(device_id)
        if uid is None:
            uid = self._next_user_id
            self._next_user_id += 1
            self._users[device_id] = uid
            self._reminders[uid] = {}
        return uid

    def get_reminders(self, user_id: int) -> list[dict]:
        return [
            {
                "drug_id": drug_id,
                "brand_name": self._brands.get(drug_id) or placeholder_brand(drug_id),
                "times": sorted(times),
            }
            for drug_id, times in self._reminders.get(user_id, {}).items()
        ]

    def set_reminder(self, user_id: int, drug_id: int, times: list[str]) -> None:
        self._reminders.setdefault(user_id, {})[drug_id] = sorted(set(times))

    def remove_reminder(self, user_id: int, drug_id: int) -> None:
        self._reminders.get(user_id, {}).pop(drug_id, None)

    def count_reminders(self, user_id: int) -> int:
        return len(self._reminders.get(user_id, {}))


class PostgresReminderRepository:
    """psycopg3 真实实现，连 Supabase（延迟导入，未安装不影响其余模块）。

    自建连接 + 实例级 RLock：路由经 run_in_threadpool 并发执行，
    psycopg3 同步连接禁止重叠操作（code review #13）。
    """

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # noqa: PLC0415
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError(
                "Postgres 后端需要 psycopg，请先安装：pip install -e '.[postgres]'"
            ) from exc

        self._conn = psycopg.connect(dsn, autocommit=True)
        self._lock = threading.RLock()

    def get_or_create_user(self, device_id: str) -> int:
        with self._lock, self._conn.cursor() as cur:
            cur.execute(
                "insert into users (device_id) values (%s)"
                " on conflict (device_id) do update set device_id = excluded.device_id"
                " returning id",
                (device_id,),
            )
            return cur.fetchone()[0]

    def get_reminders(self, user_id: int) -> list[dict]:
        with self._lock, self._conn.cursor() as cur:
            cur.execute(
                "select r.drug_id, d.brand_name, r.time_of_day"
                " from user_reminders r left join drugs d on d.id = r.drug_id"
                " where r.user_id = %s order by r.drug_id, r.time_of_day",
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
        # 连接是 autocommit，「删 + 批量插」需显式事务保证原子（同 SQLite 版纪律）。
        with self._lock, self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "delete from user_reminders where user_id = %s and drug_id = %s",
                (user_id, drug_id),
            )
            for t in sorted(set(times)):
                cur.execute(
                    "insert into user_reminders (user_id, drug_id, time_of_day)"
                    " values (%s, %s, %s)",
                    (user_id, drug_id, t),
                )

    def remove_reminder(self, user_id: int, drug_id: int) -> None:
        with self._lock, self._conn.cursor() as cur:
            cur.execute(
                "delete from user_reminders where user_id = %s and drug_id = %s",
                (user_id, drug_id),
            )

    def count_reminders(self, user_id: int) -> int:
        with self._lock, self._conn.cursor() as cur:
            cur.execute(
                "select count(distinct drug_id) from user_reminders where user_id = %s",
                (user_id,),
            )
            return cur.fetchone()[0]


__all__ = [
    "InMemoryReminderRepository",
    "PostgresReminderRepository",
    "ReminderRepository",
]

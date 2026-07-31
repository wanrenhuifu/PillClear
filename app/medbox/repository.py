"""药箱持久化仓储层。

- UserMedboxRepository：药箱 CRUD 依赖的接口（Protocol）。
- InMemoryUserMedboxRepository：离线测试与降级用，字典存储。
- PostgresUserMedboxRepository：psycopg3 真实实现，连 Supabase。

MVP 阶段用 device_id 标识用户、不做登录（schema 见 migrations/0003_user_medbox.sql）。
user_medbox 只存 drug_id + dosage_per_day；brand_name 是 drugs 表的展示数据，
get_items 负责把它带回来：真实仓储靠 SQL JOIN，内存替身用构造时注入的 brands 映射
（不依赖任何药品仓储的私有内部）。
"""

from __future__ import annotations

import threading
from typing import Protocol


def placeholder_brand(drug_id: int) -> str:
    """药品被删 / 未收录时的占位商品名（保证 brand_name 非空，满足 min_length=1）。

    三个后端共用同一格式：真实仓储 JOIN 不到（药品被删）时回退此占位；
    内存替身无 drugs 表，未登记的 drug_id 也用此占位。
    """
    return f"药品#{drug_id}"


class UserMedboxRepository(Protocol):
    """个人药箱仓储接口。"""

    def get_or_create_user(self, device_id: str) -> int:
        """按 device_id 幂等取/建用户，返回 user_id。"""
        ...

    def get_items(self, user_id: int) -> list[dict]:
        """返回 [{"drug_id":1, "brand_name":"泰诺", "dosage_per_day":3}, ...]。

        brand_name 由 JOIN drugs 得到（药品被删时为占位名，不崩溃）。
        """
        ...

    def upsert_item(self, user_id: int, drug_id: int, dosage_per_day: int | None) -> None:
        """按 (user_id, drug_id) 幂等添加/更新一项。"""
        ...

    def remove_item(self, user_id: int, drug_id: int) -> None:
        """按 drug_id 移除（不存在则为 no-op，幂等）。"""
        ...

    def count_items(self, user_id: int) -> int: ...


class InMemoryUserMedboxRepository:
    """内存实现：用于单测与降级。

    无 drugs 表可 JOIN，brand_name 取自构造时注入的 brands 映射（drug_id → 商品名，
    由测试 / 调用方按已知药品提供）；未登记的 drug_id 回退占位名。内存替身因此
    不伸手进任何药品仓储的私有数据（真实仓储靠 SQL JOIN，不走这里）。
    """

    def __init__(self, brands: dict[int, str] | None = None) -> None:
        self._brands = brands or {}
        self._users: dict[str, int] = {}  # device_id -> user_id
        self._items: dict[int, dict[int, int | None]] = {}  # user_id -> {drug_id: dosage}
        self._next_user_id = 1

    def get_or_create_user(self, device_id: str) -> int:
        uid = self._users.get(device_id)
        if uid is None:
            uid = self._next_user_id
            self._next_user_id += 1
            self._users[device_id] = uid
            self._items[uid] = {}
        return uid

    def get_items(self, user_id: int) -> list[dict]:
        return [
            {
                "drug_id": drug_id,
                "brand_name": self._brands.get(drug_id) or placeholder_brand(drug_id),
                "dosage_per_day": dosage,
            }
            for drug_id, dosage in self._items.get(user_id, {}).items()
        ]

    def upsert_item(self, user_id: int, drug_id: int, dosage_per_day: int | None) -> None:
        self._items.setdefault(user_id, {})[drug_id] = dosage_per_day

    def remove_item(self, user_id: int, drug_id: int) -> None:
        self._items.get(user_id, {}).pop(drug_id, None)

    def count_items(self, user_id: int) -> int:
        return len(self._items.get(user_id, {}))


class PostgresUserMedboxRepository:
    """psycopg3 真实实现，连 Supabase（延迟导入，未安装不影响其余模块）。

    自建连接 + 实例级 RLock：路由经 run_in_threadpool 并发执行，
    psycopg3 同步连接禁止重叠操作（code review #13）。
    """

    def __init__(self, dsn: str) -> None:
        import psycopg  # noqa: PLC0415

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

    def get_items(self, user_id: int) -> list[dict]:
        with self._lock, self._conn.cursor() as cur:
            cur.execute(
                "select m.drug_id, d.brand_name, m.dosage_per_day"
                " from user_medbox m left join drugs d on d.id = m.drug_id"
                " where m.user_id = %s order by m.added_at, m.id",
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
        with self._lock, self._conn.cursor() as cur:
            cur.execute(
                "insert into user_medbox (user_id, drug_id, dosage_per_day)"
                " values (%s, %s, %s)"
                " on conflict (user_id, drug_id) do update set"
                " dosage_per_day = excluded.dosage_per_day",
                (user_id, drug_id, dosage_per_day),
            )

    def remove_item(self, user_id: int, drug_id: int) -> None:
        with self._lock, self._conn.cursor() as cur:
            cur.execute(
                "delete from user_medbox where user_id = %s and drug_id = %s",
                (user_id, drug_id),
            )

    def count_items(self, user_id: int) -> int:
        with self._lock, self._conn.cursor() as cur:
            cur.execute("select count(*) from user_medbox where user_id = %s", (user_id,))
            return cur.fetchone()[0]


__all__ = [
    "UserMedboxRepository",
    "InMemoryUserMedboxRepository",
    "PostgresUserMedboxRepository",
    "placeholder_brand",
]

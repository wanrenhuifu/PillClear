"""共享连接 SQLite 仓储的并发串行化回归（code review #13）。

deps 按 Settings 缓存单个 SQLiteDrugRepository，药箱仓储共享其连接对象，
而 /chat、/drugs、/medbox 全部经 run_in_threadpool 并发执行。单连接
（check_same_thread=False，原无锁）在多线程下交错使用游标 / 事务，会
偶发 'Recursive use of cursors not allowed' 与事务错乱。仓储必须以共享
锁内部串行化（同 PgVectorRetriever 的既有模式）。
"""

from __future__ import annotations

import threading

import pytest

from app.knowledge.schemas import DrugRecord, Ingredient
from app.knowledge.sqlite_repo import SQLiteDrugRepository
from app.medbox.sqlite_medbox_repo import SQLiteUserMedboxRepository

_N_THREADS = 8
_N_ITERS = 40


def _drug(i: int) -> DrugRecord:
    return DrugRecord(
        brand_name=f"药品{i % 5}",
        ingredients=[Ingredient(name="对乙酰氨基酚", amount=100, unit="mg")],
    )


def test_shared_connection_without_lock_raises():
    """共享连接必须显式传共享锁：静默自建私有锁会复刻两锁一连接交错（code review #13 回归）。"""
    repo = SQLiteDrugRepository(":memory:")
    with pytest.raises(ValueError, match=r"共享.*锁"):
        SQLiteUserMedboxRepository(repo.connection)


def test_shared_connection_concurrent_reads_and_writes():
    repo = SQLiteDrugRepository(":memory:")
    # 预置 drug_id=1，读侧 upsert_item 的外键永远有效
    repo.save_drug(_drug(0), [("章节", "内容", [])])
    medbox = SQLiteUserMedboxRepository(repo.connection, lock=repo.lock)
    errors: list[Exception] = []

    def writer() -> None:
        try:
            for i in range(_N_ITERS):
                # save_drug 走 BEGIN IMMEDIATE / COMMIT 多语句事务——
                # 无锁时与读侧交错必然撕裂
                repo.save_drug(_drug(i), [(f"章节{i % 3}", f"内容{i}", [])])
        except Exception as exc:
            errors.append(exc)

    def reader() -> None:
        try:
            uid = medbox.get_or_create_user("device-1")
            for i in range(_N_ITERS):
                repo.list_drugs()
                repo.get_drug_by_brand(f"药品{i % 5}")
                medbox.upsert_item(uid, 1, (i % 3) + 1)
                medbox.get_items(uid)
                medbox.count_items(uid)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer)]
    threads += [threading.Thread(target=reader) for _ in range(_N_THREADS - 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert repo.count_drugs() == 5
    assert medbox.count_items(medbox.get_or_create_user("device-1")) == 1

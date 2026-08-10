"""用药提醒测试：next_due 纯函数 + ReminderRepository 契约（InMemory/SQLite）
+ ReminderService + GET/POST/DELETE /api/v1/reminders/{device_id} 端点集成。

刻意不挂 respx——以「装不了 mock」断言提醒链路全程不碰 LLM
（同 test_medbox_api.py 的纪律：提醒是调度数据，与药学判断无关，铁律 #1）。
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_reminder_repository,
    get_settings,
)
from app.config import Settings
from app.main import create_app
from app.reminder.repository import InMemoryReminderRepository
from app.reminder.schemas import ReminderAddRequest
from app.reminder.service import ReminderService, next_due
from app.reminder.sqlite_reminder_repo import SQLiteReminderRepository


def _brands() -> dict[int, str]:
    return {1: "泰诺", 2: "必理通"}


# ── 1. next_due 纯函数 ───────────────────────────────────────────────────
class TestNextDue:
    def test_later_today_wins(self):
        now = datetime(2026, 8, 10, 9, 0)
        assert next_due(["08:00", "20:00"], now) == datetime(2026, 8, 10, 20, 0)

    def test_all_past_today_rolls_to_tomorrow(self):
        now = datetime(2026, 8, 10, 21, 0)
        assert next_due(["08:00", "20:00"], now) == datetime(2026, 8, 11, 8, 0)

    def test_exactly_now_is_not_due(self):
        """正点那一刻本次提醒已发生，下一次是明天（严格大于 now）。"""
        now = datetime(2026, 8, 10, 8, 0)
        assert next_due(["08:00"], now) == datetime(2026, 8, 11, 8, 0)

    def test_unsorted_times_still_correct(self):
        now = datetime(2026, 8, 10, 12, 0)
        assert next_due(["20:00", "08:00"], now) == datetime(2026, 8, 10, 20, 0)

    def test_empty_times_has_no_due(self):
        assert next_due([], datetime(2026, 8, 10, 9, 0)) is None

    def test_month_boundary(self):
        now = datetime(2026, 8, 31, 23, 0)
        assert next_due(["08:00"], now) == datetime(2026, 9, 1, 8, 0)


# ── 2. InMemoryReminderRepository 契约 ───────────────────────────────────
class TestInMemoryReminderRepository:
    def test_get_or_create_user_is_idempotent(self):
        repo = InMemoryReminderRepository()
        assert repo.get_or_create_user("dev-A") == repo.get_or_create_user("dev-A")
        assert repo.get_or_create_user("dev-B") != repo.get_or_create_user("dev-A")

    def test_set_then_get_roundtrip(self):
        repo = InMemoryReminderRepository(brands=_brands())
        uid = repo.get_or_create_user("dev")
        repo.set_reminder(uid, 1, ["08:00", "20:00"])
        assert repo.get_reminders(uid) == [
            {"drug_id": 1, "brand_name": "泰诺", "times": ["08:00", "20:00"]}
        ]

    def test_set_replaces_not_duplicates(self):
        repo = InMemoryReminderRepository(brands=_brands())
        uid = repo.get_or_create_user("dev")
        repo.set_reminder(uid, 1, ["08:00"])
        repo.set_reminder(uid, 1, ["09:00", "21:00"])
        assert repo.count_reminders(uid) == 1
        assert repo.get_reminders(uid)[0]["times"] == ["09:00", "21:00"]

    def test_remove_is_idempotent(self):
        repo = InMemoryReminderRepository(brands=_brands())
        uid = repo.get_or_create_user("dev")
        repo.set_reminder(uid, 1, ["08:00"])
        repo.remove_reminder(uid, 1)
        repo.remove_reminder(uid, 1)  # 再次移除不报错
        assert repo.count_reminders(uid) == 0

    def test_unknown_drug_falls_back_to_placeholder(self):
        repo = InMemoryReminderRepository(brands=_brands())
        uid = repo.get_or_create_user("dev")
        repo.set_reminder(uid, 99, ["08:00"])
        assert repo.get_reminders(uid)[0]["brand_name"] == "药品#99"


# ── 3. SQLiteReminderRepository 契约 ─────────────────────────────────────
class TestSQLiteReminderRepository:
    def test_standalone_memory_roundtrip(self):
        repo = SQLiteReminderRepository(":memory:")
        uid = repo.get_or_create_user("dev")
        repo.set_reminder(uid, 1, ["08:00", "20:00"])
        # 独立连接无 drugs 表 JOIN，brand 回退占位名
        rows = repo.get_reminders(uid)
        assert rows[0]["drug_id"] == 1
        assert rows[0]["times"] == ["08:00", "20:00"]

    def test_set_replaces_existing_times(self):
        repo = SQLiteReminderRepository(":memory:")
        uid = repo.get_or_create_user("dev")
        repo.set_reminder(uid, 1, ["08:00"])
        repo.set_reminder(uid, 1, ["09:00", "21:00"])
        assert repo.count_reminders(uid) == 1
        assert repo.get_reminders(uid)[0]["times"] == ["09:00", "21:00"]

    def test_shared_connection_requires_shared_lock(self):
        """同药箱纪律（code review #13）：共享连接必须同时共享锁。"""
        from app.knowledge.sqlite_repo import open_sqlite

        conn = open_sqlite(":memory:", foreign_keys=False)
        with pytest.raises(ValueError, match=r"共享.*锁"):
            SQLiteReminderRepository(conn)
        conn.close()

    def test_devices_are_isolated(self):
        repo = SQLiteReminderRepository(":memory:")
        uid_a = repo.get_or_create_user("A")
        uid_b = repo.get_or_create_user("B")
        repo.set_reminder(uid_a, 1, ["08:00"])
        assert repo.count_reminders(uid_b) == 0


# ── 4. ReminderService ───────────────────────────────────────────────────
class TestReminderService:
    def _service(self) -> ReminderService:
        return ReminderService(InMemoryReminderRepository(brands=_brands()))

    def test_get_empty(self):
        assert self._service().get_reminders("dev").reminders == []

    def test_set_and_get_with_next_due(self):
        service = self._service()
        service.set_reminder(
            "dev", ReminderAddRequest(drug_id=1, brand_name="泰诺", times=["08:00", "20:00"])
        )
        result = service.get_reminders("dev", now=datetime(2026, 8, 10, 9, 0))
        item = result.reminders[0]
        assert item.drug_id == 1
        assert item.times == ["08:00", "20:00"]
        assert item.next_due_at == "2026-08-10T20:00:00"

    def test_set_replaces_times(self):
        service = self._service()
        req = ReminderAddRequest(drug_id=1, brand_name="泰诺", times=["08:00"])
        service.set_reminder("dev", req)
        result = service.set_reminder(
            "dev", ReminderAddRequest(drug_id=1, brand_name="泰诺", times=["09:00"])
        )
        assert len(result.reminders) == 1
        assert result.reminders[0].times == ["09:00"]

    def test_times_are_deduped_and_sorted(self):
        service = self._service()
        result = service.set_reminder(
            "dev", ReminderAddRequest(drug_id=1, brand_name="泰诺", times=["20:00", "08:00", "08:00"])
        )
        assert result.reminders[0].times == ["08:00", "20:00"]

    def test_remove(self):
        service = self._service()
        service.set_reminder(
            "dev", ReminderAddRequest(drug_id=1, brand_name="泰诺", times=["08:00"])
        )
        result = service.remove_reminder("dev", 1)
        assert result.reminders == []


# ── 5. 时间格式校验（schema 层）─────────────────────────────────────────
class TestTimesValidation:
    @pytest.mark.parametrize("bad", ["8:00", "24:00", "12:60", "1200", "上午8点", ""])
    def test_invalid_time_rejected(self, bad):
        with pytest.raises(ValueError):
            ReminderAddRequest(drug_id=1, brand_name="泰诺", times=[bad])

    def test_too_many_times_rejected(self):
        with pytest.raises(ValueError):
            ReminderAddRequest(
                drug_id=1,
                brand_name="泰诺",
                times=["06:00", "09:00", "12:00", "15:00", "18:00"],
            )

    def test_empty_times_rejected(self):
        with pytest.raises(ValueError):
            ReminderAddRequest(drug_id=1, brand_name="泰诺", times=[])


# ── 6. API 端点集成（dependency_overrides 注入 InMemory）─────────────────
@pytest.fixture
def client() -> TestClient:
    app = create_app()
    repo = InMemoryReminderRepository(brands=_brands())
    app.dependency_overrides[get_settings] = lambda: Settings(
        deepseek_api_key="k", _env_file=None
    )
    app.dependency_overrides[get_reminder_repository] = lambda: repo
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestReminderAPI:
    def test_get_empty(self, client):
        resp = client.get("/api/v1/reminders/dev-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "dev-1"
        assert data["reminders"] == []

    def test_post_then_get_roundtrip(self, client):
        resp = client.post(
            "/api/v1/reminders/dev-1/items",
            json={"drug_id": 1, "brand_name": "泰诺", "times": ["08:00", "20:00"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "dev-1"
        assert len(data["reminders"]) == 1
        item = data["reminders"][0]
        assert item["drug_id"] == 1
        assert item["brand_name"] == "泰诺"
        assert item["times"] == ["08:00", "20:00"]
        assert item["next_due_at"] is not None

        got = client.get("/api/v1/reminders/dev-1").json()
        assert [r["drug_id"] for r in got["reminders"]] == [1]

    def test_post_replaces_existing(self, client):
        client.post(
            "/api/v1/reminders/dev-1/items",
            json={"drug_id": 1, "brand_name": "泰诺", "times": ["08:00"]},
        )
        resp = client.post(
            "/api/v1/reminders/dev-1/items",
            json={"drug_id": 1, "brand_name": "泰诺", "times": ["09:00", "21:00"]},
        )
        assert resp.status_code == 200
        reminders = resp.json()["reminders"]
        assert len(reminders) == 1
        assert reminders[0]["times"] == ["09:00", "21:00"]

    def test_post_invalid_time_rejected_with_422(self, client):
        resp = client.post(
            "/api/v1/reminders/dev-1/items",
            json={"drug_id": 1, "brand_name": "泰诺", "times": ["25:00"]},
        )
        assert resp.status_code == 422

    def test_delete_item(self, client):
        client.post(
            "/api/v1/reminders/dev-1/items",
            json={"drug_id": 1, "brand_name": "泰诺", "times": ["08:00"]},
        )
        resp = client.delete("/api/v1/reminders/dev-1/items/1")
        assert resp.status_code == 200
        assert resp.json()["reminders"] == []

    def test_devices_are_isolated(self, client):
        client.post(
            "/api/v1/reminders/A/items",
            json={"drug_id": 1, "brand_name": "泰诺", "times": ["08:00"]},
        )
        assert client.get("/api/v1/reminders/B").json()["reminders"] == []

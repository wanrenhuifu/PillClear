"""药箱持久化测试（A 部分）：UserMedboxRepository 契约 + MedboxService 持久化方法
+ GET/POST/DELETE /api/v1/medbox/{device_id}/... 端点集成。

全程离线：InMemoryUserMedboxRepository + InMemoryDrugRepository 种子 + 依赖覆盖，
不连 psycopg / SQLite 文件、不打 LLM——药箱链路永不触碰 LLM（铁律 #1）。
"""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_drug_repository,
    get_rule_set,
    get_settings,
    get_user_medbox_repository,
)
from app.config import Settings
from app.knowledge.repository import InMemoryDrugRepository
from app.knowledge.schemas import DrugRecord, Ingredient
from app.main import create_app
from app.medbox.repository import InMemoryUserMedboxRepository
from app.medbox.schemas import Medbox, MedboxItem
from app.medbox.service import MedboxService, check_medbox


# ── 种子药品仓储：泰诺(1) / 必理通(2) 共享对乙酰氨基酚 ────────────────────
def _seed_drug_repo() -> InMemoryDrugRepository:
    repo = InMemoryDrugRepository()
    repo.upsert_drug(
        DrugRecord(
            brand_name="泰诺",
            ingredients=[Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")],
        )
    )
    repo.upsert_drug(
        DrugRecord(
            brand_name="必理通",
            ingredients=[Ingredient(name="对乙酰氨基酚", amount=500, unit="mg")],
        )
    )
    return repo


# 与 _seed_drug_repo 的入库顺序一致：泰诺=1、必理通=2。内存药箱替身无 drugs 表
# 可 JOIN，brand_name 由这份显式映射提供（真实仓储靠 SQL JOIN，不走这里）。
def _brands() -> dict[int, str]:
    return {1: "泰诺", 2: "必理通"}


# ── 1. InMemoryUserMedboxRepository 契约测试 ─────────────────────────────
class TestInMemoryUserMedboxRepository:
    def test_get_or_create_user_is_idempotent(self):
        repo = InMemoryUserMedboxRepository()
        uid1 = repo.get_or_create_user("device-A")
        uid2 = repo.get_or_create_user("device-A")
        assert uid1 == uid2
        # 不同 device_id 分配不同 user_id
        assert repo.get_or_create_user("device-B") != uid1

    def test_upsert_then_get_items_roundtrip(self):
        repo = InMemoryUserMedboxRepository(brands=_brands())
        uid = repo.get_or_create_user("dev")
        repo.upsert_item(uid, 1, 3)

        items = repo.get_items(uid)
        assert items == [
            {"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 3}
        ]

    def test_upsert_is_idempotent_update_not_duplicate(self):
        repo = InMemoryUserMedboxRepository(brands=_brands())
        uid = repo.get_or_create_user("dev")
        repo.upsert_item(uid, 1, 3)
        repo.upsert_item(uid, 1, 2)  # 同 drug_id 再次 upsert → 更新剂量
        assert repo.count_items(uid) == 1
        assert repo.get_items(uid)[0]["dosage_per_day"] == 2

    def test_upsert_allows_null_dosage(self):
        repo = InMemoryUserMedboxRepository(brands=_brands())
        uid = repo.get_or_create_user("dev")
        repo.upsert_item(uid, 2, None)
        assert repo.get_items(uid)[0]["dosage_per_day"] is None

    def test_remove_item_is_idempotent(self):
        repo = InMemoryUserMedboxRepository(brands=_brands())
        uid = repo.get_or_create_user("dev")
        repo.upsert_item(uid, 1, 3)
        repo.remove_item(uid, 1)
        repo.remove_item(uid, 1)  # 重复移除不报错
        assert repo.count_items(uid) == 0
        assert repo.get_items(uid) == []

    def test_remove_nonexistent_is_noop(self):
        repo = InMemoryUserMedboxRepository()
        uid = repo.get_or_create_user("dev")
        repo.remove_item(uid, 999)  # 从未存在
        assert repo.count_items(uid) == 0

    def test_items_are_isolated_per_user(self):
        repo = InMemoryUserMedboxRepository(brands=_brands())
        a = repo.get_or_create_user("A")
        b = repo.get_or_create_user("B")
        repo.upsert_item(a, 1, 3)
        assert repo.count_items(a) == 1
        assert repo.count_items(b) == 0

    def test_unknown_brand_falls_back_to_placeholder(self):
        """未登记的 drug_id → 占位名（min_length 仍满足），不崩溃。"""
        repo = InMemoryUserMedboxRepository(brands=_brands())
        uid = repo.get_or_create_user("dev")
        repo.upsert_item(uid, 999, 1)
        item = repo.get_items(uid)[0]
        assert item["brand_name"]  # 非空
        assert item["drug_id"] == 999


# ── 2. MedboxService 持久化方法 ──────────────────────────────────────────
def _service() -> tuple[MedboxService, InMemoryUserMedboxRepository]:
    user_repo = InMemoryUserMedboxRepository(brands=_brands())
    service = MedboxService(user_repo)
    return service, user_repo


class TestMedboxServicePersistence:
    def test_get_medbox_empty_when_no_records(self):
        service, _ = _service()
        assert service.get_medbox("new-device") == Medbox(items=[])

    def test_add_to_medbox_returns_full_medbox(self):
        service, _ = _service()
        result = service.add_to_medbox(
            "dev", MedboxItem(drug_id=1, brand_name="泰诺", dosage_per_day=3)
        )
        assert result.items == [
            MedboxItem(drug_id=1, brand_name="泰诺", dosage_per_day=3)
        ]
        # 持久化生效：再次 get 能读回
        assert service.get_medbox("dev").items == result.items

    def test_add_same_drug_updates_not_duplicates(self):
        service, _ = _service()
        service.add_to_medbox("dev", MedboxItem(drug_id=1, brand_name="泰诺", dosage_per_day=3))
        result = service.add_to_medbox(
            "dev", MedboxItem(drug_id=1, brand_name="泰诺", dosage_per_day=1)
        )
        assert len(result.items) == 1
        assert result.items[0].dosage_per_day == 1

    def test_remove_from_medbox(self):
        service, _ = _service()
        service.add_to_medbox("dev", MedboxItem(drug_id=1, brand_name="泰诺", dosage_per_day=3))
        service.add_to_medbox("dev", MedboxItem(drug_id=2, brand_name="必理通", dosage_per_day=2))
        result = service.remove_from_medbox("dev", 1)
        assert [i.drug_id for i in result.items] == [2]
        assert service.get_medbox("dev").items == result.items

    def test_devices_are_isolated(self):
        service, _ = _service()
        service.add_to_medbox("A", MedboxItem(drug_id=1, brand_name="泰诺"))
        assert service.get_medbox("B").items == []

    def test_persisted_medbox_feeds_check(self):
        """持久化药箱可直接喂给 check_medbox（D4 链路复用）。"""
        drugs = _seed_drug_repo()
        user_repo = InMemoryUserMedboxRepository(brands=_brands())
        from app.rules.engine import load_rules, DEFAULT_RULES_DIR

        service = MedboxService(user_repo)
        service.add_to_medbox("dev", MedboxItem(drug_id=1, brand_name="泰诺", dosage_per_day=3))
        service.add_to_medbox("dev", MedboxItem(drug_id=2, brand_name="必理通", dosage_per_day=2))
        rules = load_rules(DEFAULT_RULES_DIR)
        report = check_medbox(service.get_medbox("dev"), rules, drugs)
        assert [t.name for t in report.overlap.overlapping] == ["对乙酰氨基酚"]


# ── 3. API 端点集成测试 ──────────────────────────────────────────────────
@pytest.fixture
def client() -> TestClient:
    app = create_app()
    drugs = _seed_drug_repo()
    user_repo = InMemoryUserMedboxRepository(brands=_brands())
    app.dependency_overrides[get_settings] = lambda: Settings(
        deepseek_api_key="k", _env_file=None
    )
    app.dependency_overrides[get_drug_repository] = lambda: drugs
    app.dependency_overrides[get_user_medbox_repository] = lambda: user_repo
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestMedboxPersistenceAPI:
    def test_get_empty_medbox(self, client):
        resp = client.get("/api/v1/medbox/dev-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "dev-1"
        assert data["items"] == []

    def test_post_then_get_roundtrip(self, client):
        resp = client.post(
            "/api/v1/medbox/dev-1/items",
            json={"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "dev-1"
        assert data["items"] == [
            {"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 3}
        ]

        got = client.get("/api/v1/medbox/dev-1").json()
        assert got["items"] == data["items"]

    def test_post_updates_existing_drug(self, client):
        client.post(
            "/api/v1/medbox/dev-1/items",
            json={"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 3},
        )
        resp = client.post(
            "/api/v1/medbox/dev-1/items",
            json={"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 1},
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1
        assert resp.json()["items"][0]["dosage_per_day"] == 1

    def test_post_without_dosage_defaults_null(self, client):
        resp = client.post(
            "/api/v1/medbox/dev-1/items",
            json={"drug_id": 2, "brand_name": "必理通"},
        )
        assert resp.status_code == 200
        assert resp.json()["items"][0]["dosage_per_day"] is None

    def test_delete_item(self, client):
        client.post(
            "/api/v1/medbox/dev-1/items",
            json={"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 3},
        )
        client.post(
            "/api/v1/medbox/dev-1/items",
            json={"drug_id": 2, "brand_name": "必理通", "dosage_per_day": 2},
        )
        resp = client.delete("/api/v1/medbox/dev-1/items/1")
        assert resp.status_code == 200
        assert [i["drug_id"] for i in resp.json()["items"]] == [2]

    def test_delete_nonexistent_is_ok(self, client):
        resp = client.delete("/api/v1/medbox/dev-1/items/999")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_post_invalid_dosage_422(self, client):
        resp = client.post(
            "/api/v1/medbox/dev-1/items",
            json={"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 0},
        )
        assert resp.status_code == 422  # ge=1 约束

    def test_post_empty_brand_422(self, client):
        resp = client.post(
            "/api/v1/medbox/dev-1/items",
            json={"drug_id": 1, "brand_name": "", "dosage_per_day": 1},
        )
        assert resp.status_code == 422  # min_length=1 约束

    def test_devices_isolated_via_api(self, client):
        client.post(
            "/api/v1/medbox/A/items",
            json={"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 3},
        )
        assert client.get("/api/v1/medbox/B").json()["items"] == []

    def test_check_endpoint_still_works(self, client):
        """既有 POST /medbox/check 不受持久化改动影响（回归）。"""
        resp = client.post(
            "/api/v1/medbox/check",
            json={"items": [{"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 3}]},
        )
        assert resp.status_code == 200
        assert resp.json()["unresolved_drugs"] == []

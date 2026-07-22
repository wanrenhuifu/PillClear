"""药箱 API 测试：POST /api/v1/medbox/check。

全程离线：InMemoryDrugRepository 种子数据 + 依赖覆盖，不连 psycopg、
不打 LLM——药箱链路永不触碰 LLM（铁律 #1），本文件没有 respx 本身就是断言。
"""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_drug_repository, get_rule_set, get_settings
from app.config import Settings
from app.knowledge.repository import InMemoryDrugRepository
from app.knowledge.schemas import DrugRecord, Ingredient
from app.main import create_app
from app.rules.schemas import IngredientCondition, Rule, RuleConditions, RuleSet


def _seed_repo() -> InMemoryDrugRepository:
    """种子三种药：泰诺(1) / 必理通(2) 共享对乙酰氨基酚，芬必得(3) 含布洛芬。"""
    repo = InMemoryDrugRepository()
    repo.upsert_drug(
        DrugRecord(
            brand_name="泰诺",
            ingredients=[
                Ingredient(name="对乙酰氨基酚", amount=325, unit="mg"),
                Ingredient(name="马来酸氯苯那敏", amount=2, unit="mg"),
            ],
        )
    )
    repo.upsert_drug(
        DrugRecord(
            brand_name="必理通",
            ingredients=[Ingredient(name="对乙酰氨基酚", amount=500, unit="mg")],
        )
    )
    repo.upsert_drug(
        DrugRecord(
            brand_name="芬必得",
            ingredients=[Ingredient(name="布洛芬", amount=300, unit="mg")],
        )
    )
    return repo


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        deepseek_api_key="k", _env_file=None
    )
    app.dependency_overrides[get_drug_repository] = _seed_repo
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestMedboxCheck:
    def test_two_overlapping_drugs_report(self, client):
        resp = client.post(
            "/api/v1/medbox/check",
            json={
                "items": [
                    {"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 3},
                    {"drug_id": 2, "brand_name": "必理通", "dosage_per_day": 2},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        overlapping = data["overlap"]["overlapping"]
        assert [t["name"] for t in overlapping] == ["对乙酰氨基酚"]
        assert overlapping[0]["total_amount_mg"] == 1975.0  # 325*3 + 500*2
        assert overlapping[0]["sources"] == ["泰诺", "必理通"]
        assert overlapping[0]["max_daily_mg"] == 4000.0

        ids = [r["id"] for r in data["triggered_rules"]]
        assert "acetaminophen-overlap" in ids
        warning = next(
            r["warning"]
            for r in data["triggered_rules"]
            if r["id"] == "acetaminophen-overlap"
        )
        # {count}/{total_mg} 已由纯代码填充（铁律 #1），无残留占位符
        assert "{" not in warning and "}" not in warning
        assert "1975" in warning
        assert data["unresolved_drugs"] == []

    def test_substances_passthrough(self, client):
        resp = client.post(
            "/api/v1/medbox/check",
            json={
                "items": [{"drug_id": 3, "brand_name": "芬必得"}],
                "lifestyle_substances": ["酒精"],
            },
        )
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()["triggered_rules"]]
        assert "ibuprofen-alcohol" in ids

    def test_empty_medbox_empty_report(self, client):
        resp = client.post("/api/v1/medbox/check", json={"items": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["triggered_rules"] == []
        assert data["overlap"]["overlapping"] == []
        assert data["overlap"]["warnings"] == []
        assert data["unresolved_drugs"] == []

    def test_missing_items_422(self, client):
        resp = client.post("/api/v1/medbox/check", json={})
        assert resp.status_code == 422

    def test_no_conflict_clean_report(self, client):
        resp = client.post(
            "/api/v1/medbox/check",
            json={"items": [{"drug_id": 1, "brand_name": "泰诺", "dosage_per_day": 3}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["triggered_rules"] == []
        assert data["overlap"]["overlapping"] == []

    def test_unresolved_brand_surfaced(self, client):
        """未入库药品 → unresolved_drugs 明示，不得静默忽略（铁律 #4）。"""
        resp = client.post(
            "/api/v1/medbox/check",
            json={"items": [{"drug_id": 99, "brand_name": "不存在的药"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["unresolved_drugs"] == ["不存在的药"]
        assert data["triggered_rules"] == []
        assert data["overlap"]["overlapping"] == []

    def test_custom_ruleset_via_override(self, client):
        """get_rule_set 可被依赖覆盖替换（lru_cache 的测试逃生舱）。"""
        tiny = RuleSet(
            rules=[
                Rule(
                    id="test-only-rule",
                    title="t",
                    severity="info",
                    description="d",
                    conditions=RuleConditions(
                        ingredients=[IngredientCondition(name="布洛芬")]
                    ),
                    warning="命中布洛芬（合成规则）",
                    confidence="low",
                )
            ]
        )
        client.app.dependency_overrides[get_rule_set] = lambda: tiny
        resp = client.post(
            "/api/v1/medbox/check",
            json={"items": [{"drug_id": 3, "brand_name": "芬必得"}]},
        )
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()["triggered_rules"]]
        assert ids == ["test-only-rule"]  # 内置规则集已被整体替换

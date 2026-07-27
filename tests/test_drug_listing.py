"""药品列表能力测试:仓储 list_drugs() + GET /api/v1/drugs 路由。"""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_drug_repository
from app.knowledge.repository import InMemoryDrugRepository
from app.knowledge.schemas import DrugRecord, Ingredient
from app.knowledge.sqlite_repo import SQLiteDrugRepository
from app.main import create_app


def _seed(repo):
    """种子两种药:泰诺(id=1,无通用名)/ 芬必得(id=2)。"""
    repo.upsert_drug(
        DrugRecord(
            brand_name="泰诺",
            ingredients=[Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")],
        )
    )
    repo.upsert_drug(DrugRecord(brand_name="芬必得"))
    return repo


class TestListDrugsRepository:
    def test_inmemory_shape_and_order(self):
        repo = _seed(InMemoryDrugRepository())
        rows = repo.list_drugs()
        assert [(r["id"], r["brand_name"]) for r in rows] == [(1, "泰诺"), (2, "芬必得")]
        assert set(rows[0].keys()) == {"id", "brand_name", "generic_name"}
        assert rows[0]["generic_name"] is None

    def test_sqlite_shape_and_order(self):
        repo = _seed(SQLiteDrugRepository(":memory:"))
        rows = repo.list_drugs()
        assert [(r["id"], r["brand_name"]) for r in rows] == [(1, "泰诺"), (2, "芬必得")]
        assert set(rows[0].keys()) == {"id", "brand_name", "generic_name"}

    def test_empty_repo_returns_empty_list(self):
        assert InMemoryDrugRepository().list_drugs() == []
        assert SQLiteDrugRepository(":memory:").list_drugs() == []

"""KeywordRetriever 的 LIMIT 语义回归（code review #4）。

品牌精确匹配与模糊匹配的 SQL 此前没有 LIMIT：按药名检索会把命中药品的
全部章节（模糊匹配时甚至是多个药品的全部章节）倾倒进 prompt。
limit 参数必须在三级降级（精确 → 模糊 → 内容）上都生效。
"""

from __future__ import annotations

import pytest

from app.knowledge.schemas import DrugRecord, Ingredient
from app.knowledge.sqlite_repo import SQLiteDrugRepository
from app.rag.keyword_retriever import KeywordRetriever


def _seed(repo, brand, n_chunks, section_prefix="章节"):
    """自包含 seed：一个药品 n_chunks 个章节（chunk 无 embedding，_NO_EMBEDDING=[]）。"""
    drug_id = repo.upsert_drug(
        DrugRecord(brand_name=brand, ingredients=[Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")])
    )
    repo.replace_chunks(drug_id, [(f"{section_prefix}{i}", f"内容{i}", []) for i in range(n_chunks)])
    return drug_id


@pytest.fixture
def retriever() -> KeywordRetriever:
    repo = SQLiteDrugRepository(":memory:")
    _seed(repo, "泰诺", 8)
    _seed(repo, "泰诺林片", 4)
    _seed(repo, "泰诺胶囊", 4)
    return KeywordRetriever(connection=repo.connection)


@pytest.fixture
def retriever_no_bare_brand() -> KeywordRetriever:
    """没有裸名 泰诺，只有 泰诺林片 / 泰诺胶囊：搜 泰诺 走模糊匹配分支。"""
    repo = SQLiteDrugRepository(":memory:")
    _seed(repo, "泰诺林片", 4)
    _seed(repo, "泰诺胶囊", 4)
    return KeywordRetriever(connection=repo.connection)


class TestBrandSearchLimit:
    def test_exact_brand_match_honors_limit(self, retriever):
        """精确命中品牌名也受 limit 约束（此前无视 limit 返回全部章节）。"""
        assert len(retriever.search("泰诺", limit=3)) == 3

    def test_default_limit_still_covers_typical_insert(self, retriever):
        """默认 limit=5：章节不多的药品（4 章）保持全量返回。"""
        assert len(retriever.search("泰诺林片")) == 4

    def test_like_brand_match_honors_limit(self, retriever):
        """模糊命中也受 limit 约束（此前无视 limit）。"""
        assert len(retriever.search("胶囊", limit=2)) == 2

    def test_like_brand_match_across_drugs_honors_limit(
        self, retriever_no_bare_brand
    ):
        """模糊命中多个药品时按 limit 截断（此前 2 药 × 4 章全返）。"""
        assert len(retriever_no_bare_brand.search("泰诺", limit=5)) == 5

    def test_content_search_limit_regression(self, retriever):
        """内容搜索的 LIMIT 语义保持不变（回归保护）。"""
        # 「内容0」同时出现在三个药品的章节内容里
        assert len(retriever.search("内容0", limit=2)) == 2

    def test_exact_brand_match_keeps_document_order(self):
        """精确命中也按说明书章节顺序截断（ORDER BY id），而非任意子集。"""
        repo = SQLiteDrugRepository(":memory:")
        _seed(repo, "泰诺", 13)
        r = KeywordRetriever(connection=repo.connection)
        got = r.search("泰诺", limit=12)
        assert [c.section for c in got] == [f"章节{i}" for i in range(12)]

    def test_like_match_across_drugs_allocates_fairly(self):
        """多药模糊命中时每药都有份额（轮转分配），而不是第一个药吃满。"""
        repo = SQLiteDrugRepository(":memory:")
        for brand in ("泰诺林片", "泰诺胶囊", "泰诺颗粒"):
            _seed(repo, brand, 4)
        r = KeywordRetriever(connection=repo.connection)
        got = r.search("泰诺", limit=6)
        brands = [c.brand_name for c in got]
        assert "泰诺林片" in brands and "泰诺胶囊" in brands and "泰诺颗粒" in brands
        assert len(got) == 6

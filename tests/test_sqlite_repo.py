"""SQLite 后端测试：SQLiteDrugRepository / KeywordRetriever /
SQLiteUserMedboxRepository 三件套契约。

全部用 :memory:（或 tmp_path 文件）离线运行，不打网络、不连 Supabase。
检索走关键词精确匹配，无 embedding 依赖。
"""

import logging

import pytest

from app.knowledge.schemas import DrugRecord, Ingredient
from app.knowledge.sqlite_repo import SQLiteDrugRepository
from app.medbox.sqlite_medbox_repo import SQLiteUserMedboxRepository
from app.rag.keyword_retriever import KeywordRetriever


# dummy embedding — ChunkRow 类型第 3 位（SQLite 路径忽略，仅为类型兼容）
_NO_EMBEDDING: list[float] = []


def _record(brand: str, *ings) -> DrugRecord:
    return DrugRecord(
        brand_name=brand,
        ingredients=[Ingredient(name=n, amount=a, unit="mg") for n, a in ings],
    )


# ── 1. SQLiteDrugRepository 契约 ─────────────────────────────────────────
class TestSQLiteDrugRepository:
    def test_upsert_returns_id_and_counts(self):
        repo = SQLiteDrugRepository(":memory:")
        drug_id = repo.save_drug(_record("泰诺", ("对乙酰氨基酚", 325)), [])
        assert drug_id >= 1
        assert repo.count_drugs() == 1
        assert repo.count_chunks() == 0

    def test_upsert_is_idempotent_and_preserves_id(self):
        repo = SQLiteDrugRepository(":memory:")
        id1 = repo.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
        id2 = repo.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 500)))
        assert id1 == id2  # 同 brand_name → 同 id（与 Postgres ON CONFLICT 一致）
        assert repo.count_drugs() == 1
        # 成分被新值覆盖
        assert repo.get_drug_by_brand("泰诺")["ingredients"][0]["amount"] == 500.0

    def test_ingredients_verified_forced_false(self):
        """铁律：入库永不置 true——调用方传 True 也被仓储层覆盖为 0。"""
        repo = SQLiteDrugRepository(":memory:")
        repo.upsert_drug(_record("X"), )
        repo.upsert_drug(DrugRecord(brand_name="Y", ingredients_verified=True))
        assert repo.get_drug_by_brand("Y")["ingredients_verified"] in (0, False)

    def test_get_drug_by_brand_returns_dict_with_json_ingredients(self):
        repo = SQLiteDrugRepository(":memory:")
        repo.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325), ("马来酸氯苯那敏", 2)))
        row = repo.get_drug_by_brand("泰诺")
        assert row["brand_name"] == "泰诺"
        assert row["ingredients"] == [
            {"name": "对乙酰氨基酚", "amount": 325.0, "unit": "mg"},
            {"name": "马来酸氯苯那敏", "amount": 2.0, "unit": "mg"},
        ]
        assert repo.get_drug_by_brand("不存在") is None

    def test_save_drug_writes_chunks_and_is_idempotent(self):
        repo = SQLiteDrugRepository(":memory:")
        chunks = [
            ("用法用量", "口服一次1片", _NO_EMBEDDING),
            ("禁忌", "对本品过敏者禁用", _NO_EMBEDDING),
        ]
        repo.save_drug(_record("泰诺", ("对乙酰氨基酚", 325)), chunks)
        assert repo.count_chunks() == 2
        # 重跑不产生重复 chunks
        repo.save_drug(_record("泰诺", ("对乙酰氨基酚", 325)), chunks)
        assert repo.count_chunks() == 2
        assert repo.count_drugs() == 1

    def test_replace_chunks_is_idempotent(self):
        """replace_chunks 先删后插保证幂等。"""
        repo = SQLiteDrugRepository(":memory:")
        drug_id = repo.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
        repo.replace_chunks(drug_id, [("用法用量", "口服", _NO_EMBEDDING)])
        assert repo.count_chunks() == 1
        # 替换为 2 条
        repo.replace_chunks(
            drug_id,
            [("用法用量", "口服", _NO_EMBEDDING), ("禁忌", "禁用", _NO_EMBEDDING)],
        )
        assert repo.count_chunks() == 2

    def test_wal_and_foreign_keys_enabled_on_file(self, tmp_path):
        """铁律：WAL 模式必须开启 + foreign_keys=ON（:memory: 不支持 WAL，用文件验证）。"""
        db = tmp_path / "test.db"
        repo = SQLiteDrugRepository(str(db))
        mode = repo.connection.execute("PRAGMA journal_mode").fetchone()[0]
        fk = repo.connection.execute("PRAGMA foreign_keys").fetchone()[0]
        assert mode.lower() == "wal"
        assert fk == 1


# ── 2. KeywordRetriever 检索 ────────────────────────────────────────────
def _seed_two_drugs() -> SQLiteDrugRepository:
    """泰诺 + 芬必得各一条 chunk，共享 :memory: 连接。"""
    repo = SQLiteDrugRepository(":memory:")
    tainuo = repo.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
    repo.replace_chunks(tainuo, [("用法用量", "口服。成人一次1-2片，一日3次。", _NO_EMBEDDING)])
    fenbide = repo.upsert_drug(_record("芬必得", ("布洛芬", 300)))
    repo.replace_chunks(fenbide, [("禁忌", "对布洛芬过敏者禁用。", _NO_EMBEDDING)])
    return repo


class TestKeywordRetriever:
    def test_exact_brand_name_match(self):
        """搜"泰诺"精确命中品牌名，返回该药匹配到的 chunk（受 limit 约束，按章节顺序截断）。"""
        repo = _seed_two_drugs()
        retriever = KeywordRetriever(connection=repo.connection)
        citations = retriever.search("泰诺")
        assert [c.brand_name for c in citations] == ["泰诺"]
        assert citations[0].section == "用法用量"

    def test_like_brand_name_match(self):
        """搜"芬"模糊命中"芬必得"。"""
        repo = _seed_two_drugs()
        retriever = KeywordRetriever(connection=repo.connection)
        citations = retriever.search("芬")
        assert citations[0].brand_name == "芬必得"

    def test_content_fallback(self):
        """无品牌名匹配时降级到内容搜索。"""
        repo = _seed_two_drugs()
        retriever = KeywordRetriever(connection=repo.connection)
        citations = retriever.search("布洛芬过敏")
        assert len(citations) > 0
        assert any("布洛芬" in c.excerpt for c in citations)

    def test_empty_query_returns_empty(self):
        retriever = KeywordRetriever(connection=SQLiteDrugRepository(":memory:").connection)
        assert retriever.search("   ") == []

    def test_empty_db_returns_empty(self):
        repo = SQLiteDrugRepository(":memory:")
        retriever = KeywordRetriever(connection=repo.connection)
        assert retriever.search("泰诺") == []

    def test_limit_is_respected(self):
        """limit 在三级降级一律生效；content 分支语义不变。"""
        repo = SQLiteDrugRepository(":memory:")
        for i in range(5):
            drug_id = repo.upsert_drug(_record(f"药{i}", ("X", 1)))
            repo.replace_chunks(drug_id, [("注意事项", f"内容{i}", _NO_EMBEDDING)])
        retriever = KeywordRetriever(connection=repo.connection)
        assert len(retriever.search("内容", limit=2)) == 2

    def test_search_failure_degrades_to_empty(self, caplog):
        """损坏的连接 → 降级空引用，不炸 /chat。"""
        repo = SQLiteDrugRepository(":memory:")
        repo.connection.close()
        retriever = KeywordRetriever(connection=repo.connection)
        assert retriever.search("泰诺") == []


# ── 3. SQLiteUserMedboxRepository 契约 ───────────────────────────────────
class TestSQLiteUserMedboxRepository:
    def test_standalone_memory_upsert_without_drug(self):
        """完成标志场景：独立 :memory: 连接，upsert 未入库的 drug_id 也能成功。"""
        repo = SQLiteUserMedboxRepository(":memory:")
        uid = repo.get_or_create_user("test-device")
        repo.upsert_item(uid, 1, 3)
        assert repo.count_items(uid) == 1
        assert repo.get_or_create_user("test-device") == uid

    def test_get_items_joins_brand_name_from_shared_conn(self):
        drugs = SQLiteDrugRepository(":memory:")
        drug_id = drugs.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
        repo = SQLiteUserMedboxRepository(drugs.connection, lock=drugs.lock)  # 共享连接
        uid = repo.get_or_create_user("dev")
        repo.upsert_item(uid, drug_id, 3)
        assert repo.get_items(uid) == [
            {"drug_id": drug_id, "brand_name": "泰诺", "dosage_per_day": 3}
        ]

    def test_upsert_is_idempotent_update(self):
        drugs = SQLiteDrugRepository(":memory:")
        drug_id = drugs.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
        repo = SQLiteUserMedboxRepository(drugs.connection, lock=drugs.lock)
        uid = repo.get_or_create_user("dev")
        repo.upsert_item(uid, drug_id, 3)
        repo.upsert_item(uid, drug_id, 1)
        assert repo.count_items(uid) == 1
        assert repo.get_items(uid)[0]["dosage_per_day"] == 1

    def test_remove_item(self):
        drugs = SQLiteDrugRepository(":memory:")
        d1 = drugs.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
        d2 = drugs.upsert_drug(_record("芬必得", ("布洛芬", 300)))
        repo = SQLiteUserMedboxRepository(drugs.connection, lock=drugs.lock)
        uid = repo.get_or_create_user("dev")
        repo.upsert_item(uid, d1, 3)
        repo.upsert_item(uid, d2, 2)
        repo.remove_item(uid, d1)
        repo.remove_item(uid, d1)  # 幂等
        assert repo.count_items(uid) == 1
        assert repo.get_items(uid)[0]["drug_id"] == d2

    def test_users_isolated(self):
        repo = SQLiteUserMedboxRepository(":memory:")
        a = repo.get_or_create_user("A")
        b = repo.get_or_create_user("B")
        repo.upsert_item(a, 1, 3)
        assert repo.count_items(a) == 1
        assert repo.count_items(b) == 0

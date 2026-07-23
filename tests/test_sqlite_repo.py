"""SQLite 后端测试（B 部分）：SQLiteDrugRepository / SQLiteVectorRetriever /
SQLiteUserMedboxRepository 三件套契约。

全部用 :memory:（或 tmp_path 文件）离线运行，不打网络、不连 Supabase。
向量检索用 sqlite-vec 的 vec0 虚拟表 + 手工构造的稀疏向量验证 cosine 排序。
"""

import logging

import pytest

from app.knowledge.schemas import DrugRecord, Ingredient
from app.knowledge.sqlite_repo import SQLiteDrugRepository
from app.medbox.sqlite_medbox_repo import SQLiteUserMedboxRepository
from app.rag.sqlite_retriever import SQLiteVectorRetriever

DIMS = 1024


def _one_hot(index: int) -> list[float]:
    v = [0.0] * DIMS
    v[index] = 1.0
    return v


class FixedEmbedder:
    """查询向量化替身：恒定返回预设向量，不联网。fail=True 模拟 API 故障。"""

    def __init__(self, vector: list[float], fail: bool = False):
        self._vector = vector
        self.fail = fail

    def embed(self, texts):
        if self.fail:
            raise RuntimeError("embedding api down")
        return [list(self._vector) for _ in texts]


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
            ("用法用量", "口服一次1片", _one_hot(0)),
            ("禁忌", "对本品过敏者禁用", _one_hot(1)),
        ]
        repo.save_drug(_record("泰诺", ("对乙酰氨基酚", 325)), chunks)
        assert repo.count_chunks() == 2
        # 重跑不产生重复 chunks
        repo.save_drug(_record("泰诺", ("对乙酰氨基酚", 325)), chunks)
        assert repo.count_chunks() == 2
        assert repo.count_drugs() == 1

    def test_replace_chunks_updates_vec_table_in_sync(self):
        """replace_chunks 同步重写 insert_chunks 与 vec_chunks（行数一致）。"""
        repo = SQLiteDrugRepository(":memory:")
        drug_id = repo.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
        repo.replace_chunks(drug_id, [("用法用量", "口服", _one_hot(0))])
        assert repo._count_vec_chunks() == 1
        # 替换为 2 条 → vec 表也变 2 条（旧向量被清掉）
        repo.replace_chunks(
            drug_id,
            [("用法用量", "口服", _one_hot(0)), ("禁忌", "禁用", _one_hot(1))],
        )
        assert repo.count_chunks() == 2
        assert repo._count_vec_chunks() == 2

    def test_wal_and_foreign_keys_enabled_on_file(self, tmp_path):
        """铁律：WAL 模式必须开启 + foreign_keys=ON（:memory: 不支持 WAL，用文件验证）。"""
        db = tmp_path / "test.db"
        repo = SQLiteDrugRepository(str(db))
        mode = repo.connection.execute("PRAGMA journal_mode").fetchone()[0]
        fk = repo.connection.execute("PRAGMA foreign_keys").fetchone()[0]
        assert mode.lower() == "wal"
        assert fk == 1


# ── 2. SQLiteVectorRetriever 检索 ────────────────────────────────────────
def _seed_two_drugs() -> SQLiteDrugRepository:
    """泰诺 chunk 向量=[1,0,..]，芬必得 chunk 向量=[0,1,..]，共享一个 :memory: 连接。"""
    repo = SQLiteDrugRepository(":memory:")
    tainuo = repo.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
    repo.replace_chunks(tainuo, [("用法用量", "口服。成人一次1-2片，一日3次。", _one_hot(0))])
    fenbide = repo.upsert_drug(_record("芬必得", ("布洛芬", 300)))
    repo.replace_chunks(fenbide, [("禁忌", "对布洛芬过敏者禁用。", _one_hot(1))])
    return repo


class TestSQLiteVectorRetriever:
    def test_knn_orders_by_cosine_proximity(self):
        repo = _seed_two_drugs()
        # 查询向量=[1,0,..] → 与泰诺 chunk 完全同向（cosine 距离 0），应排第一
        retriever = SQLiteVectorRetriever(
            FixedEmbedder(_one_hot(0)), connection=repo.connection
        )
        citations = retriever.search("布洛芬怎么吃")
        assert [c.drug_name for c in citations] == ["泰诺", "芬必得"]
        assert citations[0].section == "用法用量"

    def test_excerpt_is_first_200_chars_and_exact_substring(self):
        repo = SQLiteDrugRepository(":memory:")
        drug_id = repo.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
        content = "长" * 300
        repo.replace_chunks(drug_id, [("注意事项", content, _one_hot(0))])
        retriever = SQLiteVectorRetriever(
            FixedEmbedder(_one_hot(0)), connection=repo.connection
        )
        (citation,) = retriever.search("q")
        assert citation.excerpt == content[:200]
        assert citation.excerpt in content

    def test_limit_is_respected(self):
        repo = _seed_two_drugs()
        retriever = SQLiteVectorRetriever(
            FixedEmbedder(_one_hot(0)), connection=repo.connection
        )
        assert len(retriever.search("q", limit=1)) == 1

    def test_empty_db_returns_empty_list(self):
        repo = SQLiteDrugRepository(":memory:")
        retriever = SQLiteVectorRetriever(
            FixedEmbedder(_one_hot(0)), connection=repo.connection
        )
        assert retriever.search("q") == []

    def test_embedder_failure_degrades_to_empty(self, caplog):
        repo = _seed_two_drugs()
        retriever = SQLiteVectorRetriever(
            FixedEmbedder(_one_hot(0), fail=True), connection=repo.connection
        )
        with caplog.at_level(logging.WARNING, logger="app.rag"):
            assert retriever.search("q") == []
        assert any("向量化" in r.message for r in caplog.records)

    def test_query_failure_degrades_to_empty(self, caplog):
        """损坏的连接 → 降级空引用 + warning，不炸 /chat（与 PgVector 一致）。"""
        repo = SQLiteDrugRepository(":memory:")
        repo.connection.close()  # 关掉连接制造查询失败
        retriever = SQLiteVectorRetriever(
            FixedEmbedder(_one_hot(0)), connection=repo.connection
        )
        with caplog.at_level(logging.WARNING, logger="app.rag"):
            assert retriever.search("q") == []
        assert any("降级" in r.message for r in caplog.records)


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
        repo = SQLiteUserMedboxRepository(drugs.connection)  # 共享连接
        uid = repo.get_or_create_user("dev")
        repo.upsert_item(uid, drug_id, 3)
        assert repo.get_items(uid) == [
            {"drug_id": drug_id, "brand_name": "泰诺", "dosage_per_day": 3}
        ]

    def test_upsert_is_idempotent_update(self):
        drugs = SQLiteDrugRepository(":memory:")
        drug_id = drugs.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
        repo = SQLiteUserMedboxRepository(drugs.connection)
        uid = repo.get_or_create_user("dev")
        repo.upsert_item(uid, drug_id, 3)
        repo.upsert_item(uid, drug_id, 1)
        assert repo.count_items(uid) == 1
        assert repo.get_items(uid)[0]["dosage_per_day"] == 1

    def test_remove_item(self):
        drugs = SQLiteDrugRepository(":memory:")
        d1 = drugs.upsert_drug(_record("泰诺", ("对乙酰氨基酚", 325)))
        d2 = drugs.upsert_drug(_record("芬必得", ("布洛芬", 300)))
        repo = SQLiteUserMedboxRepository(drugs.connection)
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

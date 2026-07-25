"""app.knowledge.ingest 单元测试：成份抽取结构、chunk 落库、幂等性。

用 InMemoryDrugRepository + mock llm_client，全程离线。
"""

import pytest

from app.config import Settings
from app.knowledge.ingest import ingest_text
from app.knowledge.parser import split_sections
from app.knowledge.repository import InMemoryDrugRepository
from app.knowledge.schemas import DrugRecord, Ingredient, IngredientList
from tests.conftest import SAMPLE_INSERT_TAINUO


class FakeLLM:
    """模拟 LLMClient.complete_json，固定返回给定成份列表。"""

    def __init__(self, ingredients):
        self._ingredients = ingredients
        self.calls = 0

    def complete_json(self, messages, response_model, **kwargs):
        self.calls += 1
        return IngredientList(ingredients=self._ingredients)


TAINUO_INGREDIENTS = [
    Ingredient(name="对乙酰氨基酚", amount=325, unit="mg"),
    Ingredient(name="马来酸氯苯那敏", amount=2, unit="mg"),
]


def test_ingredient_extraction_written_to_jsonb():
    repo = InMemoryDrugRepository()
    llm = FakeLLM(TAINUO_INGREDIENTS)
    ingest_text(
        "泰诺", SAMPLE_INSERT_TAINUO, llm=llm, repo=repo
    )
    drug = repo.get_drug_by_brand("泰诺")
    assert drug is not None
    assert drug["ingredients"] == [
        {"name": "对乙酰氨基酚", "amount": 325.0, "unit": "mg"},
        {"name": "马来酸氯苯那敏", "amount": 2.0, "unit": "mg"},
    ]
    # 铁律：入库永不置 true
    assert drug["ingredients_verified"] is False
    assert llm.calls == 1


def test_chunks_count():
    repo = InMemoryDrugRepository()
    ingest_text(
        "泰诺", SAMPLE_INSERT_TAINUO, llm=FakeLLM([]), repo=repo
    )
    expected_sections = len(split_sections(SAMPLE_INSERT_TAINUO))
    assert repo.count_chunks() == expected_sections


def test_ingest_is_idempotent():
    repo = InMemoryDrugRepository()
    llm = FakeLLM(TAINUO_INGREDIENTS)

    ingest_text("泰诺", SAMPLE_INSERT_TAINUO, llm=llm, repo=repo)
    drugs_after_first = repo.count_drugs()
    chunks_after_first = repo.count_chunks()

    ingest_text("泰诺", SAMPLE_INSERT_TAINUO, llm=llm, repo=repo)
    assert repo.count_drugs() == drugs_after_first == 1
    assert repo.count_chunks() == chunks_after_first


def test_ingest_without_sections_refused_and_existing_data_kept():
    """坏文件（无章节结构）重入库不得抹掉已有的正确数据。"""
    repo = InMemoryDrugRepository()
    ingest_text(
        "泰诺",
        SAMPLE_INSERT_TAINUO,
        llm=FakeLLM(TAINUO_INGREDIENTS),
        repo=repo,
    )
    chunks_before = repo.count_chunks()

    with pytest.raises(ValueError, match="章节"):
        ingest_text(
            "泰诺",
            "一段没有章节结构的随手笔记",
            llm=FakeLLM([]),
            repo=repo,
        )

    assert repo.count_chunks() == chunks_before  # chunks 未被删光
    assert len(repo.get_drug_by_brand("泰诺")["ingredients"]) == 2  # 成分未被清空


def test_upsert_forces_ingredients_verified_false():
    """铁律：入库永不置 true——调用方传 True 也必须被仓储层覆盖。"""
    repo = InMemoryDrugRepository()
    repo.upsert_drug(DrugRecord(brand_name="X", ingredients_verified=True))
    assert repo.get_drug_by_brand("X")["ingredients_verified"] is False


def test_main_ingredient_section_alias_recognized():
    """【主要成份】（中成药常见）不得被静默跳过成份抽取。"""
    text = (
        "【药品名称】\n通用名称：对乙酰氨基酚片\n"
        "【主要成份】\n本品每片含对乙酰氨基酚0.5克。\n"
        "【用法用量】\n口服，一次1片。"
    )
    repo = InMemoryDrugRepository()
    llm = FakeLLM([Ingredient(name="对乙酰氨基酚", amount=0.5, unit="g")])
    ingest_text("必理通", text, llm=llm, repo=repo)
    assert llm.calls == 1  # 找到了成份章节并调用抽取
    drug = repo.get_drug_by_brand("必理通")
    assert drug["ingredients"][0]["name"] == "对乙酰氨基酚"

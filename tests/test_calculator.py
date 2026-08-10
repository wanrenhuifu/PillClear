"""app.medbox.calculator 单元测试：成分叠加纯函数 + 单位换算。

铁律 #1：剂量计算必须是代码纯函数——全部断言都是 输入 → 输出，无 I/O。
"""

import pytest

from app.core.units import to_mg
from app.knowledge.schemas import Ingredient
from app.medbox.calculator import calculate_ingredient_totals, check_overlap
from app.medbox.schemas import MedboxItem


class TestToMg:
    def test_conversions(self):
        assert to_mg(1.0, "g") == 1000.0
        assert to_mg(1.0, "克") == 1000.0
        assert to_mg(500, "mg") == 500
        assert to_mg(500, "毫克") == 500
        assert to_mg(1000, "μg") == pytest.approx(1.0)
        assert to_mg(1000, "ug") == pytest.approx(1.0)
        assert to_mg(1000, "mcg") == pytest.approx(1.0)
        assert to_mg(1000, "微克") == pytest.approx(1.0)

    def test_edge_cases(self):
        assert to_mg(None, "mg") is None
        assert to_mg(325, None) == 325  # 缺单位按 mg 处理（已记录假设）
        assert to_mg(1.0, "勺") is None  # 未知单位不参与 mg 计算
        assert to_mg(1.0, " MG ") == 1.0  # 大小写 / 空白不敏感


def _item(drug_id: int, brand: str, dose: int | None = None) -> MedboxItem:
    return MedboxItem(drug_id=drug_id, brand_name=brand, dosage_per_day=dose)


def test_two_drugs_sharing_acetaminophen_total():
    """泰诺 325mg×3/日 + 必理通 0.5g×2/日 → 975 + 1000 = 1975mg。"""
    items = [_item(1, "泰诺", 3), _item(2, "必理通", 2)]
    drugs = {
        1: [Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")],
        2: [Ingredient(name="对乙酰氨基酚", amount=0.5, unit="g")],
    }
    (total,) = calculate_ingredient_totals(items, drugs)
    assert total.name == "对乙酰氨基酚"
    assert total.total_amount_mg == 1975.0
    assert total.sources == ["泰诺", "必理通"]
    assert total.max_daily_mg == 4000.0


def test_single_drug_no_overlap_entry():
    """未被共享的成分不计入（无叠加风险）。"""
    items = [_item(1, "泰诺", 3)]
    drugs = {1: [Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")]}
    assert calculate_ingredient_totals(items, drugs) == []


def test_over_limit_warning():
    """泰诺+白加黑 共享对乙酰氨基酚 4500mg > 4000mg 上限 → 生成警告。"""
    items = [_item(1, "泰诺", 9), _item(2, "白加黑", 9)]
    drugs = {
        1: [Ingredient(name="对乙酰氨基酚", amount=500, unit="mg")],
        2: [Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")],  # 7425mg total
    }
    result = check_overlap(items, drugs)
    assert len(result.warnings) == 1
    assert "对乙酰氨基酚" in result.warnings[0]
    assert "4000" in result.warnings[0]
    assert len(result.overlapping) == 1
    assert result.overlapping[0].name == "对乙酰氨基酚"


def test_under_limit_no_warning():
    """泰诺+必理通 共享对乙酰氨基酚 975mg < 4000mg → 无警告。"""
    items = [_item(1, "泰诺", 3), _item(2, "必理通", 1)]
    drugs = {
        1: [Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")],
        2: [Ingredient(name="对乙酰氨基酚", amount=0, unit="mg")],  # 0mg
    }
    result = check_overlap(items, drugs)
    assert result.warnings == []


def test_unknown_limit_no_warning():
    """未知安全上限不编造警告（铁律 #4）。"""
    items = [_item(1, "A"), _item(2, "B")]
    drugs = {
        1: [Ingredient(name="圣约翰草", amount=300, unit="mg")],
        2: [Ingredient(name="圣约翰草", amount=300, unit="mg")],
    }
    result = check_overlap(items, drugs)
    assert result.warnings == []
    assert result.overlapping[0].max_daily_mg is None


def test_empty_medbox_no_raise():
    assert check_overlap([], {}).warnings == []
    assert check_overlap([], {}).overlapping == []


def test_ingredient_without_amount_excluded():
    """成分缺 amount：不参与 mg 累加、不炸、但仍计入共享来源。"""
    items = [_item(1, "A"), _item(2, "B")]
    drugs = {
        1: [Ingredient(name="对乙酰氨基酚")],  # amount=None
        2: [Ingredient(name="对乙酰氨基酚", amount=500, unit="mg")],
    }
    (total,) = calculate_ingredient_totals(items, drugs)
    assert total.total_amount_mg == 500.0
    assert total.sources == ["A", "B"]


def test_unknown_unit_excluded_from_total():
    items = [_item(1, "A"), _item(2, "B")]
    drugs = {
        1: [Ingredient(name="布洛芬", amount=1, unit="勺")],
        2: [Ingredient(name="布洛芬", amount=200, unit="mg")],
    }
    (total,) = calculate_ingredient_totals(items, drugs)
    assert total.total_amount_mg == 200.0


def test_multiple_shared_ingredients():
    """两个复方药共享两种成分 → 两条叠加汇总。"""
    items = [_item(1, "A"), _item(2, "B")]
    drugs = {
        1: [
            Ingredient(name="对乙酰氨基酚", amount=300, unit="mg"),
            Ingredient(name="咖啡因", amount=30, unit="mg"),
        ],
        2: [
            Ingredient(name="对乙酰氨基酚", amount=200, unit="mg"),
            Ingredient(name="咖啡因", amount=20, unit="mg"),
        ],
    }
    totals = calculate_ingredient_totals(items, drugs)
    assert {t.name for t in totals} == {"对乙酰氨基酚", "咖啡因"}
    by_name = {t.name: t for t in totals}
    assert by_name["对乙酰氨基酚"].total_amount_mg == 500.0
    assert by_name["咖啡因"].total_amount_mg == 50.0


def test_dosage_multiplier_and_none_default():
    """dosage_per_day 是乘数；None 按 1 次/日计（文档化的保守低估）。"""
    items = [_item(1, "A", 3), _item(2, "B", None)]
    drugs = {
        1: [Ingredient(name="布洛芬", amount=100, unit="mg")],
        2: [Ingredient(name="布洛芬", amount=100, unit="mg")],
    }
    (total,) = calculate_ingredient_totals(items, drugs)
    assert total.total_amount_mg == 400.0  # 100*3 + 100*1


def test_same_drug_two_items_accumulates():
    """同一药品加两次药箱 = 两份服用，按 ≥2 条目计入叠加（更保守，铁律 #4）。"""
    items = [_item(1, "泰诺", 2), _item(1, "泰诺", 2)]
    drugs = {1: [Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")]}
    (total,) = calculate_ingredient_totals(items, drugs)
    assert total.total_amount_mg == 1300.0  # 325*2 + 325*2
    assert total.sources == ["泰诺", "泰诺"]


def test_duplicate_name_within_one_drug_deduped():
    """LLM 重复输出同一成分名不得虚构叠加：单药内先去重。"""
    items = [_item(1, "A"), _item(2, "B")]
    drugs = {
        1: [
            Ingredient(name="对乙酰氨基酚", amount=100, unit="mg"),
            Ingredient(name="对乙酰氨基酚", amount=100, unit="mg"),
        ],
        2: [Ingredient(name="布洛芬", amount=100, unit="mg")],
    }
    # 对乙酰氨基酚实际只来自 A 一个条目 → 未被共享 → 不计入
    assert calculate_ingredient_totals(items, drugs) == []


def test_zero_or_negative_amount_ignored():
    """LLM 垃圾剂量（≤0）不参与累加。"""
    items = [_item(1, "A"), _item(2, "B")]
    drugs = {
        1: [Ingredient(name="布洛芬", amount=0, unit="mg")],
        2: [Ingredient(name="布洛芬", amount=200, unit="mg")],
    }
    (total,) = calculate_ingredient_totals(items, drugs)
    assert total.total_amount_mg == 200.0

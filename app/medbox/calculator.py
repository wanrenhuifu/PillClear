"""成分叠加纯函数（D4）。

铁律 #1：成分叠加计算是代码纯函数，不允许 LLM 参与。
输入（药箱条目 + 各药成分）→ 输出（每个共享成分的日总摄入量与超限警告），
同样的输入永远得到同样的输出。
"""

from __future__ import annotations

from app.core.units import to_mg
from app.knowledge.schemas import Ingredient
from app.medbox.schemas import IngredientTotal, MedboxItem, OverlapResult

# 已知成分每日安全上限（mg）。硬编码参考表，后期可迁入 YAML 规则库。
_DAILY_LIMITS: dict[str, float] = {
    "对乙酰氨基酚": 4000.0,
    "布洛芬": 1200.0,  # OTC 剂量
    "阿司匹林": 4000.0,
    "咖啡因": 400.0,
}


def calculate_ingredient_totals(
    items: list[MedboxItem],
    drugs: dict[int, list[Ingredient]],
) -> list[IngredientTotal]:
    """纯函数：药箱条目 + 各药成分 → 每个被共享成分的日总摄入量。

    - 仅返回出现在 ≥2 个药箱条目中的成分（共享 = 叠加风险）。同一药品
      被加两次视为服用两份，剂量累加——更保守（铁律 #4：宁可多提醒）。
    - 日剂量 = to_mg(amount, unit) × (dosage_per_day or 1)。dosage_per_day
      为 None 时按 1 次/日计：会低估而非高估，属文档化的保守取舍。
    - 无含量 / 未知单位 / 剂量 ≤0 的条目不参与 mg 累加、也不报错——
      它们仍计入共享来源（未知剂量不得掩盖重复成分，铁律 #4）。
    - 单个药品内成分名先去重：LLM 抽取偶发重复输出同名成分时，
      不得虚构出「两种药共享」的假叠加。
    """
    stats: dict[str, dict[str, object]] = {}
    for item in items:
        dose = float(item.dosage_per_day or 1)
        seen_names: set[str] = set()
        for ing in drugs.get(item.drug_id, []):
            if ing.name in seen_names:
                continue
            seen_names.add(ing.name)
            entry = stats.setdefault(
                ing.name, {"total": 0.0, "sources": [], "count": 0}
            )
            entry["count"] += 1
            entry["sources"].append(item.brand_name)  # type: ignore[union-attr]
            mg = to_mg(ing.amount, ing.unit)
            if mg is not None and mg > 0:
                entry["total"] += mg * dose  # type: ignore[operator]
    return [
        IngredientTotal(
            name=name,
            total_amount_mg=round(entry["total"], 2),  # type: ignore[arg-type]
            sources=entry["sources"],  # type: ignore[arg-type]
            max_daily_mg=_DAILY_LIMITS.get(name),
        )
        for name, entry in stats.items()
        if entry["count"] >= 2
    ]


def check_overlap(ingredient_totals: list[IngredientTotal]) -> OverlapResult:
    """纯函数：检查成分叠加是否超过已知安全上限，生成中文警告。

    警告是确定性字符串拼接，不是 LLM 生成（铁律 #1）。
    未知上限（max_daily_mg=None）的成分不编造警告（铁律 #4）。
    """
    warnings: list[str] = []
    for total in ingredient_totals:
        if total.max_daily_mg is not None and total.total_amount_mg > total.max_daily_mg:
            warnings.append(
                f"⚠️ {total.name} 每日合计 {total.total_amount_mg}mg 已超过安全上限 "
                f"{total.max_daily_mg}mg（来自：{'、'.join(total.sources)}），"
                "有过量风险，建议只保留其中一种药，或咨询药师确认。"
            )
    return OverlapResult(overlapping=ingredient_totals, warnings=warnings)


__all__ = ["calculate_ingredient_totals", "check_overlap"]

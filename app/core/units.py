"""剂量单位归一化纯函数（D4）。

成分含量单位不受上游约束（ingest 的 LLM 抽取提示词未枚举单位，
真实数据可能出现 mg/g/μg/毫克/克/微克 等）；规则引擎的 min_amount_mg
比较与药箱叠加计算统一先换算为 mg。
"""

from __future__ import annotations

# 已知单位 → mg 换算系数（覆盖中英文写法，L 大小写不敏感）。
_UNIT_TO_MG: dict[str, float] = {
    "mg": 1.0,
    "毫克": 1.0,
    "g": 1000.0,
    "克": 1000.0,
    "μg": 0.001,
    "ug": 0.001,
    "mcg": 0.001,
    "微克": 0.001,
}


def to_mg(amount: float | None, unit: str | None) -> float | None:
    """把剂量换算为 mg（纯函数）。

    - amount 为 None → None（无含量，不参与 mg 计算）
    - unit 为 None → 按 mg 处理（OTC 说明书以 mg 为主；已记录的假设——
      极个别以 g 标注却丢了单位的成分会被低估，无单位时无法避免）
    - 未知单位 → None（不参与 mg 计算，铁律 #4 保守：宁可不算也不瞎猜）
    """
    if amount is None:
        return None
    if unit is None:
        return amount
    factor = _UNIT_TO_MG.get(unit.strip().lower())
    return amount * factor if factor is not None else None


__all__ = ["to_mg"]

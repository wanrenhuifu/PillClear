"""个人药箱数据模型（D4）。

MVP 阶段药箱无服务端持久化：客户端持有药箱、随请求上送，
服务端只按 brand_name 从 drugs 表读成分做冲突检测。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.rules.schemas import Rule


class MedboxItem(BaseModel):
    """药箱中的一项：用户选择了某个药品。"""

    drug_id: int
    brand_name: str = Field(..., min_length=1)
    # 用户每日服用次数 / 片数，用于日剂量计算；None 按 1 次/日计
    # （见 calculator 文档：保守低估，已记录风险）。
    dosage_per_day: int | None = Field(default=None, ge=1)


class Medbox(BaseModel):
    """用户的个人药箱。MVP 阶段单用户（暂不引入用户认证）。"""

    items: list[MedboxItem] = Field(default_factory=list)


class IngredientTotal(BaseModel):
    """单个成分的日剂量汇总。"""

    name: str
    total_amount_mg: float
    sources: list[str]  # 来源药品商品名（用于展示「来自：泰诺、白加黑」）
    max_daily_mg: float | None = None  # 已知安全上限；None = 未知上限


class OverlapResult(BaseModel):
    """成分叠加计算结果。"""

    overlapping: list[IngredientTotal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)  # 超安全上限的警告


class ConflictReport(BaseModel):
    """完整的药箱冲突检查报告。"""

    overlap: OverlapResult
    triggered_rules: list[Rule] = Field(default_factory=list)
    # 未入库、暂时无法参与检测的药品（铁律 #4：不确定必须明说，不得静默忽略）
    unresolved_drugs: list[str] = Field(default_factory=list)


class MedboxCheckRequest(BaseModel):
    """POST /api/v1/medbox/check 请求体。"""

    items: list[MedboxItem]
    lifestyle_substances: list[str] | None = None  # 用户自报摄入物质（如「酒精」）


__all__ = [
    "MedboxItem",
    "Medbox",
    "IngredientTotal",
    "OverlapResult",
    "ConflictReport",
    "MedboxCheckRequest",
]

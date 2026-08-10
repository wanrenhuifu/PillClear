"""个人药箱数据模型（D4）。

药箱支持两种用法：
- 无状态药箱检查：客户端随请求上送 items（POST /medbox/check）。
- 服务端持久化：用户「正在服用 / 可能同期服用的药」存于 user_medbox 表，
  MVP 阶段用 device_id 标识用户、不做登录（见 app/medbox/repository.py）。
服务端按 brand_name 从 drugs 表读成分做药箱检查（叠加 + 相互作用）。
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


class CheckReport(BaseModel):
    """完整的药箱检查报告：叠加 + 被触发的相互作用规则 + 未入库药品。"""

    overlap: OverlapResult
    triggered_rules: list[Rule] = Field(default_factory=list)
    # 未入库、暂时无法参与检测的药品（铁律 #4：不确定必须明说，不得静默忽略）
    unresolved_drugs: list[str] = Field(default_factory=list)


class MedboxCheckRequest(BaseModel):
    """POST /api/v1/medbox/check 请求体。"""

    items: list[MedboxItem]
    lifestyle_substances: list[str] | None = None  # 用户自报摄入物质（如「酒精」）


class MedboxItemAddRequest(BaseModel):
    """POST /api/v1/medbox/{device_id}/items 请求体：添加/更新药箱中的一项。"""

    drug_id: int
    brand_name: str = Field(..., min_length=1)
    dosage_per_day: int | None = Field(default=None, ge=1)


class MedboxResponse(BaseModel):
    """药箱持久化端点的统一响应：设备标识 + 当前完整药箱。"""

    device_id: str
    items: list[MedboxItem]


__all__ = [
    "CheckReport",
    "IngredientTotal",
    "Medbox",
    "MedboxCheckRequest",
    "MedboxItem",
    "MedboxItemAddRequest",
    "MedboxResponse",
    "OverlapResult",
]

"""规则引擎数据模型（D4）：YAML 规则 DSL 的 Pydantic 校验。

铁律 #1：所有冲突 / 重复成分 / 剂量判断走声明式 YAML 规则 + 确定性解释器
（app/rules/engine.py），禁止 LLM 推断药学结论。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RuleSeverity = Literal["danger", "warning", "info"]
RuleConfidence = Literal["high", "medium", "low"]


class IngredientCondition(BaseModel):
    """药物成分匹配条件：名称相等 + 可选最低剂量（mg）+ 可选最少条目数。"""

    name: str
    min_amount_mg: float | None = None  # None = 匹配任意剂量
    # 药箱中至少 N 个条目含该成分才算满足（重复成分规则置 2：
    # 扁平成分列表里每个药品的每条成分各算一个条目）。
    min_count: int = Field(default=1, ge=1)


class SubstanceCondition(BaseModel):
    """非药物物质条件（酒精、避孕药等用户自报摄入因素）。"""

    name: str


class RuleConditions(BaseModel):
    """规则条件集：所有成分条件与物质条件必须同时满足（AND）。"""

    ingredients: list[IngredientCondition] = Field(default_factory=list)
    substances: list[SubstanceCondition] | None = None


class Rule(BaseModel):
    """一条确定性冲突 / 重复规则。"""

    id: str
    title: str  # 人类可读标题，如「对乙酰氨基酚重复过量」
    severity: RuleSeverity
    description: str  # 大白话解释
    conditions: RuleConditions
    warning: str  # 展示给用户的警告文案，可含 {count}/{total_mg} 占位符
    confidence: RuleConfidence  # 证据强度；前端对 low/medium 降低断言力度（铁律 #4）
    source: str | None = None  # 参考来源（说明书 / 文献 / 机构指南）


class RuleSet(BaseModel):
    """规则集：目录下所有 YAML 文件加载合并后的结果。"""

    version: str = "1"
    rules: list[Rule] = Field(default_factory=list)


__all__ = [
    "RuleSeverity",
    "RuleConfidence",
    "IngredientCondition",
    "SubstanceCondition",
    "RuleConditions",
    "Rule",
    "RuleSet",
]

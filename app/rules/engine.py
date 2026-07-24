"""规则引擎确定性解释器（D4，纯函数）。

铁律 #1：相互作用 / 叠加判断全部走 YAML 规则 + 本解释器，禁止 LLM 推断药学结论。

匹配语义（AND）：一条规则命中当且仅当——
- 每个 IngredientCondition：扁平成分列表中满足「名称相等 + min_amount_mg」
  的条目数 ≥ min_count（扁平列表由调用方按「每药品每成分一条」构造，
  两种药都含对乙酰氨基酚 → 2 条 → min_count: 2 命中）；
- 每个 SubstanceCondition：其 name 出现在用户自报的 lifestyle_substances
  中（strip 后精确匹配）。
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.units import to_mg
from app.knowledge.schemas import Ingredient
from app.rules.schemas import IngredientCondition, Rule, RuleSet

logger = logging.getLogger("app.rules")

DEFAULT_RULES_DIR = Path(__file__).parent / "data"


def load_rules(yaml_dir: str | Path) -> RuleSet:
    """加载目录下所有 .yaml/.yml 规则文件，Pydantic 校验后合并为一个 RuleSet。

    失败要响（铁律 #1：坏规则不得静默上线）：
    - YAML 语法错误 / 模型校验失败 → ValueError（带文件路径）
    - 规则 id 全局重复 → ValueError（复制粘贴的 id 会让危险规则双倍触发）
    - 零条件规则 → ValueError（空条件匹配一切 = 误报噪音）
    - 目录没有任何规则文件 → ValueError（零冲突检测不得静默通过）
    """
    directory = Path(yaml_dir)
    files = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])
    if not files:
        raise ValueError(f"规则目录 {directory} 没有任何 .yaml/.yml 规则文件")

    merged: list[Rule] = []
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            ruleset = RuleSet.model_validate(data)
        except (yaml.YAMLError, ValidationError) as exc:
            raise ValueError(f"规则文件 {path} 校验失败: {exc}") from exc
        merged.extend(ruleset.rules)

    seen: set[str] = set()
    for rule in merged:
        if rule.id in seen:
            raise ValueError(f"规则 id 全局重复: {rule.id}")
        seen.add(rule.id)
        if not rule.conditions.ingredients and not rule.conditions.substances:
            raise ValueError(f"规则 {rule.id} 没有任何条件，会匹配一切")

    return RuleSet(rules=merged)


def count_matches(
    condition: IngredientCondition, ingredients: list[Ingredient]
) -> int:
    """扁平成分列表中满足 name + min_amount_mg 的条目数（纯函数）。

    剂量经 to_mg 换算：mg 为 None（无含量 / 未知单位）时，仅在条件
    未设 min_amount_mg 时计数——铁律 #4 保守：未知剂量不得掩盖重复成分，
    但也不得虚构一个剂量去满足门槛。
    """
    count = 0
    for ing in ingredients:
        if ing.name != condition.name:
            continue
        if condition.min_amount_mg is None:
            count += 1
            continue
        mg = to_mg(ing.amount, ing.unit)
        if mg is not None and mg >= condition.min_amount_mg:
            count += 1
    return count


def match_rules(
    rules: RuleSet,
    ingredients: list[Ingredient],
    lifestyle_substances: list[str] | None = None,
) -> list[Rule]:
    """纯函数：返回被触发的规则列表（保持 rules 原顺序，确定性输出）。"""
    substances = {s.strip() for s in lifestyle_substances or []}
    triggered: list[Rule] = []
    for rule in rules.rules:
        if not all(
            count_matches(cond, ingredients) >= cond.min_count
            for cond in rule.conditions.ingredients
        ):
            continue
        if rule.conditions.substances and not all(
            sub.name in substances for sub in rule.conditions.substances
        ):
            continue
        triggered.append(rule)
    return triggered


class _KeepUnknownKeys(dict):
    """format_map 的占位符兜底：未知键保留字面 {key}，不抛 KeyError。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def format_warning(rule: Rule, *, count: int, total_mg: float | None) -> str:
    """渲染 warning 模板（纯函数，无 LLM，铁律 #1）。

    - total_mg 为 None → 渲染「未知」（铁律 #4：不确定必须明说）
    - 未知占位符保留字面；任何格式化异常回落原文——
      模板笔误绝不能把 /medbox/check 炸成 500。
    """
    values = _KeepUnknownKeys(
        count=count, total_mg="未知" if total_mg is None else total_mg
    )
    try:
        return rule.warning.format_map(values)
    except (ValueError, IndexError, KeyError, TypeError):
        return rule.warning


__all__ = [
    "DEFAULT_RULES_DIR",
    "load_rules",
    "count_matches",
    "match_rules",
    "format_warning",
]

"""规则层：YAML 确定性规则引擎（D4，铁律 #1）。"""

from app.rules.engine import (
    DEFAULT_RULES_DIR,
    count_matches,
    format_warning,
    load_rules,
    match_and_render,
    match_rules,
)
from app.rules.schemas import (
    IngredientCondition,
    Rule,
    RuleConditions,
    RuleSet,
    RuleSeverity,
    SubstanceCondition,
)

__all__ = [
    "DEFAULT_RULES_DIR",
    "IngredientCondition",
    "Rule",
    "RuleConditions",
    "RuleSet",
    "RuleSeverity",
    "SubstanceCondition",
    "count_matches",
    "format_warning",
    "load_rules",
    "match_and_render",
    "match_rules",
]

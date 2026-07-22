"""规则层：YAML 确定性规则引擎（D4，铁律 #1）。"""

from app.rules.engine import (
    DEFAULT_RULES_DIR,
    check_conflicts,
    count_matches,
    format_warning,
    load_rules,
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
    "load_rules",
    "match_rules",
    "check_conflicts",
    "count_matches",
    "format_warning",
    "IngredientCondition",
    "SubstanceCondition",
    "RuleConditions",
    "Rule",
    "RuleSet",
    "RuleSeverity",
]

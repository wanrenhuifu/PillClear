"""app.rules 单元测试：YAML 加载与校验、规则匹配语义、警告渲染。

确定性规则引擎（铁律 #1）：全部断言走纯函数输入 → 输出，离线、无网络。
"""

import pytest

from app.knowledge.schemas import Ingredient
from app.rules.engine import (
    DEFAULT_RULES_DIR,
    check_conflicts,
    count_matches,
    format_warning,
    load_rules,
    match_rules,
)
from app.rules.schemas import IngredientCondition, Rule, RuleConditions, RuleSet


def _rule(
    *,
    min_count: int = 1,
    min_amount_mg: float | None = None,
    name: str = "对乙酰氨基酚",
    warning: str = "w {count}/{total_mg}",
) -> RuleSet:
    """构造只含一条合成规则的最小 RuleSet。"""
    return RuleSet(
        rules=[
            Rule(
                id="t1",
                title="t",
                severity="warning",
                description="d",
                conditions=RuleConditions(
                    ingredients=[
                        IngredientCondition(
                            name=name,
                            min_amount_mg=min_amount_mg,
                            min_count=min_count,
                        )
                    ],
                ),
                warning=warning,
                confidence="high",
            )
        ]
    )


# ── 内置规则数据（app/rules/data/）完整性 ─────────────────────


def test_load_shipped_rules_valid():
    ruleset = load_rules(DEFAULT_RULES_DIR)
    assert len(ruleset.rules) >= 5
    ids = [r.id for r in ruleset.rules]
    assert len(ids) == len(set(ids))  # id 全局唯一


def test_shipped_warnings_format_without_error():
    """模板 CI：所有内置规则的 warning 必须能被 format_warning 渲染，无残留占位符。"""
    for rule in load_rules(DEFAULT_RULES_DIR).rules:
        rendered = format_warning(rule, count=2, total_mg=1000)
        assert "{" not in rendered and "}" not in rendered, rule.id


# ── 匹配语义 ────────────────────────────────────────────────


def test_single_match_and_non_match():
    """两个含对乙酰氨基酚的条目命中 acetaminophen-overlap；只有一个则不命中。"""
    ruleset = load_rules(DEFAULT_RULES_DIR)
    two = [
        Ingredient(name="对乙酰氨基酚", amount=325, unit="mg"),
        Ingredient(name="对乙酰氨基酚", amount=500, unit="mg"),
    ]
    assert "acetaminophen-overlap" in [r.id for r in match_rules(ruleset, two)]

    one = [Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")]
    assert "acetaminophen-overlap" not in [r.id for r in match_rules(ruleset, one)]


def test_min_count_semantics():
    two = [
        Ingredient(name="对乙酰氨基酚", amount=500, unit="mg"),
        Ingredient(name="对乙酰氨基酚", amount=300, unit="mg"),
    ]
    one = two[:1]
    assert match_rules(_rule(min_count=2), one) == []
    assert len(match_rules(_rule(min_count=2), two)) == 1
    assert len(match_rules(_rule(min_count=1), one)) == 1


def test_multi_trigger_preserves_rule_order():
    ruleset = load_rules(DEFAULT_RULES_DIR)
    flat = [
        Ingredient(name="对乙酰氨基酚", amount=325, unit="mg"),
        Ingredient(name="对乙酰氨基酚", amount=500, unit="mg"),
        Ingredient(name="布洛芬", amount=300, unit="mg"),
        Ingredient(name="布洛芬", amount=200, unit="mg"),
    ]
    ids = [r.id for r in match_rules(ruleset, flat)]
    assert "acetaminophen-overlap" in ids and "ibuprofen-overlap" in ids
    # 确定性：保持规则文件顺序（overlap.yaml 中乙酰在前）
    assert ids.index("acetaminophen-overlap") < ids.index("ibuprofen-overlap")


def test_substance_match_alcohol():
    ruleset = load_rules(DEFAULT_RULES_DIR)
    ibuprofen = [Ingredient(name="布洛芬", amount=300, unit="mg")]
    assert "ibuprofen-alcohol" in [
        r.id for r in match_rules(ruleset, ibuprofen, ["酒精"])
    ]
    # 用户自报物质 strip 后精确匹配
    assert "ibuprofen-alcohol" in [
        r.id for r in match_rules(ruleset, ibuprofen, [" 酒精 "])
    ]
    assert "ibuprofen-alcohol" not in [
        r.id for r in match_rules(ruleset, ibuprofen, ["咖啡"])
    ]
    assert "ibuprofen-alcohol" not in [
        r.id for r in match_rules(ruleset, ibuprofen)
    ]


def test_min_amount_filter():
    rs = _rule(min_amount_mg=100)
    assert match_rules(rs, [Ingredient(name="对乙酰氨基酚", amount=50, unit="mg")]) == []
    assert (
        len(match_rules(rs, [Ingredient(name="对乙酰氨基酚", amount=150, unit="mg")]))
        == 1
    )


def test_unit_conversion_in_matching():
    """0.5g = 500mg，参与 min_amount_mg 比较。"""
    rs = _rule(min_amount_mg=400)
    assert len(match_rules(rs, [Ingredient(name="对乙酰氨基酚", amount=0.5, unit="g")])) == 1


def test_unknown_unit_still_counts_for_min_count():
    """铁律 #4 保守：未知剂量不掩盖重复成分（无门槛条件仍计数）；有剂量门槛则不计。"""
    two_unknown = [
        Ingredient(name="对乙酰氨基酚", amount=1, unit="勺"),
        Ingredient(name="对乙酰氨基酚", amount=2, unit="勺"),
    ]
    assert len(match_rules(_rule(min_count=2), two_unknown)) == 1
    assert match_rules(_rule(min_count=2, min_amount_mg=100), two_unknown) == []


def test_empty_ingredients_no_raise():
    ruleset = load_rules(DEFAULT_RULES_DIR)
    assert match_rules(ruleset, []) == []
    assert check_conflicts(ruleset, [], None) == []


def test_confidence_and_source_passthrough():
    ruleset = load_rules(DEFAULT_RULES_DIR)
    sjw = next(r for r in ruleset.rules if r.id == "st-johns-wort-contraceptive")
    assert sjw.confidence == "medium"
    assert sjw.source


def test_count_matches_pure():
    cond = IngredientCondition(name="布洛芬")
    assert count_matches(cond, [Ingredient(name="布洛芬")]) == 1
    assert count_matches(cond, [Ingredient(name="阿司匹林")]) == 0


# ── warning 渲染 ────────────────────────────────────────────


def test_format_warning_substitution():
    rule = _rule().rules[0]
    assert format_warning(rule, count=2, total_mg=1300.0) == "w 2/1300.0"


def test_format_warning_unknown_total_says_uncertain():
    """铁律 #4：拿不准必须明说——总剂量未知时渲染「未知」。"""
    rule = _rule().rules[0]
    assert "未知" in format_warning(rule, count=2, total_mg=None)


def test_format_warning_keeps_unknown_placeholders():
    rule = _rule(warning="hi {who}").rules[0]
    assert format_warning(rule, count=1, total_mg=1) == "hi {who}"


def test_format_warning_broken_template_falls_back():
    """坏模板回落原文，绝不抛异常炸接口。"""
    rule = _rule(warning="bad { 模板").rules[0]
    assert format_warning(rule, count=1, total_mg=1) == "bad { 模板"


# ── load_rules 失败要响 ─────────────────────────────────────


def test_load_rules_syntax_error_readable(tmp_path):
    (tmp_path / "bad.yaml").write_text("rules: [unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match="校验失败"):
        load_rules(tmp_path)


def test_load_rules_validation_error_readable(tmp_path):
    # 缺必填字段 → Pydantic 校验失败，包装为可读 ValueError
    (tmp_path / "x.yaml").write_text(
        "rules:\n  - id: a\n    title: t\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="校验失败"):
        load_rules(tmp_path)


def test_load_rules_duplicate_id_rejected(tmp_path):
    body = (
        "rules:\n"
        "  - id: dup\n    title: t\n    severity: info\n    description: d\n"
        "    conditions:\n      ingredients:\n        - name: X\n"
        "    warning: w\n    confidence: high\n"
    )
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="dup"):
        load_rules(tmp_path)


def test_load_rules_no_conditions_rejected(tmp_path):
    """零条件规则会匹配一切 = 误报噪音，加载即拒。"""
    (tmp_path / "a.yaml").write_text(
        "rules:\n  - id: empty\n    title: t\n    severity: info\n    description: d\n"
        "    conditions: {}\n    warning: w\n    confidence: high\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="empty"):
        load_rules(tmp_path)


def test_load_rules_empty_dir_rejected(tmp_path):
    with pytest.raises(ValueError, match="规则文件"):
        load_rules(tmp_path)

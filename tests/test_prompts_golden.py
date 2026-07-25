"""app/prompts 的 golden 测试（重构防护网）。

与 test_prompts.py 的关键词断言不同，本文件对 tests/golden/ 下的黄金文件做
**逐字比对**，锁定当前模板的完整渲染结果——重构期间任何一字漂移立刻变红。
变红即代表模板内容发生了改变，必须显式决策（接受新文案并有意识地重新生成
golden，或改回原文案），严禁为了让测试通过而悄悄编辑 golden。

重新生成 golden（仅在确认文案变更为有意之后）：
    PILLCLEAR_REGEN_GOLDEN=1 python -m pytest tests/test_prompts_golden.py
Windows PowerShell：
    $env:PILLCLEAR_REGEN_GOLDEN=1; python -m pytest tests/test_prompts_golden.py
    Remove-Item env:PILLCLEAR_REGEN_GOLDEN
"""

import os
from pathlib import Path

from app.knowledge.schemas import Citation
from app.medbox.schemas import CheckReport, IngredientTotal, OverlapResult
from app.prompts.chat import build_system_prompt
from app.prompts.formatters import (
    format_check_report_for_prompt,
    format_citations_for_prompt,
)
from app.prompts.ingest import INGREDIENT_SYSTEM_PROMPT
from app.prompts.intent import build_intent_messages
from app.prompts.safety import SAFETY_CLASSIFY_SYSTEM_PROMPT, build_safety_messages
from app.rules.schemas import IngredientCondition, Rule, RuleConditions

GOLDEN_DIR = Path(__file__).parent / "golden"
_REGEN = bool(os.environ.get("PILLCLEAR_REGEN_GOLDEN"))


def _assert_golden(name: str, actual: str) -> None:
    """逐字比对黄金文件；PILLCLEAR_REGEN_GOLDEN=1 时改写黄金文件。"""
    path = GOLDEN_DIR / name
    if _REGEN:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
        return
    assert path.exists(), (
        f"黄金文件 {path} 不存在；首次生成或确认文案有意变更后，"
        "用 PILLCLEAR_REGEN_GOLDEN=1 重新生成"
    )
    # 默认 universal newlines 读取：CRLF checkout 会还原为 \n，与库内字符串一致
    expected = path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"模板内容与黄金文件 {name} 发生漂移——若重构有意改动文案，"
        "请审核后用 PILLCLEAR_REGEN_GOLDEN=1 重新生成 golden，并在 commit 说明改动"
    )


# ── 固定输入（所有 golden 共用，保证可复现）────────────────────


def _citations() -> list[Citation]:
    return [
        Citation(brand_name="布洛芬", section="用法用量", excerpt="成人一次1粒，一日2次。"),
        Citation(brand_name="布洛芬", section="不良反应", excerpt="可见恶心、胃烧灼感。"),
        Citation(brand_name="泰诺", section="成份", excerpt="每片含对乙酰氨基酚325毫克。"),
    ]


def _overlap_rule() -> Rule:
    return Rule(
        id="acetaminophen-overlap",
        title="对乙酰氨基酚重复过量",
        severity="danger",
        description="两种药都含对乙酰氨基酚",
        conditions=RuleConditions(
            ingredients=[IngredientCondition(name="对乙酰氨基酚", min_count=2)]
        ),
        warning="⚠️ 你在吃 2 种含对乙酰氨基酚的药，每日合计约 825.0mg。",
        confidence="high",
    )


def _combo_report() -> CheckReport:
    """四种信号同时出现的组合报告：锁定多段渲染顺序。"""
    return CheckReport(
        overlap=OverlapResult(
            warnings=["⚠️ 对乙酰氨基酚每日合计超限。"],
            overlapping=[
                IngredientTotal(
                    name="对乙酰氨基酚",
                    total_amount_mg=825.0,
                    sources=["泰诺", "必理通"],
                    max_daily_mg=4000.0,
                )
            ],
        ),
        triggered_rules=[_overlap_rule()],
        unresolved_drugs=["某神秘药"],
    )


# ── 对话 system prompt ──────────────────────────────────────


class TestSystemPromptGolden:

    def test_no_citations(self):
        _assert_golden("chat_system_no_citations.txt", build_system_prompt([]))

    def test_none_citations_renders_same_as_empty(self):
        # None 与空列表走同一降级路径，渲染必须完全一致
        assert build_system_prompt(None) == build_system_prompt([])

    def test_with_citations(self):
        _assert_golden(
            "chat_system_with_citations.txt", build_system_prompt(_citations())
        )

    def test_with_check_context(self):
        check_context = (
            "规则引擎检测到以下风险（确定性结论，必须原样传达，不得否定或改写）：\n"
            "- 【danger｜对乙酰氨基酚重复过量】⚠️ 你在吃 2 种含对乙酰氨基酚的药。"
        )
        _assert_golden(
            "chat_system_with_check.txt",
            build_system_prompt(_citations(), check_context=check_context),
        )


# ── 分类器 prompt（意图 / 安全 / 入库抽取）────────────────────


class TestClassifierPromptGolden:

    def test_intent_system(self):
        _assert_golden("intent_system.txt", build_intent_messages("x")[0]["content"])

    def test_safety_system(self):
        _assert_golden("safety_system.txt", build_safety_messages("x")[0]["content"])

    def test_safety_constant_matches_builder(self):
        # builder 必须原样使用导出常量，不得在函数内二次拼接
        assert build_safety_messages("x")[0]["content"] == SAFETY_CLASSIFY_SYSTEM_PROMPT

    def test_ingredient_prompt(self):
        _assert_golden("ingredient_prompt.txt", INGREDIENT_SYSTEM_PROMPT)


# ── 引用格式化 ───────────────────────────────────────────────


class TestCitationsFormatGolden:

    def test_grouped_block(self):
        _assert_golden("citations_block.txt", format_citations_for_prompt(_citations()))

    def test_empty_fallback(self):
        _assert_golden("citations_empty.txt", format_citations_for_prompt([]))


# ── 检查报告格式化（六个分支全覆盖）───────────────────────────


class TestCheckReportFormatGolden:

    def test_empty_report_no_risk_branch(self):
        # 「无风险」分支：也必须返回说明性文本，让 LLM 如实转达
        report = CheckReport(overlap=OverlapResult())
        _assert_golden("report_empty.txt", format_check_report_for_prompt(report))

    def test_unresolved_drugs(self):
        report = CheckReport(overlap=OverlapResult(), unresolved_drugs=["某神秘药"])
        _assert_golden("report_unresolved.txt", format_check_report_for_prompt(report))

    def test_triggered_rules(self):
        report = CheckReport(
            overlap=OverlapResult(), triggered_rules=[_overlap_rule()]
        )
        _assert_golden("report_triggered.txt", format_check_report_for_prompt(report))

    def test_overlap_warnings(self):
        report = CheckReport(
            overlap=OverlapResult(warnings=["⚠️ 对乙酰氨基酚每日合计超限。"])
        )
        _assert_golden(
            "report_overlap_warnings.txt", format_check_report_for_prompt(report)
        )

    def test_shared_ingredients(self):
        # 「共享成分」分支
        report = CheckReport(
            overlap=OverlapResult(
                overlapping=[
                    IngredientTotal(
                        name="对乙酰氨基酚",
                        total_amount_mg=825.0,
                        sources=["泰诺", "必理通"],
                        max_daily_mg=4000.0,
                    )
                ]
            )
        )
        _assert_golden("report_shared.txt", format_check_report_for_prompt(report))

    def test_combo_rendering_order(self):
        # 四段信号齐全时的渲染顺序：未收录 → 触发规则 → 叠加警告 → 共享成分
        _assert_golden("report_combo.txt", format_check_report_for_prompt(_combo_report()))

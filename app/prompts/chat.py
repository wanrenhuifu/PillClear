"""聊天提示词：系统角色 + RAG 上下文注入 + 检查结论槽位。

铁律 #2：所有用药相关回答必须携带说明书原文引用（citations_used 非空）。
铁律 #3/#4：能力边界与不确定原则写进 prompt，代码层再做兜底。

意图分类的枚举 / 模型 / prompt 位于 app/prompts/intent.py；此处为向后兼容
再导出（历史调用方从 app.prompts.chat 引入 IntentCategory 等）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# 向后兼容再导出：意图分类定义已迁入 app/prompts/intent.py
from app.prompts.intent import (  # noqa: F401
    IntentCategory,
    IntentResult,
    build_intent_messages,
)

from app.prompts.templates.chat_system import (
    CHECK_RELAY_REQUIREMENTS,
    CHECK_SECTION_HEADER,
    RAG_SECTION_HEADER,
    _SYSTEM_ROLE_AND_RULES,
)

if TYPE_CHECKING:
    from app.knowledge.schemas import Citation
    from app.medbox.schemas import CheckReport


# ═══════════════════════════════════════════════════════════════
# 对话系统 Prompt（带 RAG 上下文注入）
# ═══════════════════════════════════════════════════════════════


def format_citations_for_prompt(citations: list[Citation]) -> str:
    """将检索到的引用格式化为 prompt 可用的文本块。

    每个引用包含药品名、章节名、原文摘录，按药品分组。
    空引用返回提示性文本。
    """
    if not citations:
        return "（未检索到相关说明书原文，请基于你的知识回答，但必须在 confidence 中反映不确定性——最高不超过 0.5）"

    lines: list[str] = []
    # 按商品名分组
    by_brand: dict[str, list[Citation]] = {}
    for c in citations:
        by_brand.setdefault(c.brand_name, []).append(c)

    for brand_name, refs in by_brand.items():
        lines.append(f"### {brand_name}")
        for r in refs:
            lines.append(f"- 【{r.section}】{r.excerpt}")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 检查报告格式化（任务四：规则引擎结论注入 prompt）
# ═══════════════════════════════════════════════════════════════


def format_check_report_for_prompt(report: CheckReport) -> str:
    """将确定性规则引擎的 CheckReport 格式化为 prompt 上下文。

    铁律 #1：检查结论由规则引擎产出，LLM 只负责翻译成大白话，不得改写结论。
    铁律 #4：unresolved_drugs 非空时必须明示「暂未收录、无法检测」，不得静默忽略。

    返回文本供 build_system_prompt(check_context=...) 注入检查槽位；
    即使「无风险」也返回说明性文本，让 LLM 能如实转达「未检测到风险」。
    """
    lines: list[str] = []

    # 未收录药品：最高优先明示（铁律 #4）
    if report.unresolved_drugs:
        lines.append(
            "以下药品暂未收录，无法检测其成分与相互作用："
            + "、".join(report.unresolved_drugs)
            + "。请在回答中明确告知用户这些药暂时查不到，建议咨询药师。"
        )

    # 规则引擎触发的冲突规则（确定性结论，必须原样传达）
    if report.triggered_rules:
        lines.append("规则引擎检测到以下风险（确定性结论，必须原样传达，不得否定或改写）：")
        for rule in report.triggered_rules:
            lines.append(f"- 【{rule.severity}｜{rule.title}】{rule.warning}")

    # 成分叠加超限警告（纯代码计算结果，铁律 #1）
    if report.overlap.warnings:
        lines.append("成分叠加超限警告（代码计算，必须传达）：")
        for warning in report.overlap.warnings:
            lines.append(f"- {warning}")

    # 共享成分信息（帮助 LLM 说明「哪几种药共享什么成分」）
    shared = [
        t
        for t in report.overlap.overlapping
        if len(t.sources) >= 2
    ]
    if shared:
        lines.append("被多种药品共享的成分（叠加来源）：")
        for t in shared:
            lines.append(
                f"- {t.name}：来自 {'、'.join(t.sources)}，"
                f"每日合计约 {t.total_amount_mg}mg"
            )

    if not lines:
        return "规则引擎未检测到成分叠加或已知相互作用。请如实告知用户目前未检测到风险，但仍提醒按说明书用量服用。"

    return "\n".join(lines)


def build_system_prompt(
    citations: list[Citation] | None = None,
    check_context: str | None = None,
) -> str:
    """构造完整的 system prompt：角色 + 规则 + RAG 上下文 +（可选）检查结论。

    citations 为 None 或空列表时，提示中说明无原文可用。
    check_context 非 None 时（任务四：意图为药-药 / 药-物质相互作用），追加规则引擎结论槽位，
    并明确要求 LLM 只翻译、不改写确定性结论（铁律 #1）。
    """
    rag_context = format_citations_for_prompt(citations or [])
    prompt = _SYSTEM_ROLE_AND_RULES + RAG_SECTION_HEADER + rag_context
    if check_context:
        prompt += CHECK_SECTION_HEADER + check_context + CHECK_RELAY_REQUIREMENTS
    return prompt


def build_chat_messages(
    query: str,
    citations: list[Citation] | None = None,
    chat_history: list[dict[str, str]] | None = None,
    check_context: str | None = None,
) -> list[dict[str, str]]:
    """构造完整的 /chat messages 列表。

    包含 system prompt（含 RAG 上下文、可选检查结论）、可选的对话历史、
    当前用户问题。
    """
    system = build_system_prompt(citations, check_context=check_context)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if chat_history:
        messages.extend(chat_history)
    messages.append({"role": "user", "content": query})
    return messages

"""聊天提示词组装：系统角色 + RAG 上下文注入 + 检查结论槽位。

铁律 #2：所有用药相关回答必须携带说明书原文引用（citations_used 非空）。
铁律 #3/#4：能力边界与不确定原则写进 prompt，代码层再做兜底。

静态模板文案在 app/prompts/templates/chat_system.py；
格式化函数在 app/prompts/formatters.py；意图分类在 app/prompts/intent.py。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.prompts.formatters import format_citations_for_prompt
from app.prompts.templates.chat_system import (
    AMBIGUITY_SECTION_HEADER,
    CHECK_RELAY_REQUIREMENTS,
    CHECK_SECTION_HEADER,
    RAG_SECTION_HEADER,
    _SYSTEM_ROLE_AND_RULES,
)

if TYPE_CHECKING:
    from app.knowledge.schemas import Citation


def build_system_prompt(
    citations: list[Citation] | None = None,
    check_context: str | None = None,
    ambiguity_note: str | None = None,
) -> str:
    """构造完整的 system prompt：角色 + 规则 + RAG 上下文 +（可选）检查结论 +（可选）近似匹配提示。

    check_context 非 None 时追加规则引擎结论槽位（CHECK_SECTION_HEADER +
    CHECK_RELAY_REQUIREMENTS，铁律 #1：只翻译、不改写）。
    ambiguity_note 非 None 时追加独立近似匹配提示槽位（中立标题，无「确定性」
    头、无「不能改写」要求）——它只是核名披露（铁律 #4），不是规则引擎结论
    （code review 修复：启发式披露不得伪装成确定性结论）。
    """
    rag_context = format_citations_for_prompt(citations or [])
    prompt = _SYSTEM_ROLE_AND_RULES + RAG_SECTION_HEADER + rag_context
    if ambiguity_note:
        prompt += AMBIGUITY_SECTION_HEADER + ambiguity_note
    if check_context:
        prompt += CHECK_SECTION_HEADER + check_context + CHECK_RELAY_REQUIREMENTS
    return prompt


def build_chat_messages(
    query: str,
    citations: list[Citation] | None = None,
    chat_history: list[dict[str, str]] | None = None,
    check_context: str | None = None,
    ambiguity_note: str | None = None,
) -> list[dict[str, str]]:
    """构造完整的 /chat messages 列表。

    包含 system prompt（含 RAG 上下文、可选检查结论、可选近似匹配提示）、
    可选的对话历史、当前用户问题。
    """
    system = build_system_prompt(
        citations,
        check_context=check_context,
        ambiguity_note=ambiguity_note,
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if chat_history:
        messages.extend(chat_history)
    messages.append({"role": "user", "content": query})
    return messages

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

from app.prompts.formatters import format_citations_for_prompt
from app.prompts.templates.chat_system import (
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

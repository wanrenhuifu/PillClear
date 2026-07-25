"""PillClear 提示词模块。

所有 LLM 提示词集中管理，便于测试、A/B 实验与迭代。
提示词设计原则：
- 角色明确：PillClear 的年轻化"朋友"人设
- 引用强制：RAG 上下文必须被使用并标注来源（铁律 #2）
- 安全底线：明确的能力边界（铁律 #3/#4）
- 输出可控：JSON mode，结构化输出 + Pydantic 校验
"""

from app.prompts.chat import (
    build_chat_messages,
    build_system_prompt,
)
from app.prompts.formatters import (
    format_citations_for_prompt,
    format_check_report_for_prompt,
)
from app.prompts.ingest import INGREDIENT_SYSTEM_PROMPT
from app.prompts.intent import (
    IntentCategory,
    IntentResult,
    build_intent_messages,
)
from app.prompts.safety import (
    SAFETY_CLASSIFY_SYSTEM_PROMPT,
    SafetyLLMResult,
    build_safety_messages,
)

__all__ = [
    "IntentCategory",
    "IntentResult",
    "build_chat_messages",
    "build_intent_messages",
    "build_system_prompt",
    "format_citations_for_prompt",
    "format_check_report_for_prompt",
    "INGREDIENT_SYSTEM_PROMPT",
    "SAFETY_CLASSIFY_SYSTEM_PROMPT",
    "SafetyLLMResult",
    "build_safety_messages",
]

"""意图分类提示词（任务一 / 任务三）。

把用户问题归入四类之一，并抽取药名 / 非药物摄入，供 /chat 选择
RAG 检索策略与是否触发确定性冲突检测。意图分类是「路由」而非「药学判断」，
分类失败在路由层降级为 drug_info，不影响主流程（见 app/api/routes.py）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class IntentCategory(str, Enum):
    """用户问题意图分类。"""

    DRUG_INFO = "drug_info"  # 药品说明书查询：成分、用法、副作用等
    CONFLICT_CHECK = "conflict_check"  # 药物冲突：两种药能不能一起吃
    LIFESTYLE_INTERACTION = "lifestyle_interaction"  # 药物与食物/酒精/保健品
    GENERAL_HEALTH = "general_health"  # 一般健康咨询（感冒怎么办等）


class IntentResult(BaseModel):
    """LLM 意图分类输出。"""

    intent: IntentCategory
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    drug_names: list[str] = Field(
        default_factory=list,
        description="问题中提及的药品名（用于检索与冲突检测）",
    )
    lifestyle_substances: list[str] = Field(
        default_factory=list,
        description="问题中提及的非药物摄入（酒精、避孕药、葡萄柚等）",
    )


_INTENT_SYSTEM_PROMPT = (
    "你是一个轻量级意图分类器，分析用户输入并输出 JSON。\n"
    "分类标准：\n"
    "- drug_info：查询具体药品的信息（成分、用法用量、副作用、禁忌等），"
    "或一般性用药常识。\n"
    "- conflict_check：询问两种或以上药物能否同时服用、有无冲突、"
    "需要间隔多久。\n"
    "- lifestyle_interaction：询问药物与酒精、食物、保健品、"
    "特殊饮食（如葡萄柚）的相互作用。\n"
    "- general_health：感冒、发烧、头痛等一般健康问题咨询，"
    "未提及具体药品名。\n\n"
    "drug_names 和 lifestyle_substances 从用户输入中提取，"
    "未提及则为空列表。\n\n"
    '严格输出 JSON：{"intent":"分类","confidence":0.0~1.0,'
    '"drug_names":["药名"],"lifestyle_substances":["物质名"]}'
)


def build_intent_messages(query: str) -> list[dict[str, str]]:
    """构造意图分类的 messages（低 max_tokens 调用，追求快）。"""
    return [
        {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]


__all__ = [
    "IntentCategory",
    "IntentResult",
    "build_intent_messages",
]

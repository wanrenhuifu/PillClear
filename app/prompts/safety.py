"""能力边界 LLM 二次分类提示词（任务五）。

铁律 #3：处方药 / 疾病诊断 / 特殊人群 / 急症属于越界问题。
关键词规则（app/core/safety.py::detect_category）是第一道、也是主防线；
本提示词只在关键词放行（NONE）时做「补漏」式二次判断，减少漏判。

关键约束（写进 prompt + 代码双保险）：
- LLM 只能把问题归入固定五类之一（含 none），不得自由发挥药学结论。
- LLM 结论必须回落到 BoundaryCategory 枚举 + 固定话术（代码层完成）。
- 低置信度 / 解析失败 / 调用失败一律回落到关键词结果（NONE），宁可不拦也不误拦，
  但关键词已拦的绝不会被 LLM 放行（见 check_boundary_with_llm 的短路逻辑）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SafetyLLMResult(BaseModel):
    """LLM 能力边界分类输出。

    category 用字符串而非直接绑定 BoundaryCategory：提示词模块不得反向依赖
    core 层枚举，映射在 app/core/safety.py::classify_with_llm 内完成，
    非法取值在那里回落到 NONE。
    """

    category: str = Field(
        default="none",
        description=(
            "越界分类，仅限以下取值之一："
            "emergency / special_population / diagnosis / prescription / none"
        ),
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="对该分类的置信度；低于阈值时代码回落到关键词结果",
    )


SAFETY_CLASSIFY_SYSTEM_PROMPT = (
    "你是用药安全助手的「能力边界」分类器，只判断用户问题是否属于以下越界类别，"
    "不回答任何药学问题，严格输出 JSON。\n"
    "分类标准（五选一）：\n"
    "- emergency：出现急症信号，如呼吸困难、严重过敏、剧烈胸痛、抽搐、昏迷、"
    "高热持续不退、大出血等需要立即就医的情况。\n"
    "- special_population：涉及孕妇、哺乳期、儿童、婴幼儿、老人，"
    "或高血压/糖尿病/冠心病/肝肾病等慢病人群的个性化用药。\n"
    "- diagnosis：要求诊断疾病、解读症状或化验/检查/体检报告。\n"
    "- prescription：涉及处方药（如抗生素、阿莫西林、头孢、安眠药等）的用法用量。\n"
    "- none：普通 OTC 非处方药 / 保健品咨询，不属于以上任何越界类别。\n\n"
    "判断原则：\n"
    "- 拿不准时倾向 none，不要过度拦截普通的 OTC 用药咨询。\n"
    "- 但真实的急症 / 特殊人群信号不得漏判，此时 confidence 给高一些。\n"
    "- 注意否定语境：如「我没有呼吸困难」「不是处方药」不应判为越界。\n\n"
    '严格输出 JSON：{"category":"五类之一","confidence":0.0~1.0}'
)


def build_safety_messages(query: str) -> list[dict[str, str]]:
    """构造能力边界分类的 messages（低 max_tokens 调用，追求快）。"""
    return [
        {"role": "system", "content": SAFETY_CLASSIFY_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]


__all__ = [
    "SafetyLLMResult",
    "SAFETY_CLASSIFY_SYSTEM_PROMPT",
    "build_safety_messages",
]

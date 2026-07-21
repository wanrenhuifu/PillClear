"""LLM 层异常定义。"""

from __future__ import annotations


class LLMError(Exception):
    """LLM 层错误基类。"""


class LLMRetryExhausted(LLMError):
    """重试次数耗尽仍未得到合法响应。"""

    def __init__(self, attempts: int, last_error: Exception | None = None) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"LLM 调用在 {attempts} 次尝试后仍未返回合法 JSON；"
            f"最后一次错误：{last_error!r}"
        )

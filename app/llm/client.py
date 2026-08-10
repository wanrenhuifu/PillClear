"""DeepSeek LLM 客户端封装。

职责：
- 通过 openai SDK 走 DeepSeek（OpenAI 兼容协议）。
- 强制 JSON mode，返回结果用调用方给定的 Pydantic 模型校验。
- 解析 / 校验失败时把错误信息回灌进对话并自动重试（最多 settings.llm_max_retries 次）。
- 传输层瞬时故障（连接/超时、限流、服务端 5xx）退避重试；400/401 等立即上抛。
- 记录 usage 与 prompt_cache_hit_tokens 日志。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import DEPRECATED_MODELS, Settings
from app.llm.errors import LLMRetryExhausted
from app.llm.providers import resolve_api_key, resolve_base_url, resolve_model

logger = logging.getLogger("app.llm")

T = TypeVar("T", bound=BaseModel)

_JSON_RESPONSE_FORMAT = {"type": "json_object"}

# 值得重试的瞬时错误（APIConnectionError 已含超时）；
# 参数 / 鉴权错误（400/401 等）重试无意义，让其立即上抛。
_RETRYABLE_ERRORS = (
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class LLMClient:
    """DeepSeek 客户端。openai client 可注入以便测试。"""

    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAI(
            api_key=resolve_api_key(settings),
            base_url=resolve_base_url(settings),
        )

    def complete_json(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> T:
        """调用 LLM 并返回经 response_model 校验的实例。

        失败自动重试，最多 settings.llm_max_retries 次（共 max_retries + 1 次尝试）。
        全部失败抛 LLMRetryExhausted。
        """

        model_name = model or resolve_model(self._settings)
        # 铁律：旧模型名禁令必须覆盖每一个模型名入口，不能只在 Settings 构造处拦截
        if model_name in DEPRECATED_MODELS:
            raise ValueError(
                f"模型名 {model_name!r} 已废弃，禁止使用；"
                f"请使用 'deepseek-v4-pro'。"
            )
        # response_format 被强制为 JSON mode；调用方显式传入会得到晦涩的
        # "duplicate keyword argument" TypeError，不如在这里明确拒绝。
        if "response_format" in kwargs:
            raise ValueError(
                "response_format 由 complete_json 强制指定为 JSON mode，不接受覆盖"
            )

        max_attempts = self._settings.llm_max_retries + 1
        conversation = list(messages)
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                response = self._client.chat.completions.create(
                    model=model_name,
                    messages=conversation,
                    response_format=_JSON_RESPONSE_FORMAT,
                    **kwargs,
                )
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                logger.warning(
                    "LLM 调用失败（第 %d/%d 次），准备重试：%s",
                    attempt + 1,
                    max_attempts,
                    exc,
                )
                if attempt + 1 < max_attempts:
                    time.sleep(min(2 ** attempt, 30))
                continue

            self._log_usage(response)

            if not response.choices:
                last_error = ValueError("API 返回空 choices 列表")
                logger.warning("LLM 响应异常，准备重试：%s", last_error)
                conversation = [
                    *conversation,
                    {"role": "assistant", "content": ""},
                    {
                        "role": "user",
                        "content": "上次返回异常（空响应），请重新输出严格符合要求的 JSON。",
                    },
                ]
                continue

            content = response.choices[0].message.content or ""
            try:
                data = json.loads(content)
                return response_model.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning("LLM 响应解析/校验失败，准备重试：%s", exc)
                conversation = [
                    *conversation,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "上次返回的内容无法解析或未通过校验，"
                            f"错误：{exc}。请只输出严格符合要求的 JSON，不要多余文字。"
                        ),
                    },
                ]

        raise LLMRetryExhausted(max_attempts, last_error)

    @staticmethod
    def _get_usage_field(usage: Any, name: str) -> Any:
        """从容错读取 usage 字段（优先直接属性，其次 model_extra dict）。"""
        value = getattr(usage, name, None)
        if value is None:
            extra = getattr(usage, "model_extra", None)
            if extra:
                value = extra.get(name)
        return value

    def _log_usage(self, response: Any) -> None:
        """记录 token 用量与缓存命中（字段缺失时容错）。"""

        usage = getattr(response, "usage", None)
        if usage is None:
            return

        logger.info(
            "LLM usage | prompt_tokens=%s completion_tokens=%s total_tokens=%s "
            "prompt_cache_hit_tokens=%s",
            self._get_usage_field(usage, "prompt_tokens"),
            self._get_usage_field(usage, "completion_tokens"),
            self._get_usage_field(usage, "total_tokens"),
            self._get_usage_field(usage, "prompt_cache_hit_tokens"),
        )


__all__ = ["LLMClient", "LLMRetryExhausted"]

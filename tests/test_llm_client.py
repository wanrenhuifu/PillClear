"""app.llm.client.LLMClient 与 app.config.Settings 的单元测试。

通过 respx 在 HTTP 层拦截 openai SDK 发出的请求，不产生真实网络调用。
校验模型统一使用生产环境的 LLMAnswer（含 confidence 取值范围约束），
避免测试专用模型与生产 schema 漂移。
"""

import json
import logging

import httpx
import pytest
from pydantic import ValidationError

from app.api.schemas import LLMAnswer
from app.config import DEFAULT_MODEL, Settings
from app.llm.client import LLMClient
from app.llm.errors import LLMRetryExhausted
from tests.conftest import DEEPSEEK_URL, make_completion


def _client(settings: Settings) -> LLMClient:
    return LLMClient(settings)


def test_success_parses_and_validates(respx_mock, settings):
    respx_mock.post(DEEPSEEK_URL).mock(
        return_value=make_completion('{"answer":"多喝水休息","confidence":0.9}')
    )
    result = _client(settings).complete_json(
        [{"role": "user", "content": "感冒了怎么办"}], LLMAnswer
    )
    assert isinstance(result, LLMAnswer)
    assert result.answer == "多喝水休息"
    assert result.confidence == 0.9


def test_logs_usage_tokens(respx_mock, settings, caplog):
    respx_mock.post(DEEPSEEK_URL).mock(
        return_value=make_completion('{"answer":"a","confidence":0.1}')
    )
    with caplog.at_level(logging.INFO, logger="app.llm"):
        _client(settings).complete_json([{"role": "user", "content": "x"}], LLMAnswer)
    assert "prompt_tokens=10" in caplog.text
    assert "completion_tokens=5" in caplog.text
    assert "total_tokens=15" in caplog.text


def test_logs_prompt_cache_hit_tokens(respx_mock, settings, caplog):
    usage = {
        "prompt_tokens": 20,
        "completion_tokens": 4,
        "total_tokens": 24,
        "prompt_cache_hit_tokens": 8,
    }
    respx_mock.post(DEEPSEEK_URL).mock(
        return_value=make_completion('{"answer":"a","confidence":0.1}', usage=usage)
    )
    with caplog.at_level(logging.INFO, logger="app.llm"):
        _client(settings).complete_json([{"role": "user", "content": "x"}], LLMAnswer)
    assert "prompt_cache_hit_tokens=8" in caplog.text


def test_retries_on_invalid_json_then_succeeds(respx_mock, settings):
    respx_mock.post(DEEPSEEK_URL).mock(
        side_effect=[
            make_completion("这不是 JSON"),
            make_completion('{"answer":"好了","confidence":0.5}'),
        ]
    )
    result = _client(settings).complete_json(
        [{"role": "user", "content": "x"}], LLMAnswer
    )
    assert result.answer == "好了"


def test_retries_on_validation_error_then_succeeds(respx_mock, settings):
    # 首次 JSON 合法但缺少必填字段 -> ValidationError -> 重试
    respx_mock.post(DEEPSEEK_URL).mock(
        side_effect=[
            make_completion('{"foo": 1}'),
            make_completion('{"answer":"ok","confidence":0.7}'),
        ]
    )
    result = _client(settings).complete_json(
        [{"role": "user", "content": "x"}], LLMAnswer
    )
    assert result.confidence == 0.7


def test_retries_on_connection_error_then_succeeds(respx_mock, settings):
    # 传输层瞬时故障（连接错误）应走退避重试，而不是直接上抛 500
    respx_mock.post(DEEPSEEK_URL).mock(
        side_effect=[
            httpx.ConnectError("connection reset"),
            make_completion('{"answer":"好了","confidence":0.5}'),
        ]
    )
    result = _client(settings).complete_json(
        [{"role": "user", "content": "x"}], LLMAnswer
    )
    assert result.answer == "好了"


def test_transport_errors_exhaust_to_retry_exhausted(respx_mock, settings):
    # 传输层持续故障 → 重试耗尽后抛 LLMRetryExhausted（路由层转 502）
    respx_mock.post(DEEPSEEK_URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(LLMRetryExhausted) as exc_info:
        _client(settings).complete_json([{"role": "user", "content": "x"}], LLMAnswer)
    assert exc_info.value.attempts == 3


def test_raises_when_retries_exhausted(respx_mock, settings):
    # max_retries 默认 2 -> 共 3 次尝试，全部非法 JSON
    respx_mock.post(DEEPSEEK_URL).mock(
        side_effect=[
            make_completion("bad-1"),
            make_completion("bad-2"),
            make_completion("bad-3"),
        ]
    )
    with pytest.raises(LLMRetryExhausted) as exc_info:
        _client(settings).complete_json([{"role": "user", "content": "x"}], LLMAnswer)
    assert exc_info.value.attempts == 3


def test_default_model_is_deepseek_v4_pro(respx_mock, settings):
    route = respx_mock.post(DEEPSEEK_URL).mock(
        return_value=make_completion('{"answer":"a","confidence":0.1}')
    )
    _client(settings).complete_json([{"role": "user", "content": "x"}], LLMAnswer)
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == DEFAULT_MODEL


def test_config_injection_overrides(respx_mock):
    custom_url = "https://custom.example.com/chat/completions"
    route = respx_mock.post(custom_url).mock(
        return_value=make_completion('{"answer":"a","confidence":0.1}')
    )
    settings = Settings(
        deepseek_api_key="k2",
        llm_model="deepseek-v4-flash",
        llm_base_url="https://custom.example.com",
        _env_file=None,
    )
    LLMClient(settings).complete_json([{"role": "user", "content": "x"}], LLMAnswer)
    assert route.called
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == settings.llm_model


def test_retry_request_includes_previous_error(respx_mock, settings):
    respx_mock.post(DEEPSEEK_URL).mock(
        side_effect=[
            make_completion("still not json"),
            make_completion('{"answer":"ok","confidence":0.5}'),
        ]
    )
    _client(settings).complete_json([{"role": "user", "content": "x"}], LLMAnswer)
    second_body = json.loads(respx_mock.calls[1].request.content)
    combined = json.dumps(second_body["messages"], ensure_ascii=False)
    assert "错误" in combined


def test_deprecated_model_rejected_at_config(respx_mock):
    with pytest.raises(ValidationError):
        Settings(deepseek_api_key="k", llm_model="deepseek-chat", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(deepseek_api_key="k", llm_model="deepseek-reasoner", _env_file=None)


def test_deprecated_model_rejected_at_call_time(respx_mock, settings):
    # 铁律：旧模型名禁令必须覆盖 complete_json(model=...) 这条运行时入口
    with pytest.raises(ValueError, match="已废弃"):
        _client(settings).complete_json(
            [{"role": "user", "content": "x"}], LLMAnswer, model="deepseek-chat"
        )


def test_response_format_kwarg_rejected(respx_mock, settings):
    # 显式传入 response_format 应得到清晰报错，而非晦涩的 TypeError
    with pytest.raises(ValueError, match="response_format"):
        _client(settings).complete_json(
            [{"role": "user", "content": "x"}],
            LLMAnswer,
            response_format={"type": "text"},
        )

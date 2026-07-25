"""app.config 测试：pillclear_backend 校验 + data_dir 平台解析 + LLM 多厂牌。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import DEPRECATED_MODELS, Settings, default_data_dir
from app.llm.providers import (
    PROVIDER_PRESETS,
    resolve_api_key,
    resolve_base_url,
    resolve_model,
)


class TestBackendValidation:
    @pytest.mark.parametrize("value", ["", "supabase", "sqlite"])
    def test_valid_backends_accepted(self, value):
        assert Settings(
            deepseek_api_key="k", pillclear_backend=value, _env_file=None
        ).pillclear_backend == value

    def test_typo_backend_rejected(self):
        """铁律 #4：拼写错误不得静默落到别的分支，必须显式报错。"""
        with pytest.raises(ValidationError, match="pillclear_backend"):
            Settings(deepseek_api_key="k", pillclear_backend="sqlite3", _env_file=None)


class TestDataDir:
    def test_explicit_data_dir_wins(self):
        s = Settings(deepseek_api_key="k", data_dir="/custom/dir", _env_file=None)
        assert s.resolved_data_dir() == Path("/custom/dir")

    def test_empty_data_dir_falls_back_to_platform_default(self):
        s = Settings(deepseek_api_key="k", data_dir="", _env_file=None)
        assert s.resolved_data_dir() == default_data_dir()
        assert s.resolved_data_dir().name == "PillClear"


# ── LLM 多厂牌：解析函数 ─────────────────────────────────────────────


class TestResolveApiKey:
    def test_llm_api_key_takes_precedence(self):
        s = Settings(llm_api_key="generic", deepseek_api_key="ds", _env_file=None)
        assert resolve_api_key(s) == "generic"

    def test_falls_back_to_deepseek_api_key(self):
        s = Settings(deepseek_api_key="ds", _env_file=None)
        assert resolve_api_key(s) == "ds"

    def test_returns_empty_when_neither_set(self):
        s = Settings(_env_file=None)
        assert resolve_api_key(s) == ""


class TestResolveBaseUrl:
    def test_explicit_override_wins(self):
        s = Settings(llm_provider="deepseek", llm_base_url="https://custom.example.com/v1", _env_file=None)
        assert resolve_base_url(s) == "https://custom.example.com/v1"

    def test_falls_back_to_provider_preset(self):
        s = Settings(llm_provider="openai", _env_file=None)
        assert resolve_base_url(s) == "https://api.openai.com/v1"

    def test_unknown_provider_falls_back_to_default(self):
        s = Settings(llm_provider="custom-unknown", _env_file=None)
        assert resolve_base_url(s) == "https://api.deepseek.com"

    def test_default_provider_is_deepseek(self):
        s = Settings(_env_file=None)
        assert resolve_base_url(s) == "https://api.deepseek.com"


class TestResolveModel:
    def test_explicit_override_wins(self):
        s = Settings(llm_provider="deepseek", llm_model="gpt-4o", _env_file=None)
        assert resolve_model(s) == "gpt-4o"

    def test_falls_back_to_provider_preset(self):
        s = Settings(llm_provider="qwen", _env_file=None)
        assert resolve_model(s) == "qwen-plus"

    def test_unknown_provider_falls_back_to_default(self):
        s = Settings(llm_provider="custom-unknown", _env_file=None)
        assert resolve_model(s) == "deepseek-v4-pro"

    def test_default_provider_is_deepseek(self):
        s = Settings(_env_file=None)
        assert resolve_model(s) == "deepseek-v4-pro"


class TestProviderPresets:
    """每个预置厂牌都有合法的 base_url 和 model。"""

    @pytest.mark.parametrize("key", list(PROVIDER_PRESETS.keys()))
    def test_preset_has_valid_url_and_model(self, key):
        preset = PROVIDER_PRESETS[key]
        assert preset.default_base_url.startswith("http")
        assert len(preset.default_model) > 0
        assert preset.key == key
        assert len(preset.name) > 0


class TestDeprecatedModelRejection:
    """deprecated model 校验仅对 deepseek 厂牌生效。"""

    def test_rejects_deprecated_model_for_deepseek(self):
        for deprecated in DEPRECATED_MODELS:
            with pytest.raises(ValidationError, match="已废弃"):
                Settings(
                    deepseek_api_key="k",
                    llm_provider="deepseek",
                    llm_model=deprecated,
                    _env_file=None,
                )

    def test_allows_deprecated_model_for_other_provider(self):
        """其他厂牌不受 deepseek 废弃模型名单约束。"""
        s = Settings(
            llm_api_key="k",
            llm_provider="openai",
            llm_model="deepseek-chat",
            _env_file=None,
        )
        assert s.llm_model == "deepseek-chat"

    def test_allows_deprecated_model_without_explicit_provider(self):
        """llm_provider 不是 deepseek 时即使显式传 deepseek-chat 也不拦截。
        （默认 provider 是 deepseek，所以仅默认 + deepseek-chat 组合仍会触发。）"""
        s = Settings(
            llm_api_key="k",
            llm_provider="qwen",
            llm_model="deepseek-reasoner",
            _env_file=None,
        )
        assert s.llm_model == "deepseek-reasoner"


class TestBackwardCompat:
    """现有 .env 仅设 DEEPSEEK_API_KEY 应完全兼容。"""

    def test_old_config_still_works(self):
        """仅设 deepseek_api_key、不设新字段，行为与改造前一致。"""
        s = Settings(deepseek_api_key="old-key", _env_file=None)
        assert resolve_api_key(s) == "old-key"
        assert resolve_base_url(s) == "https://api.deepseek.com"
        assert resolve_model(s) == "deepseek-v4-pro"

    def test_empty_settings_resolves_to_deepseek(self):
        """所有字段缺省时解析为 DeepSeek 默认值（与改造前一致）。"""
        s = Settings(_env_file=None)
        assert s.llm_provider == "deepseek"
        assert s.llm_model == ""
        assert s.llm_base_url == ""
        assert resolve_model(s) == "deepseek-v4-pro"
        assert resolve_base_url(s) == "https://api.deepseek.com"

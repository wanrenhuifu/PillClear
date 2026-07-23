"""app.config 测试：pillclear_backend 校验 + data_dir 平台解析。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, default_data_dir


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

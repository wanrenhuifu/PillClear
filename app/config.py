"""应用配置：通过 pydantic-settings 从环境变量 / .env 注入。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 已废弃、禁止使用的旧模型名（铁律）。
DEPRECATED_MODELS: frozenset[str] = frozenset({"deepseek-chat", "deepseek-reasoner"})

DEFAULT_MODEL = "deepseek-v4-pro"

# pillclear_backend 合法取值：""=自动 / "supabase" / "sqlite"。
# 校验拦截拼写错误（铁律 #4：不确定就明说，不得让 "sqlite3" 之类静默落到别的分支）。
VALID_BACKENDS: frozenset[str] = frozenset({"", "supabase", "sqlite"})


def default_data_dir() -> Path:
    """PC 客户端数据目录的跨平台默认值（SQLite 后端用）。

    - Windows → %APPDATA%/PillClear
    - macOS   → ~/Library/Application Support/PillClear
    - Linux   → ~/.local/share/PillClear
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / "PillClear"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PillClear"
    return Path.home() / ".local" / "share" / "PillClear"


class Settings(BaseSettings):
    """全局配置。字段可通过构造参数或环境变量注入。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deepseek_api_key: str = ""
    llm_model: str = DEFAULT_MODEL
    llm_base_url: str = "https://api.deepseek.com"
    llm_max_retries: int = 2

    # 数据库（Supabase Postgres 连接串）
    database_url: str = ""

    # 后端选择："" = 自动（配了 database_url 用 supabase，否则 sqlite）
    #           "supabase" / "sqlite" 显式指定。
    pillclear_backend: str = ""
    # SQLite 数据目录："" 时按平台自动解析（见 default_data_dir）。
    data_dir: str = ""

    # Embedding（OpenAI 兼容，默认硅基流动 BGE-M3 1024 维）
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dims: int = 1024
    embedding_max_retries: int = 2

    def resolved_data_dir(self) -> Path:
        """data_dir 非空则用之，否则按平台自动解析。"""
        return Path(self.data_dir) if self.data_dir else default_data_dir()

    @field_validator("llm_model")
    @classmethod
    def _reject_deprecated_model(cls, value: str) -> str:
        if value in DEPRECATED_MODELS:
            raise ValueError(
                f"模型名 {value!r} 已废弃，禁止使用；请使用 {DEFAULT_MODEL!r}。"
            )
        return value

    @field_validator("pillclear_backend")
    @classmethod
    def _validate_backend(cls, value: str) -> str:
        if value not in VALID_BACKENDS:
            raise ValueError(
                f"pillclear_backend {value!r} 无效；可选 ''(自动)/'supabase'/'sqlite'。"
            )
        return value

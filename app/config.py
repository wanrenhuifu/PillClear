"""应用配置：通过 pydantic-settings 从环境变量 / .env 注入。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import field_validator, model_validator
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

    # -- LLM 厂牌 -----------------------------------------------------------
    # 厂牌标识，对应 app/llm/providers.py 中的预置 key。
    # 设为预置之外的值即"自定义厂牌"——必须同时显式设置 llm_base_url 和 llm_model。
    llm_provider: str = "deepseek"

    # 通用 API key（优先于厂牌专属 key）。
    # 环境变量：LLM_API_KEY
    llm_api_key: str = ""

    # DeepSeek API key（向后兼容；建议新项目使用 LLM_API_KEY）。
    # 环境变量：DEEPSEEK_API_KEY
    deepseek_api_key: str = ""

    # 显式覆盖模型名；留空则从 provider preset 取默认值。
    llm_model: str = ""

    # 显式覆盖 API 端点；留空则从 provider preset 取默认值。
    llm_base_url: str = ""

    # JSON mode 校验/解析失败后的最大重试次数（不含首次尝试）。
    llm_max_retries: int = 2

    # 数据库（Supabase Postgres 连接串）
    database_url: str = ""

    # 后端选择："" = 自动（配了 database_url 用 supabase，否则 sqlite）
    #           "supabase" / "sqlite" 显式指定。
    pillclear_backend: str = ""
    # SQLite 数据目录："" 时按平台自动解析（见 default_data_dir）。
    data_dir: str = ""

    # CORS 允许来源(逗号分隔)。空串 = 不挂 CORS 中间件。
    # 默认放行 Vite 开发服务器;部署时按实际域名覆盖。
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Embedding（OpenAI 兼容，默认硅基流动 BGE-M3 1024 维）
    #
    # 厂牌标识，对应 app/knowledge/embed_providers.py 中的预置 key。
    # 设为预置之外的值即"自定义厂牌"——必须同时显式设置
    # embedding_base_url 和 embedding_model。
    embedding_provider: str = "siliconflow"

    # Embedding API key；留空则回退到 LLM_API_KEY / DEEPSEEK_API_KEY。
    embedding_api_key: str = ""

    # 显式覆盖模型名；留空则从 provider preset 取默认值。
    embedding_model: str = ""

    # 显式覆盖 API 端点；留空则从 provider preset 取默认值。
    embedding_base_url: str = ""

    # 向量维度（必须与 DDL vector(N) 一致——切换厂商/模型时确认）
    embedding_dims: int = 1024

    # Embedding 调用最大重试次数（不含首次尝试）
    embedding_max_retries: int = 2

    def resolved_data_dir(self) -> Path:
        """data_dir 非空则用之，否则按平台自动解析。"""
        return Path(self.data_dir) if self.data_dir else default_data_dir()

    @model_validator(mode="after")
    def _reject_deepseek_deprecated_models(self) -> "Settings":
        """仅当使用 DeepSeek 厂牌时，拒绝已废弃的旧模型名。"""
        if self.llm_provider == "deepseek" and self.llm_model in DEPRECATED_MODELS:
            raise ValueError(
                f"模型名 {self.llm_model!r} 已废弃，禁止使用；请使用 'deepseek-v4-pro'。"
            )
        return self

    @field_validator("pillclear_backend")
    @classmethod
    def _validate_backend(cls, value: str) -> str:
        if value not in VALID_BACKENDS:
            raise ValueError(
                f"pillclear_backend {value!r} 无效；可选 ''(自动)/'supabase'/'sqlite'。"
            )
        return value

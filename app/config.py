"""应用配置：通过 pydantic-settings 从环境变量 / .env 注入。"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 已废弃、禁止使用的旧模型名（铁律）。
DEPRECATED_MODELS: frozenset[str] = frozenset({"deepseek-chat", "deepseek-reasoner"})

DEFAULT_MODEL = "deepseek-v4-pro"


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

    # Embedding（OpenAI 兼容，默认硅基流动 BGE-M3 1024 维）
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dims: int = 1024
    embedding_max_retries: int = 2

    @field_validator("llm_model")
    @classmethod
    def _reject_deprecated_model(cls, value: str) -> str:
        if value in DEPRECATED_MODELS:
            raise ValueError(
                f"模型名 {value!r} 已废弃，禁止使用；请使用 {DEFAULT_MODEL!r}。"
            )
        return value

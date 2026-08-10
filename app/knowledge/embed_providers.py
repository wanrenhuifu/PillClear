"""Embedding 厂牌预置与配置解析。

与 app/llm/providers.py 模式一致：纯数据模块，定义预置厂牌和解析函数。

解析优先级：
  api_key：未设置时回退到 LLM API key（大部分厂牌 LLM 和 Embedding 共用一个 key）
  base_url：embedding_base_url（显式覆盖）> provider preset > 回退值
  model：embedding_model（显式覆盖）> provider preset > 回退值

注意：embedding_dims 不在 provider preset 中，因为维度必须与数据库 DDL
vector(N) 一致；切换厂牌/模型时请确保维度匹配，否则入库时会触发 Embedder 的维度校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings


@dataclass(frozen=True)
class EmbeddingProviderPreset:
    """一个 Embedding 厂牌的预置配置。"""

    key: str
    """厂牌标识（如 "siliconflow"、"openai"）。"""

    name: str
    """显示名。"""

    default_base_url: str
    """默认 API 端点（OpenAI 兼容协议的 base_url）。"""

    default_model: str
    """默认模型名。"""

    suggested_dims: int
    """该模型输出的向量维度（供参考；实际以 embedding_dims 配置为准）。"""


# -- 预置厂牌 -----------------------------------------------------------

EMBEDDING_PROVIDER_PRESETS: dict[str, EmbeddingProviderPreset] = {
    "siliconflow": EmbeddingProviderPreset(
        key="siliconflow",
        name="硅基流动",
        default_base_url="https://api.siliconflow.cn/v1",
        default_model="BAAI/bge-m3",
        suggested_dims=1024,
    ),
    "openai": EmbeddingProviderPreset(
        key="openai",
        name="OpenAI",
        default_base_url="https://api.openai.com/v1",
        default_model="text-embedding-3-small",
        suggested_dims=1536,
    ),
    "qwen": EmbeddingProviderPreset(
        key="qwen",
        name="通义千问",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="text-embedding-v4",
        suggested_dims=1024,
    ),
    "glm": EmbeddingProviderPreset(
        key="glm",
        name="智谱 GLM",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="embedding-3",
        suggested_dims=1024,
    ),
    "ollama": EmbeddingProviderPreset(
        key="ollama",
        name="Ollama（本地）",
        default_base_url="http://localhost:11434/v1",
        default_model="nomic-embed-text",
        suggested_dims=768,
    ),
}

KNOWN_EMBEDDING_PROVIDERS: frozenset[str] = frozenset(EMBEDDING_PROVIDER_PRESETS.keys())


# -- 解析函数 ------------------------------------------------------------

# 最终回退值：当 provider 不在预置中且用户没有显式设置时。
_FALLBACK_EMBEDDING_BASE_URL = "https://api.siliconflow.cn/v1"
_FALLBACK_EMBEDDING_MODEL = "BAAI/bge-m3"


def resolve_embedding_api_key(settings: Settings) -> str:
    """解析 Embedding API key：embedding_api_key > llm_api_key。

    多数厂牌的 LLM 和 Embedding 共用一个 API key，故未单独设置
    embedding_api_key 时自动回退到 LLM_API_KEY。

    不回退到 deepseek_api_key：那是 DeepSeek 厂牌专属的 LLM key，
    不应被送到硅基流动 / OpenAI 等 embedding 端点。
    """
    return settings.embedding_api_key or settings.llm_api_key


def resolve_embedding_base_url(settings: Settings) -> str:
    """解析 embedding base_url：显式覆盖 > provider preset > 回退值。"""
    if settings.embedding_base_url:
        return settings.embedding_base_url
    preset = EMBEDDING_PROVIDER_PRESETS.get(settings.embedding_provider)
    if preset is not None:
        return preset.default_base_url
    return _FALLBACK_EMBEDDING_BASE_URL


def resolve_embedding_model(settings: Settings) -> str:
    """解析 embedding model：显式覆盖 > provider preset > 回退值。"""
    if settings.embedding_model:
        return settings.embedding_model
    preset = EMBEDDING_PROVIDER_PRESETS.get(settings.embedding_provider)
    if preset is not None:
        return preset.default_model
    return _FALLBACK_EMBEDDING_MODEL


__all__ = [
    "EMBEDDING_PROVIDER_PRESETS",
    "KNOWN_EMBEDDING_PROVIDERS",
    "EmbeddingProviderPreset",
    "resolve_embedding_api_key",
    "resolve_embedding_base_url",
    "resolve_embedding_model",
]

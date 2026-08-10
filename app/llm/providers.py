"""LLM 厂牌预置与配置解析。

本模块是纯数据模块（无项目内依赖），定义：
- ProviderPreset：厂牌的 base_url 和默认模型
- resolve_* 函数：从 Settings 解析最终使用的 api_key / base_url / model

解析优先级：
  api_key：llm_api_key > deepseek_api_key（后者仅向后兼容）
  base_url：llm_base_url（显式覆盖）> provider preset > 回退值
  model：llm_model（显式覆盖）> provider preset > 回退值
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings


@dataclass(frozen=True)
class ProviderPreset:
    """一个 LLM 厂牌的预置配置。"""

    key: str
    """厂牌标识（如 "deepseek"、"openai"），对应 llm_provider 配置项。"""

    name: str
    """显示名（如 "DeepSeek"、"通义千问"）。"""

    default_base_url: str
    """默认 API 端点（OpenAI 兼容协议的 base_url）。"""

    default_model: str
    """默认模型名。"""


# -- 预置厂牌 -----------------------------------------------------------

PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "deepseek": ProviderPreset(
        key="deepseek",
        name="DeepSeek",
        default_base_url="https://api.deepseek.com",
        default_model="deepseek-v4-pro",
    ),
    "openai": ProviderPreset(
        key="openai",
        name="OpenAI",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o",
    ),
    "qwen": ProviderPreset(
        key="qwen",
        name="通义千问",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
    ),
    "glm": ProviderPreset(
        key="glm",
        name="智谱 GLM",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-plus",
    ),
    "moonshot": ProviderPreset(
        key="moonshot",
        name="Moonshot",
        default_base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
    ),
    "ollama": ProviderPreset(
        key="ollama",
        name="Ollama（本地）",
        default_base_url="http://localhost:11434/v1",
        default_model="llama3",
    ),
}


# -- 校验 ---------------------------------------------------------------

# 合法的 llm_provider 值（含空字符串以允许显式留空，走回退逻辑）。
# 不在此集合不意味着报错——用户可能用自定义厂牌。
KNOWN_PROVIDERS: frozenset[str] = frozenset(PROVIDER_PRESETS.keys())


# -- 解析函数 ------------------------------------------------------------

# 最终回退值：当 provider 不在预置中且用户没有显式设置时的兜底。
_FALLBACK_BASE_URL = "https://api.deepseek.com"
_FALLBACK_MODEL = "deepseek-v4-pro"


def resolve_api_key(settings: Settings) -> str:
    """解析 API key：llm_api_key 优先，deepseek_api_key 兜底（向后兼容）。"""
    return settings.llm_api_key or settings.deepseek_api_key


def resolve_base_url(settings: Settings) -> str:
    """解析 base_url：显式覆盖 > provider preset > 回退值。"""
    if settings.llm_base_url:
        return settings.llm_base_url
    preset = PROVIDER_PRESETS.get(settings.llm_provider)
    if preset is not None:
        return preset.default_base_url
    return _FALLBACK_BASE_URL


def resolve_model(settings: Settings) -> str:
    """解析 model：显式覆盖 > provider preset > 回退值。"""
    if settings.llm_model:
        return settings.llm_model
    preset = PROVIDER_PRESETS.get(settings.llm_provider)
    if preset is not None:
        return preset.default_model
    return _FALLBACK_MODEL


__all__ = [
    "KNOWN_PROVIDERS",
    "PROVIDER_PRESETS",
    "ProviderPreset",
    "resolve_api_key",
    "resolve_base_url",
    "resolve_model",
]

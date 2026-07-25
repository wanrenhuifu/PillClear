"""app.knowledge.embedder 单元测试：分批 + 瞬时故障重试 + 返回校验 + 多厂牌（mock openai client）。"""

import httpx
import openai
import pytest

from app.config import Settings
from app.knowledge.embed_providers import (
    EMBEDDING_PROVIDER_PRESETS,
    resolve_embedding_api_key,
    resolve_embedding_base_url,
    resolve_embedding_model,
)
from app.knowledge.embedder import Embedder


class _FakeItem:
    def __init__(self, vec, index=0):
        self.embedding = vec
        self.index = index


class _FakeResp:
    def __init__(self, data):
        self.data = data


class _FakeEmbeddingsClient:
    """模拟 openai client：client.embeddings.create(...)。

    drop: 模拟供应商少返回若干条；shuffle: 模拟乱序返回（index 仍正确）。
    每条向量用 [float(index)] * dims，便于断言顺序是否按 index 还原。
    """

    def __init__(self, dims=1024, fail_times=0, drop=0, shuffle=False):
        self.dims = dims
        self.fail_times = fail_times
        self.drop = drop
        self.shuffle = shuffle
        self.create_calls = 0
        self.embeddings = self

    def create(self, model, input):
        self.create_calls += 1
        if self.create_calls <= self.fail_times:
            raise openai.APIConnectionError(request=None)
        items = [_FakeItem([float(i)] * self.dims, index=i) for i in range(len(input))]
        if self.drop:
            items = items[: len(input) - self.drop]
        if self.shuffle:
            items = list(reversed(items))
        return _FakeResp(items)


def _settings():
    return Settings(embedding_api_key="k", embedding_dims=1024, _env_file=None)


def test_batching_splits_into_multiple_calls():
    client = _FakeEmbeddingsClient(dims=1024)
    embedder = Embedder(_settings(), client=client, batch_size=2)
    vectors = embedder.embed(["a", "b", "c", "d", "e"])
    assert len(vectors) == 5
    assert all(len(v) == 1024 for v in vectors)
    assert client.create_calls == 3  # 5 条、每批 2 → 3 次调用


def test_retries_on_transient_error_then_succeeds():
    client = _FakeEmbeddingsClient(dims=1024, fail_times=1)
    embedder = Embedder(_settings(), client=client, batch_size=10)
    vectors = embedder.embed(["a", "b"])
    assert len(vectors) == 2
    assert client.create_calls == 2  # 首次失败 + 重试成功


def test_raises_after_retries_exhausted():
    client = _FakeEmbeddingsClient(dims=1024, fail_times=99)
    embedder = Embedder(_settings(), client=client, batch_size=10)
    with pytest.raises(RuntimeError):
        embedder.embed(["a"])


def test_non_transient_error_not_retried():
    # 401（密钥错误）等非瞬时错误应立即失败，不做无谓重试
    resp401 = httpx.Response(
        401, request=httpx.Request("POST", "https://api.example.com")
    )

    class _AuthFail:
        def __init__(self):
            self.create_calls = 0
            self.embeddings = self

        def create(self, model, input):
            self.create_calls += 1
            raise openai.AuthenticationError(
                message="bad key", response=resp401, body=None
            )

    client = _AuthFail()
    embedder = Embedder(_settings(), client=client)
    with pytest.raises(openai.AuthenticationError):
        embedder.embed(["a"])
    assert client.create_calls == 1  # 一次即止，不重试


def test_short_response_rejected():
    # 供应商少返回 → 立即报错，绝不让 zip 静默截断导致章节错位/丢失
    client = _FakeEmbeddingsClient(dims=1024, drop=1)
    embedder = Embedder(_settings(), client=client)
    with pytest.raises(ValueError, match="数量"):
        embedder.embed(["a", "b", "c"])
    assert client.create_calls == 1  # 快速失败，不浪费重试


def test_reordered_response_restored_by_index():
    # 供应商乱序返回 → 按 item.index 还原输入顺序
    client = _FakeEmbeddingsClient(dims=1024, shuffle=True)
    embedder = Embedder(_settings(), client=client)
    vectors = embedder.embed(["a", "b", "c"])
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0]


def test_wrong_dims_rejected():
    # 返回维度与配置 embedding_dims 不一致 → 立即报错（否则落库时才炸）
    client = _FakeEmbeddingsClient(dims=768)
    embedder = Embedder(_settings(), client=client)
    with pytest.raises(ValueError, match="维度"):
        embedder.embed(["a"])


# ── Embedding 多厂牌：解析函数 ─────────────────────────────────────────


class TestResolveEmbeddingApiKey:
    def test_embedding_key_takes_precedence(self):
        s = Settings(
            embedding_api_key="emb-key",
            llm_api_key="llm-key",
            _env_file=None,
        )
        assert resolve_embedding_api_key(s) == "emb-key"

    def test_falls_back_to_llm_api_key(self):
        s = Settings(llm_api_key="llm-key", _env_file=None)
        assert resolve_embedding_api_key(s) == "llm-key"

    def test_does_not_fall_back_to_deepseek_api_key(self):
        """deepseek_api_key 是 LLM 厂牌专属 key，不应被送到 embedding 端点。"""
        s = Settings(deepseek_api_key="ds-key", _env_file=None)
        assert resolve_embedding_api_key(s) == ""

    def test_llm_api_key_fallback(self):
        """llm_api_key 设置时用作 embedding 回退，deepseek 不干扰。"""
        s = Settings(
            llm_api_key="llm-key", deepseek_api_key="ds-key", _env_file=None
        )
        assert resolve_embedding_api_key(s) == "llm-key"

    def test_returns_empty_when_none_set(self):
        s = Settings(_env_file=None)
        assert resolve_embedding_api_key(s) == ""


class TestResolveEmbeddingBaseUrl:
    def test_explicit_override_wins(self):
        s = Settings(
            embedding_provider="siliconflow",
            embedding_base_url="https://custom-emb.example.com/v1",
            _env_file=None,
        )
        assert resolve_embedding_base_url(s) == "https://custom-emb.example.com/v1"

    def test_falls_back_to_provider_preset(self):
        s = Settings(embedding_provider="openai", _env_file=None)
        assert resolve_embedding_base_url(s) == "https://api.openai.com/v1"

    def test_unknown_provider_falls_back(self):
        s = Settings(embedding_provider="custom-unknown", _env_file=None)
        assert resolve_embedding_base_url(s) == "https://api.siliconflow.cn/v1"

    def test_default_provider_is_siliconflow(self):
        s = Settings(_env_file=None)
        assert resolve_embedding_base_url(s) == "https://api.siliconflow.cn/v1"


class TestResolveEmbeddingModel:
    def test_explicit_override_wins(self):
        s = Settings(
            embedding_provider="siliconflow",
            embedding_model="custom-model",
            _env_file=None,
        )
        assert resolve_embedding_model(s) == "custom-model"

    def test_falls_back_to_provider_preset(self):
        s = Settings(embedding_provider="openai", _env_file=None)
        assert resolve_embedding_model(s) == "text-embedding-3-small"

    def test_unknown_provider_falls_back(self):
        s = Settings(embedding_provider="custom-unknown", _env_file=None)
        assert resolve_embedding_model(s) == "BAAI/bge-m3"

    def test_default_provider_is_siliconflow(self):
        s = Settings(_env_file=None)
        assert resolve_embedding_model(s) == "BAAI/bge-m3"


class TestEmbeddingProviderPresets:
    @pytest.mark.parametrize("key", list(EMBEDDING_PROVIDER_PRESETS.keys()))
    def test_preset_has_valid_fields(self, key):
        preset = EMBEDDING_PROVIDER_PRESETS[key]
        assert preset.default_base_url.startswith("http")
        assert len(preset.default_model) > 0
        assert preset.key == key
        assert len(preset.name) > 0
        assert preset.suggested_dims > 0


class TestEmbedderUsesProviderResolution:
    """验证 Embedder 确实使用 provider 解析而非直接读 settings 字段。"""

    def test_switches_endpoint_by_provider(self):
        """切换到 openai 后，client 指向 OpenAI 端点。"""
        client = _FakeEmbeddingsClient(dims=1536)
        settings = Settings(
            embedding_api_key="k",
            embedding_provider="openai",
            embedding_dims=1536,
            _env_file=None,
        )
        # 注入 fake client，不真正连网
        embedder = Embedder(settings, client=client)
        vectors = embedder.embed(["test"])
        assert len(vectors) == 1

    def test_ollama_provider(self):
        """Ollama 厂牌使用本地端点。"""
        client = _FakeEmbeddingsClient(dims=768)
        settings = Settings(
            embedding_api_key="ollama",
            embedding_provider="ollama",
            embedding_dims=768,
            _env_file=None,
        )
        embedder = Embedder(settings, client=client)
        vectors = embedder.embed(["test"])
        assert len(vectors) == 1

    def test_explicit_model_overrides_provider(self):
        """显式 embedding_model 应覆盖 provider 默认。"""
        client = _FakeEmbeddingsClient(dims=1024)
        settings = Settings(
            embedding_api_key="k",
            embedding_provider="openai",
            embedding_model="text-embedding-3-large",
            embedding_dims=1024,
            _env_file=None,
        )
        embedder = Embedder(settings, client=client)
        embedder.embed(["test"])
        assert client.create_calls == 1

    def test_backward_compat_old_settings_still_works(self):
        """仅设旧字段（无 embedding_provider），行为与改造前一致。"""
        client = _FakeEmbeddingsClient(dims=1024)
        settings = Settings(embedding_api_key="k", embedding_dims=1024, _env_file=None)
        embedder = Embedder(settings, client=client)
        vectors = embedder.embed(["a", "b"])
        assert len(vectors) == 2
        assert client.create_calls == 1

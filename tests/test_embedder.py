"""app.knowledge.embedder 单元测试：分批 + 瞬时故障重试 + 返回校验（mock openai client）。"""

import httpx
import openai
import pytest

from app.config import Settings
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

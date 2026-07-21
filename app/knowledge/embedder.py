"""Embedding 封装：OpenAI 兼容协议，默认硅基流动 BGE-M3（1024 维）。"""

from __future__ import annotations

import logging
import time

from openai import (
    APIConnectionError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from app.config import Settings

logger = logging.getLogger("app.knowledge")

# 值得重试的瞬时错误（连接/超时、限流、服务端 5xx）。
# 401/400 之类参数与鉴权错误重试无意义，让其立即上抛。
_RETRYABLE_ERRORS = (APIConnectionError, RateLimitError, InternalServerError)


class Embedder:
    """文本向量化。openai client 可注入以便测试，也可延迟创建。"""

    def __init__(
        self,
        settings: Settings,
        client: OpenAI | None = None,
        *,
        batch_size: int = 32,
    ) -> None:
        self._settings = settings
        self._batch_size = batch_size
        self._client = client  # None 时延迟创建

    def _get_client(self) -> OpenAI:
        """延迟创建 OpenAI 客户端（仅首次调用 _embed_batch 时）。"""
        if self._client is None:
            self._client = OpenAI(
                api_key=self._settings.embedding_api_key,
                base_url=self._settings.embedding_base_url,
            )
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化，返回与输入等长、顺序一致的向量列表。

        等长与顺序由 _embed_batch 强制校验（按 index 排序 + 数量核对 +
        维度核对），不满足即抛 ValueError，绝不静默截断/错位。
        """

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        max_attempts = self._settings.embedding_max_retries + 1
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                response = self._get_client().embeddings.create(
                    model=self._settings.embedding_model,
                    input=batch,
                )
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                logger.warning(
                    "Embedding 调用失败（第 %d/%d 次）：%s",
                    attempt + 1,
                    max_attempts,
                    exc,
                )
                if attempt + 1 < max_attempts:
                    time.sleep(min(2 ** attempt, 30))
                continue

            # OpenAI 兼容协议不保证 response.data 的顺序与完整性：
            # 按 item.index 还原顺序，数量不符立即失败——宁可中断入库，
            # 也不能让下游 zip 静默截断，把章节配上错误的向量。
            data = sorted(response.data, key=lambda item: getattr(item, "index", 0))
            if len(data) != len(batch):
                raise ValueError(
                    f"Embedding 返回数量 {len(data)} 与输入 {len(batch)} 不一致，"
                    "拒绝继续（防止章节-向量错位）"
                )
            vectors = [item.embedding for item in data]
            dims = self._settings.embedding_dims
            if vectors and len(vectors[0]) != dims:
                raise ValueError(
                    f"Embedding 维度 {len(vectors[0])} 与配置 embedding_dims={dims} "
                    "不一致，请检查 embedding_model 与数据库列定义"
                )
            return vectors
        raise RuntimeError(
            f"Embedding 在 {max_attempts} 次尝试后仍失败：{last_error!r}"
        ) from last_error


__all__ = ["Embedder"]

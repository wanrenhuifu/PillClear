"""RAG 引用检索接口（D3 接缝）。

铁律 #2：所有用药相关回答必须携带说明书原文引用。
当前 RAG 未就绪，路由注入 NullRetriever（返回空引用 + "开发中"提示）；
D3 实现 pgvector 检索后在此新增实现并替换 app/api/deps.py::get_retriever，
路由无需改动。
"""

from __future__ import annotations

from typing import Protocol

from app.api.schemas import Citation


class Retriever(Protocol):
    """引用检索器：为用户问题检索说明书原文摘录。"""

    def search(self, query: str, limit: int = 5) -> list[Citation]:
        """返回与 query 相关的说明书原文引用（excerpt 须为 chunk 内容精确子串）。"""
        ...


class NullRetriever:
    """占位实现：恒返回空引用（RAG 未接入，仅用于 D3 之前的管线形状）。"""

    def search(self, query: str, limit: int = 5) -> list[Citation]:
        return []


__all__ = ["Retriever", "NullRetriever"]

"""API 层的 Pydantic 请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """用户发来的用药咨询。"""

    query: str = Field(..., min_length=1, max_length=2000, description="用户问题")


class Citation(BaseModel):
    """一条说明书原文引用（D3 RAG 检索后填充）。"""

    drug_name: str = Field(..., description="药品商品名")
    section: str = Field(..., description="说明书章节名，如「用法用量」")
    excerpt: str = Field(..., description="原文摘录")


class ChatResponse(BaseModel):
    """/api/v1/chat 的统一响应。

    - blocked=True 时：boundary_message 为安全话术，answer/citations 为空。
    - blocked=False 时：answer 为 LLM 生成的大白话回答，citations 待 D3 填充。
    """

    blocked: bool
    category: str | None = Field(
        None, description="越界分类：emergency/special_population/diagnosis/prescription"
    )
    boundary_message: str | None = Field(
        None, description="越界时的固定安全话术"
    )
    answer: str | None = Field(None, description="LLM 生成的回答")
    confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="LLM 自报置信度（0~1）；低于阈值时代码追加不确定提示"
    )
    citations: list[Citation] = Field(
        default_factory=list, description="说明书原文引用（D3 RAG 检索后填充）"
    )
    sources_note: str | None = Field(
        None, description="引用来源说明；RAG 就绪后为 None"
    )
    disclaimer: str | None = Field(
        None, description="固定免责声明（代码追加，非 LLM 生成）"
    )


class LLMAnswer(BaseModel):
    """LLM JSON mode 输出的结构。"""

    answer: str = Field(..., description="大白话回答")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")

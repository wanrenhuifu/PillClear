"""knowledge 层的 Pydantic 数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """一条说明书原文引用（RAG 检索的最小单元）。

    属于 knowledge 层而非 API 层：Citation 是领域概念（说明书的证据片段），
    RAG 检索器、prompt 构建器、API 响应都使用它，但不该由 API 层定义。
    """

    brand_name: str = Field(..., description="药品商品名")
    section: str = Field(..., description="说明书章节名，如「用法用量」")
    excerpt: str = Field(..., description="原文摘录")


class Ingredient(BaseModel):
    """单个成分。amount/unit 在说明书未标含量时为 None。"""

    name: str
    amount: float | None = None
    unit: str | None = None


class IngredientList(BaseModel):
    """LLM 抽取【成份】章节的结构化输出容器。"""

    ingredients: list[Ingredient] = Field(default_factory=list)


class ParsedSection(BaseModel):
    """说明书按【】切分出的章节。"""

    section: str
    content: str


class DrugMetadata(BaseModel):
    """从说明书尽力解析出的药品元数据（缺失字段为 None）。"""

    generic_name: str | None = None
    otc_category: str | None = None
    dosage_form: str | None = None
    specification: str | None = None
    approval_number: str | None = None


class DrugRecord(BaseModel):
    """一条待入库的药品记录（主数据 + 成分；chunks 由管线另行组装）。"""

    brand_name: str
    metadata: DrugMetadata = Field(default_factory=DrugMetadata)
    ingredients: list[Ingredient] = Field(default_factory=list)
    ingredients_verified: bool = False

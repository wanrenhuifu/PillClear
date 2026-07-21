"""knowledge 层：说明书解析、向量化与入库管线（D2）。"""

from app.knowledge.embedder import Embedder
from app.knowledge.ingest import ingest_directory, ingest_text
from app.knowledge.parser import extract_metadata, split_sections
from app.knowledge.repository import (
    DrugRepository,
    InMemoryDrugRepository,
    PostgresDrugRepository,
)
from app.knowledge.schemas import (
    DrugMetadata,
    DrugRecord,
    Ingredient,
    IngredientList,
    ParsedSection,
)

__all__ = [
    "Embedder",
    "ingest_text",
    "ingest_directory",
    "split_sections",
    "extract_metadata",
    "DrugRepository",
    "InMemoryDrugRepository",
    "PostgresDrugRepository",
    "DrugMetadata",
    "DrugRecord",
    "Ingredient",
    "IngredientList",
    "ParsedSection",
]

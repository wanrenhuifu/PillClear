"""knowledge 层：说明书解析、向量化与入库管线（D2）。"""

from app.knowledge.embedder import Embedder
from app.knowledge.ingest import ingest_directory, ingest_text
from app.knowledge.parser import extract_metadata, split_sections
from app.knowledge.repository import (
    DrugReader,
    DrugRepository,
    DrugWriter,
    InMemoryDrugRepository,
    PostgresDrugRepository,
)
from app.knowledge.schemas import (
    Citation,
    DrugMetadata,
    DrugRecord,
    Ingredient,
    IngredientList,
    ParsedSection,
)

__all__ = [
    "Citation",
    "DrugMetadata",
    "DrugReader",
    "DrugRecord",
    "DrugRepository",
    "DrugWriter",
    "Embedder",
    "InMemoryDrugRepository",
    "Ingredient",
    "IngredientList",
    "ParsedSection",
    "PostgresDrugRepository",
    "extract_metadata",
    "ingest_directory",
    "ingest_text",
    "split_sections",
]

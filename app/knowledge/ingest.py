"""说明书入库管线。

流程（确定性）：解析章节 → LLM 抽取结构化成份 → 章节向量化 → 幂等 upsert。
本模块不做任何检索/问答（D3 负责）。
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from app.config import Settings
from app.knowledge.embedder import Embedder
from app.knowledge.parser import extract_metadata, split_sections
from app.knowledge.repository import (
    ChunkRow,
    DrugWriter,
    InMemoryDrugRepository,
    PostgresDrugRepository,
)
from app.knowledge.schemas import DrugRecord, IngredientList
from app.llm.client import LLMClient
from app.prompts.ingest import INGREDIENT_SYSTEM_PROMPT

logger = logging.getLogger("app.knowledge")

# 说明书成份章节名的子串特征：【成份】【成分】【主要成份】等均命中。
_INGREDIENT_SECTIONS = ("成份", "成分")

_INGREDIENT_SYSTEM_PROMPT = INGREDIENT_SYSTEM_PROMPT  # 从 app.prompts.ingest 导入


def extract_ingredients(llm: LLMClient, section_text: str) -> list:
    """用 LLM 把【成份】原文抽成结构化列表（JSON mode + Pydantic 校验）。"""

    if not section_text or not section_text.strip():
        return []
    result = llm.complete_json(
        [
            {"role": "system", "content": _INGREDIENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"【成份】原文：\n{section_text}"},
        ],
        IngredientList,
    )
    return result.ingredients


def _find_ingredient_section(sections) -> str:
    # 子串匹配：中成药/老版说明书常用【主要成份】，精确匹配会静默跳过抽取
    for s in sections:
        if any(key in s.section for key in _INGREDIENT_SECTIONS):
            return s.content
    return ""


def ingest_text(
    brand_name: str,
    text: str,
    *,
    llm: LLMClient,
    embedder: Embedder,
    repo: DrugWriter,
) -> DrugRecord:
    """入库单份说明书文本，幂等。返回构造出的 DrugRecord。

    未识别到任何章节（或章节全空）时抛 ValueError 拒绝入库——
    否则 upsert 会用空成分覆盖、replace_chunks 会删光已有 chunks，
    一份坏文件就能无声毁掉此前入库的正确数据。
    """

    sections = split_sections(text)
    if not sections:
        raise ValueError(
            f"说明书「{brand_name}」未识别到任何【章节】标题，拒绝入库以保护已有数据"
        )
    # 过滤空白章节，避免浪费 embedding 配额
    non_empty = [s for s in sections if s.content.strip()]
    if not non_empty:
        raise ValueError(f"说明书「{brand_name}」所有章节内容为空，拒绝入库")

    metadata = extract_metadata(text, sections)
    ingredients = extract_ingredients(llm, _find_ingredient_section(sections))

    # 先向量化再写库：embedding 失败时数据库无写入，避免孤儿 drug 行
    vectors = embedder.embed([s.content for s in non_empty])

    record = DrugRecord(
        brand_name=brand_name,
        metadata=metadata,
        ingredients=ingredients,
        ingredients_verified=False,
    )

    chunks: list[ChunkRow] = [
        (s.section, s.content, vec) for s, vec in zip(non_empty, vectors)
    ]
    # 原子保存（Postgres 下同一事务）：药品行与 chunks 同成败
    repo.save_drug(record, chunks)
    return record


def ingest_directory(
    directory: str | Path,
    *,
    llm: LLMClient,
    embedder: Embedder,
    repo: DrugWriter,
) -> tuple[list[str], list[tuple[str, str]]]:
    """入库目录下所有 .txt/.md。返回 (成功商品名列表, 失败 [(商品名, 错误)])。

    商品名取文件名第一个点之前的部分（"泰诺.txt.md" → "泰诺"，
    避免双重扩展名产生"泰诺.txt"幻影药品）。
    单文件失败只记录并继续，不中断整批——否则已入库文件构成无声的部分结果。
    """

    directory = Path(directory)
    brands: list[str] = []
    failures: list[tuple[str, str]] = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in (".txt", ".md"):
            continue
        brand_name = path.name.split(".", 1)[0]
        try:
            text = path.read_text(encoding="utf-8")
            ingest_text(brand_name, text, llm=llm, embedder=embedder, repo=repo)
        except Exception as exc:  # noqa: BLE001 - 单文件失败不得中断其余文件
            logger.error(
                "入库失败「%s」：%s: %s", brand_name, type(exc).__name__, exc
            )
            failures.append((brand_name, f"{type(exc).__name__}: {exc}"))
            continue
        logger.info("入库：%s", brand_name)
        brands.append(brand_name)
    return brands, failures


class _ZeroEmbedder(Embedder):
    """dry-run 用：不联网，返回全零向量（仅演示行数/结构）。"""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, batch_size=32)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._settings.embedding_dims for _ in texts]


class _DryRunLLM:
    """dry-run 用：不联网，成份抽取返回空列表（离线演示结构与行数）。"""

    def complete_json(
        self, messages: Any, response_model: Any, **kwargs: Any
    ) -> IngredientList:
        return IngredientList(ingredients=[])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="OTC 说明书入库管线")
    parser.add_argument("directory", help="说明书目录（.txt/.md）")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="离线演示：内存仓储 + 全零向量 + 空成份（不写库、不发任何网络请求）",
    )
    args = parser.parse_args()

    settings = Settings()

    if args.dry_run:
        # 完全离线：DB / embedding / LLM 三路全部使用本地替身
        repo: DrugWriter = InMemoryDrugRepository()
        embedder: Embedder = _ZeroEmbedder(settings)
        llm: Any = _DryRunLLM()
    else:
        if not settings.database_url:
            raise SystemExit("未配置 DATABASE_URL，无法写库；或使用 --dry-run。")
        repo = PostgresDrugRepository(settings.database_url)
        embedder = Embedder(settings)
        llm = LLMClient(settings)

    brands, failures = ingest_directory(
        args.directory, llm=llm, embedder=embedder, repo=repo
    )

    print("=" * 40)
    print(f"drugs 行数：{repo.count_drugs()}")
    print(f"insert_chunks 行数：{repo.count_chunks()}")
    if brands:
        sample = repo.get_drug_by_brand(brands[0])
        print(f"\n示例药品「{brands[0]}」成份 JSON：")
        print(
            json.dumps(sample["ingredients"], ensure_ascii=False, indent=2)
            if sample
            else "（无）"
        )
    if failures:
        print(f"\n{len(failures)} 个文件入库失败：")
        for name, err in failures:
            print(f"  - {name}: {err}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

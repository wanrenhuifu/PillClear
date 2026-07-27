"""药品数据仓储层。

- DrugWriter：入库管线依赖的写入接口（Protocol）。
- DrugReader：药箱检查依赖的查询接口（Protocol）。
- 一个实现类可同时满足两者（如 PostgresDrugRepository）。
- InMemoryDrugRepository：离线测试与 --dry-run 用，实现幂等 upsert 语义。
- PostgresDrugRepository：psycopg3 + pgvector 的真实实现。
"""

from __future__ import annotations

from typing import Any, Protocol

from app.knowledge.schemas import DrugRecord

# 一条 chunk：(section, content, embedding)
ChunkRow = tuple[str, str, list[float]]


class DrugWriter(Protocol):
    """药品写入接口：说明书入库管线所需的仓储方法。"""

    def upsert_drug(self, record: DrugRecord) -> int:
        """按 brand_name upsert 药品，返回 drug_id（幂等）。"""
        ...

    def replace_chunks(self, drug_id: int, chunks: list[ChunkRow]) -> None:
        """以 drug_id 先删后插章节，保证重复运行不产生重复数据。"""
        ...

    def save_drug(self, record: DrugRecord, chunks: list[ChunkRow]) -> int:
        """原子保存药品及其章节 chunks（幂等），返回 drug_id。"""
        ...

    def count_drugs(self) -> int: ...

    def count_chunks(self) -> int: ...


class DrugReader(Protocol):
    """药品查询接口：药箱检查所需的仓储方法。"""

    def get_drug_by_brand(self, brand_name: str) -> dict[str, Any] | None:
        """按商品名查询药品记录。"""
        ...

    def list_drugs(self) -> list[dict[str, Any]]:
        """列出全部药品(id/brand_name/generic_name),按 id 升序。药品选择器数据源。"""
        ...


# 向后兼容别名：历史代码仍可用 DrugRepository 替代 DrugWriter。
DrugRepository = DrugWriter


class InMemoryDrugRepository:
    """内存实现：用于单测与离线 dry-run。"""

    def __init__(self) -> None:
        self._drugs: dict[str, dict[str, Any]] = {}
        self._chunks: dict[int, list[ChunkRow]] = {}
        self._next_id = 1

    def upsert_drug(self, record: DrugRecord) -> int:
        existing = self._drugs.get(record.brand_name)
        drug_id = existing["id"] if existing else self._next_id
        if existing is None:
            self._next_id += 1
        self._drugs[record.brand_name] = {
            "id": drug_id,
            "brand_name": record.brand_name,
            "generic_name": record.metadata.generic_name,
            "otc_category": record.metadata.otc_category,
            "dosage_form": record.metadata.dosage_form,
            "specification": record.metadata.specification,
            "approval_number": record.metadata.approval_number,
            "ingredients": [i.model_dump() for i in record.ingredients],
            # 铁律：入库永不置 true。仓储层强制覆盖（与 Postgres 实现一致），
            # 即使调用方传入 True 也不得让未核对成分看起来"已人工核对"。
            "ingredients_verified": False,
        }
        return drug_id

    def replace_chunks(self, drug_id: int, chunks: list[ChunkRow]) -> None:
        self._chunks[drug_id] = list(chunks)

    def save_drug(self, record: DrugRecord, chunks: list[ChunkRow]) -> int:
        drug_id = self.upsert_drug(record)
        self.replace_chunks(drug_id, chunks)
        return drug_id

    def count_drugs(self) -> int:
        return len(self._drugs)

    def count_chunks(self) -> int:
        return sum(len(v) for v in self._chunks.values())

    def get_drug_by_brand(self, brand_name: str) -> dict[str, Any] | None:
        return self._drugs.get(brand_name)

    def list_drugs(self) -> list[dict[str, Any]]:
        return [
            {
                "id": d["id"],
                "brand_name": d["brand_name"],
                "generic_name": d["generic_name"],
            }
            for d in sorted(self._drugs.values(), key=lambda d: d["id"])
        ]


class PostgresDrugRepository:
    """psycopg3 + pgvector 的真实入库实现。

    延迟导入 psycopg / pgvector，未安装或未配置 DATABASE_URL 时也不影响其余模块导入。
    """

    def __init__(self, dsn: str) -> None:
        import psycopg  # noqa: PLC0415
        from pgvector.psycopg import register_vector  # noqa: PLC0415

        self._conn = psycopg.connect(dsn, autocommit=True)
        register_vector(self._conn)

    def upsert_drug(self, record: DrugRecord) -> int:
        from psycopg.types.json import Jsonb  # noqa: PLC0415

        ingredients = [i.model_dump() for i in record.ingredients]
        # 铁律：ingredients_verified 入库永不置 true，等人工核对。
        # 仓储层强制覆盖，避免新入库路径绕过。
        ingredients_verified = False
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into drugs (
                    brand_name, generic_name, otc_category, dosage_form,
                    specification, approval_number, ingredients, ingredients_verified
                ) values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (brand_name) do update set
                    generic_name    = excluded.generic_name,
                    otc_category    = excluded.otc_category,
                    dosage_form     = excluded.dosage_form,
                    specification   = excluded.specification,
                    approval_number = excluded.approval_number,
                    ingredients     = excluded.ingredients,
                    -- 成分被新抽取结果替换 → 人工核对状态必须归零，
                    -- 否则 D4 规则引擎会"信任"一份从未被核对过的新数据。
                    ingredients_verified = excluded.ingredients_verified
                returning id
                """,
                (
                    record.brand_name,
                    record.metadata.generic_name,
                    record.metadata.otc_category,
                    record.metadata.dosage_form,
                    record.metadata.specification,
                    record.metadata.approval_number,
                    Jsonb(ingredients),
                    ingredients_verified,
                ),
            )
            return cur.fetchone()[0]

    def replace_chunks(self, drug_id: int, chunks: list[ChunkRow]) -> None:
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute("delete from insert_chunks where drug_id = %s", (drug_id,))
                if chunks:
                    cur.executemany(
                        "insert into insert_chunks (drug_id, section, content, embedding)"
                        " values (%s, %s, %s, %s)",
                        [(drug_id, s, c, e) for s, c, e in chunks],
                    )

    def save_drug(self, record: DrugRecord, chunks: list[ChunkRow]) -> int:
        # 同一事务内 upsert + 重写 chunks：要么一起成功，要么一起回滚，
        # 杜绝"药品行已提交、chunks 写入失败"的孤儿行 / stale chunks 窗口。
        with self._conn.transaction():
            drug_id = self.upsert_drug(record)
            self.replace_chunks(drug_id, chunks)
        return drug_id

    def count_drugs(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("select count(*) from drugs")
            return cur.fetchone()[0]

    def count_chunks(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("select count(*) from insert_chunks")
            return cur.fetchone()[0]

    def get_drug_by_brand(self, brand_name: str) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "select id, brand_name, generic_name, otc_category, dosage_form,"
                " specification, approval_number, ingredients, ingredients_verified"
                " from drugs where brand_name = %s",
                (brand_name,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))

    def list_drugs(self) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute("select id, brand_name, generic_name from drugs order by id")
            return [
                dict(zip(("id", "brand_name", "generic_name"), row))
                for row in cur.fetchall()
            ]


__all__ = [
    "DrugWriter",
    "DrugReader",
    "DrugRepository",  # 向后兼容：= DrugWriter
    "InMemoryDrugRepository",
    "PostgresDrugRepository",
    "ChunkRow",
]

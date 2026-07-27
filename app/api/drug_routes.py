"""药品列表路由:前端药品选择器的数据源(只读)。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_drug_repository
from app.api.schemas import DrugSummary
from app.knowledge.repository import DrugReader

router = APIRouter()


@router.get("/drugs", response_model=list[DrugSummary])
async def list_drugs_endpoint(
    repo: DrugReader = Depends(get_drug_repository),
) -> list[DrugSummary]:
    """列出已入库药品(商品名 + 通用名),供前端药箱选择器检索。"""
    rows = await run_in_threadpool(repo.list_drugs)
    return [
        DrugSummary(
            drug_id=r["id"], brand_name=r["brand_name"], generic_name=r["generic_name"]
        )
        for r in rows
    ]

"""药箱 API 路由：冲突检测（D4）。

铁律 #1：冲突判断全部走确定性规则引擎，本层只做编排与 I/O，永不碰 LLM。
铁律 #5：本端点只返回结构化数据；大白话话术与免责声明由 /chat 聚合层承担。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_medbox_service
from app.medbox.schemas import (
    ConflictReport,
    Medbox,
    MedboxCheckRequest,
    MedboxItem,
    MedboxItemAddRequest,
    MedboxResponse,
)
from app.medbox.service import MedboxService

router = APIRouter()


@router.post("/medbox/check", response_model=ConflictReport)
async def check_medbox(
    request: MedboxCheckRequest,
    service: MedboxService = Depends(get_medbox_service),
) -> ConflictReport:
    """个人药箱冲突检测：成分叠加 + 规则匹配。

    仓储查询可能阻塞（PostgresDrugRepository 走 psycopg 同步连接），
    与 /chat 同款 run_in_threadpool 放入线程池。
    """
    return await run_in_threadpool(
        service.check_conflicts,
        Medbox(items=request.items),
        request.lifestyle_substances,
    )


# ── 药箱持久化（MVP 用 device_id 标识用户，无登录）─────────────────────


@router.get("/medbox/{device_id}", response_model=MedboxResponse)
async def get_medbox(
    device_id: str,
    service: MedboxService = Depends(get_medbox_service),
) -> MedboxResponse:
    """获取用户保存的药箱（无记录则为空）。"""
    medbox = await run_in_threadpool(service.get_medbox, device_id)
    return MedboxResponse(device_id=device_id, items=medbox.items)


@router.post("/medbox/{device_id}/items", response_model=MedboxResponse)
async def add_medbox_item(
    device_id: str,
    request: MedboxItemAddRequest,
    service: MedboxService = Depends(get_medbox_service),
) -> MedboxResponse:
    """添加/更新一项到药箱，返回完整药箱。"""
    medbox = await run_in_threadpool(
        service.add_to_medbox,
        device_id,
        MedboxItem(
            drug_id=request.drug_id,
            brand_name=request.brand_name,
            dosage_per_day=request.dosage_per_day,
        ),
    )
    return MedboxResponse(device_id=device_id, items=medbox.items)


@router.delete("/medbox/{device_id}/items/{drug_id}", response_model=MedboxResponse)
async def remove_medbox_item(
    device_id: str,
    drug_id: int,
    service: MedboxService = Depends(get_medbox_service),
) -> MedboxResponse:
    """从药箱移除一项，返回完整药箱。"""
    medbox = await run_in_threadpool(service.remove_from_medbox, device_id, drug_id)
    return MedboxResponse(device_id=device_id, items=medbox.items)

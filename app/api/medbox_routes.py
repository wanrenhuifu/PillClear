"""药箱 API 路由：冲突检测（D4）。

铁律 #1：冲突判断全部走确定性规则引擎，本层只做编排与 I/O，永不碰 LLM。
铁律 #5：本端点只返回结构化数据；大白话话术与免责声明由 /chat 聚合层承担。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_medbox_service
from app.medbox.schemas import ConflictReport, Medbox, MedboxCheckRequest
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

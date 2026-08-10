"""用药提醒 API 路由：GET/POST/DELETE /api/v1/reminders/{device_id}。

提醒是调度数据：本层只做编排与 I/O，永不碰 LLM（铁律 #1，同药箱纪律）。
大白话话术与免责声明属于 /chat 聚合层，本端点只返回结构化数据（铁律 #5）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_reminder_service
from app.reminder.schemas import ReminderAddRequest, ReminderResponse
from app.reminder.service import ReminderService

router = APIRouter()


@router.get("/reminders/{device_id}", response_model=ReminderResponse)
async def get_reminders(
    device_id: str,
    service: ReminderService = Depends(get_reminder_service),
) -> ReminderResponse:
    """获取用户全部提醒（含服务端计算的 next_due_at）；无记录则为空。"""
    return await run_in_threadpool(service.get_reminders, device_id)


@router.post("/reminders/{device_id}/items", response_model=ReminderResponse)
async def set_reminder(
    device_id: str,
    request: ReminderAddRequest,
    service: ReminderService = Depends(get_reminder_service),
) -> ReminderResponse:
    """覆盖式设置某药品的提醒时刻表，返回全部提醒。"""
    return await run_in_threadpool(service.set_reminder, device_id, request)


@router.delete("/reminders/{device_id}/items/{drug_id}", response_model=ReminderResponse)
async def remove_reminder(
    device_id: str,
    drug_id: int,
    service: ReminderService = Depends(get_reminder_service),
) -> ReminderResponse:
    """移除某药品的提醒，返回剩余提醒。"""
    return await run_in_threadpool(service.remove_reminder, device_id, drug_id)
